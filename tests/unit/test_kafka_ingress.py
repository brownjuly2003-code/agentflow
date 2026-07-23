from __future__ import annotations

import json
from datetime import UTC, datetime

from src.processing.flink_jobs.kafka_ingress import (
    build_kafka_source_ddl,
    configured_input_topics,
    row_to_envelope,
)


def test_kafka_source_ddl_exposes_record_metadata() -> None:
    ddl = build_kafka_source_ddl(
        bootstrap_servers="kafka:9092",
        topics=("orders.raw", "cdc.postgres.public.orders_v2"),
        group_id="agentflow-stream-processor",
    )

    assert "topic STRING METADATA FROM 'topic' VIRTUAL" in ddl
    assert "partition_id INT METADATA FROM 'partition' VIRTUAL" in ddl
    assert "kafka_offset BIGINT METADATA FROM 'offset' VIRTUAL" in ddl
    assert "kafka_timestamp TIMESTAMP_LTZ(3) METADATA FROM 'timestamp' VIRTUAL" in ddl
    assert "'topic' = 'orders.raw;cdc.postgres.public.orders_v2'" in ddl
    assert "'format' = 'raw'" in ddl


def test_kafka_source_ddl_includes_security_properties() -> None:
    ddl = build_kafka_source_ddl(
        bootstrap_servers="kafka:9093",
        topics=("orders.raw",),
        group_id="agentflow-stream-processor",
        security_properties={
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "SCRAM-SHA-512",
            "sasl.jaas.config": 'Login required username="agent" password="secret";',
        },
    )

    assert "'properties.security.protocol' = 'SASL_SSL'" in ddl
    assert "'properties.sasl.mechanism' = 'SCRAM-SHA-512'" in ddl
    assert "'properties.sasl.jaas.config'" in ddl


def test_row_to_envelope_preserves_payload_and_kafka_identity() -> None:
    envelope = json.loads(
        row_to_envelope(
            (
                '{"before":null,"after":{"order_id":"ORD-1"}}',
                "cdc.postgres.public.orders_v2",
                2,
                47,
                datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
            )
        )
    )

    assert envelope == {
        "_agentflow_kafka": {
            "version": 1,
            "topic": "cdc.postgres.public.orders_v2",
            "partition": 2,
            "offset": 47,
            "timestamp": "2026-07-23T12:00:00+00:00",
        },
        "value": '{"before":null,"after":{"order_id":"ORD-1"}}',
    }


def test_input_topics_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv(
        "AGENTFLOW_KAFKA_INPUT_TOPICS",
        "orders.raw, acme.cdc.postgres.public.orders_v2",
    )

    assert configured_input_topics() == (
        "orders.raw",
        "acme.cdc.postgres.public.orders_v2",
    )
