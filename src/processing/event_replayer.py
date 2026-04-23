from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from opentelemetry import trace

from src.processing.outbox import OutboxProcessor, ensure_outbox_table
from src.processing.tracing import inject_trace_to_kafka_headers, telemetry_disabled
from src.quality.validators.schema_validator import validate_event
from src.quality.validators.semantic_validator import validate_semantics

DEFAULT_KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
DEFAULT_REPLAY_TOPIC = "events.raw"
tracer = trace.get_tracer("agentflow.event_replayer")


class DeadLetterEventNotFoundError(LookupError):
    pass


class ReplayValidationError(ValueError):
    pass


@dataclass
class ReplayResult:
    event_id: str
    status: str
    retry_count: int
    last_retried_at: datetime
    payload: dict


def ensure_dead_letter_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dead_letter_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT,
            payload JSON,
            failure_reason TEXT,
            failure_detail TEXT,
            received_at TIMESTAMP,
            retry_count INTEGER DEFAULT 0,
            last_retried_at TIMESTAMP,
            status TEXT DEFAULT 'failed'
        )
        """
    )


class EventReplayer:
    def __init__(
        self,
        conn,
        producer: Callable[[str, dict], None] | None = None,
        bootstrap_servers: str | None = None,
    ) -> None:
        self._conn = conn
        self._producer = producer or self._produce_to_kafka
        self._bootstrap_servers = bootstrap_servers or DEFAULT_KAFKA_BOOTSTRAP
        ensure_dead_letter_table(self._conn)
        ensure_outbox_table(self._conn)

    def replay(
        self,
        event_id: str,
        corrected_payload: dict | None = None,
    ) -> ReplayResult:
        row = self._load_row(event_id)
        payload = self._decoded_payload(row["payload"])
        candidate = dict(payload)
        if corrected_payload:
            candidate.update(corrected_payload)
        self._validate(candidate)

        replayed_at = datetime.now(UTC)
        retry_count = int(row["retry_count"] or 0) + 1
        outbox_id = str(uuid4())
        self._conn.execute("BEGIN TRANSACTION")
        try:
            self._conn.execute(
                """
                UPDATE dead_letter_events
                SET payload = ?, status = 'replay_pending', retry_count = ?, last_retried_at = ?
                WHERE event_id = ?
                """,
                [
                    json.dumps(candidate),
                    retry_count,
                    replayed_at,
                    event_id,
                ],
            )
            self._conn.execute(
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
                VALUES (?, ?, ?, ?, ?, NULL, 'pending', 0, ?, NULL)
                """,
                [
                    outbox_id,
                    event_id,
                    json.dumps(candidate),
                    DEFAULT_REPLAY_TOPIC,
                    replayed_at,
                    replayed_at,
                ],
            )
            self._conn.execute("COMMIT")
        except Exception:  # nosec B110 - rollback must preserve the original replay failure
            # Transaction rollback must happen before unexpected errors propagate.
            self._conn.execute("ROLLBACK")
            raise
        status = "replay_pending"
        processor = OutboxProcessor(
            conn=self._conn,
            producer=self._producer,
            bootstrap_servers=self._bootstrap_servers,
        )
        if processor.process_entry(outbox_id):
            status = "replayed"
        return ReplayResult(
            event_id=event_id,
            status=status,
            retry_count=retry_count,
            last_retried_at=replayed_at,
            payload=candidate,
        )

    def dismiss(self, event_id: str) -> None:
        self._load_row(event_id)
        self._conn.execute(
            "UPDATE dead_letter_events SET status = 'dismissed' WHERE event_id = ?",
            [event_id],
        )

    def _load_row(self, event_id: str) -> dict:
        row = self._conn.execute(
            """
            SELECT
                event_id,
                payload,
                retry_count
            FROM dead_letter_events
            WHERE event_id = ?
            """,
            [event_id],
        ).fetchone()
        if row is None:
            raise DeadLetterEventNotFoundError(event_id)
        return {
            "event_id": row[0],
            "payload": row[1],
            "retry_count": row[2],
        }

    def _decoded_payload(self, payload) -> dict:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            decoded = json.loads(payload)
            if isinstance(decoded, dict):
                return decoded
        raise ReplayValidationError("Dead-letter payload must be a JSON object.")

    def _validate(self, payload: dict) -> None:
        schema_result = validate_event(payload)
        if not schema_result.is_valid:
            first_error = schema_result.errors[0] if schema_result.errors else {}
            raise ReplayValidationError(first_error.get("msg", "Schema validation failed."))

        semantic_result = validate_semantics(payload)
        semantic_errors = [
            issue.message for issue in semantic_result.issues if issue.severity == "error"
        ]
        if semantic_errors:
            raise ReplayValidationError(semantic_errors[0])

    def _produce_to_kafka(self, topic: str, payload: dict) -> None:
        from confluent_kafka import Producer

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
            producer.produce(
                topic,
                key=str(payload.get("event_id", "")),
                value=json.dumps(payload).encode("utf-8"),
                headers=list(headers.items()) or None,
            )
            producer.flush(10)
