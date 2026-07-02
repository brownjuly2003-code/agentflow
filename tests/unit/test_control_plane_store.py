"""ADR 0010 slices 1-2: the ControlPlaneStore port and its embedded adapter.

Covers the store-level contract the dispatcher relies on (enqueue-win
semantics, due-claim ordering and bounds, the outcome state machine, parking,
attempt-log roundtrip), the alert-delivery history log and the YAML-backed
alert-rule repository (slice 2), the ``get_control_plane_store``
resolution/ratchet, and the structural pin that keeps the webhook and alert
paths from re-growing direct ``query_engine._conn`` reaches.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from src.serving.control_plane import (
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
def alert_store(
    conn: duckdb.DuckDBPyConnection, tmp_path: Path
) -> EmbeddedControlPlaneStore:
    path = tmp_path / "alerts.yaml"
    return EmbeddedControlPlaneStore(
        conn_provider=lambda: conn, alert_rules_path_provider=lambda: path
    )


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


def test_get_store_postgres_is_a_fail_closed_ratchet_until_slice_5(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR 0010: the scale profile must not silently fall back to the embedded
    # (split-brain at replicaCount>1) store — it fails the boot instead, and
    # this test is deleted only when PostgresControlPlaneStore ships.
    monkeypatch.setenv(CONTROL_PLANE_STORE_ENV, "postgres")
    with pytest.raises(NotImplementedError, match="slice 5"):
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
    """ADR 0010 slices 1-2 ratchet: the webhook/alert dispatchers and their
    routers go through the ControlPlaneStore port; direct ``query_engine._conn``
    reaches must not re-grow there. The single sanctioned reach is the
    composition seam in ``control_plane/store.py``."""
    for relative in (
        "src/serving/api/webhook_dispatcher.py",
        "src/serving/api/routers/webhooks.py",
        "src/serving/api/alerts/dispatcher.py",
        "src/serving/api/alerts/escalation.py",
        "src/serving/api/routers/alerts.py",
    ):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "query_engine._conn" not in source, relative
