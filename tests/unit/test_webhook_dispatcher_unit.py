"""Unit coverage for the pure helpers in ``src.serving.api.webhook_dispatcher``:
config CRUD (create/load/list/get/deactivate), event-filter matching, the HMAC
signature, deterministic body serialization, and the JSON default encoder.

The async delivery/dispatch loop (httpx + DuckDB) is covered by
``tests/integration/test_webhooks.py``; these tests pin the side-effect-free
logic at the unit layer so a filter or signature regression fails fast.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
import httpx
import pytest

from src.serving.api.webhook_dispatcher import (
    WebhookDispatcher,
    WebhookFilters,
    _event_body,
    _event_type_matches,
    _json_default,
    _log_delivery,
    _matches_filters,
    _seen_event_key,
    _signature,
    create_webhook,
    deactivate_webhook,
    ensure_webhook_deliveries_table,
    get_delivery_logs,
    get_webhook,
    list_webhooks,
    load_webhooks,
)
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.semantic_layer.query import QueryEngine


def _engine_stub(conn: duckdb.DuckDBPyConnection) -> QueryEngine:
    # A minimal real QueryEngine over the test connection: the journal scan
    # goes through the serving backend (fetch_pipeline_events), the durable
    # queue through `_conn`. Built via __new__ so initialize_demo_data cannot
    # widen the schema-variant pipeline_events fixtures with its ALTERs.
    engine = QueryEngine.__new__(QueryEngine)
    backend = DuckDBBackend(db_path=":memory:", connection=conn)
    engine._duckdb_backend = backend
    engine._backend = backend
    engine._backend_name = backend.name
    engine._conn = conn
    return engine


def _stub_app(conn: duckdb.DuckDBPyConnection) -> SimpleNamespace:
    # WebhookDispatcher reaches the journal via query_engine.fetch_pipeline_events
    # and the control-plane delivery queue via query_engine._conn.
    return SimpleNamespace(state=SimpleNamespace(query_engine=_engine_stub(conn)))


@pytest.fixture
def pipeline_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR DEFAULT 'default',
            event_type VARCHAR, processed_at TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO pipeline_events (event_id, topic, tenant_id, event_type, processed_at) VALUES
        ('e1', 'orders.raw', 'acme', 'order.created', NOW() - INTERVAL '2 minutes'),
        ('e2', 'orders.raw', 'acme', 'order.paid',    NOW() - INTERVAL '1 minute'),
        ('e3', 'orders.raw', 'other', 'order.created', NOW())
        """
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "webhooks.yaml"


def test_create_then_load_and_list_roundtrip(config_path: Path) -> None:
    created = create_webhook(
        config_path,
        url="https://example.test/hook",
        tenant="acme",
        filters=WebhookFilters(event_types=["order"]),
    )

    assert created.secret  # a secret is generated
    assert load_webhooks(config_path)  # persisted
    listed = list_webhooks(config_path, "acme")
    assert [w.id for w in listed] == [created.id]
    # tenant isolation: another tenant sees nothing
    assert list_webhooks(config_path, "other") == []


def test_get_webhook_respects_tenant_and_activity(config_path: Path) -> None:
    created = create_webhook(
        config_path,
        url="https://example.test/hook",
        tenant="acme",
        filters=WebhookFilters(),
    )

    assert get_webhook(config_path, created.id, "acme") is not None
    assert get_webhook(config_path, created.id, "other") is None
    assert get_webhook(config_path, "missing-id", "acme") is None


def test_deactivate_hides_webhook(config_path: Path) -> None:
    created = create_webhook(
        config_path,
        url="https://example.test/hook",
        tenant="acme",
        filters=WebhookFilters(),
    )

    assert deactivate_webhook(config_path, created.id, "acme") is True
    assert list_webhooks(config_path, "acme") == []
    # second deactivation is a no-op
    assert deactivate_webhook(config_path, created.id, "acme") is False


def test_load_webhooks_missing_or_empty_returns_empty(tmp_path: Path) -> None:
    assert load_webhooks(tmp_path / "absent.yaml") == []
    empty = tmp_path / "empty.yaml"
    empty.write_text("   \n", encoding="utf-8")
    assert load_webhooks(empty) == []


def test_matches_filters_event_type_prefix_and_exact() -> None:
    event = {"event_type": "order.created", "entity_id": "ORD-1"}
    assert _matches_filters(event, WebhookFilters(event_types=["order"])) is True
    assert _matches_filters(event, WebhookFilters(event_types=["order.created"])) is True
    assert _matches_filters(event, WebhookFilters(event_types=["payment"])) is False


