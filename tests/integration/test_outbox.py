from __future__ import annotations

import asyncio
import json
import sys
import types
from importlib import import_module
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

import src.serving.api.main as main_module
from src.processing.event_replayer import EventReplayer, ensure_dead_letter_table

pytestmark = pytest.mark.integration

EVENT_ID = "44444444-4444-4444-4444-444444444444"
OUTBOX_ID = "55555555-5555-5555-5555-555555555555"


def _payload(event_id: str = EVENT_ID) -> dict:
    return {
        "event_id": event_id,
        "event_type": "order.created",
        "timestamp": "2026-04-11T12:00:00+00:00",
        "source": "deadletter-test",
        "order_id": "ORD-20260411-9001",
        "user_id": "USR-42",
        "status": "confirmed",
        "items": [
            {"product_id": "PROD-001", "quantity": 1, "unit_price": "79.99"},
            {"product_id": "PROD-002", "quantity": 1, "unit_price": "20.00"},
        ],
        "total_amount": "99.99",
        "currency": "USD",
    }


def _seed_dead_letter_event(conn, payload: dict, status: str = "failed") -> None:
    ensure_dead_letter_table(conn)
    conn.execute("DELETE FROM dead_letter_events")
    conn.execute(
        """
        INSERT INTO dead_letter_events (
            event_id,
            event_type,
            payload,
            failure_reason,
            failure_detail,
            received_at,
            retry_count,
            last_retried_at,
            status
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0, NULL, ?)
        """,
        [
            payload["event_id"],
            payload["event_type"],
            json.dumps(payload),
            "semantic_validation",
            "retry requested",
            status,
        ],
    )


