"""Core Flink streaming job: validates, enriches, and routes events.

Pipeline: Kafka source → Schema validation → Enrichment → Deduplication → Iceberg sink
Invalid events are routed to a dead letter topic with error metadata.

This is the main entry point for the Flink cluster. Submit with:
    flink run -py stream_processor.py
"""

import json
import os
from datetime import timedelta

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
from pyflink.datastream.functions import MapFunction, ProcessFunction
from pyflink.datastream.output_tag import OutputTag

# Side output for invalid events
DEAD_LETTER_TAG = OutputTag("dead-letter", Types.STRING())


class EventTimestampAssigner(TimestampAssigner):
    """Extracts event_time from the JSON payload for watermark generation."""

    def extract_timestamp(self, value, record_timestamp):
        try:
            event = json.loads(value)
            from datetime import UTC, datetime

            from src.ingestion.cdc.normalizer import is_debezium_event, normalize_debezium_event

            if is_debezium_event(event):
                event = normalize_debezium_event(event)
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

    def process_element(self, value, ctx: ProcessFunction.Context):
        from datetime import UTC, datetime

        from src.processing.transformations.enrichment import (
            compute_payment_risk_score,
            enrich_clickstream,
            enrich_order,
        )
        from src.quality.validators.schema_validator import validate_event
        from src.quality.validators.semantic_validator import validate_semantics

        # 1. Parse JSON
        try:
            event = json.loads(value)
        except json.JSONDecodeError as e:
            ctx.output(
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

        from src.ingestion.cdc.normalizer import is_debezium_event, normalize_debezium_event

        try:
            if is_debezium_event(event):
                event = normalize_debezium_event(event)
        except ValueError as e:
            ctx.output(
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
        is_cdc_event = event.get("source") in {"postgres_cdc", "mysql_cdc"} and "operation" in event

        # 2. Schema validation (Pydantic models)
        schema_result = validate_event(event)
        if not schema_result.is_valid:
            ctx.output(
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
                ctx.output(
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

        yield json.dumps(event)


class DeduplicateByEventId(MapFunction):
    """Deduplicates events using a Flink keyed state with TTL.

    Events with the same event_id within the TTL window are dropped.
    This handles at-least-once delivery from Kafka producers.
    """

    def open(self, runtime_context):
        from pyflink.datastream.state import StateTtlConfig, ValueStateDescriptor

        ttl_config = (
            StateTtlConfig.new_builder(timedelta(minutes=10))
            .set_update_type(StateTtlConfig.UpdateType.OnCreateAndWrite)
            .build()
        )

        state_desc = ValueStateDescriptor("seen", Types.BOOLEAN())
        state_desc.enable_time_to_live(ttl_config)
        self.seen_state = runtime_context.get_state(state_desc)

    def map(self, value):
        if self.seen_state.value():
            return None  # duplicate
        self.seen_state.update(True)
        return value


def build_pipeline():
    env = StreamExecutionEnvironment.get_execution_environment()

    # Checkpointing for exactly-once
    env.enable_checkpointing(30_000)  # 30s
    env.get_checkpoint_config().set_min_pause_between_checkpoints(10_000)
    env.set_parallelism(int(os.getenv("FLINK_PARALLELISM", "2")))

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    # Multi-topic Kafka source
    source = (
        KafkaSource.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_topics(
            "orders.raw",
            "payments.raw",
            "clicks.raw",
            "products.cdc",
            "cdc.postgres.public.orders_v2",
            "cdc.postgres.public.users_enriched",
            "cdc.mysql.agentflow_demo.products_current",
            "cdc.mysql.agentflow_demo.sessions_aggregated",
        )
        .set_group_id("agentflow-stream-processor")
        .set_starting_offsets(KafkaOffsetsInitializer.earliest())
        .set_value_only_deserializer(SimpleStringSchema())
        .build()
    )

    watermark_strategy = WatermarkStrategy.for_bounded_out_of_orderness(
        timedelta(seconds=5)
    ).with_timestamp_assigner(EventTimestampAssigner())

    # Main pipeline
    stream = env.from_source(source, watermark_strategy, "kafka-source")

    # Validate + enrich (with dead letter side output)
    validated = stream.process(ValidateAndEnrich(), output_type=Types.STRING())

    # Dead letter sink
    dead_letter_sink = (
        KafkaSink.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic("events.deadletter")
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
        .build()
    )

    validated.get_side_output(DEAD_LETTER_TAG).sink_to(dead_letter_sink)

    # Deduplicate by event_id
    deduped = (
        validated.key_by(lambda x: json.loads(x).get("event_id", ""))
        .map(DeduplicateByEventId(), output_type=Types.STRING())
        .filter(lambda x: x is not None)
    )

    # Validated events sink (for downstream consumers)
    validated_sink = (
        KafkaSink.builder()
        .set_bootstrap_servers(bootstrap_servers)
        .set_record_serializer(
            KafkaRecordSerializationSchema.builder()
            .set_topic("events.validated")
            .set_value_serialization_schema(SimpleStringSchema())
            .build()
        )
        .build()
    )

    deduped.sink_to(validated_sink)

    return env


if __name__ == "__main__":
    pipeline = build_pipeline()
    pipeline.execute("agentflow-stream-processor")
