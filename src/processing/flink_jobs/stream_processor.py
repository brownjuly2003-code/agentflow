"""Core Flink streaming job: validates, enriches, and routes events.

Pipeline: Kafka source → Schema validation → Enrichment → Deduplication → Kafka sinks
Invalid events are routed to a dead letter topic with error metadata.

This is the main entry point for the Flink cluster. Submit with:
    flink run -py stream_processor.py
"""

import json
import os
from collections.abc import Iterator
from typing import Any

from pyflink.common import Configuration, Types, WatermarkStrategy
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.time import Duration, Time
from pyflink.common.watermark_strategy import TimestampAssigner
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import (
    KafkaRecordSerializationSchema,
    KafkaSink,
)
from pyflink.datastream.functions import MapFunction, ProcessFunction
from pyflink.datastream.output_tag import OutputTag

from src.processing.flink_jobs.kafka_ingress import (
    build_kafka_ingress_stream,
    configured_input_topics,
)
from src.processing.kafka_security import flink_kafka_security_properties

# Side output for invalid events
DEAD_LETTER_TAG = OutputTag("dead-letter", Types.STRING())


def _event_tenant(event: dict) -> str:
    source_metadata = event.get("source_metadata", {})
    metadata_tenant = source_metadata.get("tenant") if isinstance(source_metadata, dict) else None
    tenant = event.get("tenant") or metadata_tenant
    return str(tenant) if tenant else "default"


