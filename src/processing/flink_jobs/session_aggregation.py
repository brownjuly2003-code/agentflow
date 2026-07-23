"""Compatibility surface for the canonical ``session_aggregator`` job.

The historical module contained a second Flink implementation that only
closed a session when another event arrived. Production build and launch now
delegate to ``session_aggregator.py``; the pure state helper remains for
callers that use it in deterministic, non-Flink tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

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
            event_count=int(cast(int, snapshot["event_count"])),
            total_value=float(cast(float, snapshot["total_value"])),
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
    """Deprecated deterministic helper; not a Flink job implementation."""

    def __init__(self, session_gap: timedelta = SESSION_GAP):
        self._session_gap = session_gap
        self._state: dict[str, _SessionState] = {}

    def process_event(self, event: Mapping[str, object]) -> list[dict[str, object]]:
        user_id = str(event["user_id"])
        event_time = _parse_timestamp(event["timestamp"])
        value = float(cast(float, event.get("value", 0.0) or 0.0))

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
        return {user_id: state.to_snapshot() for user_id, state in self._state.items()}

    def restore(self, snapshot: Mapping[str, Mapping[str, object]]) -> None:
        self._state = {
            str(user_id): _SessionState.from_snapshot(state) for user_id, state in snapshot.items()
        }


def build_session_pipeline(
    env: StreamExecutionEnvironment,
    source_topic: str,
    sink_topic: str,
) -> Any:
    """Delegate legacy callers to the one canonical Flink implementation."""
    from src.processing.flink_jobs.session_aggregator import build_pipeline

    return build_pipeline(
        env=env,
        source_topic=source_topic,
        sink_topic=sink_topic,
    )


def main() -> None:
    from src.processing.flink_jobs.session_aggregator import build_pipeline

    pipeline = build_pipeline()
    pipeline.execute("agentflow-session-aggregator")


if __name__ == "__main__":
    main()
