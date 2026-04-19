import importlib
import json
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest


class _FakeValueState:
    def __init__(self):
        self.current = None
        self.was_cleared = False

    def value(self):
        return self.current

    def update(self, value):
        self.current = value

    def clear(self):
        self.current = None
        self.was_cleared = True


class _FakeRuntimeContext:
    def __init__(self):
        self.descriptors = []
        self.states = {}

    def get_state(self, descriptor):
        self.descriptors.append(descriptor)
        return self.states.setdefault(descriptor.name, _FakeValueState())


class _FakeTimerService:
    def __init__(self):
        self.registered = []
        self.deleted = []

    def register_event_time_timer(self, value):
        self.registered.append(value)

    def delete_event_time_timer(self, value):
        self.deleted.append(value)


class _FakeProcessContext:
    def __init__(self, timestamp, key="session-key", timer_service=None):
        self._timestamp = timestamp
        self._key = key
        self._timer_service = timer_service or _FakeTimerService()

    def timestamp(self):
        return self._timestamp

    def get_current_key(self):
        return self._key

    def timer_service(self):
        return self._timer_service


class _FakeStream:
    def __init__(self):
        self.key_by_fn = None
        self.process_function = None
        self.output_type = None
        self.sink = None

    def key_by(self, func):
        self.key_by_fn = func
        return self

    def process(self, function, output_type=None):
        self.process_function = function
        self.output_type = output_type
        return self

    def sink_to(self, sink):
        self.sink = sink


class _FakeExecutionEnvironment:
    current_env = None

    @classmethod
    def get_execution_environment(cls):
        return cls.current_env or cls()

    def __init__(self):
        self.checkpointing = None
        self.parallelism = None
        self.from_source_args = None
        self.stream = _FakeStream()

    def enable_checkpointing(self, interval):
        self.checkpointing = interval

    def set_parallelism(self, value):
        self.parallelism = value

    def from_source(self, source, watermark_strategy, name):
        self.from_source_args = (source, watermark_strategy, name)
        return self.stream

    def execute(self, job_name):
        self.job_name = job_name


@pytest.fixture
def session_aggregator(monkeypatch):
    target = "src.processing.flink_jobs.session_aggregator"
    for name in list(sys.modules):
        if name == target or name.startswith("pyflink"):
            sys.modules.pop(name, None)

    pyflink = types.ModuleType("pyflink")
    pyflink.__path__ = []

    common = types.ModuleType("pyflink.common")
    common.__path__ = []

    class _Types:
        @staticmethod
        def STRING():
            return "STRING"

        @staticmethod
        def LONG():
            return "LONG"

    class _WatermarkStrategy:
        def __init__(self, out_of_orderness=None):
            self.out_of_orderness = out_of_orderness
            self.timestamp_assigner = None

        @classmethod
        def for_bounded_out_of_orderness(cls, value):
            return cls(value)

        def with_timestamp_assigner(self, assigner):
            self.timestamp_assigner = assigner
            return self

    common.Types = _Types
    common.WatermarkStrategy = _WatermarkStrategy

    serialization = types.ModuleType("pyflink.common.serialization")

    class _SimpleStringSchema:
        pass

    serialization.SimpleStringSchema = _SimpleStringSchema

    watermark_strategy = types.ModuleType("pyflink.common.watermark_strategy")

    class _TimestampAssigner:
        pass

    watermark_strategy.TimestampAssigner = _TimestampAssigner

    datastream = types.ModuleType("pyflink.datastream")
    datastream.__path__ = []
    datastream.StreamExecutionEnvironment = _FakeExecutionEnvironment

    connectors = types.ModuleType("pyflink.datastream.connectors")
    connectors.__path__ = []
    kafka = types.ModuleType("pyflink.datastream.connectors.kafka")

    class _Builder:
        def __init__(self):
            self.values = {}

        def set_bootstrap_servers(self, value):
            self.values["bootstrap_servers"] = value
            return self

        def set_topics(self, value):
            self.values["topics"] = value
            return self

        def set_group_id(self, value):
            self.values["group_id"] = value
            return self

        def set_starting_offsets(self, value):
            self.values["starting_offsets"] = value
            return self

        def set_value_only_deserializer(self, value):
            self.values["value_only_deserializer"] = value
            return self

        def set_record_serializer(self, value):
            self.values["record_serializer"] = value
            return self

        def set_topic(self, value):
            self.values["topic"] = value
            return self

        def set_value_serialization_schema(self, value):
            self.values["value_serialization_schema"] = value
            return self

        def build(self):
            return dict(self.values)

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

        class OnTimerContext:
            pass

    functions.KeyedProcessFunction = _KeyedProcessFunction

    state = types.ModuleType("pyflink.datastream.state")

    class _ValueStateDescriptor:
        def __init__(self, name, type_info):
            self.name = name
            self.type_info = type_info

    state.ValueStateDescriptor = _ValueStateDescriptor

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

    return importlib.import_module(target)


