"""Session aggregation Flink job: builds user sessions from clickstream events.

Groups clickstream events into sessions using a 30-minute gap-based window.
Outputs session summaries with: duration, page count, conversion signals, funnel stage.

Submit with:
    flink run -py session_aggregator.py
"""

import json
import os
from datetime import UTC, datetime, timedelta

from pyflink.common import Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
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

SESSION_GAP_MINUTES = 30
SESSION_GAP_MS = SESSION_GAP_MINUTES * 60 * 1000
WATERMARK_OUT_OF_ORDERNESS_SECONDS = 10
CHECKPOINT_INTERVAL_MS = 30_000


class ClickTimestampAssigner(TimestampAssigner):
    def extract_timestamp(self, value, record_timestamp):
        try:
            event = json.loads(value)
            ts = datetime.fromisoformat(event["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            return int(ts.timestamp() * 1000)
        except (json.JSONDecodeError, KeyError, ValueError):
            return record_timestamp


class SessionWindowFunction(KeyedProcessFunction):
    """Accumulates clickstream events into sessions using processing-time timers.

    State per session_id:
    - session_data: JSON with accumulated pages, first/last event time, event count
    - timer_ts: timestamp of the gap-expiry timer

    When the timer fires (no new event for 30 min), emit session summary.
    """

    def open(self, runtime_context):
        self.session_state = runtime_context.get_state(
            ValueStateDescriptor("session_data", Types.STRING())
        )
        self.timer_state = runtime_context.get_state(
            ValueStateDescriptor("timer_ts", Types.LONG())
        )

    def process_element(self, value, ctx: KeyedProcessFunction.Context):
        event = json.loads(value)
        event_ts = ctx.timestamp()

        current = self.session_state.value()
        if current:
            session = json.loads(current)
        else:
            session = {
                "session_id": event.get("session_id", ctx.get_current_key()),
                "user_id": event.get("user_id"),
                "first_event_ts": event_ts,
                "last_event_ts": event_ts,
                "event_count": 0,
                "pages": [],
                "has_add_to_cart": False,
                "has_checkout": False,
                "product_ids_viewed": [],
            }

        # Update session
        session["last_event_ts"] = event_ts
        session["event_count"] += 1

        page = event.get("page_url", "")
        if page and page not in session["pages"]:
            session["pages"].append(page)

        if event.get("event_type") == "add_to_cart":
            session["has_add_to_cart"] = True
        if "/checkout" in page:
            session["has_checkout"] = True

        pid = event.get("product_id")
        if pid and pid not in session["product_ids_viewed"]:
            session["product_ids_viewed"].append(pid)

        self.session_state.update(json.dumps(session))

        # Reset gap timer
        old_timer = self.timer_state.value()
        if old_timer:
            ctx.timer_service().delete_event_time_timer(old_timer)

        new_timer = event_ts + SESSION_GAP_MS
        ctx.timer_service().register_event_time_timer(new_timer)
        self.timer_state.update(new_timer)

    def on_timer(self, timestamp, ctx: KeyedProcessFunction.OnTimerContext):
        """Session gap expired — emit session summary."""
        current = self.session_state.value()
        if not current:
            return

        session = json.loads(current)
        duration_ms = session["last_event_ts"] - session["first_event_ts"]

        # Determine funnel stage
        if session["has_checkout"]:
            funnel_stage = "checkout"
        elif session["has_add_to_cart"]:
            funnel_stage = "add_to_cart"
        elif len(session["product_ids_viewed"]) > 0:
            funnel_stage = "product_view"
        elif session["event_count"] > 1:
            funnel_stage = "browse"
        else:
            funnel_stage = "bounce"

        summary = {
            "session_id": session["session_id"],
            "user_id": session["user_id"],
            "started_at": datetime.fromtimestamp(
                session["first_event_ts"] / 1000, tz=UTC
            ).isoformat(),
            "ended_at": datetime.fromtimestamp(
                session["last_event_ts"] / 1000, tz=UTC
            ).isoformat(),
            "duration_seconds": duration_ms / 1000,
            "event_count": session["event_count"],
            "unique_pages": len(session["pages"]),
            "products_viewed": len(session["product_ids_viewed"]),
            "funnel_stage": funnel_stage,
            "is_conversion": session["has_checkout"],
        }

        # Emit
        yield json.dumps(summary)

        # Clear state
        self.session_state.clear()
        self.timer_state.clear()


def build_pipeline():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.enable_checkpointing(CHECKPOINT_INTERVAL_MS)
    env.set_parallelism(int(os.getenv("FLINK_PARALLELISM", "2")))

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    source = KafkaSource.builder() \
        .set_bootstrap_servers(bootstrap_servers) \
        .set_topics("clicks.raw") \
        .set_group_id("agentflow-session-aggregator") \
        .set_starting_offsets(KafkaOffsetsInitializer.earliest()) \
        .set_value_only_deserializer(SimpleStringSchema()) \
        .build()

    watermark_strategy = WatermarkStrategy \
        .for_bounded_out_of_orderness(
            timedelta(seconds=WATERMARK_OUT_OF_ORDERNESS_SECONDS)
        ) \
        .with_timestamp_assigner(ClickTimestampAssigner())

    stream = env.from_source(source, watermark_strategy, "clicks-source")

    sessions = stream \
        .key_by(lambda x: json.loads(x).get("session_id", "unknown")) \
        .process(SessionWindowFunction(), output_type=Types.STRING())

    sink = KafkaSink.builder() \
        .set_bootstrap_servers(bootstrap_servers) \
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic("sessions.aggregated")
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        ) \
        .build()

    sessions.sink_to(sink)

    return env


if __name__ == "__main__":
    pipeline = build_pipeline()
    pipeline.execute("agentflow-session-aggregator")
