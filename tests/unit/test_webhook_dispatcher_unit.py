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
    _matches_filters,
    _seen_event_key,
    _signature,
    create_webhook,
    deactivate_webhook,
    get_webhook,
    list_webhooks,
    load_webhooks,
)
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.control_plane import EmbeddedControlPlaneStore
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


def _registry_app(config_path: Path) -> SimpleNamespace:
    # Registration CRUD resolves the control-plane store from the app
    # (ADR 0010 slice 5); the embedded store persists registrations to the
    # app's webhook_config_path YAML, exactly like the pre-port path-based
    # helpers did.
    return SimpleNamespace(state=SimpleNamespace(webhook_config_path=config_path))


def test_create_then_load_and_list_roundtrip(config_path: Path) -> None:
    app = _registry_app(config_path)
    created = create_webhook(
        app,
        url="https://example.test/hook",
        tenant="acme",
        filters=WebhookFilters(event_types=["order"]),
    )

    assert created.secret  # a secret is generated
    assert config_path.exists()  # persisted to the embedded profile's YAML
    assert load_webhooks(app)
    listed = list_webhooks(app, "acme")
    assert [w.id for w in listed] == [created.id]
    # tenant isolation: another tenant sees nothing
    assert list_webhooks(app, "other") == []


def test_get_webhook_respects_tenant_and_activity(config_path: Path) -> None:
    app = _registry_app(config_path)
    created = create_webhook(
        app,
        url="https://example.test/hook",
        tenant="acme",
        filters=WebhookFilters(),
    )

    assert get_webhook(app, created.id, "acme") is not None
    assert get_webhook(app, created.id, "other") is None
    assert get_webhook(app, "missing-id", "acme") is None


def test_deactivate_hides_webhook(config_path: Path) -> None:
    app = _registry_app(config_path)
    created = create_webhook(
        app,
        url="https://example.test/hook",
        tenant="acme",
        filters=WebhookFilters(),
    )

    assert deactivate_webhook(app, created.id, "acme") is True
    assert list_webhooks(app, "acme") == []
    # second deactivation is a no-op
    assert deactivate_webhook(app, created.id, "acme") is False


def test_load_webhooks_missing_or_empty_returns_empty(tmp_path: Path) -> None:
    assert load_webhooks(_registry_app(tmp_path / "absent.yaml")) == []
    empty = tmp_path / "empty.yaml"
    empty.write_text("   \n", encoding="utf-8")
    assert load_webhooks(_registry_app(empty)) == []


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
    # settle_seconds=0: this probe is about seeding mechanics, and its fixture
    # stamps e3 with NOW() — under the default settle watermark an open-second
    # row is deliberately not seeded (pinned separately below).
    dispatcher = WebhookDispatcher(_stub_app(pipeline_conn), settle_seconds=0)

    dispatcher.mark_existing_events_seen()

    assert dispatcher.seen_event_ids == {"acme:e1", "acme:e2", "other:e3"}


# --- bounded incremental journal scan (issue #183) ----------------------------