@pytest.fixture
def opened_window(session_aggregator):
    runtime_context = _FakeRuntimeContext()
    window = session_aggregator.SessionWindowFunction()
    window.open(runtime_context)
    return session_aggregator, window, runtime_context


def test_extract_timestamp_uses_event_timestamp(session_aggregator):
    assigner = session_aggregator.ClickTimestampAssigner()

    result = assigner.extract_timestamp(
        json.dumps({"timestamp": "2026-04-17T09:30:00+00:00"}),
        123,
    )

    assert result == int(datetime(2026, 4, 17, 9, 30, tzinfo=UTC).timestamp() * 1000)


def test_extract_timestamp_assumes_utc_for_naive_values(session_aggregator):
    assigner = session_aggregator.ClickTimestampAssigner()

    result = assigner.extract_timestamp(
        json.dumps({"timestamp": "2026-04-17T09:30:00"}),
        456,
    )

    assert result == int(datetime(2026, 4, 17, 9, 30, tzinfo=UTC).timestamp() * 1000)


@pytest.mark.parametrize(
    ("payload", "record_timestamp"),
    [
        ("not-json", 111),
        (json.dumps({"event_type": "page_view"}), 222),
        (json.dumps({"timestamp": "invalid"}), 333),
    ],
)
def test_extract_timestamp_falls_back_for_invalid_payload(
    session_aggregator, payload, record_timestamp
):
    assigner = session_aggregator.ClickTimestampAssigner()

    result = assigner.extract_timestamp(payload, record_timestamp)

    assert result == record_timestamp


def test_open_initializes_value_states(opened_window):
    session_aggregator, _, runtime_context = opened_window

    assert [descriptor.name for descriptor in runtime_context.descriptors] == [
        "session_data",
        "timer_ts",
    ]
    assert [descriptor.type_info for descriptor in runtime_context.descriptors] == [
        session_aggregator.Types.STRING(),
        session_aggregator.Types.LONG(),
    ]


def test_process_element_initializes_session_and_timer(opened_window):
    session_aggregator, window, _ = opened_window
    timer_service = _FakeTimerService()
    event_ts = int(datetime(2026, 4, 17, 10, 0, tzinfo=UTC).timestamp() * 1000)

    window.process_element(
        json.dumps(
            {
                "session_id": "session-1",
                "user_id": "user-1",
                "event_type": "page_view",
                "page_url": "/products/sku-1",
                "product_id": "sku-1",
            }
        ),
        _FakeProcessContext(event_ts, timer_service=timer_service),
    )

    session = json.loads(window.session_state.value())
    assert session == {
        "session_id": "session-1",
        "user_id": "user-1",
        "first_event_ts": event_ts,
        "last_event_ts": event_ts,
        "event_count": 1,
        "pages": ["/products/sku-1"],
        "has_add_to_cart": False,
        "has_checkout": False,
        "product_ids_viewed": ["sku-1"],
    }
    assert timer_service.deleted == []
    assert timer_service.registered == [event_ts + session_aggregator.SESSION_GAP_MS]
    assert window.timer_state.value() == event_ts + session_aggregator.SESSION_GAP_MS