def _decode_ingress_value(value: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("Kafka ingress payload is not a JSON object")
    metadata = decoded.get("_agentflow_kafka")
    if metadata is None:
        return decoded, None
    if not isinstance(metadata, dict) or metadata.get("version") != 1:
        raise ValueError("Kafka ingress envelope has an unsupported metadata version")
    payload = decoded.get("value")
    if not isinstance(payload, str):
        raise ValueError("Kafka ingress envelope value is not a string")
    event = json.loads(payload)
    if not isinstance(event, dict):
        raise ValueError("Kafka ingress envelope value is not a JSON object")
    return event, metadata


class EventTimestampAssigner(TimestampAssigner):
    """Extracts event_time from the JSON payload for watermark generation."""

    def extract_timestamp(self, value: str, record_timestamp: int) -> int:
        try:
            event, kafka_metadata = _decode_ingress_value(value)
            from datetime import UTC, datetime

            from src.ingestion.cdc.normalizer import is_debezium_event, normalize_debezium_event

            if is_debezium_event(event):
                event = normalize_debezium_event(event, kafka_metadata=kafka_metadata)
            ts = datetime.fromisoformat(event["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            return int(ts.timestamp() * 1000)
        except (json.JSONDecodeError, KeyError, ValueError):
            return record_timestamp


class ValidateAndEnrich(ProcessFunction):
    """Validates, enriches, and routes events using the shared quality layer.

    Pipeline per event:
    1. Parse JSON
    2. Schema validation via quality.validators.schema_validator
    3. Semantic validation via quality.validators.semantic_validator
    4. Domain enrichment via processing.transformations.enrichment
    5. Processing metadata (latency, version)

    Invalid events (schema or semantic errors) → dead letter topic.
    """

    def process_element(
        self,
        value: str,
        ctx: ProcessFunction.Context,  # noqa: ARG002 - required by the ProcessFunction interface
    ) -> Iterator[tuple[str | OutputTag, str]]:
        # PyFlink routes side outputs by *yielding* ``(OutputTag, value)`` — the
        # Java ``ctx.output(tag, value)`` API does not exist on pyflink's
        # ProcessFunction context (``InternalProcessFunctionContext`` has no
        # ``.output``), so emitting via ctx raised AttributeError and broke the
        # dead-letter path. The main output yields ``(event_id, payload)``; the
        # framework tells them apart by the first element's type (str vs
        # OutputTag), so the tuple main output is unambiguous. (R4 follow-up)
        from datetime import UTC, datetime

        from src.processing.transformations.enrichment import (
            compute_payment_risk_score,
            enrich_clickstream,
            enrich_order,
        )
        from src.quality.validators.schema_validator import validate_event
        from src.quality.validators.semantic_validator import validate_semantics

        # 1. Parse the Kafka metadata envelope and its JSON value.
        try:
            event, kafka_metadata = _decode_ingress_value(value)
        except (json.JSONDecodeError, ValueError) as e:
            yield (
                DEAD_LETTER_TAG,
                json.dumps(
                    {
                        "raw": value[:1000],
                        "error": f"JSON parse error: {e}",
                        "stage": "parse",
                    }
                ),
            )
            return

        from src.ingestion.cdc.normalizer import (
            TenantResolutionError,
            is_debezium_event,
            normalize_debezium_event,
        )

        try:
            if is_debezium_event(event):
                event = normalize_debezium_event(event, kafka_metadata=kafka_metadata)
        except TenantResolutionError as e:
            yield (
                DEAD_LETTER_TAG,
                json.dumps(
                    {
                        "raw": value[:1000],
                        "error": str(e),
                        "reason": "tenant_resolution_failed",
                        "stage": "cdc_normalization",
                    }
                ),
            )
            return
        except ValueError as e:
            yield (
                DEAD_LETTER_TAG,
                json.dumps(
                    {
                        "raw": value[:1000],
                        "error": str(e),
                        "stage": "cdc_normalization",
                    }
                ),
            )
            return

        event_id = event.get("event_id", "unknown")
        event_type = event.get("event_type", "unknown")
        event["tenant"] = _event_tenant(event)
        is_cdc_event = event.get("source") in {"postgres_cdc", "mysql_cdc"} and "operation" in event

        # 2. Schema validation (Pydantic models)
        schema_result = validate_event(event)
        if not schema_result.is_valid:
            yield (
                DEAD_LETTER_TAG,
                json.dumps(
                    {
                        "event_id": event_id,
                        "error": schema_result.errors,
                        "stage": "schema_validation",
                    }
                ),
            )
            return

        # 3. Semantic validation (business rules)
        semantic_result = validate_semantics(event)
        if not semantic_result.is_clean:
            error_issues = [
                i.to_dict()
                if hasattr(i, "to_dict")
                else {
                    "rule": i.rule,
                    "severity": i.severity,
                    "field": i.field,
                    "message": i.message,
                }
                for i in semantic_result.issues
                if i.severity == "error"
            ]
            if error_issues:
                yield (
                    DEAD_LETTER_TAG,
                    json.dumps(
                        {
                            "event_id": event_id,
                            "error": error_issues,
                            "stage": "semantic_validation",
                        }
                    ),
                )
                return

        # 4. Domain enrichment by event type
        if is_cdc_event:
            pass
        elif event_type.startswith("order."):
            event = enrich_order(event)
        elif event_type in ("click", "page_view", "add_to_cart"):
            event = enrich_clickstream(event)
        elif event_type.startswith("payment."):
            event = compute_payment_risk_score(event)

        # 5. Processing metadata
        now = datetime.now(UTC)
        try:
            event_ts = datetime.fromisoformat(event["timestamp"])
            if event_ts.tzinfo is None:
                event_ts = event_ts.replace(tzinfo=UTC)
            latency_ms = int((now - event_ts).total_seconds() * 1000)
        except (ValueError, TypeError):
            latency_ms = -1

        event["_enriched"] = {
            "processing_time": now.isoformat(),
            "pipeline_latency_ms": latency_ms,
            "processor_version": "1.0.0",
        }

        event["_partition_key"] = (
            event.get("user_id")
            or event.get("order_id")
            or event.get("entity_id")
            or event["event_id"]
        )

        # Tenant scope is part of event identity throughout the materialization
        # path. Encode the pair unambiguously so two tenants may reuse an
        # event_id without sharing keyed dedup state, while still avoiding a
        # second full-payload parse downstream (audit M-C3).
        dedup_identity = json.dumps(
            [event["tenant"], str(event.get("event_id", ""))],
            separators=(",", ":"),
        )
        yield dedup_identity, json.dumps(event)


class DeduplicateByEventId(MapFunction):
    """Deduplicates events using a Flink keyed state with TTL.

    Receives ``(tenant/event_id identity, payload)`` pairs keyed by that
    identity; pairs already seen within the TTL window are dropped. This
    handles at-least-once delivery without suppressing another tenant's event.
    """

    def open(self, runtime_context: Any) -> None:
        from pyflink.datastream.state import StateTtlConfig, ValueStateDescriptor

        ttl_config = (
            StateTtlConfig.new_builder(Time.minutes(10))
            .set_update_type(StateTtlConfig.UpdateType.OnCreateAndWrite)
            .build()
        )

        state_desc = ValueStateDescriptor("seen", Types.BOOLEAN())
        state_desc.enable_time_to_live(ttl_config)
        self.seen_state = runtime_context.get_state(state_desc)

    def map(self, value: tuple[str, str]) -> str | None:
        if self.seen_state.value():
            return None  # duplicate
        self.seen_state.update(True)
        return value[1]


def build_pipeline() -> StreamExecutionEnvironment:
    env = StreamExecutionEnvironment.get_execution_environment()

    # Checkpointing gives at-least-once source replay on recovery. It is NOT
    # Kafka-transactional exactly-once (the events.validated sink is built with no
    # DeliveryGuarantee); the effective exactly-once seen at the serving layer is
    # completed downstream by the bridge's idempotent, event_id-keyed apply — see
    # src/processing/bridge_consumer.py.
    checkpoint_interval_ms = int(os.getenv("FLINK_CHECKPOINT_INTERVAL_MS", "30000"))
    env.enable_checkpointing(checkpoint_interval_ms)
    env.get_checkpoint_config().set_min_pause_between_checkpoints(10_000)
    env.set_parallelism(int(os.getenv("FLINK_PARALLELISM", "2")))

    # Bounded restart budget: with the default infinite fixed-delay strategy a
    # job whose environment is persistently broken (e.g. checkpoint storage
    # full) restarts forever, re-emitting from the last checkpoint on every
    # attempt and flooding downstream with duplicates. Exceeding the failure
    # rate parks the job in FAILED, where alerting and the operator take over.
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
    input_topics = configured_input_topics()
    kafka_security = flink_kafka_security_properties()

    watermark_strategy = WatermarkStrategy.for_bounded_out_of_orderness(
        Duration.of_seconds(5)
    ).with_timestamp_assigner(EventTimestampAssigner())

    # The Table connector exposes topic/partition/offset/timestamp metadata;
    # the DataStream KafkaSource Python wrapper exposes only value bytes.
    stream = build_kafka_ingress_stream(
        env,
        bootstrap_servers=bootstrap_servers,
        topics=input_topics,
        group_id=os.getenv("AGENTFLOW_FLINK_GROUP_ID", "agentflow-stream-processor"),
        security_properties=kafka_security,
    ).assign_timestamps_and_watermarks(watermark_strategy)

    # Validate + enrich (with dead letter side output); emits
    # (tenant/event_id identity, payload) pairs so the dedup key is read from
    # the tuple instead of a second full-JSON parse (audit M-C3).
    validated = stream.process(
        ValidateAndEnrich(),
        output_type=Types.TUPLE([Types.STRING(), Types.STRING()]),
    )

    # Dead letter sink
    dead_letter_builder = KafkaSink.builder().set_bootstrap_servers(bootstrap_servers)
    for key, value in kafka_security.items():
        dead_letter_builder.set_property(key, value)
    dead_letter_sink = dead_letter_builder.set_record_serializer(
        KafkaRecordSerializationSchema.builder()
        .set_topic("events.deadletter")
        .set_value_serialization_schema(SimpleStringSchema())
        .build()
    ).build()

    validated.get_side_output(DEAD_LETTER_TAG).sink_to(dead_letter_sink)

    # Deduplicate by tenant-scoped event identity.
    deduped = (
        validated.key_by(lambda pair: pair[0])
        .map(DeduplicateByEventId(), output_type=Types.STRING())
        .filter(lambda x: x is not None)
    )

    # Validated events sink (for downstream consumers)
    validated_builder = KafkaSink.builder().set_bootstrap_servers(bootstrap_servers)
    for key, value in kafka_security.items():
        validated_builder.set_property(key, value)
    validated_sink = validated_builder.set_record_serializer(
        KafkaRecordSerializationSchema.builder()
        .set_topic("events.validated")
        .set_value_serialization_schema(SimpleStringSchema())
        .build()
    ).build()

    deduped.sink_to(validated_sink)

    return env


if __name__ == "__main__":
    pipeline = build_pipeline()
    pipeline.execute("agentflow-stream-processor")
