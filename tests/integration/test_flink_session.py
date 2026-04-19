from datetime import UTC, datetime, timedelta

from src.processing.flink_jobs.checkpointing import configure_checkpointing
from src.processing.flink_jobs.session_aggregation import SESSION_GAP, SessionAggregator

BASE_TIME = datetime(2026, 4, 12, 12, 0, tzinfo=UTC)


def _event(user_id: str, offset_minutes: int, value: float = 0.0) -> dict:
    return {
        "user_id": user_id,
        "timestamp": (BASE_TIME + timedelta(minutes=offset_minutes)).isoformat(),
        "value": value,
    }


def test_session_opens_on_first_event():
    aggregator = SessionAggregator()

    emitted = aggregator.process_event(_event("user-1", 0, value=10.0))

    assert emitted == []
    assert aggregator.snapshot() == {
        "user-1": {
            "start_time": BASE_TIME.isoformat(),
            "last_time": BASE_TIME.isoformat(),
            "event_count": 1,
            "total_value": 10.0,
        }
    }


def test_session_updates_within_gap():
    aggregator = SessionAggregator()
    aggregator.process_event(_event("user-1", 0, value=10.0))

    emitted = aggregator.process_event(_event("user-1", 20, value=7.5))

    assert emitted == []
    assert aggregator.snapshot()["user-1"] == {
        "start_time": BASE_TIME.isoformat(),
        "last_time": (BASE_TIME + timedelta(minutes=20)).isoformat(),
        "event_count": 2,
        "total_value": 17.5,
    }


def test_session_closes_when_gap_exceeds_threshold():
    aggregator = SessionAggregator()
    aggregator.process_event(_event("user-1", 0, value=10.0))
    aggregator.process_event(_event("user-1", 10, value=5.0))

    emitted = aggregator.process_event(_event("user-1", 45, value=2.0))

    assert emitted == [
        {
            "user_id": "user-1",
            "session_start": BASE_TIME.isoformat(),
            "session_end": (BASE_TIME + timedelta(minutes=10)).isoformat(),
            "event_count": 2,
            "total_value": 15.0,
            "status": "closed",
        }
    ]
    assert aggregator.snapshot()["user-1"] == {
        "start_time": (BASE_TIME + timedelta(minutes=45)).isoformat(),
        "last_time": (BASE_TIME + timedelta(minutes=45)).isoformat(),
        "event_count": 1,
        "total_value": 2.0,
    }


def test_session_state_survives_snapshot_restore():
    aggregator = SessionAggregator()
    aggregator.process_event(_event("user-1", 0, value=10.0))
    aggregator.process_event(_event("user-1", 5, value=5.0))
    snapshot = aggregator.snapshot()

    restored = SessionAggregator()
    restored.restore(snapshot)

    emitted = restored.process_event(_event("user-1", 25, value=2.5))

    assert emitted == []
    assert restored.snapshot()["user-1"] == {
        "start_time": BASE_TIME.isoformat(),
        "last_time": (BASE_TIME + timedelta(minutes=25)).isoformat(),
        "event_count": 3,
        "total_value": 17.5,
    }


def test_sessions_are_isolated_per_user():
    aggregator = SessionAggregator()
    aggregator.process_event(_event("user-1", 0, value=1.0))
    aggregator.process_event(_event("user-2", 0, value=3.0))
    aggregator.process_event(_event("user-2", 5, value=4.0))

    emitted = aggregator.process_event(
        {
            "user_id": "user-1",
            "timestamp": (BASE_TIME + SESSION_GAP + timedelta(minutes=1)).isoformat(),
            "value": 2.0,
        }
    )

    assert emitted == [
        {
            "user_id": "user-1",
            "session_start": BASE_TIME.isoformat(),
            "session_end": BASE_TIME.isoformat(),
            "event_count": 1,
            "total_value": 1.0,
            "status": "closed",
        }
    ]
    assert aggregator.snapshot()["user-2"] == {
        "start_time": BASE_TIME.isoformat(),
        "last_time": (BASE_TIME + timedelta(minutes=5)).isoformat(),
        "event_count": 2,
        "total_value": 7.0,
    }


class _FakeCheckpointConfig:
    def __init__(self):
        self.mode = None
        self.min_pause = None
        self.timeout = None
        self.max_concurrent = None
        self.cleanup = None
        self.storage = None

    def set_checkpointing_mode(self, value):
        self.mode = value

    def set_min_pause_between_checkpoints(self, value):
        self.min_pause = value

    def set_checkpoint_timeout(self, value):
        self.timeout = value

    def set_max_concurrent_checkpoints(self, value):
        self.max_concurrent = value

    def enable_externalized_checkpoints(self, value):
        self.cleanup = value

    def set_checkpoint_storage(self, value):
        self.storage = value


class _FakeEnv:
    def __init__(self):
        self.interval = None
        self.config = _FakeCheckpointConfig()

    def enable_checkpointing(self, value):
        self.interval = value

    def get_checkpoint_config(self):
        return self.config


def test_checkpointing_configuration_uses_exactly_once(monkeypatch):
    env = _FakeEnv()
    monkeypatch.setenv("FLINK_CHECKPOINT_DIR", "file:///var/lib/flink-checkpoints")

    configure_checkpointing(env)

    assert env.interval == 60_000
    assert env.config.mode == "EXACTLY_ONCE"
    assert env.config.min_pause == 30_000
    assert env.config.timeout == 120_000
    assert env.config.max_concurrent == 1
    assert env.config.cleanup == "RETAIN_ON_CANCELLATION"
    assert env.config.storage == "file:///var/lib/flink-checkpoints"
