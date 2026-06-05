"""Unit tests for the Flink wiring in session_aggregation.build_session_pipeline.

The pyflink surface is faked through sys.modules (the imports inside
build_session_pipeline resolve at call time), so these run without PyFlink.
They pin the audit M-C2 fix: one SessionAggregator instance per operator,
created in open(), with full-replace restore() per event so no state leaks
between keys and recovery still reads Flink state as the source of truth.
"""

import json
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

from src.processing.flink_jobs import session_aggregation

BASE_TIME = datetime(2026, 4, 12, 12, 0, tzinfo=UTC)


class _FakeMapState:
    def __init__(self):
        self.entries = {}

    def contains(self, key):
        return key in self.entries

    def get(self, key):
        return self.entries[key]

    def put(self, key, value):
        self.entries[key] = value


class _FakeRuntimeContext:
    def __init__(self):
        self.descriptors = []
        self.map_state = _FakeMapState()

    def get_map_state(self, descriptor):
        self.descriptors.append(descriptor)
        return self.map_state


class _FakeCheckpointConfig:
    def set_checkpointing_mode(self, value):
        self.mode = value

    def set_min_pause_between_checkpoints(self, value):
        self.min_pause = value

    def set_checkpoint_timeout(self, value):
        self.timeout = value

    def set_max_concurrent_checkpoints(self, value):
        self.max_concurrent = value

    def set_externalized_checkpoint_retention(self, value):
        self.retention = value


class _FakeProcessedStream:
    def __init__(self):
        self.sink = None

    def sink_to(self, sink):
        self.sink = sink


class _FakeKeyedStream:
    def __init__(self, env):
        self.env = env

    def process(self, function, output_type=None):
        self.env.process_function = function
        self.env.process_output_type = output_type
        return self.env.processed_stream


class _FakeSourceStream:
    def __init__(self, env):
        self.env = env

    def key_by(self, fn):
        self.env.key_by_fn = fn
        return _FakeKeyedStream(self.env)


class _FakeEnv:
    def __init__(self):
        self.checkpoint_config = _FakeCheckpointConfig()
        self.processed_stream = _FakeProcessedStream()
        self.process_function = None
        self.process_output_type = None
        self.key_by_fn = None

    def enable_checkpointing(self, interval):
        self.checkpointing = interval

    def get_checkpoint_config(self):
        return self.checkpoint_config

    def configure(self, configuration):
        self.configured = configuration

    def from_source(self, source, watermark_strategy, name):
        self.from_source_args = (source, watermark_strategy, name)
        return _FakeSourceStream(self)


@pytest.fixture
def fake_pyflink(monkeypatch):
    pyflink = types.ModuleType("pyflink")
    pyflink.__path__ = []

    common = types.ModuleType("pyflink.common")
    common.__path__ = []

    class _Types:
        @staticmethod
        def STRING():
            return "STRING"

    common.Types = _Types

    class _Configuration:
        def __init__(self):
            self.values = {}

        def set_string(self, key, value):
            self.values[key] = value
            return self

    common.Configuration = _Configuration

    serialization = types.ModuleType("pyflink.common.serialization")

    class _SimpleStringSchema:
        pass

    serialization.SimpleStringSchema = _SimpleStringSchema

    watermark_strategy = types.ModuleType("pyflink.common.watermark_strategy")

    class _WatermarkStrategy:
        @classmethod
        def for_monotonous_timestamps(cls):
            return cls()

    watermark_strategy.WatermarkStrategy = _WatermarkStrategy

    datastream = types.ModuleType("pyflink.datastream")
    datastream.__path__ = []

    class _CheckpointingMode:
        EXACTLY_ONCE = "EXACTLY_ONCE"

    class _ExternalizedCheckpointRetention:
        RETAIN_ON_CANCELLATION = "RETAIN_ON_CANCELLATION"

    datastream.CheckpointingMode = _CheckpointingMode
    datastream.ExternalizedCheckpointRetention = _ExternalizedCheckpointRetention

    connectors = types.ModuleType("pyflink.datastream.connectors")
    connectors.__path__ = []
    kafka = types.ModuleType("pyflink.datastream.connectors.kafka")

    class _Builder:
        def __getattr__(self, name):
            if name.startswith("set_"):
                return lambda *args, **kwargs: self
            raise AttributeError(name)

        def build(self):
            return {}

    class _KafkaSource:
        @staticmethod
        def builder():
            return _Builder()

    class _KafkaSink:
        @staticmethod
        def builder():
            return _Builder()

    class _KafkaRecordSerializationSchema:
        @staticmethod
        def builder():
            return _Builder()

    class _KafkaOffsetsInitializer:
        @staticmethod
        def earliest():
            return "earliest"

    kafka.KafkaSource = _KafkaSource
    kafka.KafkaSink = _KafkaSink
    kafka.KafkaRecordSerializationSchema = _KafkaRecordSerializationSchema
    kafka.KafkaOffsetsInitializer = _KafkaOffsetsInitializer

    functions = types.ModuleType("pyflink.datastream.functions")

    class _KeyedProcessFunction:
        class Context:
            pass

    functions.KeyedProcessFunction = _KeyedProcessFunction

    state = types.ModuleType("pyflink.datastream.state")

    class _MapStateDescriptor:
        def __init__(self, name, key_type, value_type):
            self.name = name
            self.key_type = key_type
            self.value_type = value_type

    state.MapStateDescriptor = _MapStateDescriptor

    common.serialization = serialization
    common.watermark_strategy = watermark_strategy
    datastream.connectors = connectors
    connectors.kafka = kafka
    datastream.functions = functions
    datastream.state = state
    pyflink.common = common
    pyflink.datastream = datastream

    monkeypatch.setitem(sys.modules, "pyflink", pyflink)
    monkeypatch.setitem(sys.modules, "pyflink.common", common)
    monkeypatch.setitem(sys.modules, "pyflink.common.serialization", serialization)
    monkeypatch.setitem(sys.modules, "pyflink.common.watermark_strategy", watermark_strategy)
    monkeypatch.setitem(sys.modules, "pyflink.datastream", datastream)
    monkeypatch.setitem(sys.modules, "pyflink.datastream.connectors", connectors)
    monkeypatch.setitem(sys.modules, "pyflink.datastream.connectors.kafka", kafka)
    monkeypatch.setitem(sys.modules, "pyflink.datastream.functions", functions)
    monkeypatch.setitem(sys.modules, "pyflink.datastream.state", state)


