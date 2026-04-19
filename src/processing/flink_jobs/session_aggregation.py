from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.processing.flink_jobs.checkpointing import configure_checkpointing

if TYPE_CHECKING:
    from pyflink.datastream import StreamExecutionEnvironment


SESSION_GAP = timedelta(minutes=30)


@dataclass
class _SessionState:
    start_time: datetime
    last_time: datetime
    event_count: int
    total_value: float

    def to_snapshot(self) -> dict[str, object]:
        return {
            "start_time": self.start_time.isoformat(),
            "last_time": self.last_time.isoformat(),
            "event_count": self.event_count,
            "total_value": self.total_value,
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, object]) -> _SessionState:
        return cls(
            start_time=_parse_timestamp(snapshot["start_time"]),
            last_time=_parse_timestamp(snapshot["last_time"]),
            event_count=int(snapshot["event_count"]),
            total_value=float(snapshot["total_value"]),
        )


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamp must be an ISO-8601 string")

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _closed_session(user_id: str, state: _SessionState) -> dict[str, object]:
    return {
        "user_id": user_id,
        "session_start": state.start_time.isoformat(),
        "session_end": state.last_time.isoformat(),
        "event_count": state.event_count,
        "total_value": state.total_value,
        "status": "closed",
    }


class SessionAggregator:
    def __init__(self, session_gap: timedelta = SESSION_GAP):
        self._session_gap = session_gap
        self._state: dict[str, _SessionState] = {}

    def process_event(self, event: Mapping[str, object]) -> list[dict[str, object]]:
        user_id = str(event["user_id"])
        event_time = _parse_timestamp(event["timestamp"])
        value = float(event.get("value", 0.0) or 0.0)

        current = self._state.get(user_id)
        if current is None:
            self._state[user_id] = _SessionState(
                start_time=event_time,
                last_time=event_time,
                event_count=1,
                total_value=value,
            )
            return []

        if event_time - current.last_time > self._session_gap:
            closed = _closed_session(user_id, current)
            self._state[user_id] = _SessionState(
                start_time=event_time,
                last_time=event_time,
                event_count=1,
                total_value=value,
            )
            return [closed]

        current.start_time = min(current.start_time, event_time)
        current.last_time = max(current.last_time, event_time)
        current.event_count += 1
        current.total_value += value
        return []

    def snapshot(self) -> dict[str, dict[str, object]]:
        return {
            user_id: state.to_snapshot()
            for user_id, state in self._state.items()
        }

    def restore(self, snapshot: Mapping[str, Mapping[str, object]]) -> None:
        self._state = {
            str(user_id): _SessionState.from_snapshot(state)
            for user_id, state in snapshot.items()
        }


def build_session_pipeline(
    env: StreamExecutionEnvironment,
    source_topic: str,
    sink_topic: str,
) -> Any:
    try:
        from pyflink.common import Types
        from pyflink.common.serialization import SimpleStringSchema
        from pyflink.common.watermark_strategy import WatermarkStrategy
        from pyflink.datastream.connectors.kafka import (
            KafkaOffsetsInitializer,
            KafkaRecordSerializationSchema,
            KafkaSink,
            KafkaSource,
        )
        from pyflink.datastream.functions import KeyedProcessFunction
        from pyflink.datastream.state import MapStateDescriptor
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyFlink is not installed. Install the project with the 'flink' extra."
        ) from exc

    class FlinkSessionAggregator(KeyedProcessFunction):
        def open(self, runtime_context):
            descriptor = MapStateDescriptor(
                "session_state",
                Types.STRING(),
                Types.STRING(),
            )
            self.state = runtime_context.get_map_state(descriptor)

        def process_element(self, raw_event, ctx):
            event = json.loads(raw_event)
            user_id = str(event["user_id"])
            aggregator = SessionAggregator()

            if self.state.contains(user_id):
                aggregator.restore({user_id: json.loads(self.state.get(user_id))})

            for session in aggregator.process_event(event):
                yield json.dumps(session)

            self.state.put(user_id, json.dumps(aggregator.snapshot()[user_id]))

    configure_checkpointing(env)

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_topics(source_topic)
        .set_group_id("agentflow-session-aggregation")
        .set_starting_offsets(KafkaOffsetsInitializer.earliest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    sessions = (
        env.from_source(
            source,
            WatermarkStrategy.for_monotonous_timestamps(),
            "Session Aggregation Source",
        )
        .key_by(lambda raw: json.loads(raw)["user_id"])
        .process(FlinkSessionAggregator(), output_type=Types.STRING())
    )

    sink = (
        KafkaSink.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic(sink_topic)
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
        .build()
    )

    sessions.sink_to(sink)
    return sessions


def main() -> None:
    try:
        from pyflink.datastream import StreamExecutionEnvironment
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyFlink is not installed. Install the project with the 'flink' extra."
        ) from exc

    env = StreamExecutionEnvironment.get_execution_environment()
    build_session_pipeline(
        env=env,
        source_topic=os.getenv("FLINK_SOURCE_TOPIC", "events.validated"),
        sink_topic=os.getenv("FLINK_SESSION_SINK_TOPIC", "sessions.aggregated"),
    )
    env.execute("agentflow-session-aggregation")


if __name__ == "__main__":
    main()
