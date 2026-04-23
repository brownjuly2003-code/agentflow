import importlib
import json
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest


class _FakeOutputTag:
    def __init__(self, name, type_info):
        self.name = name
        self.type_info = type_info


class _FakeValueState:
    def __init__(self):
        self.current = None

    def value(self):
        return self.current

    def update(self, value):
        self.current = value


class _FakeRuntimeContext:
    def __init__(self):
        self.descriptors = []
        self.states = {}

    def get_state(self, descriptor):
        self.descriptors.append(descriptor)
        return self.states.setdefault(descriptor.name, _FakeValueState())


class _FakeCheckpointConfig:
    def __init__(self):
        self.min_pause_between_checkpoints = None

    def set_min_pause_between_checkpoints(self, value):
        self.min_pause_between_checkpoints = value


class _FakeSourceStream:
    def __init__(self, env):
        self.env = env
        self.process_function = None
        self.output_type = None

    def process(self, function, output_type=None):
        self.process_function = function
        self.output_type = output_type
        self.env.validated_stream = _FakeValidatedStream(self.env)
        return self.env.validated_stream


class _FakeValidatedStream:
    def __init__(self, env):
        self.env = env
        self.side_output_tag = None
        self.key_by_fn = None

    def get_side_output(self, tag):
        self.side_output_tag = tag
        self.env.dead_letter_stream = _FakeSinkStream()
        return self.env.dead_letter_stream

    def key_by(self, func):
        self.key_by_fn = func
        self.env.keyed_stream = _FakeKeyedStream(self.env)
        return self.env.keyed_stream


class _FakeKeyedStream:
    def __init__(self, env):
        self.env = env
        self.map_function = None
        self.output_type = None

    def map(self, function, output_type=None):
        self.map_function = function
        self.output_type = output_type
        self.env.mapped_stream = _FakeMappedStream(self.env)
        return self.env.mapped_stream


class _FakeMappedStream:
    def __init__(self, env):
        self.env = env
        self.filter_fn = None

    def filter(self, func):
        self.filter_fn = func
        self.env.filtered_stream = _FakeSinkStream()
        return self.env.filtered_stream


class _FakeSinkStream:
    def __init__(self):
        self.sink = None

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
        self.checkpoint_config = _FakeCheckpointConfig()
        self.from_source_args = None
        self.source_stream = _FakeSourceStream(self)
        self.validated_stream = None
        self.dead_letter_stream = None
        self.keyed_stream = None
        self.mapped_stream = None
        self.filtered_stream = None

    def enable_checkpointing(self, interval):
        self.checkpointing = interval

    def get_checkpoint_config(self):
        return self.checkpoint_config

    def set_parallelism(self, value):
        self.parallelism = value

    def from_source(self, source, watermark_strategy, name):
        self.from_source_args = (source, watermark_strategy, name)
        return self.source_stream

    def execute(self, job_name):
        self.job_name = job_name


class _FakeProcessContext:
    def __init__(self):
        self.outputs = []

    def output(self, tag, value):
        self.outputs.append((tag, value))


class _ValidationResult:
    def __init__(self, is_valid=True, errors=None):
        self.is_valid = is_valid
        self.errors = errors or []


class _SemanticIssue:
    def __init__(self, rule, severity, field, message, with_to_dict=False):
        self.rule = rule
        self.severity = severity
        self.field = field
        self.message = message
        self._with_to_dict = with_to_dict

    def to_dict(self):
        if not self._with_to_dict:
            raise AttributeError("to_dict disabled")
        return {
            "rule": self.rule,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
        }


class _SemanticResult:
    def __init__(self, is_clean=True, issues=None):
        self.is_clean = is_clean
        self.issues = issues or []


def _install_processor_dependencies(
    monkeypatch,
    *,
    validate_event=None,
    validate_semantics=None,
    enrich_order=None,
    enrich_clickstream=None,
    compute_payment_risk_score=None,
):
    enrichment = types.ModuleType("src.processing.transformations.enrichment")
    enrichment.enrich_order = enrich_order or (lambda event: {**event, "enriched_by": "order"})
    enrichment.enrich_clickstream = enrich_clickstream or (
        lambda event: {**event, "enriched_by": "clickstream"}
    )
    enrichment.compute_payment_risk_score = compute_payment_risk_score or (
        lambda event: {**event, "enriched_by": "payment"}
    )

    schema_validator = types.ModuleType("src.quality.validators.schema_validator")
    schema_validator.validate_event = validate_event or (lambda event: _ValidationResult())

    semantic_validator = types.ModuleType("src.quality.validators.semantic_validator")
    semantic_validator.validate_semantics = validate_semantics or (lambda event: _SemanticResult())

    monkeypatch.setitem(
        sys.modules,
        "src.processing.transformations.enrichment",
        enrichment,
    )
    monkeypatch.setitem(
        sys.modules,
        "src.quality.validators.schema_validator",
        schema_validator,
    )
    monkeypatch.setitem(
        sys.modules,
        "src.quality.validators.semantic_validator",
        semantic_validator,
    )


