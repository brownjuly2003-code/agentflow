from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import duckdb
import structlog
from opentelemetry import trace

from src.processing.outbox import OutboxProcessor
from src.processing.tracing import inject_trace_to_kafka_headers, telemetry_disabled
from src.quality.validators.schema_validator import validate_event
from src.quality.validators.semantic_validator import validate_semantics
from src.serving.control_plane import ControlPlaneStore, EmbeddedControlPlaneStore

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


class EventReplayer:
    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection | None = None,
        producer: Callable[[str, dict], None] | None = None,
        bootstrap_servers: str | None = None,
        *,
        store: ControlPlaneStore | None = None,
    ) -> None:
        if conn is None and store is None:
            raise ValueError("conn or store is required")
        self._producer = producer or self._produce_to_kafka
        self._bootstrap_servers = bootstrap_servers or DEFAULT_KAFKA_BOOTSTRAP
        # ADR 0010 slice 3: table access goes through the ControlPlaneStore
        # port, same seam as OutboxProcessor. routers/deadletter.py resolves
        # the app's shared store and passes it via ``store=`` so it never
        # reaches the query engine's connection directly.
        if store is not None:
            self._store: ControlPlaneStore = store
        else:
            assert conn is not None  # guaranteed by the check above
            resolved_conn = conn
            self._store = EmbeddedControlPlaneStore(conn_provider=lambda: resolved_conn)
        self._store.ensure_outbox_schema()

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
        self._store.enqueue_outbox_replay(
            outbox_id=outbox_id,
            event_id=event_id,
            payload=candidate,
            topic=DEFAULT_REPLAY_TOPIC,
            retry_count=retry_count,
            replayed_at=replayed_at,
        )
        status = "replay_pending"
        processor = OutboxProcessor(
            store=self._store,
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
        self._store.dismiss_dead_letter_event(event_id)

    def _load_row(self, event_id: str) -> dict:
        row = self._store.get_dead_letter_event_for_replay(event_id)
        if row is None:
            raise DeadLetterEventNotFoundError(event_id)
        return row

    def _decoded_payload(self, payload: object) -> dict:
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