def _journal_conn(rows: list[tuple[str, str, str, str | datetime]]) -> duckdb.DuckDBPyConnection:
    """pipeline_events with explicit timestamps: (event_id, tenant, event_type, ts).

    ``ts`` may be a string literal (fixed-date regressions) or an aware
    datetime (binds exactly like production journal writes)."""
    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR DEFAULT 'default',
            event_type VARCHAR, processed_at TIMESTAMP
        )
        """
    )
    for event_id, tenant, event_type, ts in rows:
        conn.execute(
            "INSERT INTO pipeline_events VALUES (?, 'orders.raw', ?, ?, ?)",
            [event_id, tenant, event_type, ts],
        )
    return conn


def test_mark_existing_events_seen_is_bounded_and_sets_cursor() -> None:
    conn = _journal_conn(
        [
            ("old", "acme", "order.created", "2026-07-10 10:00:00"),
            ("mid", "acme", "order.created", "2026-07-10 10:00:05"),
            ("new", "acme", "order.created", "2026-07-10 10:00:10"),
        ]
    )
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn), scan_batch_size=2)

        dispatcher.mark_existing_events_seen()

        # O(batch), not O(journal): only the newest batch seeds the set...
        assert dispatcher.seen_event_ids == {"acme:mid", "acme:new"}
        # ...and the cursor sits at the journal tail (composite keyset), excluding
        # older rows.
        assert dispatcher._scan_cursor == ("2026-07-10 10:00:10", "new")
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_dispatch_scans_a_bounded_window_after_the_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _journal_conn(
        [
            ("e-old", "acme", "order.created", "2026-07-10 10:00:00"),
            ("e-new", "acme", "order.created", "2026-07-10 10:00:10"),
        ]
    )
    try:
        app = _stub_app(conn)
        dispatcher = WebhookDispatcher(app)
        dispatcher.mark_existing_events_seen()

        captured: list[dict] = []
        real_fetch = app.state.query_engine.fetch_pipeline_events

        def spy_fetch(**kwargs: object) -> list[dict]:
            captured.append(kwargs)
            return real_fetch(**kwargs)

        monkeypatch.setattr(app.state.query_engine, "fetch_pipeline_events", spy_fetch)

        await dispatcher.dispatch_new_events()

        (kwargs,) = captured
        assert kwargs["limit"] == dispatcher.scan_batch_size
        # Composite keyset: both halves of the frontier are handed to the scan.
        assert kwargs["min_processed_at"] == "2026-07-10 10:00:10"
        assert kwargs["min_event_id"] == "e-new"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_dispatch_advances_cursor_over_newly_seen_events() -> None:
    conn = _journal_conn([("e1", "acme", "order.created", "2026-07-10 10:00:00")])
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn))

        await dispatcher.dispatch_new_events()
        assert dispatcher._scan_cursor == ("2026-07-10 10:00:00", "e1")

        conn.execute(
            "INSERT INTO pipeline_events VALUES "
            "('e2', 'orders.raw', 'acme', 'order.paid', '2026-07-10 10:00:07')"
        )
        await dispatcher.dispatch_new_events()

        assert dispatcher._scan_cursor == ("2026-07-10 10:00:07", "e2")
        assert "acme:e2" in dispatcher.seen_event_ids
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_dispatch_advances_cursor_over_an_all_seen_full_batch() -> None:
    # Livelock guard: a full batch of already-seen rows must still move the
    # cursor, otherwise a seen frontier wider than one batch pins the window.
    # With the composite keyset the frontier is strict (the boundary row is not
    # re-fetched), so two passes clear e1..e4 rather than overlapping on e2/e3.
    conn = _journal_conn(
        [
            (f"e{i}", "acme", "order.created", f"2026-07-10 10:00:0{i}")
            for i in range(1, 5)  # e1..e4 at :01..:04
        ]
    )
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn), scan_batch_size=2)
        for i in range(1, 5):
            dispatcher.seen_event_ids.add(f"acme:e{i}")

        await dispatcher.dispatch_new_events()  # window (start, e2] — all seen
        assert dispatcher._scan_cursor == ("2026-07-10 10:00:02", "e2")

        await dispatcher.dispatch_new_events()  # window (e2, e4] — all seen
        assert dispatcher._scan_cursor == ("2026-07-10 10:00:04", "e4")
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_dispatch_drains_a_second_holding_more_than_a_batch(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression for audit_2026-07-17 #1 (cohort-wedge). A SINGLE second that
    # holds MORE than scan_batch_size journal rows must not pin the scan. With a
    # second-granular cursor the bounded batch fills with that second's
    # lowest-event_id rows, `advance` is set to that SAME second, the next fetch
    # (`WHERE processed_at >= cursor`) returns the identical rows, and every
    # webhook for every event at/after that second is silently, permanently
    # undelivered. The composite (processed_at, event_id) keyset advances WITHIN
    # the saturated second, so the scan drains it and moves past.
    #
    # PROVING PROPERTY: on the pre-fix second-granular cursor this test FAILS
    # (only the first `batch` events ever deliver; the tail and everything after
    # the second are lost) and TERMINATES rather than hanging — confirmed by
    # temporarily reverting the fix.
    batch = 5
    cohort = 12  # > batch: the wedge trigger
    saturated = "2026-07-10 10:00:00"
    rows = [(f"e{i:03d}", "acme", "order.created", saturated) for i in range(cohort)]
    # ...plus rows strictly AFTER the saturated second — exactly what the wedge
    # hides forever behind the pinned cursor.
    rows.append(("z-after-1", "acme", "order.created", "2026-07-10 10:00:01"))
    rows.append(("z-after-2", "acme", "order.created", "2026-07-10 10:00:02"))
    conn = _journal_conn(rows)
    try:
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path
        create_webhook(app, url="https://a.test/h", tenant="acme", filters=WebhookFilters())
        dispatcher = WebhookDispatcher(app, scan_batch_size=batch)

        delivered: list[str] = []

        async def _deliver(webhook: object, event: dict) -> dict:
            delivered.append(str(event["event_id"]))
            return {"success": True, "status_code": 200, "event_id": event["event_id"]}

        monkeypatch.setattr(dispatcher, "deliver", _deliver)

        # Drive the poll loop by hand. Each pass advances the keyset strictly, so
        # a bounded number of passes drains the journal; bound the loop so a
        # regression that RE-wedges surfaces as a failed assertion, never a spin.
        for _ in range(50):
            before = dispatcher._scan_cursor
            await dispatcher.dispatch_new_events()
            if dispatcher._scan_cursor == before:
                break  # no forward progress -> drained (or, pre-fix, wedged)

        expected = {f"e{i:03d}" for i in range(cohort)} | {"z-after-1", "z-after-2"}
        # Every event — the high-event_id tail of the saturated second AND
        # everything after it — is delivered exactly once (idempotent enqueue +
        # strict keyset: no duplicate POSTs).
        assert set(delivered) == expected
        assert len(delivered) == len(expected)
        # The cursor climbed PAST the saturated second to the true journal tail.
        assert dispatcher._scan_cursor == ("2026-07-10 10:00:02", "z-after-2")
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_settle_watermark_holds_back_open_second_rows_then_delivers(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Audit 2026-07-17 #1 follow-up (review finding): a STRICT keyset cursor
    # advanced into the still-open second permanently drops any same-second row
    # that becomes visible later with a lower event_id (ClickHouse processed_at
    # is second-granular, event ids are UUIDs — not monotonic). The settle
    # watermark keeps every fetch out of unsettled seconds, so the frontier
    # only crosses seconds no writer will stamp again.
    #
    # Rows are stamped exactly the way production DuckDB journal writes are —
    # binding an AWARE datetime.now(UTC) (local_pipeline binds the same) — so
    # this test also pins the frame equivalence the watermark relies on: the
    # aware param and CAST(now() AS TIMESTAMP) both land in the session-local
    # frame, whatever the host zone.
    now_utc = datetime.now(UTC).replace(microsecond=123456)
    stored = now_utc.astimezone().replace(tzinfo=None)  # DuckDB's stored (session-local) frame
    open_ts = stored.strftime("%Y-%m-%d %H:%M:%S.%f")
    conn = _journal_conn(
        [
            ("e-settled", "acme", "order.created", now_utc - timedelta(seconds=30)),
            ("zz-open-high", "acme", "order.created", now_utc),
        ]
    )
    try:
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path
        create_webhook(app, url="https://a.test/h", tenant="acme", filters=WebhookFilters())
        dispatcher = WebhookDispatcher(app, settle_seconds=5)

        delivered: list[str] = []

        async def _deliver(webhook: object, event: dict) -> dict:
            delivered.append(str(event["event_id"]))
            return {"success": True, "status_code": 200, "event_id": event["event_id"]}

        monkeypatch.setattr(dispatcher, "deliver", _deliver)

        await dispatcher.dispatch_new_events()
        # Only the settled row is visible; the cursor must NOT enter the open
        # second.
        assert delivered == ["e-settled"]
        settled_ts = (stored - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S.%f")
        assert dispatcher._scan_cursor == (settled_ts, "e-settled")

        # The drop scenario the watermark exists for: a same-second row with a
        # LOWER event_id becomes visible after the high one already did. Behind
        # a strict frontier it would be excluded forever; behind the watermark
        # it is simply not visible yet.
        conn.execute(
            "INSERT INTO pipeline_events VALUES (?, 'orders.raw', ?, ?, ?)",
            ["aa-open-low", "acme", "order.created", now_utc],
        )
        await dispatcher.dispatch_new_events()
        assert delivered == ["e-settled"]  # still held back — and not lost

        # Time passes (simulated by dropping the watermark): BOTH open-second
        # rows deliver, including the late lower-id one, exactly once each.
        dispatcher.settle_seconds = 0
        await dispatcher.dispatch_new_events()
        assert sorted(delivered) == ["aa-open-low", "e-settled", "zz-open-high"]
        assert dispatcher._scan_cursor == (open_ts, "zz-open-high")
    finally:
        conn.close()


def test_mark_existing_does_not_seed_unsettled_rows(config_path: Path) -> None:
    # Startup: rows younger than the settle watermark are NOT marked seen —
    # they deliver once settled (an event that raced a restart is not lost);
    # a row the pre-restart process already delivered is suppressed by the
    # durable enqueue's idempotent key, not re-POSTed. Stamps bind aware
    # datetime.now(UTC), exactly like production journal writes.
    now_utc = datetime.now(UTC).replace(microsecond=123456)
    conn = _journal_conn(
        [
            ("e-old", "acme", "order.created", now_utc - timedelta(seconds=30)),
            ("e-fresh", "acme", "order.created", now_utc),
        ]
    )
    try:
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path
        dispatcher = WebhookDispatcher(app, settle_seconds=5)

        dispatcher.mark_existing_events_seen()

        assert "acme:e-old" in dispatcher.seen_event_ids
        assert "acme:e-fresh" not in dispatcher.seen_event_ids
        assert dispatcher._scan_cursor is not None
        assert dispatcher._scan_cursor[1] == "e-old"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_dispatch_cursor_freezes_on_enqueue_failure_then_retries(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An event whose durable enqueue fails must stay inside the scan window
    # (the retry-forever semantics the full scan provided): the cursor freezes
    # before it, and the next pass re-fetches and retries it.
    conn = _journal_conn(
        [
            ("e-fail", "acme", "order.created", "2026-07-10 10:00:01"),
            ("e-ok", "acme", "order.created", "2026-07-10 10:00:02"),
        ]
    )
    try:
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path
        create_webhook(app, url="https://a.test/h", tenant="acme", filters=WebhookFilters())
        dispatcher = WebhookDispatcher(app)

        delivered: list[str] = []

        async def _deliver(webhook: object, event: dict) -> dict:
            delivered.append(str(event["event_id"]))
            return {"success": True, "status_code": 200, "event_id": event["event_id"]}

        monkeypatch.setattr(dispatcher, "deliver", _deliver)

        real_enqueue = dispatcher._enqueue_delivery
        fail_once = {"armed": True}

        def flaky_enqueue(webhook: object, event: dict) -> bool:
            if event.get("event_id") == "e-fail" and fail_once["armed"]:
                raise RuntimeError("store down")
            return real_enqueue(webhook, event)

        monkeypatch.setattr(dispatcher, "_enqueue_delivery", flaky_enqueue)

        await dispatcher.dispatch_new_events()

        # e-fail is not seen and the cursor did not advance past it; e-ok was
        # durably enqueued and delivered, so it is seen.
        assert "acme:e-fail" not in dispatcher.seen_event_ids
        assert "acme:e-ok" in dispatcher.seen_event_ids
        assert dispatcher._scan_cursor is None
        assert delivered == ["e-ok"]

        fail_once["armed"] = False
        await dispatcher.dispatch_new_events()

        assert "acme:e-fail" in dispatcher.seen_event_ids
        assert dispatcher._scan_cursor == ("2026-07-10 10:00:02", "e-ok")
        # e-ok's durable row already existed (idempotent enqueue), so the
        # retry pass delivered exactly the failed event — no duplicate POST.
        assert delivered == ["e-ok", "e-fail"]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_seen_set_stays_bounded_across_scans() -> None:
    conn = _journal_conn(
        [
            (f"e{i}", "acme", "order.created", f"2026-07-10 10:00:{i:02d}")
            for i in range(1, 8)  # 7 events
        ]
    )
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn), seen_cache_size=3)

        await dispatcher.dispatch_new_events()

        assert len(dispatcher.seen_event_ids) == 3  # capped, not 7
        # The cursor, not the seen-set, is what keeps old rows out of the
        # window — it reached the journal tail even though early ids were
        # evicted.
        assert dispatcher._scan_cursor == ("2026-07-10 10:00:07", "e7")
    finally:
        conn.close()


def test_mark_existing_seeds_cursor_past_a_malformed_newest_timestamp() -> None:
    # Defensive seed-edge (audit #185): if the newest journal row's processed_at
    # does not parse, the cursor must fall back to the next parseable row rather
    # than stay None. A None cursor makes the first dispatch fetch with
    # min_processed_at=None (from the oldest journal row) and re-deliver the
    # whole batch mark_existing_events_seen just marked seen.
    events = [
        {"event_id": "new", "tenant_id": "acme", "processed_at": "not-a-timestamp"},
        {"event_id": "mid", "tenant_id": "acme", "processed_at": "2026-07-10 10:00:05"},
        {"event_id": "old", "tenant_id": "acme", "processed_at": "2026-07-10 10:00:00"},
    ]
    app = SimpleNamespace(
        state=SimpleNamespace(
            query_engine=SimpleNamespace(fetch_pipeline_events=lambda **kwargs: list(events))
        )
    )
    dispatcher = WebhookDispatcher(app)

    dispatcher.mark_existing_events_seen()

    # newest row's ts is malformed -> cursor falls back to the next parseable row
    assert dispatcher._scan_cursor == ("2026-07-10 10:00:05", "mid")
    # every row is marked seen regardless of ts validity (id-keyed, not ts-keyed)
    assert dispatcher.seen_event_ids == {"acme:new", "acme:mid", "acme:old"}


@pytest.mark.asyncio
async def test_dispatch_does_not_dedup_same_event_id_across_tenants() -> None:
    # Dedup is strictly on tenant:event_id (audit #184 removed the dead bare
    # `event_id in seen` check). The same event_id already seen for one tenant
    # must not suppress that id for another tenant — they are distinct events.
    conn = _journal_conn([("e1", "other", "order.created", "2026-07-10 10:00:00")])
    try:
        dispatcher = WebhookDispatcher(_stub_app(conn))
        dispatcher.seen_event_ids.add("acme:e1")  # same id, different tenant, already seen

        await dispatcher.dispatch_new_events()

        # 'other:e1' is processed (marked seen) despite 'acme:e1' being seen
        assert "other:e1" in dispatcher.seen_event_ids
        assert dispatcher._scan_cursor == ("2026-07-10 10:00:00", "e1")
    finally:
        conn.close()


def test_delivery_logs_roundtrip() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = EmbeddedControlPlaneStore(conn_provider=lambda: conn)
        store.log_webhook_delivery(
            delivery_id="d1",
            webhook_id="wh-1",
            event_id="e1",
            event_type="order.created",
            attempt=1,
            status_code=200,
            success=True,
            error=None,
        )
        logs = store.get_webhook_delivery_logs("wh-1")
        assert len(logs) == 1
        assert logs[0]["webhook_id"] == "wh-1"
        assert logs[0]["success"] is True
        # unrelated webhook id sees nothing
        assert store.get_webhook_delivery_logs("wh-other") == []
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
        app = _stub_app(conn)
        app.state.webhook_config_path = config_path
        wh1 = create_webhook(app, url="https://a.test/h1", tenant="acme", filters=WebhookFilters())
        wh2 = create_webhook(app, url="https://b.test/h2", tenant="acme", filters=WebhookFilters())
        # settle_seconds=0: the probe is failure isolation, and its single row
        # is stamped NOW() — held back by the default settle watermark.
        dispatcher = WebhookDispatcher(app, settle_seconds=0)

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
        app = _stub_app(conn)
        app.state.webhook_config_path = tmp_path / "webhooks.yaml"
        created = create_webhook(
            app, url="https://example.test/hook", tenant="acme", filters=WebhookFilters()
        )
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
        app = _stub_app(conn)
        app.state.webhook_config_path = tmp_path / "webhooks.yaml"
        created = create_webhook(
            app, url="https://example.test/hook", tenant="acme", filters=WebhookFilters()
        )
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
        app = _stub_app(conn)
        app.state.webhook_config_path = tmp_path / "webhooks.yaml"
        created = create_webhook(
            app, url="https://example.test/hook", tenant="acme", filters=WebhookFilters()
        )

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
