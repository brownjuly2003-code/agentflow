"""Unit coverage for the at-least-once delivery loop in
``src.processing.outbox`` (a mutmut target): pending/entry dispatch, the
success/retry/poison state machine, exponential + Kafka-floor backoff, the
mark-sent and schedule-retry transactions, payload decoding, and the Kafka
producer adapter with a fake ``confluent_kafka.Producer``. The full streaming
path is exercised by ``tests/integration/test_outbox.py``; these tests pin the
processor logic at the unit layer with an injected DuckDB connection and a stub
producer so a delivery or retry-scheduling regression fails fast."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

import src.processing.outbox as outbox_module
from src.processing.event_replayer import ensure_dead_letter_table
from src.processing.outbox import OutboxProcessor

TOPIC = "agentflow.orders"


def _payload(event_id: str = "evt-1") -> dict:
    return {"event_id": event_id, "event_type": "order.created", "order_id": "ORD-1"}


def _insert_outbox(
    conn: duckdb.DuckDBPyConnection,
    *,
    outbox_id: str,
    event_id: str = "evt-1",
    status: str = "pending",
    retry_count: int = 0,
    next_attempt_at: datetime | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO outbox (id, event_id, payload, topic, status, retry_count, next_attempt_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            outbox_id,
            event_id,
            json.dumps(_payload(event_id)),
            TOPIC,
            status,
            retry_count,
            next_attempt_at,
        ],
    )


def _status(conn: duckdb.DuckDBPyConnection, outbox_id: str) -> tuple:
    return conn.execute(
        "SELECT status, retry_count, next_attempt_at, last_error FROM outbox WHERE id = ?",
        [outbox_id],
    ).fetchone()


class _SpyProducer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, topic: str, payload: dict) -> None:
        self.calls.append((topic, payload))


class _RaisingProducer:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def __call__(self, topic: str, payload: dict) -> None:
        raise self.exc


@pytest.fixture
def conn(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(tmp_path / "outbox.duckdb"))
    # _mark_sent / _schedule_retry touch dead_letter_events on every dispatch,
    # so the table must exist for the success and poison paths alike.
    ensure_dead_letter_table(connection)
    try:
        yield connection
    finally:
        connection.close()


def _processor(conn: duckdb.DuckDBPyConnection, producer, max_retries: int = 5) -> OutboxProcessor:
    return OutboxProcessor(conn=conn, producer=producer, max_retries=max_retries)


class TestConstruction:
    def test_requires_conn_or_path(self) -> None:
        with pytest.raises(ValueError, match="duckdb_path or conn is required"):
            OutboxProcessor()


class TestProcessPending:
    def test_dispatches_and_marks_sent(self, conn: duckdb.DuckDBPyConnection) -> None:
        spy = _SpyProducer()
        processor = _processor(conn, spy)
        _insert_outbox(conn, outbox_id="o1", event_id="evt-1")
        _insert_outbox(conn, outbox_id="o2", event_id="evt-2")

        processed = processor.process_pending()

        assert processed == 2
        assert {topic for topic, _ in spy.calls} == {TOPIC}
        assert _status(conn, "o1")[0] == "sent"
        assert _status(conn, "o2")[0] == "sent"

    def test_skips_rows_with_future_next_attempt(self, conn: duckdb.DuckDBPyConnection) -> None:
        spy = _SpyProducer()
        processor = _processor(conn, spy)
        future = datetime.now(UTC) + timedelta(hours=1)
        _insert_outbox(conn, outbox_id="o1", next_attempt_at=future)

        assert processor.process_pending() == 0
        assert spy.calls == []


class TestProcessEntry:
    def test_dispatches_single_entry(self, conn: duckdb.DuckDBPyConnection) -> None:
        spy = _SpyProducer()
        processor = _processor(conn, spy)
        _insert_outbox(conn, outbox_id="o1")

        assert processor.process_entry("o1") is True
        assert _status(conn, "o1")[0] == "sent"

    def test_missing_or_non_pending_entry_returns_false(
        self, conn: duckdb.DuckDBPyConnection
    ) -> None:
        spy = _SpyProducer()
        processor = _processor(conn, spy)
        _insert_outbox(conn, outbox_id="o1", status="sent")

        assert processor.process_entry("o1") is False
        assert processor.process_entry("does-not-exist") is False


class TestRetryStateMachine:
    def test_retryable_error_schedules_retry(self, conn: duckdb.DuckDBPyConnection) -> None:
        processor = _processor(conn, _RaisingProducer(ConnectionError("broker down")))
        _insert_outbox(conn, outbox_id="o1")

        assert processor.process_entry("o1") is False
        status, retry_count, next_attempt_at, last_error = _status(conn, "o1")
        assert status == "pending"
        assert retry_count == 1
        assert next_attempt_at is not None
        assert "broker down" in last_error

    def test_non_kafka_runtime_error_propagates(self, conn: duckdb.DuckDBPyConnection) -> None:
        processor = _processor(conn, _RaisingProducer(RuntimeError("unexpected bug")))
        _insert_outbox(conn, outbox_id="o1")

        with pytest.raises(RuntimeError, match="unexpected bug"):
            processor.process_entry("o1")

    def test_kafka_shaped_runtime_error_is_retried(self, conn: duckdb.DuckDBPyConnection) -> None:
        processor = _processor(
            conn, _RaisingProducer(RuntimeError("KafkaError{code=_MSG_TIMED_OUT}"))
        )
        _insert_outbox(conn, outbox_id="o1")

        assert processor.process_entry("o1") is False
        status, retry_count, next_attempt_at, _ = _status(conn, "o1")
        assert status == "pending"
        assert retry_count == 1
        # Kafka errors get at least a 30s backoff floor.
        assert next_attempt_at >= datetime.now(UTC).replace(
            tzinfo=next_attempt_at.tzinfo
        ) + timedelta(seconds=20)

    def test_exhausting_retries_marks_failed_and_dead_letters(
        self, conn: duckdb.DuckDBPyConnection
    ) -> None:
        ensure_dead_letter_table(conn)
        conn.execute(
            """
            INSERT INTO dead_letter_events (
                event_id, event_type, payload, failure_reason, failure_detail,
                received_at, retry_count, last_retried_at, status
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0, NULL, 'failed')
            """,
            ["evt-1", "order.created", json.dumps(_payload()), "semantic", "x"],
        )
        processor = _processor(conn, _RaisingProducer(ConnectionError("down")), max_retries=1)
        _insert_outbox(conn, outbox_id="o1", retry_count=0)

        assert processor.process_entry("o1") is False
        status, _, next_attempt_at, _ = _status(conn, "o1")
        assert status == "failed"
        assert next_attempt_at is None
        dl_status = conn.execute(
            "SELECT status FROM dead_letter_events WHERE event_id = ?", ["evt-1"]
        ).fetchone()[0]
        assert dl_status == "failed"


class TestMarkSent:
    def test_marks_dead_letter_replayed_on_success(self, conn: duckdb.DuckDBPyConnection) -> None:
        ensure_dead_letter_table(conn)
        conn.execute(
            """
            INSERT INTO dead_letter_events (
                event_id, event_type, payload, failure_reason, failure_detail,
                received_at, retry_count, last_retried_at, status
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0, NULL, 'failed')
            """,
            ["evt-1", "order.created", json.dumps(_payload()), "semantic", "x"],
        )
        processor = _processor(conn, _SpyProducer())
        _insert_outbox(conn, outbox_id="o1", event_id="evt-1")

        assert processor.process_entry("o1") is True
        dl_status = conn.execute(
            "SELECT status FROM dead_letter_events WHERE event_id = ?", ["evt-1"]
        ).fetchone()[0]
        assert dl_status == "replayed"

    def test_rolls_back_when_dead_letter_update_fails(
        self, conn: duckdb.DuckDBPyConnection
    ) -> None:
        processor = _processor(conn, _SpyProducer())
        _insert_outbox(conn, outbox_id="o1")
        # Drop the dead_letter table so the in-transaction update fails; the
        # mark-sent transaction must roll back and re-raise rather than leave
        # the outbox row half-committed.
        conn.execute("DROP TABLE dead_letter_events")

        with pytest.raises(duckdb.Error):
            processor.process_entry("o1")

        assert _status(conn, "o1")[0] == "pending"


class TestDecodePayload:
    def test_dict_passthrough(self, conn: duckdb.DuckDBPyConnection) -> None:
        processor = _processor(conn, _SpyProducer())
        assert processor._decode_payload({"a": 1}) == {"a": 1}

    def test_json_string_decoded(self, conn: duckdb.DuckDBPyConnection) -> None:
        processor = _processor(conn, _SpyProducer())
        assert processor._decode_payload('{"a": 1}') == {"a": 1}

    def test_non_object_json_raises(self, conn: duckdb.DuckDBPyConnection) -> None:
        processor = _processor(conn, _SpyProducer())
        with pytest.raises(ValueError, match="must be a JSON object"):
            processor._decode_payload("[1, 2, 3]")

    def test_non_string_non_dict_raises(self, conn: duckdb.DuckDBPyConnection) -> None:
        processor = _processor(conn, _SpyProducer())
        with pytest.raises(ValueError, match="must be a JSON object"):
            processor._decode_payload(12345)


class _FakeKafkaProducer:
    deliver_error: object | None = None
    flush_remaining: int = 0
    reject_on_delivery_kwarg: bool = False

    def __init__(self, config: dict) -> None:
        self.config = config
        self.produced: list[tuple] = []
        self._cb = None

    def produce(self, topic, key=None, value=None, headers=None, on_delivery=None):  # noqa: ANN001
        if on_delivery is not None and type(self).reject_on_delivery_kwarg:
            raise TypeError("produce() got an unexpected keyword argument 'on_delivery'")
        self.produced.append((topic, key, value))
        self._cb = on_delivery

    def flush(self, timeout):  # noqa: ANN001
        if self._cb is not None:
            self._cb(type(self).deliver_error, object())
        return type(self).flush_remaining


@pytest.fixture
def fake_kafka(monkeypatch: pytest.MonkeyPatch):
    _FakeKafkaProducer.deliver_error = None
    _FakeKafkaProducer.flush_remaining = 0
    _FakeKafkaProducer.reject_on_delivery_kwarg = False
    monkeypatch.setattr("confluent_kafka.Producer", _FakeKafkaProducer)
    return _FakeKafkaProducer


class TestProduceToKafka:
    def test_successful_produce(self, conn: duckdb.DuckDBPyConnection, fake_kafka) -> None:
        processor = OutboxProcessor(conn=conn, bootstrap_servers="kafka:9092")
        # default producer is _produce_to_kafka; dispatch a row through it
        _insert_outbox(conn, outbox_id="o1")
        assert processor.process_entry("o1") is True
        assert _status(conn, "o1")[0] == "sent"

    def test_delivery_error_triggers_retry(
        self, conn: duckdb.DuckDBPyConnection, fake_kafka
    ) -> None:
        # confluent delivery errors stringify as KafkaError{...}; _produce_to_kafka
        # raises that and _process_row reschedules it as a retry.
        fake_kafka.deliver_error = "KafkaError{code=_MSG_TIMED_OUT,str=Broker: timed out}"
        processor = OutboxProcessor(conn=conn)
        _insert_outbox(conn, outbox_id="o1")
        assert processor.process_entry("o1") is False
        assert _status(conn, "o1")[0] == "pending"

    def test_unflushed_messages_raise_runtime_error(
        self, conn: duckdb.DuckDBPyConnection, fake_kafka
    ) -> None:
        fake_kafka.flush_remaining = 1
        processor = OutboxProcessor(conn=conn)
        _insert_outbox(conn, outbox_id="o1")
        assert processor.process_entry("o1") is False
        assert "not delivered" in _status(conn, "o1")[3]

    def test_produce_without_on_delivery_kwarg(
        self, conn: duckdb.DuckDBPyConnection, fake_kafka
    ) -> None:
        # Some confluent-kafka builds reject the on_delivery kwarg; the adapter
        # retries produce() without it.
        fake_kafka.reject_on_delivery_kwarg = True
        processor = OutboxProcessor(conn=conn)
        _insert_outbox(conn, outbox_id="o1")
        assert processor.process_entry("o1") is True
        assert _status(conn, "o1")[0] == "sent"


class TestRunForever:
    @pytest.mark.asyncio
    async def test_run_forever_swallows_duckdb_errors_then_exits(
        self, conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        processor = _processor(conn, _SpyProducer())
        sleeps = {"n": 0}

        async def fake_sleep(_seconds: float) -> None:
            sleeps["n"] += 1
            if sleeps["n"] >= 2:
                raise asyncio.CancelledError

        def boom(*_args: object, **_kwargs: object) -> int:
            raise duckdb.Error("transient lock")

        monkeypatch.setattr(outbox_module.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(processor, "process_pending", boom)

        with pytest.raises(asyncio.CancelledError):
            await processor.run_forever()

        # the owned-conn guard ran on exit; this processor does not own conn
        assert sleeps["n"] >= 2