def test_matches_filters_entity_ids_and_min_amount() -> None:
    order = {"event_type": "order.created", "order_id": "ORD-1", "total_amount": "150.00"}
    assert _matches_filters(order, WebhookFilters(entity_ids=["ORD-1"])) is True
    assert _matches_filters(order, WebhookFilters(entity_ids=["ORD-9"])) is False
    assert _matches_filters(order, WebhookFilters(min_amount=100.0)) is True
    assert _matches_filters(order, WebhookFilters(min_amount=200.0)) is False
    # min_amount only applies to order events
    clickstream = {"event_type": "clickstream.view", "amount": "999"}
    assert _matches_filters(clickstream, WebhookFilters(min_amount=1.0)) is False


def test_event_type_matches_prefix_semantics() -> None:
    assert _event_type_matches("order.created", "order") is True
    assert _event_type_matches("order", "order") is True
    assert _event_type_matches("orders.created", "order") is False


def test_seen_event_key_namespaces_by_tenant() -> None:
    assert _seen_event_key({"event_id": "e1", "tenant_id": "acme"}) == "acme:e1"
    assert _seen_event_key({"event_id": "e1"}) == "default:e1"


def test_signature_is_stable_hmac_sha256() -> None:
    body = b'{"a":1}'
    secret = "topsecret"  # noqa: S105
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert _signature(secret, body) == expected


def test_event_body_is_deterministic_and_encodes_special_types() -> None:
    event = {
        "event_id": "e1",
        "ts": datetime(2026, 4, 10, 13, 0, tzinfo=UTC),
        "amount": Decimal("19.99"),
    }
    body = _event_body(event)
    # sorted keys -> deterministic ordering; special types encoded as primitives
    decoded = json.loads(body)
    assert list(decoded) == sorted(decoded)
    assert decoded["amount"] == 19.99
    assert decoded["ts"].startswith("2026-04-10T13:00:00")


def test_json_default_encodes_datetime_decimal_and_fallback() -> None:
    assert _json_default(datetime(2026, 1, 1, tzinfo=UTC)).startswith("2026-01-01")
    assert _json_default(Decimal("3.50")) == 3.5
    assert _json_default(object()).startswith("<object")


def test_fetch_pipeline_events_filters_by_tenant(
    pipeline_conn: duckdb.DuckDBPyConnection,
) -> None:
    dispatcher = WebhookDispatcher(_stub_app(pipeline_conn))

    events = dispatcher._fetch_pipeline_events(tenant="acme")

    assert [e["event_id"] for e in events] == ["e1", "e2"]  # 'other' tenant excluded, ts-ordered


def test_fetch_pipeline_events_no_rows_returns_empty() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute(
        "CREATE TABLE pipeline_events "
        "(event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR, processed_at TIMESTAMP)"
    )
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn))
        assert dispatcher._fetch_pipeline_events() == []
    finally:
        conn.close()


def test_mark_existing_events_seen_populates_seen_ids(
    pipeline_conn: duckdb.DuckDBPyConnection,
) -> None:
    dispatcher = WebhookDispatcher(_stub_app(pipeline_conn))

    dispatcher.mark_existing_events_seen()

    assert dispatcher.seen_event_ids == {"acme:e1", "acme:e2", "other:e3"}


def test_delivery_logs_roundtrip() -> None:
    conn = duckdb.connect(":memory:")
    try:
        ensure_webhook_deliveries_table(conn)
        _log_delivery(
            conn,
            delivery_id="d1",
            webhook_id="wh-1",
            event_id="e1",
            event_type="order.created",
            attempt=1,
            status_code=200,
            success=True,
            error=None,
        )
        logs = get_delivery_logs(conn, "wh-1")
        assert len(logs) == 1
        assert logs[0]["webhook_id"] == "wh-1"
        assert logs[0]["success"] is True
        # unrelated webhook id sees nothing
        assert get_delivery_logs(conn, "wh-other") == []
    finally:
        conn.close()


# --- durable delivery queue / re-drive (audit_28_06_26.md #3) -----------------


def _event(event_id: str = "e1", tenant: str = "default") -> dict:
    return {
        "event_id": event_id,
        "tenant_id": tenant,
        "event_type": "order.created",
        "order_id": "ORD-1",
    }


def _queue_row(conn: duckdb.DuckDBPyConnection, webhook_id: str, event_id: str):
    return conn.execute(
        "SELECT status, attempts, next_attempt_at FROM webhook_delivery_queue "
        "WHERE webhook_id = ? AND event_id = ?",
        [webhook_id, event_id],
    ).fetchone()


