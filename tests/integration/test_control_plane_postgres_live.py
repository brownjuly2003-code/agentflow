"""Live probes for ``PostgresControlPlaneStore`` (ADR 0010 rollout slice 5).

This is the probe suite the ADR names for the slice: enqueue-win uniqueness
under parallel writers, parallel claim exclusivity, lease-expiry re-drive,
restart re-drive, outbox↔dead-letter transactional atomicity (invariant 8,
including the rollback half), alert-tick single-flight — plus a contract
parity sweep that exercises every port method against a real PostgreSQL so
the two adapters cannot drift.

Needs a live server: set ``AGENTFLOW_TEST_PG_DSN`` (CI provides a
``postgres:17`` service; locally the standalone-PG recipe from
``docs/perf/vault-pii-governance-pg-verify-2026-07-02.md`` works). The whole
module skips when the env var is absent — the same self-skip pattern as
``test_clickhouse_backend_live.py``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

psycopg = pytest.importorskip("psycopg")

from src.serving.control_plane.postgres import (  # noqa: E402
    _MIGRATIONS,
    _SCHEMA_STATEMENTS,
    PostgresControlPlaneStore,
)
from src.serving.control_plane.store import UsageRow  # noqa: E402

PG_DSN = os.getenv("AGENTFLOW_TEST_PG_DSN", "")

pytestmark = pytest.mark.skipif(
    not PG_DSN,
    reason="AGENTFLOW_TEST_PG_DSN is not set; PostgresControlPlaneStore live probes need a server",
)

_TABLES = (
    "webhook_delivery_queue",
    "webhook_deliveries",
    "alert_history",
    "webhook_registrations",
    "alert_rules",
    "outbox",
    "dead_letter_events",
    "api_usage",
    "api_sessions",
)


@pytest.fixture
def store() -> Iterator[PostgresControlPlaneStore]:
    instance = PostgresControlPlaneStore(PG_DSN)
    instance.ensure_outbox_schema()  # creates the full schema
    with psycopg.connect(PG_DSN) as conn:
        for table in _TABLES:
            conn.execute(f"TRUNCATE {table}")  # noqa: S608 - table names are literals above
    yield instance
    # Every store owns a bounded connection pool now (audit P1-1); leaking
    # ~35 of them across the suite would exhaust the server's slots.
    instance.close()


def _enqueue(store: PostgresControlPlaneStore, webhook_id: str, event_id: str) -> bool:
    return store.enqueue_webhook_delivery(
        webhook_id=webhook_id,
        event_id=event_id,
        tenant="acme",
        event_type="order.created",
        body=json.dumps({"event_id": event_id}),
    )


def _queue_row(webhook_id: str, event_id: str) -> tuple | None:
    with psycopg.connect(PG_DSN) as conn:
        return conn.execute(
            "SELECT status, attempts, next_attempt_at, last_error, lease_expires_at "
            "FROM webhook_delivery_queue WHERE webhook_id = %s AND event_id = %s",
            (webhook_id, event_id),
        ).fetchone()


def _release_enqueue_lease(*event_ids: str) -> None:
    """Hand freshly enqueued rows over to the claim path.

    The enqueue winner stamps a claim lease on insert (it inline-delivers;
    see ``test_enqueue_stamps_lease_so_redrive_cannot_steal_inline``), so a
    fresh row is invisible to ``claim_due_webhook_deliveries`` until an
    outcome clears the lease or it expires. The claim-semantics probes below
    are about the *claim* path, not the inline race — release the lease the
    way expiry would, without disturbing status/attempts/next_attempt_at.
    """
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "UPDATE webhook_delivery_queue SET lease_expires_at = NULL WHERE event_id = ANY(%s)",
            (list(event_ids),),
        )


def _stagger_created_at(table: str, key_column: str, key: str, offset_seconds: int) -> None:
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            f"UPDATE {table} SET created_at = now() + make_interval(secs => %s) "  # noqa: S608
            f"WHERE {key_column} = %s",
            (offset_seconds, key),
        )


def _seed_dead_letter(event_id: str, *, tenant_id: str = "acme", status: str = "failed") -> None:
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            """
            INSERT INTO dead_letter_events (
                event_id, tenant_id, event_type, payload, failure_reason,
                failure_detail, received_at, retry_count, last_retried_at, status
            ) VALUES (%s, %s, 'order.created', '{"a": 1}', 'semantic', 'x', now(), 0, NULL, %s)
            """,
            (event_id, tenant_id, status),
        )


def _seed_outbox(outbox_id: str, *, event_id: str = "evt-1", status: str = "pending") -> None:
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            """
            INSERT INTO outbox (id, event_id, payload, topic, status, retry_count,
                                next_attempt_at)
            VALUES (%s, %s, '{"a": 1}', 'agentflow.orders', %s, 0, now())
            """,
            (outbox_id, event_id, status),
        )


# --- ADR probe 1: enqueue-win uniqueness under parallel writers -------------------


def test_parallel_enqueues_produce_exactly_one_winner(store: PostgresControlPlaneStore) -> None:
    workers = 8
    barrier = threading.Barrier(workers)

    def race() -> bool:
        barrier.wait()
        return _enqueue(store, "wh-1", "e-contested")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        wins = list(pool.map(lambda _: race(), range(workers)))

    assert sum(wins) == 1  # ON CONFLICT DO NOTHING + rowcount: one inline delivery
    with psycopg.connect(PG_DSN) as conn:
        count = conn.execute("SELECT COUNT(*) FROM webhook_delivery_queue").fetchone()[0]
    assert count == 1


def test_enqueue_stamps_lease_so_redrive_cannot_steal_inline(
    store: PostgresControlPlaneStore,
) -> None:
    """Winner holds a claim lease during inline delivery (multi-pod race).

    Without this, the other replica's process_delivery_queue can claim the
    still-pending row while the winner is mid-POST and both emit a delivery.
    """
    assert _enqueue(store, "wh-1", "e-leased") is True
    # Still pending, but leased → claim_due must not hand it out yet.
    assert store.claim_due_webhook_deliveries(limit=10) == []
    status, _, _, _, lease = _queue_row("wh-1", "e-leased")
    assert status == "pending"
    assert lease is not None
    # Outcome clears the lease; a failed inline then schedules backoff redrive.
    store.record_webhook_delivery_outcome(
        webhook_id="wh-1",
        event_id="e-leased",
        success=True,
        status_code=200,
        error=None,
        max_attempts=5,
        backoff_seconds=[1.0, 5.0, 25.0],
    )
    status, _, _, _, lease = _queue_row("wh-1", "e-leased")
    assert status == "delivered"
    assert lease is None


# --- ADR probe 2: parallel claim exclusivity ---------------------------------------


def test_parallel_claims_never_hand_the_same_row_to_two_workers(
    store: PostgresControlPlaneStore,
) -> None:
    for index in range(10):
        _enqueue(store, "wh-1", f"e{index}")
    _release_enqueue_lease(*(f"e{index}" for index in range(10)))
    workers = 4
    barrier = threading.Barrier(workers)

    def claim() -> list[str]:
        barrier.wait()
        return [row.event_id for row in store.claim_due_webhook_deliveries(limit=10)]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        batches = list(pool.map(lambda _: claim(), range(workers)))

    claimed = [event_id for batch in batches for event_id in batch]
    assert len(claimed) == len(set(claimed))  # FOR UPDATE SKIP LOCKED: no double claim
    assert set(claimed) == {f"e{index}" for index in range(10)}  # nothing lost either


def test_claimed_rows_are_invisible_until_their_lease_expires(
    store: PostgresControlPlaneStore,
) -> None:
    _enqueue(store, "wh-1", "e1")
    _release_enqueue_lease("e1")
    assert [row.event_id for row in store.claim_due_webhook_deliveries(limit=10)] == ["e1"]
    # Still pending (the claim is a lease, not a state flip), but leased —
    # a second worker sees nothing.
    assert store.claim_due_webhook_deliveries(limit=10) == []
    status, _, _, _, lease = _queue_row("wh-1", "e1")
    assert status == "pending"
    assert lease is not None


# --- ADR probe 3: lease-expiry re-drive --------------------------------------------


def test_expired_lease_makes_the_row_due_again(store: PostgresControlPlaneStore) -> None:
    short_lease = PostgresControlPlaneStore(PG_DSN, claim_lease_seconds=0.4)
    try:
        _enqueue(short_lease, "wh-1", "e1")
        _release_enqueue_lease("e1")
        assert [row.event_id for row in short_lease.claim_due_webhook_deliveries(limit=10)] == [
            "e1"
        ]
        assert short_lease.claim_due_webhook_deliveries(limit=10) == []
    finally:
        short_lease.close()

    time.sleep(0.6)

    # Crash recovery without coordination: the owner never reported an
    # outcome, the lease ran out, any worker may claim the row again.
    assert [row.event_id for row in store.claim_due_webhook_deliveries(limit=10)] == ["e1"]


def test_outcome_clears_the_lease_so_backoff_alone_governs_redrive(
    store: PostgresControlPlaneStore,
) -> None:
    _enqueue(store, "wh-1", "e1")
    store.claim_due_webhook_deliveries(limit=10)
    store.record_webhook_delivery_outcome(
        webhook_id="wh-1",
        event_id="e1",
        success=False,
        status_code=500,
        error="boom",
        max_attempts=5,
        backoff_seconds=[0.1],
    )
    status, attempts, next_at, _, lease = _queue_row("wh-1", "e1")
    assert (status, attempts) == ("pending", 1)
    assert next_at is not None
    assert lease is None  # the outcome released the claim
    time.sleep(0.2)
    assert [row.event_id for row in store.claim_due_webhook_deliveries(limit=10)] == ["e1"]


# --- ADR probe 4: restart re-drive --------------------------------------------------


def test_pending_delivery_survives_a_new_store_instance(
    store: PostgresControlPlaneStore,
) -> None:
    _enqueue(store, "wh-1", "e1")
    _release_enqueue_lease("e1")  # the winner's inline attempt died with the process
    del store  # simulate process exit; only the PostgreSQL rows remain

    reborn = PostgresControlPlaneStore(PG_DSN)
    try:
        claimed = reborn.claim_due_webhook_deliveries(limit=10)
        assert [row.event_id for row in claimed] == ["e1"]
        assert claimed[0].body == json.dumps({"event_id": "e1"})  # canonical body verbatim
    finally:
        reborn.close()


# --- webhook outcome state machine (parity with the embedded pins) -----------------


def test_outcome_state_machine_backs_off_then_parks_dead(
    store: PostgresControlPlaneStore,
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
    status, attempts, next_at, _, _ = _queue_row("wh-1", "e1")
    assert (status, attempts) == ("pending", 1)
    assert next_at is not None

    store.record_webhook_delivery_outcome(
        webhook_id="wh-1",
        event_id="e1",
        success=False,
        status_code=500,
        error="boom",
        max_attempts=2,
        backoff_seconds=[10.0],
    )
    status, attempts, next_at, _, _ = _queue_row("wh-1", "e1")
    assert (status, attempts) == ("dead", 2)
    assert next_at is None


def test_outcome_success_marks_delivered_and_park_marks_dead(
    store: PostgresControlPlaneStore,
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
    status, _, _, last_error, _ = _queue_row("wh-1", "e1")
    assert (status, last_error) == ("delivered", None)

    _enqueue(store, "ghost", "e2")
    store.park_webhook_delivery(webhook_id="ghost", event_id="e2", error="webhook removed")
    status, _, next_at, last_error, _ = _queue_row("ghost", "e2")
    assert (status, next_at, last_error) == ("dead", None, "webhook removed")


def test_claims_come_back_oldest_first_within_the_limit(
    store: PostgresControlPlaneStore,
) -> None:
    for index in range(3):
        _enqueue(store, "wh-1", f"e{index}")
        _stagger_created_at("webhook_delivery_queue", "event_id", f"e{index}", index)
    _release_enqueue_lease("e0", "e1", "e2")

    claimed = store.claim_due_webhook_deliveries(limit=2)

    assert [row.event_id for row in claimed] == ["e0", "e1"]


# --- attempt log + alert history (parity) ------------------------------------------


def test_webhook_delivery_log_roundtrip_newest_first(store: PostgresControlPlaneStore) -> None:
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
        with psycopg.connect(PG_DSN) as conn:
            conn.execute(
                "UPDATE webhook_deliveries SET delivered_at = now() + make_interval(secs => %s) "
                "WHERE delivery_id = %s",
                (attempt, f"d{attempt}"),
            )

    logs = store.get_webhook_delivery_logs("wh-1")

    assert [entry["delivery_id"] for entry in logs] == ["d2", "d1"]
    assert logs[0]["success"] is True
    assert store.get_webhook_delivery_logs("wh-other") == []
    assert len(store.get_webhook_delivery_logs("wh-1", limit=1)) == 1


def test_alert_history_roundtrip_decodes_payload(store: PostgresControlPlaneStore) -> None:
    store.log_alert_delivery(
        delivery_id="d1",
        alert_id="a1",
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
        status_code=200,
        success=True,
        error=None,
        payload={"alert_id": "a1", "status": "firing"},
    )

    history = store.get_alert_delivery_history("a1")

    assert len(history) == 1
    assert history[0]["payload"] == {"alert_id": "a1", "status": "firing"}
    assert history[0]["window"] == "1h"
    assert store.get_alert_delivery_history("a-ghost") == []


# --- webhook registration + alert rule repositories (parity) -----------------------


def test_webhook_registrations_round_trip_and_full_replace(
    store: PostgresControlPlaneStore,
) -> None:
    first = [
        {"id": "wh-1", "url": "https://a.test/h", "tenant": "acme", "active": True},
        {"id": "wh-2", "url": "https://b.test/h", "tenant": "beta", "active": True},
    ]
    store.save_webhook_registrations(first)
    assert store.load_webhook_registrations() == first

    # Full-set save has the YAML file's replace semantics: wh-2 disappears.
    second = [{"id": "wh-1", "url": "https://a.test/h", "tenant": "acme", "active": False}]
    store.save_webhook_registrations(second)
    assert store.load_webhook_registrations() == second

    store.save_webhook_registrations([])
    assert store.load_webhook_registrations() == []


def test_alert_rules_round_trip_preserves_order(store: PostgresControlPlaneStore) -> None:
    rules = [
        {"id": "a2", "name": "second-created-first", "state": "firing"},
        {"id": "a1", "name": "listed-after", "state": "ok"},
    ]

    store.save_alert_rules(rules)

    assert store.load_alert_rules() == rules  # position column, not id order


def test_record_sets_require_ids(store: PostgresControlPlaneStore) -> None:
    with pytest.raises(ValueError, match="'id'"):
        store.save_alert_rules([{"name": "no id"}])


# --- ADR probe 6: alert tick single-flight ------------------------------------------


def test_alert_tick_claim_single_flights_and_releases(
    store: PostgresControlPlaneStore,
) -> None:
    store.save_alert_rules([{"id": "a1", "state": "ok"}])

    assert store.claim_alert_tick("a1", lease_seconds=60.0) is True
    # Second claimant (another replica's dispatcher tick) loses.
    assert store.claim_alert_tick("a1", lease_seconds=60.0) is False

    # Completion releases the claim and persists the advanced state in the
    # same transaction.
    store.complete_alert_tick("a1", record={"id": "a1", "state": "firing"})
    assert store.load_alert_rules() == [{"id": "a1", "state": "firing"}]
    assert store.claim_alert_tick("a1", lease_seconds=60.0) is True


def test_alert_tick_claim_expires_on_its_own(store: PostgresControlPlaneStore) -> None:
    store.save_alert_rules([{"id": "a1", "state": "ok"}])
    assert store.claim_alert_tick("a1", lease_seconds=0.4) is True
    assert store.claim_alert_tick("a1", lease_seconds=0.4) is False
    time.sleep(0.6)
    # A crashed claim owner silences a rule only until the lease runs out.
    assert store.claim_alert_tick("a1", lease_seconds=0.4) is True


def test_crud_save_does_not_release_an_in_flight_tick_claim(
    store: PostgresControlPlaneStore,
) -> None:
    store.save_alert_rules([{"id": "a1", "state": "ok"}])
    assert store.claim_alert_tick("a1", lease_seconds=60.0) is True

    # A concurrent CRUD full-set save (update_alert / deactivate_alert on
    # another pod) must not hand this rule's tick to a second evaluator.
    store.save_alert_rules([{"id": "a1", "state": "ok", "name": "renamed"}])

    assert store.claim_alert_tick("a1", lease_seconds=60.0) is False


def test_complete_alert_tick_without_record_only_releases(
    store: PostgresControlPlaneStore,
) -> None:
    store.save_alert_rules([{"id": "a1", "state": "ok"}])
    assert store.claim_alert_tick("a1", lease_seconds=60.0) is True

    store.complete_alert_tick("a1", record=None)

    assert store.load_alert_rules() == [{"id": "a1", "state": "ok"}]  # untouched
    assert store.claim_alert_tick("a1", lease_seconds=60.0) is True  # released


# --- ADR probe 5: outbox↔dead-letter atomicity (invariant 8) ------------------------


def test_mark_outbox_sent_flips_both_rows_in_one_transaction(
    store: PostgresControlPlaneStore,
) -> None:
    _seed_outbox("o1", event_id="e1")
    _seed_dead_letter("e1")

    store.mark_outbox_sent(outbox_id="o1", event_id="e1")

    with psycopg.connect(PG_DSN) as conn:
        outbox_status = conn.execute("SELECT status FROM outbox WHERE id = 'o1'").fetchone()[0]
        dl_status = conn.execute(
            "SELECT status FROM dead_letter_events WHERE event_id = 'e1'"
        ).fetchone()[0]
    assert (outbox_status, dl_status) == ("sent", "replayed")


def test_mark_outbox_sent_rolls_back_when_dead_letter_update_fails(
    store: PostgresControlPlaneStore,
) -> None:
    _seed_outbox("o1", event_id="e1")
    with psycopg.connect(PG_DSN) as conn:
        conn.execute("DROP TABLE dead_letter_events")

    try:
        with pytest.raises(psycopg.Error):
            store.mark_outbox_sent(outbox_id="o1", event_id="e1")

        # The transaction rolled back: the outbox flip did not survive alone.
        with psycopg.connect(PG_DSN) as conn:
            status = conn.execute("SELECT status FROM outbox WHERE id = 'o1'").fetchone()[0]
        assert status == "pending"
    finally:
        # Repair the fault injection with raw baseline DDL. A fresh store
        # deliberately re-creates nothing here: the migration ledger already
        # records the schema as applied, and lazily resurrecting dropped
        # tables is exactly the hazard the adapter's docstring pins.
        with psycopg.connect(PG_DSN) as conn:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)  # restore the table


def test_enqueue_outbox_replay_rolls_back_when_outbox_insert_fails(
    store: PostgresControlPlaneStore,
) -> None:
    _seed_dead_letter("e1", status="failed")
    with psycopg.connect(PG_DSN) as conn:
        conn.execute("DROP TABLE outbox")

    try:
        with pytest.raises(psycopg.Error):
            store.enqueue_outbox_replay(
                outbox_id="o1",
                event_id="e1",
                payload={"event_id": "e1"},
                topic="events.raw",
                retry_count=1,
                replayed_at=datetime.now(UTC),
            )

        with psycopg.connect(PG_DSN) as conn:
            status = conn.execute(
                "SELECT status FROM dead_letter_events WHERE event_id = 'e1'"
            ).fetchone()[0]
        assert status == "failed"  # the dead-letter flip rolled back too
    finally:
        # Repair the fault injection with raw baseline DDL. A fresh store
        # deliberately re-creates nothing here: the migration ledger already
        # records the schema as applied, and lazily resurrecting dropped
        # tables is exactly the hazard the adapter's docstring pins.
        with psycopg.connect(PG_DSN) as conn:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)


def test_enqueue_outbox_replay_marks_pending_and_inserts_in_one_transaction(
    store: PostgresControlPlaneStore,
) -> None:
    _seed_dead_letter("e1", status="failed")
    replayed_at = datetime.now(UTC)

    store.enqueue_outbox_replay(
        outbox_id="o1",
        event_id="e1",
        payload={"event_id": "e1", "total_amount": "9.99"},
        topic="events.raw",
        retry_count=1,
        replayed_at=replayed_at,
    )

    with psycopg.connect(PG_DSN) as conn:
        dl_status, dl_retry = conn.execute(
            "SELECT status, retry_count FROM dead_letter_events WHERE event_id = 'e1'"
        ).fetchone()
        outbox_row = conn.execute(
            "SELECT event_id, topic, status FROM outbox WHERE id = 'o1'"
        ).fetchone()
    assert (dl_status, dl_retry) == ("replay_pending", 1)
    assert outbox_row == ("e1", "events.raw", "pending")


def test_schedule_outbox_retry_backs_off_then_fails_and_dead_letters(
    store: PostgresControlPlaneStore,
) -> None:
    _seed_outbox("o1", event_id="e1")
    _seed_dead_letter("e1")

    store.schedule_outbox_retry(
        outbox_id="o1", event_id="e1", retry_count=1, error_message="boom", max_retries=2
    )
    with psycopg.connect(PG_DSN) as conn:
        status, next_at = conn.execute(
            "SELECT status, next_attempt_at FROM outbox WHERE id = 'o1'"
        ).fetchone()
    assert status == "pending"
    assert next_at is not None

    store.schedule_outbox_retry(
        outbox_id="o1", event_id="e1", retry_count=2, error_message="boom", max_retries=2
    )
    with psycopg.connect(PG_DSN) as conn:
        status, next_at = conn.execute(
            "SELECT status, next_attempt_at FROM outbox WHERE id = 'o1'"
        ).fetchone()
        dl_status = conn.execute(
            "SELECT status FROM dead_letter_events WHERE event_id = 'e1'"
        ).fetchone()[0]
    assert (status, next_at, dl_status) == ("failed", None, "failed")


def test_schedule_outbox_retry_floors_kafka_shaped_errors_at_30s(
    store: PostgresControlPlaneStore,
) -> None:
    _seed_outbox("o1", event_id="e1")

    store.schedule_outbox_retry(
        outbox_id="o1",
        event_id="e1",
        retry_count=1,
        error_message="KafkaError{code=_MSG_TIMED_OUT}",
        max_retries=5,
    )

    with psycopg.connect(PG_DSN) as conn:
        next_at = conn.execute("SELECT next_attempt_at FROM outbox WHERE id = 'o1'").fetchone()[0]
    assert next_at >= datetime.now(UTC) + timedelta(seconds=20)


def test_outbox_claims_are_leased_and_claim_by_id_is_exclusive(
    store: PostgresControlPlaneStore,
) -> None:
    for index in range(3):
        _seed_outbox(f"o{index}", event_id=f"e{index}")
        _stagger_created_at("outbox", "id", f"o{index}", index)

    claimed = store.claim_due_outbox_entries(limit=2)
    assert [entry.id for entry in claimed] == ["o0", "o1"]
    assert claimed[0].topic == "agentflow.orders"

    # o0/o1 are leased; only o2 is left for a second claimant.
    assert [entry.id for entry in store.claim_due_outbox_entries(limit=10)] == ["o2"]

    # Claim-by-id (the replay inline path): everything is leased now.
    assert store.get_pending_outbox_entry("o0") is None
    store.mark_outbox_sent(outbox_id="o0", event_id="e0")
    assert store.get_pending_outbox_entry("o0") is None  # sent, not pending

    # A freshly inserted replay row is claimable by id exactly once.
    _seed_outbox("o-replay", event_id="e-replay")
    entry = store.get_pending_outbox_entry("o-replay")
    assert entry is not None
    assert entry.event_id == "e-replay"
    assert store.get_pending_outbox_entry("o-replay") is None


# --- dead-letter reads (parity) ------------------------------------------------------


def test_dead_letter_reads_are_tenant_scoped_and_paginate(
    store: PostgresControlPlaneStore,
) -> None:
    _seed_dead_letter("e1", tenant_id="acme")
    _seed_dead_letter("e2", tenant_id="acme")
    _seed_dead_letter("e-beta", tenant_id="beta")
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "UPDATE dead_letter_events SET failure_reason = 'schema' WHERE event_id = 'e2'"
        )

    assert store.dead_letter_event_exists("e1", "acme") is True
    assert store.dead_letter_event_exists("e1", "beta") is False

    record = store.get_dead_letter_event("e1", "acme")
    assert record is not None
    assert record["failure_reason"] == "semantic"
    assert store.get_dead_letter_event("e1", "beta") is None

    items, total = store.list_dead_letter_events(tenant_id="acme", reason=None, page=1, page_size=1)
    assert total == 2
    assert len(items) == 1

    items, total = store.list_dead_letter_events(
        tenant_id="acme", reason="schema", page=1, page_size=10
    )
    assert total == 1
    assert items[0]["event_id"] == "e2"

    stats = store.get_dead_letter_stats("acme")
    assert stats["counts"] == {"semantic": 1, "schema": 1}
    assert stats["last_24h"] == 2
    assert len(stats["trend"]) >= 1

    replay_row = store.get_dead_letter_event_for_replay("e1")
    assert replay_row is not None
    assert json.loads(replay_row["payload"]) == {"a": 1}
    assert store.get_dead_letter_event_for_replay("ghost") is None

    store.dismiss_dead_letter_event("e1")
    with psycopg.connect(PG_DSN) as conn:
        status = conn.execute(
            "SELECT status FROM dead_letter_events WHERE event_id = 'e1'"
        ).fetchone()[0]
    assert status == "dismissed"


# --- usage accounting + session analytics (parity) ----------------------------------


def test_usage_roundtrip_by_tenant_key_and_old_key_slot(
    store: PostgresControlPlaneStore,
) -> None:
    store.ensure_usage_schema()
    for endpoint in ("/v1/query", "/v1/entity"):
        store.record_api_usage(
            tenant="acme",
            key_name="agent",
            endpoint=endpoint,
            key_id="k1",
            key_slot="current",
        )
    store.record_api_usage(
        tenant="beta", key_name="etl", endpoint="/v1/query", key_id="k-old", key_slot="previous"
    )

    assert store.get_usage_by_tenant() == [
        {"tenant": "acme", "requests_last_24h": 2},
        {"tenant": "beta", "requests_last_24h": 1},
    ]
    assert store.get_usage_by_key() == {("acme", "agent"): 2, ("beta", "etl"): 1}
    assert store.get_old_key_usage_by_key_id() == {"k-old": 1}


def _session_record(**overrides: object) -> dict:
    record = {
        "tenant": "acme",
        "key_name": "agent",
        "endpoint": "/v1/query",
        "method": "POST",
        "status_code": 200,
        "duration_ms": 12.5,
        "cache_hit": False,
        "entity_type": None,
        "entity_id": None,
        "metric_name": None,
        "query_engine": "duckdb",
        "query_text": "revenue today",
    }
    record.update(overrides)
    return record


def test_session_writes_are_idempotent_per_request_id(
    store: PostgresControlPlaneStore,
) -> None:
    store.record_api_session("r1", _session_record())
    # A retried background write must not double-count (insert-or-replace).
    store.record_api_session("r1", _session_record(status_code=500))

    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute("SELECT status_code FROM api_sessions").fetchall()
    assert rows == [(500,)]


def test_session_analytics_windows_and_shapes(store: PostgresControlPlaneStore) -> None:
    store.record_api_session("r1", _session_record())
    store.record_api_session("r2", _session_record(status_code=500, cache_hit=True))
    store.record_api_session(
        "r3",
        _session_record(
            tenant="beta",
            endpoint="/v1/entity/order/ORD-1",
            entity_type="order",
            entity_id="ORD-1",
            query_text=None,
        ),
    )

    usage = store.get_usage_analytics(window="1h")
    assert usage["window"] == "1h"
    acme = next(item for item in usage["tenants"] if item["tenant"] == "acme")
    assert acme["total_requests"] == 2
    assert acme["error_rate"] == pytest.approx(0.5)
    assert acme["cache_hit_rate"] == pytest.approx(0.5)
    assert acme["top_endpoints"] == ["/v1/query"]

    scoped = store.get_usage_analytics(window="1h", tenant="beta")
    assert [item["tenant"] for item in scoped["tenants"]] == ["beta"]

    top_queries = store.get_top_queries(window="1h")
    assert top_queries["queries"][0] == {"query": "revenue today", "count": 2}

    top_entities = store.get_top_entities(window="1h")
    assert top_entities["entities"][0] == {
        "entity_type": "order",
        "entity_id": "ORD-1",
        "count": 1,
    }

    latency = store.get_latency_analytics(window="1h")
    endpoints = {item["endpoint"]: item for item in latency["endpoints"]}
    assert endpoints["/v1/query"]["requests"] == 2
    assert endpoints["/v1/query"]["p50_ms"] == pytest.approx(12.5)

    anomalies = store.get_anomalies(window="24h")
    assert anomalies["anomalies"] == []  # no history to spike against

    assert store.get_queries_per_second_last_minute() == pytest.approx(3 / 60.0, abs=0.01)

    with pytest.raises(ValueError, match="Invalid window"):
        store.get_usage_analytics(window="fortnight")


def test_qps_degrades_to_zero_when_the_server_is_unreachable() -> None:
    # pool_timeout_seconds bounds the checkout wait: PoolTimeout is a
    # psycopg.OperationalError subclass, so the degrade-to-zero guard sees
    # the same exception family it always did — just after the pool gives
    # up instead of after connect_timeout.
    unreachable = PostgresControlPlaneStore(
        "postgresql://nobody@127.0.0.1:1/agentflow?connect_timeout=1",
        pool_timeout_seconds=1.5,
    )
    try:
        assert unreachable.get_queries_per_second_last_minute() == 0.0
    finally:
        unreachable.close()


# --- end to end: the app on the postgres profile ------------------------------------


def test_app_on_postgres_profile_shares_state_across_boots(
    store: PostgresControlPlaneStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The split-brain the ADR set out to kill, demonstrated dead: a webhook
    registered through one app boot is visible to a *fresh* boot (a second
    pod, in production terms), because registrations, usage and sessions all
    live in PostgreSQL — no per-pod YAML, no per-pod DuckDB file."""
    from datetime import datetime as _datetime

    from fastapi.testclient import TestClient

    from src.serving.api.auth import TenantKey
    from src.serving.api.main import app

    monkeypatch.setenv("AGENTFLOW_CONTROLPLANE_STORE", "postgres")
    monkeypatch.setenv("AGENTFLOW_CONTROLPLANE_PG_DSN", PG_DSN)

    previous_webhook_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
    previous_alert_autostart = getattr(app.state, "alert_dispatcher_autostart", True)
    app.state.webhook_dispatcher_autostart = False
    app.state.alert_dispatcher_autostart = False

    def _authenticate(client: TestClient) -> None:
        manager = client.app.state.auth_manager
        manager.keys_by_value = {
            "acme-key": TenantKey(
                key="acme-key",
                name="acme-agent",
                tenant="acme",
                rate_limit_rpm=100,
                allowed_entity_types=None,
                created_at=_datetime.now(UTC).date(),
            )
        }
        manager._rate_windows.clear()

    try:
        with TestClient(app) as first_boot:
            assert isinstance(first_boot.app.state.control_plane_store, PostgresControlPlaneStore)
            # AuthManager shares the app-wide store on this profile (slice 5
            # injection in main.py) — usage/sessions land in PostgreSQL.
            assert first_boot.app.state.auth_manager.store is (
                first_boot.app.state.control_plane_store
            )
            _authenticate(first_boot)
            response = first_boot.post(
                "/v1/webhooks",
                headers={"X-API-Key": "acme-key"},
                json={"url": "http://agent.test/webhook", "filters": {}},
            )
            assert response.status_code == 201
            webhook_id = response.json()["id"]

        with TestClient(app) as second_boot:
            _authenticate(second_boot)
            response = second_boot.get("/v1/webhooks", headers={"X-API-Key": "acme-key"})
            assert response.status_code == 200
            assert [item["id"] for item in response.json()["webhooks"]] == [webhook_id]
    finally:
        app.state.webhook_dispatcher_autostart = previous_webhook_autostart
        app.state.alert_dispatcher_autostart = previous_alert_autostart

    with psycopg.connect(PG_DSN) as conn:
        registrations = conn.execute("SELECT COUNT(*) FROM webhook_registrations").fetchone()[0]
        usage_tenants = conn.execute("SELECT DISTINCT tenant FROM api_usage").fetchall()
    assert registrations == 1
    assert usage_tenants == [("acme",)]  # request accounting went to PostgreSQL too


