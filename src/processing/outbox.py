from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from contextlib import nullcontext

import duckdb
import structlog
from confluent_kafka import KafkaException
from opentelemetry import trace

from src.processing.tracing import inject_trace_to_kafka_headers, telemetry_disabled
from src.serving.control_plane import ControlPlaneStore, EmbeddedControlPlaneStore, OutboxEntry
from src.serving.duckdb_connection import connect_duckdb

logger = structlog.get_logger()
tracer = trace.get_tracer("agentflow.outbox")

DEFAULT_KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


class OutboxProcessor:
    def __init__(
        self,
        duckdb_path: str | None = None,
        conn: duckdb.DuckDBPyConnection | None = None,
        producer: Callable[[str, dict], None] | None = None,
        bootstrap_servers: str | None = None,
        max_retries: int = 5,
        *,
        store: ControlPlaneStore | None = None,
    ) -> None:
        if conn is None and duckdb_path is None and store is None:
            raise ValueError("duckdb_path or conn is required")
        self._owns_conn = conn is None and store is None
        self._conn: duckdb.DuckDBPyConnection | None = (
            None
            if store is not None
            else (conn if conn is not None else connect_duckdb(str(duckdb_path)))
        )
        self._producer = producer or self._produce_to_kafka
        self._bootstrap_servers = bootstrap_servers or DEFAULT_KAFKA_BOOTSTRAP
        self._max_retries = max_retries
        # ADR 0010 slice 3: table access goes through the ControlPlaneStore
        # port. When no store is injected (the common case — main.py and every
        # existing test construct via conn/duckdb_path), this builds a private
        # embedded store bound to whichever connection this instance owns —
        # not necessarily the app's shared query_engine connection (see
        # main.py's file-vs-:memory: branch this preserves verbatim).
        self._store: ControlPlaneStore = store or EmbeddedControlPlaneStore(
            conn_provider=lambda: self._connection
        )
        self._store.ensure_outbox_schema()

    @property
    def _connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("OutboxProcessor connection is closed")
        return self._conn

    def close(self) -> None:
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None

    async def run_forever(self) -> None:
        try:
            while True:
                await asyncio.sleep(2)
                try:
                    await self.process_pending_async()
                except duckdb.Error as exc:
                    logger.warning(
                        "outbox_processing_failed",
                        error=str(exc),
                        bootstrap_servers=self._bootstrap_servers,
                        owns_connection=self._owns_conn,
                        exc_info=True,
                    )
        finally:
            self.close()

    def process_pending(self, limit: int = 100) -> int:
        entries = self._store.claim_due_outbox_entries(limit=limit)
        processed = 0
        for entry in entries:
            if self._process_entry(entry):
                processed += 1
        return processed

    async def process_pending_async(self, limit: int = 100) -> int:
        """Async variant used by run_forever.

        DuckDB reads/updates stay on the event loop (the connection may be shared
        with the query engine, so it must not be touched from a worker thread),
        but the blocking Kafka produce+flush(10) is offloaded so a slow or
        unreachable broker can't freeze the whole event loop. (audit_28_06_26.md #1)
        """
        entries = self._store.claim_due_outbox_entries(limit=limit)
        processed = 0
        for entry in entries:
            if await self._process_entry_async(entry):
                processed += 1
        return processed

    async def _process_entry_async(self, entry: OutboxEntry) -> bool:
        decoded_payload = self._decode_payload(entry.payload)
        try:
            await asyncio.to_thread(self._producer, entry.topic, decoded_payload)
        except (BufferError, ConnectionError, TimeoutError, KafkaException, RuntimeError) as exc:
            error_message = str(exc)
            if isinstance(exc, RuntimeError) and not (
                error_message.startswith("KafkaError{")
                or "Kafka message(s) were not delivered" in error_message
            ):
                raise
            next_retry_count = int(entry.retry_count or 0) + 1
            logger.warning(
                "outbox_delivery_retry_scheduled",
                outbox_id=entry.id,
                event_id=entry.event_id,
                topic=entry.topic,
                retry_count=next_retry_count,
                error=error_message,
                exc_info=True,
            )
            self._store.schedule_outbox_retry(
                outbox_id=entry.id,
                event_id=entry.event_id,
                retry_count=next_retry_count,
                error_message=error_message,
                max_retries=self._max_retries,
            )
            return False
        self._store.mark_outbox_sent(outbox_id=entry.id, event_id=entry.event_id)
        return True

    def process_entry(self, outbox_id: str) -> bool:
        entry = self._store.get_pending_outbox_entry(outbox_id)
        if entry is None:
            return False
        return self._process_entry(entry)

    def _process_entry(self, entry: OutboxEntry) -> bool:
        decoded_payload = self._decode_payload(entry.payload)
        try:
            self._producer(entry.topic, decoded_payload)
        except (BufferError, ConnectionError, TimeoutError, KafkaException, RuntimeError) as exc:
            error_message = str(exc)
            if isinstance(exc, RuntimeError) and not (
                error_message.startswith("KafkaError{")
                or "Kafka message(s) were not delivered" in error_message
            ):
                raise
            next_retry_count = int(entry.retry_count or 0) + 1
            logger.warning(
                "outbox_delivery_retry_scheduled",
                outbox_id=entry.id,
                event_id=entry.event_id,
                topic=entry.topic,
                retry_count=next_retry_count,
                error=error_message,
                exc_info=True,
            )
            self._store.schedule_outbox_retry(
                outbox_id=entry.id,
                event_id=entry.event_id,
                retry_count=next_retry_count,
                error_message=error_message,
                max_retries=self._max_retries,
            )
            return False
        self._store.mark_outbox_sent(outbox_id=entry.id, event_id=entry.event_id)
        return True

    def _decode_payload(self, payload: object) -> dict:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            decoded = json.loads(payload)
            if isinstance(decoded, dict):
                return decoded
        raise ValueError("Outbox payload must be a JSON object.")

    def _produce_to_kafka(self, topic: str, payload: dict) -> None:
        from confluent_kafka import Producer

        delivery_errors: list[str] = []

        def on_delivery(err: object, msg: object) -> None:
            del msg
            if err is not None:
                delivery_errors.append(str(err))

        producer = Producer({"bootstrap.servers": self._bootstrap_servers})
        produce_span = (
            tracer.start_as_current_span("kafka.produce")
            if not telemetry_disabled()
            else nullcontext()
        )
        with produce_span as span:
            if span is not None and span.is_recording():
                span.set_attribute("topic", topic)
                event_type = payload.get("event_type")
                if event_type is not None:
                    span.set_attribute("event_type", str(event_type))
                tenant_id = payload.get("tenant_id") or structlog.contextvars.get_contextvars().get(
                    "tenant_id"
                )
                if tenant_id is not None:
                    span.set_attribute("tenant_id", str(tenant_id))
            headers = inject_trace_to_kafka_headers({})
            try:
                producer.produce(
                    topic,
                    key=str(payload.get("event_id", "")),
                    value=json.dumps(payload).encode("utf-8"),
                    headers=list(headers.items()) or None,
                    on_delivery=on_delivery,
                )
            except TypeError as exc:
                if "on_delivery" not in str(exc):
                    raise
                producer.produce(
                    topic,
                    key=str(payload.get("event_id", "")),
                    value=json.dumps(payload).encode("utf-8"),
                    headers=list(headers.items()) or None,
                )
            remaining = producer.flush(10)
            if delivery_errors:
                raise RuntimeError(delivery_errors[0])
            if remaining != 0:
                raise RuntimeError(f"{remaining} Kafka message(s) were not delivered")
