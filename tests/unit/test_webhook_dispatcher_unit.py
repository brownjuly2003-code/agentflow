"""Unit coverage for the pure helpers in ``src.serving.api.webhook_dispatcher``:
config CRUD (create/load/list/get/deactivate), event-filter matching, the HMAC
signature, deterministic body serialization, and the JSON default encoder.

The async delivery/dispatch loop (httpx + DuckDB) is covered by
``tests/integration/test_webhooks.py``; these tests pin the side-effect-free
logic at the unit layer so a filter or signature regression fails fast.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
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


def _stub_app(conn: duckdb.DuckDBPyConnection) -> SimpleNamespace:
    # WebhookDispatcher only reaches conn via app.state.query_engine._conn.
    return SimpleNamespace(state=SimpleNamespace(query_engine=SimpleNamespace(_conn=conn)))


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