# --- audit P1-1 probes: bounded pool, one-transaction batch, versioned migrations ---


def test_pool_bounds_connections_under_concurrent_writers() -> None:
    tight = PostgresControlPlaneStore(PG_DSN, pool_min_size=1, pool_max_size=3)
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [
                pool.submit(
                    tight.record_api_usage,
                    tenant="pool-probe",
                    key_name="k",
                    endpoint=f"/v1/entity/{index}",
                    key_id=None,
                    key_slot="current",
                )
                for index in range(48)
            ]
            for future in futures:
                future.result(timeout=60)
        # The budget held under 16 concurrent writers: the pool never grew
        # past its ceiling, and no write was dropped to achieve that.
        assert tight._pool.get_stats()["pool_size"] <= 3
        with psycopg.connect(PG_DSN) as conn:
            written = conn.execute(
                "SELECT COUNT(*) FROM api_usage WHERE tenant = 'pool-probe'"
            ).fetchone()[0]
        assert written == 48
    finally:
        tight.close()


def test_usage_batch_lands_as_one_transaction(store: PostgresControlPlaneStore) -> None:
    store.record_api_usage_batch([])  # empty batch: no connection, no error

    rows = [
        UsageRow(
            tenant="acme",
            key_name="k",
            endpoint=f"/v1/metric/{index}",
            key_id=None,
            key_slot="current",
        )
        for index in range(256)
    ]
    store.record_api_usage_batch(rows)
    with psycopg.connect(PG_DSN) as conn:
        distinct_xmin, total = conn.execute(
            "SELECT COUNT(DISTINCT xmin::text), COUNT(*) FROM api_usage"
        ).fetchone()
    assert total == 256
    # Every row carries the same inserting-transaction id: the batch was ONE
    # transaction, not 256 connect/commit cycles (audit P1-1).
    assert distinct_xmin == 1