@pytest.fixture
def stream_processor(monkeypatch):
    target = "src.processing.flink_jobs.stream_processor"
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
        def BOOLEAN():
            return "BOOLEAN"

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

        def set_topics(self, *values):
            self.values["topics"] = values
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

    class _MapFunction:
        pass

    class _ProcessFunction:
        class Context:
            pass

    functions.MapFunction = _MapFunction
    functions.ProcessFunction = _ProcessFunction

    output_tag = types.ModuleType("pyflink.datastream.output_tag")
    output_tag.OutputTag = _FakeOutputTag

    state = types.ModuleType("pyflink.datastream.state")

    class _StateTtlConfig:
        class UpdateType:
            OnCreateAndWrite = "OnCreateAndWrite"

        def __init__(self, ttl, update_type):
            self.ttl = ttl
            self.update_type = update_type

        @classmethod
        def new_builder(cls, ttl):
            return _StateTtlBuilder(ttl)

    class _StateTtlBuilder:
        def __init__(self, ttl):
            self.ttl = ttl
            self.update_type = None

        def set_update_type(self, update_type):
            self.update_type = update_type
            return self

        def build(self):
            return _StateTtlConfig(self.ttl, self.update_type)

    class _ValueStateDescriptor:
        def __init__(self, name, type_info):
            self.name = name
            self.type_info = type_info
            self.ttl_config = None

        def enable_time_to_live(self, ttl_config):
            self.ttl_config = ttl_config

    state.StateTtlConfig = _StateTtlConfig
    state.ValueStateDescriptor = _ValueStateDescriptor

    common.serialization = serialization
    common.watermark_strategy = watermark_strategy
    datastream.connectors = connectors
    connectors.kafka = kafka
    datastream.functions = functions
    datastream.output_tag = output_tag
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
    monkeypatch.setitem(sys.modules, "pyflink.datastream.output_tag", output_tag)
    monkeypatch.setitem(sys.modules, "pyflink.datastream.state", state)

    return importlib.import_module(target)


def test_extract_timestamp_uses_event_timestamp(stream_processor):
    assigner = stream_processor.EventTimestampAssigner()

    result = assigner.extract_timestamp(
        json.dumps({"timestamp": "2026-04-17T09:30:00+00:00"}),
        123,
    )

    assert result == int(datetime(2026, 4, 17, 9, 30, tzinfo=UTC).timestamp() * 1000)


def test_extract_timestamp_assumes_utc_for_naive_values(stream_processor):
    assigner = stream_processor.EventTimestampAssigner()

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
        (json.dumps({"timestamp": "not-a-timestamp"}), 333),
    ],
)
def test_extract_timestamp_falls_back_for_invalid_payload(
    stream_processor, payload, record_timestamp
):
    assigner = stream_processor.EventTimestampAssigner()

    result = assigner.extract_timestamp(payload, record_timestamp)

    assert result == record_timestamp


def test_process_element_routes_corrupt_json_to_dlq(stream_processor, monkeypatch):
    _install_processor_dependencies(monkeypatch)
    processor = stream_processor.ValidateAndEnrich()
    ctx = _FakeProcessContext()

    emitted = list(processor.process_element("{bad json", ctx))

    assert emitted == []
    assert len(ctx.outputs) == 1
    tag, payload = ctx.outputs[0]
    assert tag is stream_processor.DEAD_LETTER_TAG
    assert json.loads(payload)["stage"] == "parse"


def test_process_element_routes_schema_errors_to_dlq(stream_processor, monkeypatch):
    _install_processor_dependencies(
        monkeypatch,
        validate_event=lambda event: _ValidationResult(
            is_valid=False,
            errors=[{"type": "missing", "field": "event_id"}],
        ),
    )
    processor = stream_processor.ValidateAndEnrich()
    ctx = _FakeProcessContext()

    emitted = list(processor.process_element(json.dumps({"event_type": "order.created"}), ctx))

    assert emitted == []
    assert json.loads(ctx.outputs[0][1]) == {
        "event_id": "unknown",
        "error": [{"type": "missing", "field": "event_id"}],
        "stage": "schema_validation",
    }


