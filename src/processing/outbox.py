from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import duckdb
import structlog
from confluent_kafka import KafkaException
from opentelemetry import trace

from src.processing.tracing import inject_trace_to_kafka_headers, telemetry_disabled

logger = structlog.get_logger()
tracer = trace.get_tracer("agentflow.outbox")

DEFAULT_KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


def ensure_outbox_table(conn) -> None:
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


class OutboxProcessor:
    def __init__(
        self,
        duckdb_path: str | None = None,
        conn=None,
        producer: Callable[[str, dict], None] | None = None,
        bootstrap_servers: str | None = None,
        max_retries: int = 5,
    ) -> None:
        if conn is None and duckdb_path is None:
            raise ValueError("duckdb_path or conn is required")
        self._owns_conn = conn is None
        self._conn = conn if conn is not None else duckdb.connect(str(duckdb_path))
        self._producer = producer or self._produce_to_kafka
        self._bootstrap_servers = bootstrap_servers or DEFAULT_KAFKA_BOOTSTRAP
        self._max_retries = max_retries
        ensure_outbox_table(self._conn)

    def close(self) -> None:
        if self._owns_conn and self._conn is not None:
            self._conn.close()
            self._conn = None

    async def run_forever(self) -> None:
        try:
            while True:
                await asyncio.sleep(2)
                try:
                    self.process_pending()
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
        rows = self._conn.execute(
            """
            SELECT id, event_id, payload, topic, retry_count
            FROM outbox
            WHERE status = 'pending'
              AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
            ORDER BY created_at
            LIMIT ?
            """,
            [datetime.now(UTC), limit],
        ).fetchall()
        processed = 0
        for row in rows:
            if self._process_row(row):
                processed += 1
        return processed

    def process_entry(self, outbox_id: str) -> bool:
        row = self._conn.execute(
            """
            SELECT id, event_id, payload, topic, retry_count
            FROM outbox
            WHERE id = ?
              AND status = 'pending'
            """,
            [outbox_id],
        ).fetchone()
        if row is None:
            return False
        return self._process_row(row)

    def _process_row(self, row) -> bool:
        outbox_id, event_id, payload, topic, retry_count = row
        decoded_payload = self._decode_payload(payload)
        try:
            self._producer(topic, decoded_payload)
        except (BufferError, ConnectionError, TimeoutError, KafkaException, RuntimeError) as exc:
            error_message = str(exc)
            if isinstance(exc, RuntimeError) and not (
                error_message.startswith("KafkaError{")
                or "Kafka message(s) were not delivered" in error_message
            ):
                raise
            next_retry_count = int(retry_count or 0) + 1
            logger.warning(
                "outbox_delivery_retry_scheduled",
                outbox_id=outbox_id,
                event_id=event_id,
                topic=topic,
                retry_count=next_retry_count,
                error=error_message,
                exc_info=True,
            )
            self._schedule_retry(
                outbox_id=outbox_id,
                event_id=event_id,
                retry_count=next_retry_count,
                error_message=error_message,
            )
            return False
        self._mark_sent(outbox_id=outbox_id, event_id=event_id)
        return True

    def _mark_sent(self, outbox_id: str, event_id: str) -> None:
        sent_at = datetime.now(UTC)
        self._conn.execute("BEGIN TRANSACTION")
        try:
            self._conn.execute(
                """
                UPDATE outbox
                SET status = 'sent',
                    sent_at = ?,
                    last_error = NULL
                WHERE id = ?
                """,
                [sent_at, outbox_id],
            )
            self._conn.execute(
                "UPDATE dead_letter_events SET status = 'replayed' WHERE event_id = ?",
                [event_id],
            )
            self._conn.execute("COMMIT")
        except Exception:  # nosec B110 - rollback must preserve the original replay failure
            # Transaction rollback must happen before unexpected errors propagate.
            self._conn.execute("ROLLBACK")
            raise

    def _schedule_retry(
        self,
        outbox_id: str,
        event_id: str,
        retry_count: int,
        error_message: str,
    ) -> None:
        status = "pending"
        retry_delay_seconds = 2**retry_count
        is_kafka_error = (
            error_message.startswith("KafkaError{")
            or "Kafka message(s) were not delivered" in error_message
        )
        if is_kafka_error:
            retry_delay_seconds = max(retry_delay_seconds, 30)
        next_attempt_at: datetime | None = datetime.now(UTC) + timedelta(
            seconds=retry_delay_seconds
        )
        self._conn.execute("BEGIN TRANSACTION")
        try:
            if retry_count >= self._max_retries:
                status = "failed"
                next_attempt_at = None
            self._conn.execute(
                """
                UPDATE outbox
                SET status = ?,
                    retry_count = ?,
                    next_attempt_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                [status, retry_count, next_attempt_at, error_message, outbox_id],
            )
            if status == "failed":
                self._conn.execute(
                    "UPDATE dead_letter_events SET status = 'failed' WHERE event_id = ?",
                    [event_id],
                )
            self._conn.execute("COMMIT")
        except Exception:  # nosec B110 - rollback must preserve the original retry scheduling failure
            # Transaction rollback must happen before unexpected errors propagate.
            self._conn.execute("ROLLBACK")
            raise

    def _decode_payload(self, payload) -> dict:
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

        def on_delivery(err, msg) -> None:
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