def test_schema_version_ledger_is_stamped_and_stable(store: PostgresControlPlaneStore) -> None:
    with psycopg.connect(PG_DSN) as conn:
        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM control_plane_schema_version ORDER BY version"
            ).fetchall()
        ]
    assert versions == [version for version, _, _ in _MIGRATIONS]

    # A second store on the same database reads the ledger and applies nothing.
    second = PostgresControlPlaneStore(PG_DSN)
    try:
        second.ping()
        with psycopg.connect(PG_DSN) as conn:
            recount = conn.execute("SELECT COUNT(*) FROM control_plane_schema_version").fetchone()[
                0
            ]
        assert recount == len(_MIGRATIONS)
    finally:
        second.close()


def test_pre_versioning_database_upgrades_in_place_without_data_loss(
    store: PostgresControlPlaneStore,
) -> None:
    # A deployment provisioned before the ledger existed: tables and data are
    # present, control_plane_schema_version is not.
    store.record_api_usage(
        tenant="acme", key_name="k", endpoint="/v1/entity", key_id=None, key_slot="current"
    )
    with psycopg.connect(PG_DSN) as conn:
        conn.execute("DROP TABLE control_plane_schema_version")

    reborn = PostgresControlPlaneStore(PG_DSN)
    try:
        reborn.ping()  # first use runs the migration path
        with psycopg.connect(PG_DSN) as conn:
            surviving = conn.execute("SELECT COUNT(*) FROM api_usage").fetchone()[0]
            versions = [
                row[0]
                for row in conn.execute(
                    "SELECT version FROM control_plane_schema_version ORDER BY version"
                ).fetchall()
            ]
        # Baseline DDL is pure IF NOT EXISTS: the pre-upgrade row survived,
        # and the database is now stamped like a fresh one.
        assert surviving == 1
        assert versions == [version for version, _, _ in _MIGRATIONS]
    finally:
        reborn.close()


