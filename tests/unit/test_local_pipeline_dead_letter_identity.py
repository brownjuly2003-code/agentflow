"""AF-10: id-less dead-letters must not share one pipeline_events identity.

Every reject without an ``event_id`` used to journal under the literal
``'unknown'``, so a later real event whose id *is* ``unknown`` was treated as
an already-seen duplicate. These tests pin a fresh ``missing-id:<uuid4>``
journal identity per id-less event, without changing the Iceberg dead-letter
row (raw payload id stays null).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import duckdb
import pytest

from agentflow_runtime.ingestion.producers.event_producer import generate_order
from agentflow_runtime.processing.local_pipeline import (
    _ensure_tables,
    _process_event,
    _process_event_serving_only,
    apply_serving_batch,
)

# Locked journal prefix. Imported by name in helper tests; inlined here so the
# pipeline-path cases still collect (and fail on the 'unknown' collision)
# before the helper exists.
_MISSING_ID_PREFIX = "missing-id:"


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    _ensure_tables(connection)
    try:
        yield connection
    finally:
        connection.close()


def _order_event() -> dict:
    _, event = generate_order()
    return json.loads(event.model_dump_json())


def _cdc_event(*, event_id: str) -> dict:
    """Schema-valid CDC payload; CdcEvent is the only canonical model that
    accepts a non-UUID ``event_id`` such as the literal ``'unknown'``."""
    return {
        "event_id": event_id,
        "event_type": "orders.update",
        "operation": "update",
        "timestamp": "2026-08-25T10:00:00+00:00",
        "source": "postgres_cdc",
        "entity_type": "orders",
        "entity_id": "1",
        "before": {"status": "pending"},
        "after": {"status": "paid"},
        "source_metadata": {"db": "shop", "lsn": 42},
    }


class FakeServingSink:
    """Records every apply_serving_batch ClickHouse round-trip."""

    def __init__(self) -> None:
        self.insert_orders_calls: list[list[dict]] = []
        self.insert_products_calls: list[list[dict]] = []
        self.upsert_sessions_calls: list[list[dict]] = []
        self.refresh_user_aggregates_calls: list[object] = []
        self.journal_batches: list[list[dict]] = []

    def insert_orders(self, events: list[dict]) -> None:
        self.insert_orders_calls.append(events)

    def insert_products(self, events: list[dict]) -> None:
        self.insert_products_calls.append(events)

    def upsert_sessions(self, events: list[dict]) -> None:
        self.upsert_sessions_calls.append(events)

    def refresh_user_aggregates(self, users: object) -> None:
        self.refresh_user_aggregates_calls.append(users)

    def record_pipeline_events(self, rows: list[dict]) -> None:
        self.journal_batches.append(rows)


class TestJournalEventId:
    def test_returns_own_id_unchanged_for_string_and_non_string(self) -> None:
        from agentflow_runtime.processing.local_pipeline import _journal_event_id

        assert _journal_event_id({"event_id": "evt-1"}) == "evt-1"
        assert _journal_event_id({"event_id": 42}) == "42"

    def test_missing_none_and_empty_get_fresh_prefixed_identities(self) -> None:
        from agentflow_runtime.processing.local_pipeline import (
            MISSING_EVENT_ID_PREFIX,
            _journal_event_id,
        )

        for payload in ({}, {"event_id": None}, {"event_id": ""}):
            first = _journal_event_id(payload)
            second = _journal_event_id(payload)
            assert first.startswith(MISSING_EVENT_ID_PREFIX)
            assert second.startswith(MISSING_EVENT_ID_PREFIX)
            assert first != second
            assert first != "unknown"
            assert second != "unknown"


def test_two_idless_rejects_journal_two_distinct_prefixed_rows(conn) -> None:
    first = _order_event()
    second = _order_event()
    del first["event_id"]
    del second["event_id"]

    ok_first, reason_first = _process_event(conn, first)
    ok_second, reason_second = _process_event(conn, second)

    assert ok_first is False
    assert ok_second is False
    assert reason_first
    assert reason_second
    rows = conn.execute(
        "SELECT event_id FROM pipeline_events WHERE topic = 'events.deadletter' ORDER BY 1"
    ).fetchall()
    assert len(rows) == 2
    ids = [row[0] for row in rows]
    assert ids[0] != ids[1]
    for event_id in ids:
        assert event_id.startswith(_MISSING_ID_PREFIX)
        assert event_id != "unknown"


def test_synthetic_identity_does_not_shadow_literal_unknown(conn) -> None:
    idless = _order_event()
    del idless["event_id"]
    ok_idless, _ = _process_event(conn, idless)
    assert ok_idless is False

    # OrderEvent.event_id is constrained to a 36-char UUID pattern, so a
    # schema-valid event whose id is the literal "unknown" has to be CDC.
    unknown = _cdc_event(event_id="unknown")
    ok_unknown, reason = _process_event(conn, unknown)

    assert ok_unknown is True
    assert reason == "ok"
    rows = conn.execute(
        "SELECT event_id, topic FROM pipeline_events WHERE event_id = 'unknown'"
    ).fetchall()
    assert rows == [("unknown", "events.validated")]
    deadletter_unknown = conn.execute(
        "SELECT COUNT(*) FROM pipeline_events "
        "WHERE event_id = 'unknown' AND topic = 'events.deadletter'"
    ).fetchone()
    assert deadletter_unknown == (0,)


def test_schema_invalid_event_with_real_id_is_journaled_under_that_id(conn) -> None:
    event = _order_event()
    real_id = str(event["event_id"])
    del event["items"]

    success, reason = _process_event(conn, event)

    assert success is False
    assert reason.startswith("schema:")
    row = conn.execute(
        "SELECT event_id FROM pipeline_events WHERE topic = 'events.deadletter'"
    ).fetchone()
    assert row is not None
    assert row[0] == real_id
    assert not str(row[0]).startswith(_MISSING_ID_PREFIX)


def test_serving_only_idless_events_get_distinct_prefixed_result_ids() -> None:
    # _process_event_serving_only is a one-event wrapper around apply_serving_batch
    # and discards the event_id from the returned tuple. The unknown-fallback
    # and results.append((event_id, ...)) live in apply_serving_batch; that is
    # the serving-only path. The wrapper still calls insert_orders /
    # insert_products / upsert_sessions / refresh_user_aggregates /
    # record_pipeline_events, so the fake sink stubs all five.
    sink = FakeServingSink()
    events = []
    for _ in range(2):
        event = _order_event()
        del event["event_id"]
        events.append(event)

    wrapper_outcomes = [
        _process_event_serving_only(events[0], sink),
        _process_event_serving_only(events[1], sink),
    ]
    assert wrapper_outcomes[0][0] is False
    assert wrapper_outcomes[1][0] is False

    batch_sink = FakeServingSink()
    results = apply_serving_batch(events, batch_sink)

    assert len(results) == 2
    ids = [event_id for event_id, _ok, _reason in results]
    assert ids[0] != ids[1]
    for event_id, ok, reason in results:
        assert ok is False
        assert reason
        assert event_id.startswith(_MISSING_ID_PREFIX)
        assert event_id != "unknown"

    assert len(batch_sink.journal_batches) == 1
    journal_rows = batch_sink.journal_batches[0]
    assert len(journal_rows) == 2
    journal_ids = [row["event_id"] for row in journal_rows]
    assert journal_ids == ids
    for row in journal_rows:
        assert row["topic"] == "events.deadletter"

    wrapper_ids = [row["event_id"] for batch in sink.journal_batches for row in batch]
    assert len(wrapper_ids) == 2
    assert wrapper_ids[0] != wrapper_ids[1]
    for event_id in wrapper_ids:
        assert event_id.startswith(_MISSING_ID_PREFIX)
        assert event_id != "unknown"