def test_process_element_updates_session_and_deduplicates_collections(opened_window):
    session_aggregator, window, _ = opened_window
    timer_service = _FakeTimerService()
    first_ts = int(datetime(2026, 4, 17, 10, 0, tzinfo=UTC).timestamp() * 1000)
    second_ts = int(datetime(2026, 4, 17, 10, 5, tzinfo=UTC).timestamp() * 1000)

    window.process_element(
        json.dumps(
            {
                "session_id": "session-1",
                "user_id": "user-1",
                "event_type": "page_view",
                "page_url": "/products/sku-1",
                "product_id": "sku-1",
            }
        ),
        _FakeProcessContext(first_ts, timer_service=timer_service),
    )
    window.process_element(
        json.dumps(
            {
                "session_id": "session-1",
                "user_id": "user-1",
                "event_type": "add_to_cart",
                "page_url": "/checkout",
                "product_id": "sku-1",
            }
        ),
        _FakeProcessContext(second_ts, timer_service=timer_service),
    )

    session = json.loads(window.session_state.value())
    assert session["first_event_ts"] == first_ts
    assert session["last_event_ts"] == second_ts
    assert session["event_count"] == 2
    assert session["pages"] == ["/products/sku-1", "/checkout"]
    assert session["has_add_to_cart"] is True
    assert session["has_checkout"] is True
    assert session["product_ids_viewed"] == ["sku-1"]
    assert timer_service.deleted == [first_ts + session_aggregator.SESSION_GAP_MS]
    assert timer_service.registered[-1] == second_ts + session_aggregator.SESSION_GAP_MS


def test_process_element_uses_current_key_for_missing_session_id(opened_window):
    _, window, _ = opened_window
    event_ts = int(datetime(2026, 4, 17, 10, 0, tzinfo=UTC).timestamp() * 1000)

    window.process_element(
        json.dumps({"user_id": "user-1", "event_type": "page_view"}),
        _FakeProcessContext(event_ts, key="derived-session"),
    )

    session = json.loads(window.session_state.value())
    assert session["session_id"] == "derived-session"


def test_on_timer_returns_no_output_when_state_is_empty(opened_window):
    _, window, _ = opened_window

    assert list(window.on_timer(123, object())) == []


def test_on_timer_emits_summary_and_clears_state(opened_window):
    _, window, _ = opened_window
    start = int(datetime(2026, 4, 17, 10, 0, tzinfo=UTC).timestamp() * 1000)
    end = int(datetime(2026, 4, 17, 10, 12, tzinfo=UTC).timestamp() * 1000)
    window.session_state.update(
        json.dumps(
            {
                "session_id": "session-1",
                "user_id": "user-1",
                "first_event_ts": start,
                "last_event_ts": end,
                "event_count": 1,
                "pages": ["/landing"],
                "has_add_to_cart": False,
                "has_checkout": False,
                "product_ids_viewed": [],
            }
        )
    )
    window.timer_state.update(end + 1)

    emitted = [json.loads(item) for item in window.on_timer(end + 1, object())]

    assert emitted == [
        {
            "session_id": "session-1",
            "user_id": "user-1",
            "started_at": "2026-04-17T10:00:00+00:00",
            "ended_at": "2026-04-17T10:12:00+00:00",
            "duration_seconds": 720.0,
            "event_count": 1,
            "unique_pages": 1,
            "products_viewed": 0,
            "funnel_stage": "bounce",
            "is_conversion": False,
        }
    ]
    assert window.session_state.value() is None
    assert window.timer_state.value() is None
    assert window.session_state.was_cleared is True
    assert window.timer_state.was_cleared is True