def test_concurrent_replicas_serialize_the_migration_run(
    store: PostgresControlPlaneStore,
) -> None:
    # Without the advisory lock, N fresh replicas racing _ensure_schema would
    # all read MAX(version)=0 and all INSERT version 1 — the losers die on the
    # primary key. With it they queue, and the losers apply nothing.
    with psycopg.connect(PG_DSN) as conn:
        conn.execute("DROP TABLE control_plane_schema_version")

    replicas = [PostgresControlPlaneStore(PG_DSN) for _ in range(4)]
    barrier = threading.Barrier(len(replicas))

    def boot(replica: PostgresControlPlaneStore) -> None:
        barrier.wait()
        replica.ping()

    try:
        with ThreadPoolExecutor(max_workers=len(replicas)) as pool:
            list(pool.map(boot, replicas))
        with psycopg.connect(PG_DSN) as conn:
            versions = [
                row[0]
                for row in conn.execute(
                    "SELECT version FROM control_plane_schema_version ORDER BY version"
                ).fetchall()
            ]
        assert versions == [version for version, _, _ in _MIGRATIONS]
    finally:
        for replica in replicas:
            replica.close()


def test_process_roles_split_serving_from_delivery_loops(
    store: PostgresControlPlaneStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit P1-1 acceptance: API replicas without the worker role run no
    background delivery loops — scaling them multiplies request capacity,
    not PostgreSQL scanners — and the worker runs the loops without the
    serving-side cache machinery."""
    from fastapi.testclient import TestClient

    from src.serving.api.main import app

    monkeypatch.setenv("AGENTFLOW_CONTROLPLANE_STORE", "postgres")
    monkeypatch.setenv("AGENTFLOW_CONTROLPLANE_PG_DSN", PG_DSN)

    monkeypatch.setenv("AGENTFLOW_PROCESS_ROLE", "api")
    with TestClient(app):
        assert app.state.process_role == "api"
        assert app.state.outbox_processor_task is None
        assert app.state.webhook_dispatcher._task is None
        assert app.state.alert_dispatcher._task is None
        assert app.state.search_index_rebuild_task is not None  # it still serves search

    monkeypatch.setenv("AGENTFLOW_PROCESS_ROLE", "worker")
    with TestClient(app):
        assert app.state.process_role == "worker"
        assert app.state.outbox_processor_task is not None
        assert app.state.webhook_dispatcher._task is not None
        assert app.state.alert_dispatcher._task is not None
        assert app.state.search_index_rebuild_task is None  # nobody asks it questions