def test_enqueue_delivery_is_idempotent_on_webhook_event() -> None:
    conn = duckdb.connect(":memory:")
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn))
        webhook = SimpleNamespace(id="wh-1")
        dispatcher._enqueue_delivery(webhook, _event("e1"))
        dispatcher._enqueue_delivery(webhook, _event("e1"))  # re-scan: no duplicate
        assert conn.execute("SELECT count(*) FROM webhook_delivery_queue").fetchone()[0] == 1
        status, attempts, _ = _queue_row(conn, "wh-1", "e1")
        assert status == "pending"
        assert attempts == 0
    finally:
        conn.close()


def test_enqueue_delivery_returns_true_only_for_a_new_row() -> None:
    conn = duckdb.connect(":memory:")
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn))
        webhook = SimpleNamespace(id="wh-1")
        # A fresh (webhook, event) inserts and tells the caller to inline-deliver.
        assert dispatcher._enqueue_delivery(webhook, _event("e1")) is True
        # A re-scan of an already-queued pair is a no-op and must NOT be
        # re-delivered inline (that would storm the receiver every poll cycle
        # whenever an unrelated webhook left the event unseen). (audit_30_06_26.md C2)
        assert dispatcher._enqueue_delivery(webhook, _event("e1")) is False
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_dispatch_isolates_webhook_failure_and_enqueues_all(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two webhooks match the same event; the first one's inline delivery raises
    # an error deliver() does not catch (e.g. httpx.InvalidURL). Pre-fix that
    # exception propagated out of dispatch_new_events *after* the event was
    # already marked seen, so the second webhook was never enqueued and its
    # delivery was lost for good. Now each webhook is durably enqueued first and
    # isolated, and the event is marked seen only once all are enqueued.
    # (audit_30_06_26.md C2)
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, "
            "tenant_id VARCHAR DEFAULT 'default', event_type VARCHAR, processed_at TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO pipeline_events VALUES "
            "('e1', 'orders.raw', 'acme', 'order.created', NOW())"
        )
        wh1 = create_webhook(
            config_path, url="https://a.test/h1", tenant="acme", filters=WebhookFilters()
        )
        wh2 = create_webhook(
            config_path, url="https://b.test/h2", tenant="acme", filters=WebhookFilters()
        )
        monkeypatch.setattr(
            "src.serving.api.webhook_dispatcher.get_webhook_config_path",
            lambda app: config_path,
        )
        dispatcher = WebhookDispatcher(_stub_app(conn))

        async def _deliver(webhook: object, event: dict) -> dict:
            if getattr(webhook, "id", None) == wh1.id:
                raise httpx.InvalidURL("boom")
            return {"success": True, "status_code": 200, "event_id": event["event_id"]}

        monkeypatch.setattr(dispatcher, "deliver", _deliver)

        await dispatcher.dispatch_new_events()  # must not raise

        # Both webhooks are durably enqueued despite wh1's inline failure...
        assert _queue_row(conn, wh1.id, "e1") is not None
        assert _queue_row(conn, wh2.id, "e1") is not None
        # ...wh2 delivered, wh1 left 'pending' for process_delivery_queue to re-drive.
        assert _queue_row(conn, wh2.id, "e1")[0] == "delivered"
        assert _queue_row(conn, wh1.id, "e1")[0] == "pending"
        # The event is marked seen (durably enqueued) so it isn't re-scanned.
        assert "acme:e1" in dispatcher.seen_event_ids
    finally:
        conn.close()


def test_record_outcome_success_marks_delivered() -> None:
    conn = duckdb.connect(":memory:")
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn))
        dispatcher._enqueue_delivery(SimpleNamespace(id="wh-1"), _event("e1"))
        dispatcher._record_delivery_outcome("wh-1", "e1", {"success": True, "status_code": 200})
        assert _queue_row(conn, "wh-1", "e1")[0] == "delivered"
    finally:
        conn.close()


def test_record_outcome_failure_reschedules_then_dies_at_max() -> None:
    conn = duckdb.connect(":memory:")
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn))
        dispatcher.max_delivery_attempts = 2
        dispatcher.backoff_seconds = [10.0]
        dispatcher._enqueue_delivery(SimpleNamespace(id="wh-1"), _event("e1"))

        dispatcher._record_delivery_outcome("wh-1", "e1", {"success": False, "status_code": 500})
        status, attempts, next_at = _queue_row(conn, "wh-1", "e1")
        assert (status, attempts) == ("pending", 1)
        assert next_at is not None  # scheduled for re-drive

        dispatcher._record_delivery_outcome("wh-1", "e1", {"success": False, "status_code": 500})
        status, attempts, next_at = _queue_row(conn, "wh-1", "e1")
        assert (status, attempts) == ("dead", 2)
        assert next_at is None  # parked, no longer re-driven
    finally:
        conn.close()