def _build_process_function(monkeypatch):
    env = _FakeEnv()
    session_aggregation.build_session_pipeline(env, "smoke-in", "smoke-out")
    function = env.process_function
    assert function is not None
    runtime_context = _FakeRuntimeContext()
    function.open(runtime_context)
    return function, runtime_context


def _event(user_id, offset_minutes, value=1.0):
    return json.dumps(
        {
            "user_id": user_id,
            "timestamp": (BASE_TIME + timedelta(minutes=offset_minutes)).isoformat(),
            "value": value,
        }
    )


def test_flink_session_aggregator_is_constructed_once(fake_pyflink, monkeypatch):
    instances = []
    real_aggregator = session_aggregation.SessionAggregator

    class _CountingAggregator(real_aggregator):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(session_aggregation, "SessionAggregator", _CountingAggregator)

    function, _ = _build_process_function(monkeypatch)

    assert list(function.process_element(_event("user-1", 0), None)) == []
    assert list(function.process_element(_event("user-2", 0), None)) == []

    assert len(instances) == 1


def test_restore_replaces_state_so_keys_do_not_leak(fake_pyflink, monkeypatch):
    instances = []
    real_aggregator = session_aggregation.SessionAggregator

    class _CountingAggregator(real_aggregator):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    monkeypatch.setattr(session_aggregation, "SessionAggregator", _CountingAggregator)

    function, runtime_context = _build_process_function(monkeypatch)

    list(function.process_element(_event("user-1", 0), None))
    list(function.process_element(_event("user-2", 0), None))

    # Flink state carries both keys; the shared in-memory aggregator must
    # only ever hold the key of the event being processed (full-replace
    # restore), so recovery reads Flink state, never a stale local copy.
    assert set(runtime_context.map_state.entries) == {"user-1", "user-2"}
    assert set(instances[-1]._state) == {"user-2"}


def test_session_closes_across_state_round_trip(fake_pyflink, monkeypatch):
    function, runtime_context = _build_process_function(monkeypatch)

    assert list(function.process_element(_event("user-1", 0, value=10.0), None)) == []
    emitted = [
        json.loads(item) for item in function.process_element(_event("user-1", 45, value=2.0), None)
    ]

    assert emitted == [
        {
            "user_id": "user-1",
            "session_start": BASE_TIME.isoformat(),
            "session_end": BASE_TIME.isoformat(),
            "event_count": 1,
            "total_value": 10.0,
            "status": "closed",
        }
    ]
    snapshot = json.loads(runtime_context.map_state.entries["user-1"])
    assert snapshot["event_count"] == 1
    assert snapshot["total_value"] == 2.0