def test_process_element_routes_semantic_errors_to_dlq(stream_processor, monkeypatch):
    issue = _SemanticIssue(
        rule="order_total_consistency",
        severity="error",
        field="total_amount",
        message="mismatch",
        with_to_dict=True,
    )
    _install_processor_dependencies(
        monkeypatch,
        validate_semantics=lambda event: _SemanticResult(is_clean=False, issues=[issue]),
    )
    processor = stream_processor.ValidateAndEnrich()
    ctx = _FakeProcessContext()
    value = json.dumps({"event_id": "evt-1", "event_type": "order.created"})

    emitted = list(processor.process_element(value, ctx))

    assert emitted == []
    assert json.loads(ctx.outputs[0][1]) == {
        "event_id": "evt-1",
        "error": [
            {
                "rule": "order_total_consistency",
                "severity": "error",
                "field": "total_amount",
                "message": "mismatch",
            }
        ],
        "stage": "semantic_validation",
    }


def test_process_element_ignores_semantic_warnings(stream_processor, monkeypatch):
    issue = _SemanticIssue(
        rule="payment_failure_reason_required",
        severity="warning",
        field="failure_reason",
        message="missing",
    )
    _install_processor_dependencies(
        monkeypatch,
        validate_semantics=lambda event: _SemanticResult(is_clean=False, issues=[issue]),
    )
    processor = stream_processor.ValidateAndEnrich()
    ctx = _FakeProcessContext()
    value = json.dumps(
        {
            "event_id": "evt-2",
            "event_type": "payment.failed",
            "timestamp": "2026-04-17T09:30:00+00:00",
        }
    )

    emitted = [json.loads(item) for item in processor.process_element(value, ctx)]

    assert ctx.outputs == []
    assert emitted[0]["enriched_by"] == "payment"


def test_process_element_enriches_order_and_sets_metadata(stream_processor, monkeypatch):
    _install_processor_dependencies(
        monkeypatch,
        enrich_order=lambda event: {**event, "enriched_by": "order"},
    )
    processor = stream_processor.ValidateAndEnrich()
    ctx = _FakeProcessContext()
    value = json.dumps(
        {
            "event_id": "evt-3",
            "event_type": "order.created",
            "timestamp": "2026-04-17T09:30:00+00:00",
            "user_id": "user-1",
            "order_id": "order-1",
        }
    )

    emitted = [json.loads(item) for item in processor.process_element(value, ctx)]
    event = emitted[0]
    processing_time = datetime.fromisoformat(event["_enriched"]["processing_time"])
    original_time = datetime.fromisoformat("2026-04-17T09:30:00+00:00")

    assert event["enriched_by"] == "order"
    assert event["_partition_key"] == "user-1"
    assert event["_enriched"]["processor_version"] == "1.0.0"
    assert event["_enriched"]["pipeline_latency_ms"] == int(
        (processing_time - original_time).total_seconds() * 1000
    )


def test_process_element_uses_clickstream_enrichment(stream_processor, monkeypatch):
    calls = []

    def _enrich_clickstream(event):
        calls.append(event["event_id"])
        return {**event, "enriched_by": "clickstream"}

    _install_processor_dependencies(monkeypatch, enrich_clickstream=_enrich_clickstream)
    processor = stream_processor.ValidateAndEnrich()
    value = json.dumps(
        {
            "event_id": "evt-4",
            "event_type": "page_view",
            "timestamp": "2026-04-17T09:30:00+00:00",
            "order_id": "order-4",
        }
    )

    emitted = [json.loads(item) for item in processor.process_element(value, _FakeProcessContext())]

    assert calls == ["evt-4"]
    assert emitted[0]["enriched_by"] == "clickstream"
    assert emitted[0]["_partition_key"] == "order-4"


def test_process_element_uses_payment_enrichment(stream_processor, monkeypatch):
    calls = []

    def _compute_payment_risk_score(event):
        calls.append(event["event_id"])
        return {**event, "enriched_by": "payment"}

    _install_processor_dependencies(
        monkeypatch,
        compute_payment_risk_score=_compute_payment_risk_score,
    )
    processor = stream_processor.ValidateAndEnrich()
    value = json.dumps(
        {
            "event_id": "evt-5",
            "event_type": "payment.captured",
            "timestamp": "2026-04-17T09:30:00+00:00",
        }
    )

    emitted = [json.loads(item) for item in processor.process_element(value, _FakeProcessContext())]

    assert calls == ["evt-5"]
    assert emitted[0]["enriched_by"] == "payment"
    assert emitted[0]["_partition_key"] == "evt-5"