@pytest.mark.parametrize(
    ("session", "expected_stage", "expected_conversion"),
    [
        (
            {
                "session_id": "s1",
                "user_id": "u1",
                "first_event_ts": 1_000,
                "last_event_ts": 2_000,
                "event_count": 3,
                "pages": ["/checkout"],
                "has_add_to_cart": True,
                "has_checkout": True,
                "product_ids_viewed": ["sku-1"],
            },
            "checkout",
            True,
        ),
        (
            {
                "session_id": "s2",
                "user_id": "u2",
                "first_event_ts": 1_000,
                "last_event_ts": 2_000,
                "event_count": 2,
                "pages": ["/cart"],
                "has_add_to_cart": True,
                "has_checkout": False,
                "product_ids_viewed": [],
            },
            "add_to_cart",
            False,
        ),
        (
            {
                "session_id": "s3",
                "user_id": "u3",
                "first_event_ts": 1_000,
                "last_event_ts": 2_000,
                "event_count": 1,
                "pages": ["/products/sku-1"],
                "has_add_to_cart": False,
                "has_checkout": False,
                "product_ids_viewed": ["sku-1"],
            },
            "product_view",
            False,
        ),
        (
            {
                "session_id": "s4",
                "user_id": "u4",
                "first_event_ts": 1_000,
                "last_event_ts": 2_000,
                "event_count": 2,
                "pages": ["/landing", "/pricing"],
                "has_add_to_cart": False,
                "has_checkout": False,
                "product_ids_viewed": [],
            },
            "browse",
            False,
        ),
    ],
)
def test_on_timer_sets_expected_funnel_stage(
    opened_window, session, expected_stage, expected_conversion
):
    _, window, _ = opened_window
    window.session_state.update(json.dumps(session))

    emitted = [json.loads(item) for item in window.on_timer(999, object())]

    assert emitted[0]["funnel_stage"] == expected_stage
    assert emitted[0]["is_conversion"] is expected_conversion


def test_build_pipeline_uses_defaults_and_wires_stream(session_aggregator, monkeypatch):
    env = _FakeExecutionEnvironment()
    session_aggregator.StreamExecutionEnvironment.current_env = env
    monkeypatch.delenv("FLINK_PARALLELISM", raising=False)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    result = session_aggregator.build_pipeline()
    source, watermark_strategy, name = env.from_source_args

    assert result is env
    assert env.checkpointing == 30_000
    assert env.parallelism == 2
    assert source["bootstrap_servers"] == "localhost:9092"
    assert source["topics"] == "clicks.raw"
    assert source["group_id"] == "agentflow-session-aggregator"
    assert source["starting_offsets"] == "earliest"
    assert name == "clicks-source"
    assert watermark_strategy.out_of_orderness == timedelta(seconds=10)
    assert isinstance(
        watermark_strategy.timestamp_assigner,
        session_aggregator.ClickTimestampAssigner,
    )
    assert env.stream.output_type == session_aggregator.Types.STRING()
    assert isinstance(env.stream.process_function, session_aggregator.SessionWindowFunction)
    assert env.stream.key_by_fn(json.dumps({"session_id": "session-1"})) == "session-1"
    assert env.stream.key_by_fn(json.dumps({})) == "unknown"
    assert env.stream.sink["bootstrap_servers"] == "localhost:9092"
    assert env.stream.sink["record_serializer"]["topic"] == "sessions.aggregated"


def test_build_pipeline_respects_environment_overrides(session_aggregator, monkeypatch):
    env = _FakeExecutionEnvironment()
    session_aggregator.StreamExecutionEnvironment.current_env = env
    monkeypatch.setenv("FLINK_PARALLELISM", "5")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")

    session_aggregator.build_pipeline()
    source, _, _ = env.from_source_args

    assert env.parallelism == 5
    assert source["bootstrap_servers"] == "kafka:29092"
    assert env.stream.sink["bootstrap_servers"] == "kafka:29092"