def _create_outbox_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            payload JSON NOT NULL,
            topic TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP,
            status TEXT DEFAULT 'pending',
            retry_count INTEGER DEFAULT 0,
            next_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_error TEXT
        )
        """
    )


def _insert_pending_outbox(conn, payload: dict, outbox_id: str = OUTBOX_ID) -> None:
    _create_outbox_table(conn)
    conn.execute(
        """
        INSERT INTO outbox (
            id,
            event_id,
            payload,
            topic,
            created_at,
            sent_at,
            status,
            retry_count,
            next_attempt_at,
            last_error
        )
        VALUES (
            ?, ?, ?, 'events.raw', CURRENT_TIMESTAMP,
            NULL, 'pending', 0, CURRENT_TIMESTAMP, NULL
        )
        """,
        [
            outbox_id,
            payload["event_id"],
            json.dumps(payload),
        ],
    )


def test_replay_persists_outbox_entry_and_updates_deadletter_state(tmp_path: Path) -> None:
    db_path = tmp_path / "outbox_enqueue.duckdb"
    conn = duckdb.connect(str(db_path))
    payload = _payload()
    _seed_dead_letter_event(conn, payload)

    result = EventReplayer(
        conn,
        producer=lambda topic, message: None,
    ).replay(EVENT_ID)

    dead_letter_row = conn.execute(
        """
        SELECT status, retry_count, payload
        FROM dead_letter_events
        WHERE event_id = ?
        """,
        [EVENT_ID],
    ).fetchone()
    outbox_row = conn.execute(
        """
        SELECT event_id, topic, status, payload
        FROM outbox
        WHERE event_id = ?
        """,
        [EVENT_ID],
    ).fetchone()
    conn.close()

    assert result.event_id == EVENT_ID
    assert result.retry_count == 1
    assert dead_letter_row is not None
    assert dead_letter_row[0] in {"replay_pending", "replayed"}
    assert dead_letter_row[1] == 1
    assert json.loads(dead_letter_row[2])["total_amount"] == "99.99"
    assert outbox_row is not None
    assert outbox_row[0] == EVENT_ID
    assert outbox_row[1] == "events.raw"
    assert outbox_row[2] in {"pending", "sent"}
    assert json.loads(outbox_row[3])["total_amount"] == "99.99"


def test_replay_rolls_back_deadletter_update_when_outbox_insert_fails(tmp_path: Path) -> None:
    db_path = tmp_path / "outbox_atomicity.duckdb"
    base_conn = duckdb.connect(str(db_path))
    payload = _payload()
    _seed_dead_letter_event(base_conn, payload)

    class FailingOutboxConnection:
        def __init__(self, wrapped) -> None:
            self._wrapped = wrapped

        def execute(self, sql: str, params=None):
            if "INSERT INTO outbox" in sql:
                raise RuntimeError("outbox insert failed")
            if params is None:
                return self._wrapped.execute(sql)
            return self._wrapped.execute(sql, params)

    with pytest.raises(RuntimeError, match="outbox insert failed"):
        EventReplayer(
            FailingOutboxConnection(base_conn),
            producer=lambda topic, message: None,
        ).replay(EVENT_ID)

    row = base_conn.execute(
        """
        SELECT status, retry_count, payload
        FROM dead_letter_events
        WHERE event_id = ?
        """,
        [EVENT_ID],
    ).fetchone()
    base_conn.close()

    assert row == ("failed", 0, json.dumps(payload))


def test_outbox_processor_marks_entry_sent_and_deadletter_replayed(tmp_path: Path) -> None:
    outbox_module = import_module("src.processing.outbox")
    db_path = tmp_path / "outbox_process.duckdb"
    conn = duckdb.connect(str(db_path))
    payload = _payload()
    produced_messages: list[tuple[str, dict]] = []
    _seed_dead_letter_event(conn, payload, status="replay_pending")
    _insert_pending_outbox(conn, payload)
    conn.close()

    processor = outbox_module.OutboxProcessor(
        duckdb_path=str(db_path),
        producer=lambda topic, message: produced_messages.append((topic, message)),
    )
    try:
        processed = processor.process_pending()
    finally:
        processor.close()

    verify_conn = duckdb.connect(str(db_path))
    outbox_row = verify_conn.execute(
        "SELECT status, sent_at, retry_count FROM outbox WHERE id = ?",
        [OUTBOX_ID],
    ).fetchone()
    dead_letter_row = verify_conn.execute(
        "SELECT status FROM dead_letter_events WHERE event_id = ?",
        [EVENT_ID],
    ).fetchone()
    verify_conn.close()

    assert processed == 1
    assert produced_messages == [("events.raw", payload)]
    assert outbox_row is not None
    assert outbox_row[0] == "sent"
    assert outbox_row[1] is not None
    assert outbox_row[2] == 0
    assert dead_letter_row == ("replayed",)


def test_outbox_processor_leaves_entry_pending_on_kafka_failure(tmp_path: Path) -> None:
    outbox_module = import_module("src.processing.outbox")
    db_path = tmp_path / "outbox_retry.duckdb"
    conn = duckdb.connect(str(db_path))
    payload = _payload()
    _seed_dead_letter_event(conn, payload, status="replay_pending")
    _insert_pending_outbox(conn, payload)
    conn.close()

    processor = outbox_module.OutboxProcessor(
        duckdb_path=str(db_path),
        producer=lambda topic, message: (_ for _ in ()).throw(ConnectionError("kafka down")),
    )
    try:
        processed = processor.process_pending()
    finally:
        processor.close()

    verify_conn = duckdb.connect(str(db_path))
    outbox_row = verify_conn.execute(
        """
        SELECT status, retry_count, next_attempt_at, last_error
        FROM outbox
        WHERE id = ?
        """,
        [OUTBOX_ID],
    ).fetchone()
    dead_letter_row = verify_conn.execute(
        "SELECT status FROM dead_letter_events WHERE event_id = ?",
        [EVENT_ID],
    ).fetchone()
    verify_conn.close()

    assert processed == 0
    assert outbox_row is not None
    assert outbox_row[0] == "pending"
    assert outbox_row[1] == 1
    assert outbox_row[2] is not None
    assert outbox_row[3] == "kafka down"
    assert dead_letter_row == ("replay_pending",)


def test_outbox_processor_propagates_unexpected_producer_errors(tmp_path: Path) -> None:
    outbox_module = import_module("src.processing.outbox")
    db_path = tmp_path / "outbox_unexpected.duckdb"
    conn = duckdb.connect(str(db_path))
    payload = _payload()
    _seed_dead_letter_event(conn, payload, status="replay_pending")
    _insert_pending_outbox(conn, payload)
    conn.close()

    processor = outbox_module.OutboxProcessor(
        duckdb_path=str(db_path),
        producer=lambda topic, message: (_ for _ in ()).throw(RuntimeError("serializer bug")),
    )
    try:
        with pytest.raises(RuntimeError, match="serializer bug"):
            processor.process_pending()
    finally:
        processor.close()

    verify_conn = duckdb.connect(str(db_path))
    outbox_row = verify_conn.execute(
        """
        SELECT status, retry_count, last_error
        FROM outbox
        WHERE id = ?
        """,
        [OUTBOX_ID],
    ).fetchone()
    dead_letter_row = verify_conn.execute(
        "SELECT status FROM dead_letter_events WHERE event_id = ?",
        [EVENT_ID],
    ).fetchone()
    verify_conn.close()

    assert outbox_row == ("pending", 0, None)
    assert dead_letter_row == ("replay_pending",)


@pytest.mark.anyio
async def test_outbox_run_forever_propagates_unexpected_processing_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox_module = import_module("src.processing.outbox")
    sleep_calls = 0

    async def fake_sleep(_: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls > 1:
            raise AssertionError("run_forever continued after unexpected error")

    class ProcessorStub:
        def __init__(self) -> None:
            self.closed = False

        def process_pending(self) -> int:
            raise RuntimeError("unexpected processor bug")

        def close(self) -> None:
            self.closed = True

    stub = ProcessorStub()
    monkeypatch.setattr(outbox_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="unexpected processor bug"):
        await outbox_module.OutboxProcessor.run_forever(stub)

    assert stub.closed is True


def test_outbox_processor_recovers_pending_entries_after_restart(tmp_path: Path) -> None:
    outbox_module = import_module("src.processing.outbox")
    db_path = tmp_path / "outbox_restart.duckdb"
    conn = duckdb.connect(str(db_path))
    payload = _payload()
    produced_messages: list[tuple[str, dict]] = []
    _seed_dead_letter_event(conn, payload, status="replay_pending")
    _insert_pending_outbox(conn, payload)
    conn.close()

    first_processor = outbox_module.OutboxProcessor(duckdb_path=str(db_path))
    first_processor.close()

    second_processor = outbox_module.OutboxProcessor(
        duckdb_path=str(db_path),
        producer=lambda topic, message: produced_messages.append((topic, message)),
    )
    try:
        processed = second_processor.process_pending()
    finally:
        second_processor.close()

    verify_conn = duckdb.connect(str(db_path))
    outbox_status = verify_conn.execute(
        "SELECT status FROM outbox WHERE id = ?",
        [OUTBOX_ID],
    ).fetchone()
    dead_letter_status = verify_conn.execute(
        "SELECT status FROM dead_letter_events WHERE event_id = ?",
        [EVENT_ID],
    ).fetchone()
    verify_conn.close()

    assert processed == 1
    assert produced_messages == [("events.raw", payload)]
    assert outbox_status == ("sent",)
    assert dead_letter_status == ("replayed",)


def test_outbox_processor_injects_trace_context_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox_module = import_module("src.processing.outbox")
    captured: dict[str, object] = {}

    class FakeProducer:
        def __init__(self, config: dict[str, object]) -> None:
            captured["config"] = config

        def produce(
            self,
            topic: str,
            key: str,
            value: bytes,
            headers=None,
        ) -> None:
            captured["topic"] = topic
            captured["key"] = key
            captured["value"] = value
            captured["headers"] = headers

        def flush(self, timeout: int) -> int:
            captured["flush_timeout"] = timeout
            return 0

    monkeypatch.setitem(
        sys.modules,
        "confluent_kafka",
        types.SimpleNamespace(Producer=FakeProducer),
    )

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        trace.set_tracer_provider(
            TracerProvider(resource=Resource.create({"service.name": "agentflow-test"}))
        )

    processor = outbox_module.OutboxProcessor(
        duckdb_path=str(tmp_path / "headers.duckdb"),
        bootstrap_servers="kafka:9092",
    )

    try:
        tracer = trace.get_tracer("tests.outbox")
        with tracer.start_as_current_span("http.request") as span:
            processor._produce_to_kafka("events.raw", _payload())
            span_context = span.get_span_context()
    finally:
        processor.close()

    headers = dict(captured["headers"])
    traceparent = headers["traceparent"].decode("utf-8")
    trace_id = format(span_context.trace_id, "032x")
    _, traceparent_trace_id, _, _ = traceparent.split("-", 3)

    assert captured["topic"] == "events.raw"
    assert captured["key"] == EVENT_ID
    assert traceparent_trace_id == trace_id


def test_api_lifespan_starts_outbox_processor_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    class FakeOutboxProcessor:
        def __init__(self, duckdb_path: str, producer=None, bootstrap_servers=None) -> None:
            self.duckdb_path = duckdb_path
            self.producer = producer
            self.bootstrap_servers = bootstrap_servers

        async def run_forever(self) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise

        def close(self) -> None:
            return None

    monkeypatch.setattr(main_module, "OutboxProcessor", FakeOutboxProcessor, raising=False)
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "startup.duckdb"))
    monkeypatch.setenv("AGENTFLOW_USAGE_DB_PATH", str(tmp_path / "startup_usage.duckdb"))
    main_module.app.state.webhook_dispatcher_autostart = False

    with TestClient(main_module.app) as client:
        assert hasattr(client.app.state, "outbox_processor_task")
        assert client.app.state.outbox_processor_task.done() is False
        assert started.is_set()