def test_process_element_uses_negative_latency_for_invalid_timestamp(stream_processor, monkeypatch):
    _install_processor_dependencies(monkeypatch)
    processor = stream_processor.ValidateAndEnrich()
    value = json.dumps(
        {
            "event_id": "evt-6",
            "event_type": "order.created",
            "timestamp": "not-a-timestamp",
        }
    )

    emitted = [json.loads(item) for item in processor.process_element(value, _FakeProcessContext())]

    assert emitted[0]["_enriched"]["pipeline_latency_ms"] == -1


def test_open_initializes_ttl_state_for_deduplication(stream_processor):
    runtime_context = _FakeRuntimeContext()
    deduplicator = stream_processor.DeduplicateByEventId()

    deduplicator.open(runtime_context)

    assert [descriptor.name for descriptor in runtime_context.descriptors] == ["seen"]
    assert runtime_context.descriptors[0].type_info == stream_processor.Types.BOOLEAN()
    assert runtime_context.descriptors[0].ttl_config.ttl == timedelta(minutes=10)
    assert runtime_context.descriptors[0].ttl_config.update_type == "OnCreateAndWrite"


def test_map_returns_value_for_first_seen_event(stream_processor):
    runtime_context = _FakeRuntimeContext()
    deduplicator = stream_processor.DeduplicateByEventId()
    deduplicator.open(runtime_context)

    result = deduplicator.map("payload-1")

    assert result == "payload-1"
    assert deduplicator.seen_state.value() is True


def test_map_drops_duplicates_after_first_seen_event(stream_processor):
    runtime_context = _FakeRuntimeContext()
    deduplicator = stream_processor.DeduplicateByEventId()
    deduplicator.open(runtime_context)

    deduplicator.map("payload-1")
    result = deduplicator.map("payload-1")

    assert result is None


def test_build_pipeline_uses_defaults_and_wires_sinks(stream_processor, monkeypatch):
    env = _FakeExecutionEnvironment()
    stream_processor.StreamExecutionEnvironment.current_env = env
    monkeypatch.delenv("FLINK_PARALLELISM", raising=False)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    result = stream_processor.build_pipeline()
    source, watermark_strategy, name = env.from_source_args

    assert result is env
    assert env.checkpointing == 30_000
    assert env.checkpoint_config.min_pause_between_checkpoints == 10_000
    assert env.parallelism == 2
    assert source["bootstrap_servers"] == "localhost:9092"
    assert source["topics"] == (
        "orders.raw",
        "payments.raw",
        "clicks.raw",
        "products.cdc",
    )
    assert source["group_id"] == "agentflow-stream-processor"
    assert source["starting_offsets"] == "earliest"
    assert name == "kafka-source"
    assert watermark_strategy.out_of_orderness == timedelta(seconds=5)
    assert isinstance(
        watermark_strategy.timestamp_assigner,
        stream_processor.EventTimestampAssigner,
    )
    assert env.source_stream.output_type == stream_processor.Types.STRING()
    assert isinstance(env.source_stream.process_function, stream_processor.ValidateAndEnrich)
    assert env.validated_stream.side_output_tag is stream_processor.DEAD_LETTER_TAG
    assert env.validated_stream.key_by_fn(json.dumps({"event_id": "evt-7"})) == "evt-7"
    assert env.validated_stream.key_by_fn(json.dumps({})) == ""
    assert isinstance(env.keyed_stream.map_function, stream_processor.DeduplicateByEventId)
    assert env.keyed_stream.output_type == stream_processor.Types.STRING()
    assert env.mapped_stream.filter_fn(None) is False
    assert env.mapped_stream.filter_fn("value") is True
    assert env.dead_letter_stream.sink["bootstrap_servers"] == "localhost:9092"
    assert env.dead_letter_stream.sink["record_serializer"]["topic"] == "events.deadletter"
    assert env.filtered_stream.sink["bootstrap_servers"] == "localhost:9092"
    assert env.filtered_stream.sink["record_serializer"]["topic"] == "events.validated"


def test_build_pipeline_respects_environment_overrides(stream_processor, monkeypatch):
    env = _FakeExecutionEnvironment()
    stream_processor.StreamExecutionEnvironment.current_env = env
    monkeypatch.setenv("FLINK_PARALLELISM", "5")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")

    stream_processor.build_pipeline()
    source, _, _ = env.from_source_args

    assert env.parallelism == 5
    assert source["bootstrap_servers"] == "kafka:29092"
    assert env.dead_letter_stream.sink["bootstrap_servers"] == "kafka:29092"
    assert env.filtered_stream.sink["bootstrap_servers"] == "kafka:29092"
