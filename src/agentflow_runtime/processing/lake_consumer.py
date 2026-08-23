"""Idempotent ``events.validated`` to Iceberg materializer."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from collections.abc import Sequence
from typing import Any, NamedTuple

import structlog

from agentflow_runtime.processing.iceberg_sink import IcebergSink
from agentflow_runtime.processing.kafka_security import confluent_kafka_consumer_config

logger = structlog.get_logger()

VALIDATED_TOPIC = "events.validated"
DEFAULT_GROUP_ID = "agentflow-iceberg-materializer"


class LakeBatchResult(NamedTuple):
    consumed: int
    appended: int
    duplicates: int


class ValidatedLakeConsumer:
    def __init__(
        self,
        consumer: Any,
        *,
        sink: IcebergSink,
        batch_max: int = 256,
        poll_timeout: float = 1.0,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        self._consumer = consumer
        self._sink = sink
        self._batch_max = batch_max
        self._poll_timeout = poll_timeout
        self._retry_backoff_seconds = retry_backoff_seconds

    def _apply_batch(self, messages: Sequence[Any]) -> LakeBatchResult:
        unique_events: dict[tuple[str, str], dict[str, Any]] = {}
        duplicates = 0
        for message in messages:
            event = json.loads(message.value().decode("utf-8"))
            if not isinstance(event, dict) or not event.get("event_id"):
                raise ValueError("validated lake event is missing event_id")
            if not event.get("tenant"):
                raise ValueError("validated lake event is missing tenant")
            identity = (str(event["tenant"]), str(event["event_id"]))
            if identity in unique_events:
                duplicates += 1
                continue
            unique_events[identity] = event

        existing = self._sink.existing_event_identities(
            "validated_events",
            list(unique_events),
        )
        duplicates += len(existing)
        to_append = [event for identity, event in unique_events.items() if identity not in existing]
        appended = self._sink.write_batch("validated_events", to_append)
        return LakeBatchResult(
            consumed=len(messages),
            appended=appended,
            duplicates=duplicates,
        )

    def run_once(self) -> LakeBatchResult | None:
        messages = self._consumer.consume(
            num_messages=self._batch_max,
            timeout=self._poll_timeout,
        )
        messages = [message for message in (messages or []) if not _is_error(message)]
        if not messages:
            return None
        try:
            result = self._apply_batch(messages)
        except Exception:
            logger.error("lake_materialization_failed", exc_info=True)
            self._rewind(messages)
            time.sleep(self._retry_backoff_seconds)
            return None

        self._consumer.commit(asynchronous=False)
        logger.info(
            "lake_batch_materialized",
            consumed=result.consumed,
            appended=result.appended,
            duplicates=result.duplicates,
        )
        return result

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            self.run_once()

    def _rewind(self, messages: Sequence[Any]) -> None:
        first: dict[tuple[str, int], Any] = {}
        for message in messages:
            key = (message.topic(), message.partition())
            if key not in first or message.offset() < first[key].offset():
                first[key] = message
        from confluent_kafka import TopicPartition

        for message in first.values():
            self._consumer.seek(
                TopicPartition(message.topic(), message.partition(), message.offset())
            )


def _is_error(message: Any) -> bool:
    if message is None:
        return True
    return message.error() is not None


def main() -> int:
    from confluent_kafka import Consumer

    sink = IcebergSink(os.getenv("AGENTFLOW_ICEBERG_CONFIG", "config/iceberg.yaml"))
    consumer = Consumer(
        confluent_kafka_consumer_config(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            group_id=os.getenv("AGENTFLOW_LAKE_GROUP_ID", DEFAULT_GROUP_ID),
            offset_reset=os.getenv("AGENTFLOW_LAKE_OFFSET_RESET", "earliest"),
        )
    )
    consumer.subscribe([VALIDATED_TOPIC])

    stop_event = threading.Event()

    def _stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    materializer = ValidatedLakeConsumer(consumer, sink=sink)
    try:
        materializer.run_forever(stop_event)
    finally:
        consumer.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
