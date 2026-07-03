"""ADR 0010 slices 1-3: the ControlPlaneStore port and its embedded adapter.

Covers the store-level contract the dispatcher relies on (enqueue-win
semantics, due-claim ordering and bounds, the outcome state machine, parking,
attempt-log roundtrip), the alert-delivery history log and the YAML-backed
alert-rule repository (slice 2), the replay outbox + dead-letter transitions
including invariant 8's transactional atomicity (slice 3), the
``get_control_plane_store`` resolution/ratchet, and the structural pin that
keeps the webhook/alert/outbox/dead-letter paths from re-growing direct
``query_engine._conn`` reaches.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from src.serving.control_plane import (
    CONTROL_PLANE_PG_DSN_ENV,
    CONTROL_PLANE_STORE_ENV,
    EmbeddedControlPlaneStore,
    get_control_plane_store,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def store(conn: duckdb.DuckDBPyConnection) -> EmbeddedControlPlaneStore:
    return EmbeddedControlPlaneStore(conn_provider=lambda: conn)


@pytest.fixture
def alert_store(conn: duckdb.DuckDBPyConnection, tmp_path: Path) -> EmbeddedControlPlaneStore:
    path = tmp_path / "alerts.yaml"
    return EmbeddedControlPlaneStore(
        conn_provider=lambda: conn, alert_rules_path_provider=lambda: path
    )


@pytest.fixture
def outbox_store(conn: duckdb.DuckDBPyConnection) -> EmbeddedControlPlaneStore:
    store = EmbeddedControlPlaneStore(conn_provider=lambda: conn)
    store.ensure_outbox_schema()
    return store


def _enqueue(store: EmbeddedControlPlaneStore, webhook_id: str, event_id: str) -> bool:
    return store.enqueue_webhook_delivery(
        webhook_id=webhook_id,
        event_id=event_id,
        tenant="acme",
        event_type="order.created",
        body='{"event_id":"' + event_id + '"}',
    )


def _row(conn: duckdb.DuckDBPyConnection, webhook_id: str, event_id: str):
    return conn.execute(
        "SELECT status, attempts, next_attempt_at, last_error FROM webhook_delivery_queue "
        "WHERE webhook_id = ? AND event_id = ?",
        [webhook_id, event_id],
    ).fetchone()


# --- enqueue: the winner-only contract ---------------------------------------


def test_enqueue_returns_true_only_for_the_inserting_call(
    store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    assert _enqueue(store, "wh-1", "e1") is True
    # Idempotent on the (webhook, event) key: a re-scan is not a win, so the
    # caller never inline-re-POSTs an already-queued delivery.
    assert _enqueue(store, "wh-1", "e1") is False
    assert conn.execute("SELECT count(*) FROM webhook_delivery_queue").fetchone()[0] == 1


# --- claim_due: ordering, bounds, due-ness ------------------------------------


def test_claim_due_returns_oldest_first_and_respects_limit(
    store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    for index in range(3):
        _enqueue(store, "wh-1", f"e{index}")
        # created_at drives the order; stagger it explicitly (CURRENT_TIMESTAMP
        # has coarse resolution within one transaction).
        conn.execute(
            "UPDATE webhook_delivery_queue SET created_at = ?, next_attempt_at = NULL "
            "WHERE event_id = ?",
            [datetime.now(UTC) + timedelta(seconds=index), f"e{index}"],
        )

    claimed = store.claim_due_webhook_deliveries(limit=2)

    assert [row.event_id for row in claimed] == ["e0", "e1"]
    assert claimed[0].webhook_id == "wh-1"
    assert claimed[0].tenant == "acme"
    assert claimed[0].body is not None


def test_claim_due_skips_future_and_non_pending_rows(
    store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _enqueue(store, "wh-1", "future")
    _enqueue(store, "wh-1", "done")
    conn.execute(
        "UPDATE webhook_delivery_queue SET next_attempt_at = ? WHERE event_id = 'future'",
        [datetime.now(UTC) + timedelta(hours=1)],
    )
    conn.execute(
        "UPDATE webhook_delivery_queue SET status = 'delivered', next_attempt_at = NULL "
        "WHERE event_id = 'done'"
    )

    assert store.claim_due_webhook_deliveries(limit=10) == []


# --- outcome state machine -----------------------------------------------------


def test_outcome_success_marks_delivered_and_clears_error(
    store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _enqueue(store, "wh-1", "e1")
    store.record_webhook_delivery_outcome(
        webhook_id="wh-1",
        event_id="e1",
        success=True,
        status_code=200,
        error=None,
        max_attempts=5,
        backoff_seconds=[1.0],
    )
    status, _attempts, _next_at, last_error = _row(conn, "wh-1", "e1")
    assert status == "delivered"
    assert last_error is None


def test_outcome_failure_backs_off_then_parks_dead_at_max(
    store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _enqueue(store, "wh-1", "e1")

    store.record_webhook_delivery_outcome(
        webhook_id="wh-1",
        event_id="e1",
        success=False,
        status_code=500,
        error="boom",
        max_attempts=2,
        backoff_seconds=[10.0],
    )
    status, attempts, next_at, _ = _row(conn, "wh-1", "e1")
    assert (status, attempts) == ("pending", 1)
    assert next_at is not None  # re-drive scheduled with backoff

    store.record_webhook_delivery_outcome(
        webhook_id="wh-1",
        event_id="e1",
        success=False,
        status_code=500,
        error="boom",
        max_attempts=2,
        backoff_seconds=[10.0],
    )
    status, attempts, next_at, _ = _row(conn, "wh-1", "e1")
    assert (status, attempts) == ("dead", 2)
    assert next_at is None  # parked for good


def test_park_marks_dead_with_reason(
    store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _enqueue(store, "ghost", "e1")
    store.park_webhook_delivery(
        webhook_id="ghost", event_id="e1", error="webhook inactive or removed"
    )
    status, _attempts, next_at, last_error = _row(conn, "ghost", "e1")
    assert status == "dead"
    assert next_at is None
    assert last_error == "webhook inactive or removed"


# --- attempt log ---------------------------------------------------------------


def test_delivery_log_roundtrip_is_isolated_per_webhook_and_newest_first(
    store: EmbeddedControlPlaneStore,
) -> None:
    for attempt in (1, 2):
        store.log_webhook_delivery(
            delivery_id=f"d{attempt}",
            webhook_id="wh-1",
            event_id="e1",
            event_type="order.created",
            attempt=attempt,
            status_code=500 if attempt == 1 else 200,
            success=attempt == 2,
            error="boom" if attempt == 1 else None,
        )

    logs = store.get_webhook_delivery_logs("wh-1")

    assert [entry["attempt"] for entry in logs] == [2, 1] or [
        entry["delivery_id"] for entry in logs
    ] == ["d2", "d1"]
    assert store.get_webhook_delivery_logs("wh-other") == []
    assert store.get_webhook_delivery_logs("wh-1", limit=1)[0]["delivery_id"] in {"d1", "d2"}


# --- alert delivery history -----------------------------------------------------


def _log_alert(
    store: EmbeddedControlPlaneStore, *, delivery_id: str, alert_id: str, success: bool
) -> None:
    store.log_alert_delivery(
        delivery_id=delivery_id,
        alert_id=alert_id,
        alert_name="High error rate",
        tenant="acme",
        metric="error_rate",
        current_value=0.5,
        previous_value=0.1,
        change_pct=400.0,
        threshold=0.1,
        condition="above",
        window="1h",
        event_type="alert.triggered",
        status_code=200 if success else 500,
        success=success,
        error=None if success else "boom",
        payload={"alert_id": alert_id, "status": "firing"},
    )


def test_alert_delivery_log_roundtrip_is_isolated_per_alert_and_newest_first(
    alert_store: EmbeddedControlPlaneStore,
) -> None:
    _log_alert(alert_store, delivery_id="d1", alert_id="a1", success=False)
    _log_alert(alert_store, delivery_id="d2", alert_id="a1", success=True)
    _log_alert(alert_store, delivery_id="d-other", alert_id="a-other", success=True)

    history = alert_store.get_alert_delivery_history("a1")

    assert [entry["delivery_id"] for entry in history] == ["d2", "d1"]
    assert history[0]["success"] is True
    assert history[1]["error"] == "boom"
    assert alert_store.get_alert_delivery_history("a-ghost") == []
    assert alert_store.get_alert_delivery_history("a1", limit=1) == history[:1]


def test_alert_delivery_history_decodes_json_payload(
    alert_store: EmbeddedControlPlaneStore,
) -> None:
    _log_alert(alert_store, delivery_id="d1", alert_id="a1", success=True)

    history = alert_store.get_alert_delivery_history("a1")

    assert history[0]["payload"] == {"alert_id": "a1", "status": "firing"}


# --- alert rule repository (YAML round-trip) --------------------------------------


def test_load_alert_rules_returns_empty_list_when_file_is_missing(
    alert_store: EmbeddedControlPlaneStore,
) -> None:
    assert alert_store.load_alert_rules() == []


def test_save_then_load_alert_rules_round_trips_verbatim(
    alert_store: EmbeddedControlPlaneStore,
) -> None:
    rules = [
        {"id": "a1", "name": "High error rate", "state": "firing", "last_escalation_level": 2},
        {"id": "a2", "name": "Low revenue", "state": "ok", "last_escalation_level": 0},
    ]

    alert_store.save_alert_rules(rules)

    assert alert_store.load_alert_rules() == rules


def test_save_alert_rules_creates_parent_directories(tmp_path: Path, conn) -> None:
    nested_path = tmp_path / "nested" / "alerts.yaml"
    store = EmbeddedControlPlaneStore(
        conn_provider=lambda: conn, alert_rules_path_provider=lambda: nested_path
    )

    store.save_alert_rules([{"id": "a1"}])

    assert nested_path.exists()
    assert store.load_alert_rules() == [{"id": "a1"}]


def test_alert_rules_methods_require_a_path_provider(store: EmbeddedControlPlaneStore) -> None:
    # ``store`` (unlike ``alert_store``) was constructed without
    # alert_rules_path_provider — mirrors a caller that only wired the webhook
    # queue's conn_provider and forgot the alert-rule repository.
    with pytest.raises(RuntimeError, match="alert_rules_path_provider"):
        store.load_alert_rules()


# --- webhook registration repository (YAML round-trip, slice 5) -------------------


@pytest.fixture
def registration_store(tmp_path: Path) -> EmbeddedControlPlaneStore:
    path = tmp_path / "webhooks.yaml"
    return EmbeddedControlPlaneStore(webhook_registrations_path_provider=lambda: path)


def test_load_webhook_registrations_empty_when_file_is_missing(
    registration_store: EmbeddedControlPlaneStore,
) -> None:
    assert registration_store.load_webhook_registrations() == []


def test_save_then_load_webhook_registrations_round_trips_verbatim(
    registration_store: EmbeddedControlPlaneStore,
) -> None:
    registrations = [
        {"id": "wh-1", "url": "https://a.test/h", "tenant": "acme", "active": True},
        {"id": "wh-2", "url": "https://b.test/h", "tenant": "beta", "active": False},
    ]

    registration_store.save_webhook_registrations(registrations)

    assert registration_store.load_webhook_registrations() == registrations


def test_load_webhook_registrations_reads_the_pre_port_yaml_shape(tmp_path: Path) -> None:
    # Byte-compatibility pin: a config/webhooks.yaml written by the pre-port
    # save_webhooks (a top-level ``webhooks:`` list) loads unchanged.
    path = tmp_path / "webhooks.yaml"
    path.write_text(
        "webhooks:\n- id: wh-1\n  url: https://a.test/h\n  tenant: acme\n  active: true\n",
        encoding="utf-8",
    )
    store = EmbeddedControlPlaneStore(webhook_registrations_path_provider=lambda: path)

    assert store.load_webhook_registrations() == [
        {"id": "wh-1", "url": "https://a.test/h", "tenant": "acme", "active": True}
    ]


def test_webhook_registration_methods_require_a_path_provider(
    store: EmbeddedControlPlaneStore,
) -> None:
    with pytest.raises(RuntimeError, match="webhook_registrations_path_provider"):
        store.load_webhook_registrations()


# --- alert tick claims (slice 5) ---------------------------------------------------


def test_embedded_claim_alert_tick_always_grants(
    alert_store: EmbeddedControlPlaneStore,
) -> None:
    # One process, one dispatcher loop: the embedded adapter satisfies the
    # single-flight contract degenerately, like its claim_due siblings.
    assert alert_store.claim_alert_tick("a1", lease_seconds=60.0) is True
    assert alert_store.claim_alert_tick("a1", lease_seconds=60.0) is True


def test_embedded_complete_alert_tick_persists_only_that_rule(
    alert_store: EmbeddedControlPlaneStore,
) -> None:
    alert_store.save_alert_rules([{"id": "a1", "state": "ok"}, {"id": "a2", "state": "ok"}])

    alert_store.complete_alert_tick("a1", record={"id": "a1", "state": "firing"})

    assert alert_store.load_alert_rules() == [
        {"id": "a1", "state": "firing"},
        {"id": "a2", "state": "ok"},
    ]


def test_embedded_complete_alert_tick_without_record_is_a_no_op(
    alert_store: EmbeddedControlPlaneStore,
) -> None:
    alert_store.save_alert_rules([{"id": "a1", "state": "ok"}])

    alert_store.complete_alert_tick("a1", record=None)

    assert alert_store.load_alert_rules() == [{"id": "a1", "state": "ok"}]


@pytest.mark.asyncio
async def test_dispatch_alerts_single_flights_rules_through_the_claim() -> None:
    """ADR 0010 §2 wiring pin: the dispatcher evaluates only the rules whose
    tick it claimed, and completes every claim it took — with the advanced
    record when the rule changed, with ``None`` when it did not."""
    from src.serving.api.alerts import dispatcher as dispatcher_module
    from src.serving.api.alerts import escalation as escalation_module
    from src.serving.api.alerts.dispatcher import AlertDispatcher, AlertRule

    now = datetime.now(UTC)
    rules = [
        AlertRule(
            id=f"a{index}",
            name=f"rule {index}",
            tenant="acme",
            metric="error_rate",
            window="1h",
            condition="above",
            threshold=0.1,
            webhook_url="https://example.test/hook",
            secret="s",
            created_at=now,
            updated_at=now,
        )
        for index in range(3)
    ]

    class _ClaimingStubStore:
        def __init__(self) -> None:
            self.claims: list[str] = []
            self.completions: list[tuple[str, bool]] = []

        def load_alert_rules(self) -> list[dict]:
            return [rule.model_dump(mode="json") for rule in rules]

        def claim_alert_tick(self, rule_id: str, *, lease_seconds: float) -> bool:
            self.claims.append(rule_id)
            return rule_id != "a1"  # a1's tick belongs to "another replica"

        def complete_alert_tick(self, rule_id: str, *, record: dict | None) -> None:
            self.completions.append((rule_id, record is not None))

    stub_store = _ClaimingStubStore()
    app = SimpleNamespace(state=SimpleNamespace(control_plane_store=stub_store))
    dispatcher = AlertDispatcher(app)  # type: ignore[arg-type]

    evaluated: list[str] = []

    async def _fake_dispatch_alert(dispatcher_arg, alert, now_arg):
        evaluated.append(alert.id)
        # a2 advances state; a0 does not.
        return alert, alert.id == "a2", 0

    original = escalation_module.dispatch_alert
    escalation_module.dispatch_alert = _fake_dispatch_alert  # type: ignore[assignment]
    try:
        await dispatcher.dispatch_alerts()
    finally:
        escalation_module.dispatch_alert = original  # type: ignore[assignment]
    del dispatcher_module  # imported for parity with the dispatcher under test

    assert stub_store.claims == ["a0", "a1", "a2"]
    assert evaluated == ["a0", "a2"]  # the lost claim was never evaluated
    assert stub_store.completions == [("a0", False), ("a2", True)]


# --- replay outbox + dead-letter (invariant 8) ------------------------------------


def _seed_dead_letter(
    conn: duckdb.DuckDBPyConnection,
    *,
    event_id: str,
    tenant_id: str = "acme",
    status: str = "failed",
) -> None:
    conn.execute(
        """
        INSERT INTO dead_letter_events (
            event_id, tenant_id, event_type, payload, failure_reason,
            failure_detail, received_at, retry_count, last_retried_at, status
        ) VALUES (?, ?, 'order.created', '{"a": 1}', 'semantic', 'x', ?, 0, NULL, ?)
        """,
        [event_id, tenant_id, datetime.now(UTC), status],
    )


def _seed_outbox(
    conn: duckdb.DuckDBPyConnection,
    *,
    outbox_id: str,
    event_id: str = "evt-1",
    status: str = "pending",
) -> None:
    conn.execute(
        """
        INSERT INTO outbox (id, event_id, payload, topic, status, retry_count, next_attempt_at)
        VALUES (?, ?, '{"a": 1}', 'agentflow.orders', ?, 0, ?)
        """,
        [outbox_id, event_id, status, datetime.now(UTC)],
    )


def test_claim_due_outbox_entries_returns_oldest_first(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    for index in range(3):
        _seed_outbox(conn, outbox_id=f"o{index}", event_id=f"e{index}")
        conn.execute(
            "UPDATE outbox SET created_at = ? WHERE id = ?",
            [datetime.now(UTC) + timedelta(seconds=index), f"o{index}"],
        )

    claimed = outbox_store.claim_due_outbox_entries(limit=2)

    assert [entry.id for entry in claimed] == ["o0", "o1"]
    assert claimed[0].topic == "agentflow.orders"


def test_get_pending_outbox_entry_returns_none_when_not_pending_or_missing(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_outbox(conn, outbox_id="o1", status="sent")
    assert outbox_store.get_pending_outbox_entry("o1") is None
    assert outbox_store.get_pending_outbox_entry("does-not-exist") is None


def test_mark_outbox_sent_flips_both_rows_in_one_transaction(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_outbox(conn, outbox_id="o1", event_id="e1")
    _seed_dead_letter(conn, event_id="e1")

    outbox_store.mark_outbox_sent(outbox_id="o1", event_id="e1")

    assert conn.execute("SELECT status FROM outbox WHERE id = 'o1'").fetchone()[0] == "sent"
    assert (
        conn.execute("SELECT status FROM dead_letter_events WHERE event_id = 'e1'").fetchone()[0]
        == "replayed"
    )


def test_mark_outbox_sent_rolls_back_when_dead_letter_update_fails(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_outbox(conn, outbox_id="o1", event_id="e1")
    conn.execute("DROP TABLE dead_letter_events")

    with pytest.raises(duckdb.Error):
        outbox_store.mark_outbox_sent(outbox_id="o1", event_id="e1")

    assert conn.execute("SELECT status FROM outbox WHERE id = 'o1'").fetchone()[0] == "pending"


def test_schedule_outbox_retry_backs_off_then_fails_and_dead_letters(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_outbox(conn, outbox_id="o1", event_id="e1")
    _seed_dead_letter(conn, event_id="e1")

    outbox_store.schedule_outbox_retry(
        outbox_id="o1", event_id="e1", retry_count=1, error_message="boom", max_retries=2
    )
    status, next_at = conn.execute(
        "SELECT status, next_attempt_at FROM outbox WHERE id = 'o1'"
    ).fetchone()
    assert status == "pending"
    assert next_at is not None

    outbox_store.schedule_outbox_retry(
        outbox_id="o1", event_id="e1", retry_count=2, error_message="boom", max_retries=2
    )
    status, next_at = conn.execute(
        "SELECT status, next_attempt_at FROM outbox WHERE id = 'o1'"
    ).fetchone()
    assert status == "failed"
    assert next_at is None
    assert (
        conn.execute("SELECT status FROM dead_letter_events WHERE event_id = 'e1'").fetchone()[0]
        == "failed"
    )


def test_schedule_outbox_retry_floors_kafka_shaped_errors_at_30s(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_outbox(conn, outbox_id="o1", event_id="e1")
    _seed_dead_letter(conn, event_id="e1")

    outbox_store.schedule_outbox_retry(
        outbox_id="o1",
        event_id="e1",
        retry_count=1,
        error_message="KafkaError{code=_MSG_TIMED_OUT}",
        max_retries=5,
    )

    next_at = conn.execute("SELECT next_attempt_at FROM outbox WHERE id = 'o1'").fetchone()[0]
    assert next_at >= datetime.now(UTC).replace(tzinfo=next_at.tzinfo) + timedelta(seconds=20)


def test_enqueue_outbox_replay_marks_pending_and_inserts_row_in_one_transaction(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_dead_letter(conn, event_id="e1", status="failed")
    replayed_at = datetime.now(UTC)

    outbox_store.enqueue_outbox_replay(
        outbox_id="o1",
        event_id="e1",
        payload={"event_id": "e1", "total_amount": "9.99"},
        topic="events.raw",
        retry_count=1,
        replayed_at=replayed_at,
    )

    dl_status, dl_retry = conn.execute(
        "SELECT status, retry_count FROM dead_letter_events WHERE event_id = 'e1'"
    ).fetchone()
    assert dl_status == "replay_pending"
    assert dl_retry == 1
    outbox_row = conn.execute(
        "SELECT event_id, topic, status FROM outbox WHERE id = 'o1'"
    ).fetchone()
    assert outbox_row == ("e1", "events.raw", "pending")


def test_enqueue_outbox_replay_rolls_back_when_outbox_insert_fails(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_dead_letter(conn, event_id="e1", status="failed")
    conn.execute("DROP TABLE outbox")

    with pytest.raises(duckdb.Error):
        outbox_store.enqueue_outbox_replay(
            outbox_id="o1",
            event_id="e1",
            payload={"event_id": "e1"},
            topic="events.raw",
            retry_count=1,
            replayed_at=datetime.now(UTC),
        )

    assert (
        conn.execute("SELECT status FROM dead_letter_events WHERE event_id = 'e1'").fetchone()[0]
        == "failed"
    )


def test_get_dead_letter_event_for_replay_returns_none_when_missing(
    outbox_store: EmbeddedControlPlaneStore,
) -> None:
    assert outbox_store.get_dead_letter_event_for_replay("ghost") is None


def test_dismiss_dead_letter_event_marks_dismissed(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_dead_letter(conn, event_id="e1")
    outbox_store.dismiss_dead_letter_event("e1")
    assert (
        conn.execute("SELECT status FROM dead_letter_events WHERE event_id = 'e1'").fetchone()[0]
        == "dismissed"
    )


def test_dead_letter_event_exists_is_tenant_scoped(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_dead_letter(conn, event_id="e1", tenant_id="acme")
    assert outbox_store.dead_letter_event_exists("e1", "acme") is True
    assert outbox_store.dead_letter_event_exists("e1", "beta") is False
    assert outbox_store.dead_letter_event_exists("ghost", "acme") is False


def test_get_dead_letter_event_is_tenant_scoped_and_shapes_detail(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_dead_letter(conn, event_id="e1", tenant_id="acme")

    record = outbox_store.get_dead_letter_event("e1", "acme")

    assert record is not None
    assert record["event_id"] == "e1"
    assert record["failure_reason"] == "semantic"
    assert outbox_store.get_dead_letter_event("e1", "beta") is None


def test_list_dead_letter_events_paginates_and_filters_by_reason(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_dead_letter(conn, event_id="e1", tenant_id="acme")
    _seed_dead_letter(conn, event_id="e2", tenant_id="acme")
    _seed_dead_letter(conn, event_id="e-beta", tenant_id="beta")
    conn.execute("UPDATE dead_letter_events SET failure_reason = 'schema' WHERE event_id = 'e2'")

    items, total = outbox_store.list_dead_letter_events(
        tenant_id="acme", reason=None, page=1, page_size=1
    )
    assert total == 2
    assert len(items) == 1

    items, total = outbox_store.list_dead_letter_events(
        tenant_id="acme", reason="schema", page=1, page_size=10
    )
    assert total == 1
    assert items[0]["event_id"] == "e2"


def test_get_dead_letter_stats_counts_by_reason_and_last_24h(
    outbox_store: EmbeddedControlPlaneStore, conn: duckdb.DuckDBPyConnection
) -> None:
    _seed_dead_letter(conn, event_id="e1", tenant_id="acme")
    _seed_dead_letter(conn, event_id="e2", tenant_id="acme")
    _seed_dead_letter(conn, event_id="e-beta", tenant_id="beta")
    conn.execute("UPDATE dead_letter_events SET failure_reason = 'schema' WHERE event_id = 'e2'")

    stats = outbox_store.get_dead_letter_stats("acme")

    assert stats["counts"] == {"semantic": 1, "schema": 1}
    assert stats["last_24h"] == 2


# --- get_control_plane_store resolution + ratchet -------------------------------


def _stub_app(conn: duckdb.DuckDBPyConnection) -> SimpleNamespace:
    engine = SimpleNamespace(_conn=conn)
    return SimpleNamespace(state=SimpleNamespace(query_engine=engine))


def test_get_store_defaults_to_embedded_and_caches_on_app_state(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CONTROL_PLANE_STORE_ENV, raising=False)
    app = _stub_app(conn)

    store = get_control_plane_store(app)  # type: ignore[arg-type]

    assert isinstance(store, EmbeddedControlPlaneStore)
    assert app.state.control_plane_store is store
    assert get_control_plane_store(app) is store  # type: ignore[arg-type]


def test_get_store_postgres_requires_a_dsn(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR 0010: the scale profile must not silently fall back to the embedded
    # (split-brain at replicaCount>1) store — a missing DSN fails the boot.
    monkeypatch.setenv(CONTROL_PLANE_STORE_ENV, "postgres")
    monkeypatch.delenv(CONTROL_PLANE_PG_DSN_ENV, raising=False)
    with pytest.raises(ValueError, match=CONTROL_PLANE_PG_DSN_ENV):
        get_control_plane_store(_stub_app(conn))  # type: ignore[arg-type]


def test_get_store_postgres_resolves_the_adapter_and_caches_it(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.serving.control_plane import postgres as postgres_module
    from src.serving.control_plane.postgres import PostgresControlPlaneStore

    # The selection seam is under test, not psycopg: stub the module object so
    # this resolves identically whether or not the optional dependency is
    # installed (the CI unit job installs no optional extras).
    monkeypatch.setattr(postgres_module, "psycopg", SimpleNamespace())
    monkeypatch.setenv(CONTROL_PLANE_STORE_ENV, "postgres")
    monkeypatch.setenv(CONTROL_PLANE_PG_DSN_ENV, "postgresql://cp@localhost:5432/agentflow")
    app = _stub_app(conn)

    store = get_control_plane_store(app)  # type: ignore[arg-type]

    # Construction is connection-free (schema DDL runs on first method use),
    # so resolution succeeds without a live server.
    assert isinstance(store, PostgresControlPlaneStore)
    assert app.state.control_plane_store is store
    assert get_control_plane_store(app) is store  # type: ignore[arg-type]


def test_get_store_postgres_fails_loudly_without_psycopg(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.serving.control_plane import postgres as postgres_module

    monkeypatch.setenv(CONTROL_PLANE_STORE_ENV, "postgres")
    monkeypatch.setenv(CONTROL_PLANE_PG_DSN_ENV, "postgresql://cp@localhost:5432/agentflow")
    monkeypatch.setattr(postgres_module, "psycopg", None)
    with pytest.raises(RuntimeError, match="psycopg"):
        get_control_plane_store(_stub_app(conn))  # type: ignore[arg-type]


def test_get_store_postgres_rejects_a_malformed_lease_override(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONTROL_PLANE_STORE_ENV, "postgres")
    monkeypatch.setenv(CONTROL_PLANE_PG_DSN_ENV, "postgresql://cp@localhost:5432/agentflow")
    monkeypatch.setenv("AGENTFLOW_CONTROLPLANE_LEASE_SECONDS", "soon")
    with pytest.raises(ValueError, match="LEASE_SECONDS"):
        get_control_plane_store(_stub_app(conn))  # type: ignore[arg-type]


def test_get_store_rejects_unknown_kind(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONTROL_PLANE_STORE_ENV, "sqlite")
    with pytest.raises(ValueError, match="Unknown control-plane store"):
        get_control_plane_store(_stub_app(conn))  # type: ignore[arg-type]


def test_get_store_follows_a_swapped_query_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The embedded adapter must bind to the *live* engine connection (tests and
    # lifespans swap app.state.query_engine), exactly like the pre-port direct
    # ``_conn`` lookups did.
    monkeypatch.delenv(CONTROL_PLANE_STORE_ENV, raising=False)
    first = duckdb.connect(":memory:")
    second = duckdb.connect(":memory:")
    try:
        app = _stub_app(first)
        store = get_control_plane_store(app)  # type: ignore[arg-type]
        assert store._conn is first
        app.state.query_engine = SimpleNamespace(_conn=second)
        assert store._conn is second
    finally:
        first.close()
        second.close()


# --- structural ratchet ----------------------------------------------------------


def test_webhook_path_does_not_reach_into_the_engine_connection() -> None:
    """ADR 0010 slices 1-3 ratchet: the webhook/alert/outbox/dead-letter
    dispatchers and their routers go through the ControlPlaneStore port;
    direct ``query_engine._conn`` reaches must not re-grow there. The single
    sanctioned reach is the composition seam in ``control_plane/store.py``."""
    for relative in (
        "src/serving/api/webhook_dispatcher.py",
        "src/serving/api/routers/webhooks.py",
        "src/serving/api/alerts/dispatcher.py",
        "src/serving/api/alerts/escalation.py",
        "src/serving/api/routers/alerts.py",
        "src/processing/outbox.py",
        "src/processing/event_replayer.py",
        "src/serving/api/routers/deadletter.py",
    ):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "query_engine._conn" not in source, relative


def test_ops_timeline_path_does_not_reach_into_the_engine_connection_or_vault() -> None:
    """ADR 0011 invariant I1: the ops surfaces (Order 360 timeline first,
    D2) compose exactly the QueryEngine/ServingBackend and ControlPlaneStore
    ports — no raw ``query_engine._conn`` reach, no vault DSN, ever."""
    source = (PROJECT_ROOT / "src/serving/api/routers/agent_query.py").read_text(
        encoding="utf-8"
    )
    assert "query_engine._conn" not in source
    assert "_conn." not in source
    assert "VAULT_DSN" not in source
