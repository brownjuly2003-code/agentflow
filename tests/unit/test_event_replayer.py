"""Unit coverage for ``src.processing.event_replayer``: the dead-letter
replay / dismiss paths, payload decoding, the schema+semantic validation gate,
and the not-found / invalid-payload error branches.

Exercised at the unit layer with an in-memory DuckDB connection and an injected
stub producer, so a replay or validation regression fails fast without Kafka.
The full streaming path is covered by ``tests/integration/test_deadletter.py``
and ``tests/integration/test_outbox.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import duckdb
import pytest

from src.processing.event_replayer import (
    DeadLetterEventNotFoundError,
    EventReplayer,
    ReplayValidationError,
    ensure_dead_letter_table,
)

# Event schema pins event_id to a 36-char uuid pattern (^[a-f0-9\-]{36}$).
EVENT_ID_1 = "11111111-1111-4111-8111-111111111111"
EVENT_ID_2 = "22222222-2222-4222-8222-222222222222"
EVENT_ID_3 = "33333333-3333-4333-8333-333333333333"
EVENT_ID_5 = "55555555-5555-4555-8555-555555555555"


def _valid_payload(event_id: str = EVENT_ID_1) -> dict:
    # items sum to 99.99, matching total_amount, so semantic validation passes.
    return {
        "event_id": event_id,
        "event_type": "order.created",
        "timestamp": "2026-04-10T13:00:00+00:00",
        "source": "replayer-test",
        "order_id": "ORD-20260410-9001",
        "user_id": "USR-42",
        "status": "confirmed",
        "items": [
            {"product_id": "PROD-001", "quantity": 1, "unit_price": "79.99"},
            {"product_id": "PROD-002", "quantity": 1, "unit_price": "20.00"},
        ],
        "total_amount": "99.99",
        "currency": "USD",
    }


def _insert_dead_letter(
    conn: duckdb.DuckDBPyConnection,
    *,
    event_id: str,
    payload: dict,
    status: str = "failed",
    retry_count: int = 0,
) -> None:
    conn.execute(
        """
        INSERT INTO dead_letter_events
            (event_id, tenant_id, event_type, payload, failure_reason,
             received_at, retry_count, status)
        VALUES (?, 'default', ?, ?, 'semantic_validation', ?, ?, ?)
        """,
        [
            event_id,
            payload.get("event_type"),
            json.dumps(payload),
            datetime.now(UTC),
            retry_count,
            status,
        ],
    )


def _status(conn: duckdb.DuckDBPyConnection, event_id: str) -> str:
    row = conn.execute(
        "SELECT status FROM dead_letter_events WHERE event_id = ?", [event_id]
    ).fetchone()
    assert row is not None
    return str(row[0])


class _SpyProducer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, topic: str, payload: dict) -> None:
        self.calls.append((topic, payload))


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    try:
        ensure_dead_letter_table(connection)
        yield connection
    finally:
        connection.close()


def test_replay_valid_event_marks_replayed_and_produces(conn: duckdb.DuckDBPyConnection) -> None:
    _insert_dead_letter(conn, event_id=EVENT_ID_1, payload=_valid_payload())
    producer = _SpyProducer()
    replayer = EventReplayer(conn, producer=producer)

    result = replayer.replay(EVENT_ID_1)

    assert result.status == "replayed"
    assert result.retry_count == 1
    assert producer.calls
    topic, produced = producer.calls[0]
    assert topic == "events.raw"
    assert produced["event_id"] == EVENT_ID_1
    assert _status(conn, EVENT_ID_1) == "replayed"


def test_replay_applies_corrected_payload(conn: duckdb.DuckDBPyConnection) -> None:
    invalid = _valid_payload(EVENT_ID_2)
    invalid["total_amount"] = "10.00"  # stated != computed -> semantic failure as stored
    _insert_dead_letter(conn, event_id=EVENT_ID_2, payload=invalid)
    producer = _SpyProducer()
    replayer = EventReplayer(conn, producer=producer)

    result = replayer.replay(EVENT_ID_2, corrected_payload={"total_amount": "99.99"})

    assert result.status == "replayed"
    assert result.payload["total_amount"] == "99.99"
    assert producer.calls[0][1]["total_amount"] == "99.99"


def test_replay_rejects_semantically_invalid_payload(conn: duckdb.DuckDBPyConnection) -> None:
    invalid = _valid_payload(EVENT_ID_3)
    invalid["total_amount"] = "10.00"
    _insert_dead_letter(conn, event_id=EVENT_ID_3, payload=invalid)
    replayer = EventReplayer(conn, producer=_SpyProducer())

    with pytest.raises(ReplayValidationError):
        replayer.replay(EVENT_ID_3)
    # Validation runs before the transaction, so the stored row is untouched.
    assert _status(conn, EVENT_ID_3) == "failed"


def test_replay_unknown_event_raises_not_found(conn: duckdb.DuckDBPyConnection) -> None:
    replayer = EventReplayer(conn, producer=_SpyProducer())
    with pytest.raises(DeadLetterEventNotFoundError):
        replayer.replay("missing")


def test_replay_rejects_non_object_payload(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "INSERT INTO dead_letter_events (event_id, payload, status) VALUES (?, ?, 'failed')",
        ["non-object-row", json.dumps([1, 2, 3])],
    )
    replayer = EventReplayer(conn, producer=_SpyProducer())
    with pytest.raises(ReplayValidationError):
        replayer.replay("non-object-row")


def test_dismiss_marks_event_dismissed(conn: duckdb.DuckDBPyConnection) -> None:
    _insert_dead_letter(conn, event_id=EVENT_ID_5, payload=_valid_payload(EVENT_ID_5))
    replayer = EventReplayer(conn, producer=_SpyProducer())

    replayer.dismiss(EVENT_ID_5)

    assert _status(conn, EVENT_ID_5) == "dismissed"


def test_dismiss_unknown_event_raises_not_found(conn: duckdb.DuckDBPyConnection) -> None:
    replayer = EventReplayer(conn, producer=_SpyProducer())
    with pytest.raises(DeadLetterEventNotFoundError):
        replayer.dismiss("missing")
