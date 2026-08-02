"""Canonical session aggregation Flink job.

Consumes validated events, groups tenant-scoped sessions with event-time
timers, and emits bounded session summaries after 30 minutes of inactivity.

Submit with:
    flink run -py src/processing/flink_jobs/session_aggregator.py
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from pyflink.common import Configuration, Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.time import Duration
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import (
    KafkaOffsetsInitializer,
    KafkaRecordSerializationSchema,
    KafkaSink,
    KafkaSource,
)
from pyflink.datastream.functions import KeyedProcessFunction
from pyflink.datastream.state import ValueStateDescriptor

from src.processing.flink_jobs.session_window import (
    accumulate_session,
    is_session_event,
    new_session,
    raw_session_key,
    summarize_session,
)
from src.processing.kafka_security import flink_kafka_security_properties

SESSION_GAP_MINUTES = 30
SESSION_GAP_MS = SESSION_GAP_MINUTES * 60 * 1000
WATERMARK_OUT_OF_ORDERNESS_SECONDS = 10
CHECKPOINT_INTERVAL_MS = 30_000
MAX_UNIQUE_PAGES = int(os.getenv("FLINK_SESSION_MAX_UNIQUE_PAGES", "1000"))
MAX_UNIQUE_PRODUCTS = int(os.getenv("FLINK_SESSION_MAX_UNIQUE_PRODUCTS", "1000"))


class ClickTimestampAssigner(TimestampAssigner):
    def extract_timestamp(self, value: str, record_timestamp: int) -> int:
        try:
            event = json.loads(value)
            ts = datetime.fromisoformat(event["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            return int(ts.timestamp() * 1000)
        except (json.JSONDecodeError, KeyError, ValueError):
            return record_timestamp


class SessionWindowFunction(KeyedProcessFunction):
    """Accumulates clickstream events using event-time gap timers.

    State per ``(tenant_id, session_id)``:
    - session_data: JSON with accumulated pages, first/last event time, event count
    - timer_ts: timestamp of the gap-expiry timer

    Events at or behind the current watermark are dropped and counted. Unique
    page/product collections are capped so a long-lived hot key cannot grow
    state without bound.
    """

    def __init__(
        self,
        *,
        max_unique_pages: int = MAX_UNIQUE_PAGES,
        max_unique_products: int = MAX_UNIQUE_PRODUCTS,
    ) -> None:
        if max_unique_pages < 1 or max_unique_products < 1:
            raise ValueError("session collection limits must be positive")
        self.max_unique_pages = max_unique_pages
        self.max_unique_products = max_unique_products

    def open(self, runtime_context: Any) -> None:
        self.session_state = runtime_context.get_state(
            ValueStateDescriptor("session_data", Types.STRING())
        )
        self.timer_state = runtime_context.get_state(ValueStateDescriptor("timer_ts", Types.LONG()))
        self.late_events_dropped = runtime_context.get_metric_group().counter("late_events_dropped")

    def process_element(self, value: str, ctx: KeyedProcessFunction.Context) -> None:
        event = json.loads(value)
        session_id = event.get("session_id")
        if not session_id:
            raise ValueError("session_id is required for session aggregation")
        event_ts = ctx.timestamp()
        if event_ts is None:
            raise ValueError("event timestamp is required for session aggregation")
        if event_ts <= ctx.timer_service().current_watermark():
            self.late_events_dropped.inc()
            return

        current = self.session_state.value()
        if current:
            session = json.loads(current)
        else:
            session = new_session(event, event_ts)

        # Out-of-order events that are still ahead of the watermark belong to
        # the session, but must not move its end backward or shorten the timer.
        accumulate_session(
            session,
            event,
            event_ts,
            max_unique_pages=self.max_unique_pages,
            max_unique_products=self.max_unique_products,
        )

        self.session_state.update(json.dumps(session))

        # Reset gap timer
        old_timer = self.timer_state.value()
        new_timer = session["last_event_ts"] + SESSION_GAP_MS
        if old_timer and old_timer != new_timer:
            ctx.timer_service().delete_event_time_timer(old_timer)
        if old_timer != new_timer:
            ctx.timer_service().register_event_time_timer(new_timer)
            self.timer_state.update(new_timer)

    def on_timer(self, timestamp: int, ctx: KeyedProcessFunction.OnTimerContext) -> Iterator[str]:
        """Session gap expired — emit session summary."""
        current = self.session_state.value()
        if not current:
            return

        session = json.loads(current)
        summary = summarize_session(session)

        # Emit
        yield json.dumps(summary)

        # Clear state
        self.session_state.clear()
        self.timer_state.clear()


def build_pipeline(
    *,
    env: StreamExecutionEnvironment | None = None,
    source_topic: str | None = None,
    sink_topic: str | None = None,
) -> StreamExecutionEnvironment:
    env = env or StreamExecutionEnvironment.get_execution_environment()
    checkpoint_interval_ms = int(
        os.getenv("FLINK_CHECKPOINT_INTERVAL_MS", str(CHECKPOINT_INTERVAL_MS))
    )
    env.enable_checkpointing(checkpoint_interval_ms)
    env.set_parallelism(int(os.getenv("FLINK_PARALLELISM", "2")))

    # Bounded restart budget — same rationale as stream_processor.build_pipeline:
    # a persistently failing job must park in FAILED, not restart forever.
    # Flink 2.x removed env.set_restart_strategy (FLIP-381); the strategy must
    # go through Configuration + env.configure.
    restart_config = Configuration()
    restart_config.set_string("restart-strategy.type", "failure-rate")
    restart_config.set_string(
        "restart-strategy.failure-rate.max-failures-per-interval",
        str(int(os.getenv("FLINK_RESTART_MAX_FAILURES_PER_INTERVAL", "3"))),
    )
    restart_config.set_string(
        "restart-strategy.failure-rate.failure-rate-interval",
        f"{int(os.getenv('FLINK_RESTART_FAILURE_RATE_INTERVAL_MS', '300000'))} ms",  # 5 min
    )
    restart_config.set_string(
        "restart-strategy.failure-rate.delay",
        f"{int(os.getenv('FLINK_RESTART_DELAY_MS', '10000'))} ms",  # 10s
    )
    env.configure(restart_config)

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    kafka_security = flink_kafka_security_properties()

    source_builder = (
        KafkaSource.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_topics(source_topic or os.getenv("FLINK_SESSION_SOURCE_TOPIC", "events.validated"))
        .set_group_id(os.getenv("FLINK_SESSION_GROUP_ID", "agentflow-session-aggregator"))
        .set_starting_offsets(KafkaOffsetsInitializer.earliest())
        .set_value_only_deserializer(SimpleStringSchema())
    )
    if kafka_security:
        source_builder.set_properties(kafka_security)
    source = source_builder.build()

    watermark_strategy = WatermarkStrategy.for_bounded_out_of_orderness(
        Duration.of_seconds(WATERMARK_OUT_OF_ORDERNESS_SECONDS)
    ).with_timestamp_assigner(ClickTimestampAssigner())

    stream = env.from_source(source, watermark_strategy, "session-events-source")

    sessions = (
        stream.filter(is_session_event)
        .key_by(raw_session_key)
        .process(SessionWindowFunction(), output_type=Types.STRING())
    )

    sink_builder = (
        KafkaSink.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic(sink_topic or os.getenv("FLINK_SESSION_SINK_TOPIC", "sessions.aggregated"))
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
    )
    if kafka_security:
        sink_builder.set_properties(kafka_security)
    sink = sink_builder.build()

    sessions.sink_to(sink)

    return env


if __name__ == "__main__":
    pipeline = build_pipeline()
    pipeline.execute("agentflow-session-aggregator")