def test_process_delivery_queue_redrives_due_pending(tmp_path: Path) -> None:
    conn = duckdb.connect(":memory:")
    try:
        config_path = tmp_path / "webhooks.yaml"
        created = create_webhook(
            config_path, url="https://example.test/hook", tenant="acme", filters=WebhookFilters()
        )
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path
        dispatcher = WebhookDispatcher(app)
        dispatcher._enqueue_delivery(SimpleNamespace(id=created.id), _event("e1", tenant="acme"))
        dispatcher._record_delivery_outcome(
            created.id, "e1", {"success": False, "status_code": 500}
        )
        conn.execute("UPDATE webhook_delivery_queue SET next_attempt_at = NULL")  # force due

        attempted: list[str] = []

        async def _fake_deliver_body(webhook, *, body, event_id, event_type):
            attempted.append(event_id)
            return {"success": True, "status_code": 200}

        dispatcher._deliver_body = _fake_deliver_body
        asyncio.run(dispatcher.process_delivery_queue())

        assert attempted == ["e1"]
        assert _queue_row(conn, created.id, "e1")[0] == "delivered"
    finally:
        conn.close()


def test_process_delivery_queue_parks_dead_when_webhook_removed(tmp_path: Path) -> None:
    conn = duckdb.connect(":memory:")
    try:
        config_path = tmp_path / "webhooks.yaml"  # no webhook registered -> lookup returns None
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path
        dispatcher = WebhookDispatcher(app)
        dispatcher._enqueue_delivery(SimpleNamespace(id="ghost"), _event("e1", tenant="acme"))

        attempted: list[int] = []

        async def _fake_deliver_body(*args, **kwargs):
            attempted.append(1)
            return {"success": True}

        dispatcher._deliver_body = _fake_deliver_body
        asyncio.run(dispatcher.process_delivery_queue())

        assert attempted == []  # a removed webhook is never posted to
        assert _queue_row(conn, "ghost", "e1")[0] == "dead"
    finally:
        conn.close()


def test_process_delivery_queue_skips_not_due(tmp_path: Path) -> None:
    conn = duckdb.connect(":memory:")
    try:
        config_path = tmp_path / "webhooks.yaml"
        created = create_webhook(
            config_path, url="https://example.test/hook", tenant="acme", filters=WebhookFilters()
        )
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path
        dispatcher = WebhookDispatcher(app)
        dispatcher._enqueue_delivery(SimpleNamespace(id=created.id), _event("e1", tenant="acme"))
        conn.execute(
            "UPDATE webhook_delivery_queue SET next_attempt_at = ?",
            [datetime.now(UTC) + timedelta(hours=1)],  # due in the future
        )

        attempted: list[int] = []

        async def _fake_deliver_body(*args, **kwargs):
            attempted.append(1)
            return {"success": True}

        dispatcher._deliver_body = _fake_deliver_body
        asyncio.run(dispatcher.process_delivery_queue())

        assert attempted == []
        assert _queue_row(conn, created.id, "e1")[0] == "pending"
    finally:
        conn.close()


def test_pending_delivery_survives_a_new_dispatcher_instance(tmp_path: Path) -> None:
    """The core #3 guarantee: a failed delivery left pending in the durable queue
    is re-driven by a *fresh* dispatcher (i.e. after a process restart) — the
    in-memory seen-set cannot do this."""
    conn = duckdb.connect(":memory:")
    try:
        config_path = tmp_path / "webhooks.yaml"
        created = create_webhook(
            config_path, url="https://example.test/hook", tenant="acme", filters=WebhookFilters()
        )
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path

        first = WebhookDispatcher(app)
        first._enqueue_delivery(SimpleNamespace(id=created.id), _event("e1", tenant="acme"))
        first._record_delivery_outcome(created.id, "e1", {"success": False, "status_code": 503})
        conn.execute("UPDATE webhook_delivery_queue SET next_attempt_at = NULL")
        del first  # simulate process exit; only the durable row remains

        reborn = WebhookDispatcher(app)
        attempted: list[str] = []

        async def _fake_deliver_body(webhook, *, body, event_id, event_type):
            attempted.append(event_id)
            return {"success": True, "status_code": 200}

        reborn._deliver_body = _fake_deliver_body
        asyncio.run(reborn.process_delivery_queue())

        assert attempted == ["e1"]
        assert _queue_row(conn, created.id, "e1")[0] == "delivered"
    finally:
        conn.close()
