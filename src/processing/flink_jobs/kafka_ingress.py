"""Kafka Table source that preserves record identity for the Python pipeline."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

DEFAULT_INPUT_TOPICS = (
    "orders.raw",
    "payments.raw",
    "clicks.raw",
    "products.cdc",
    "cdc.postgres.public.orders_v2",
    "cdc.postgres.public.users_enriched",
    "cdc.mysql.agentflow_demo.products_current",
    "cdc.mysql.agentflow_demo.sessions_aggregated",
)


def configured_input_topics() -> tuple[str, ...]:
    raw = os.getenv("AGENTFLOW_KAFKA_INPUT_TOPICS")
    if raw is None:
        return DEFAULT_INPUT_TOPICS
    topics = tuple(topic.strip() for topic in raw.split(",") if topic.strip())
    if not topics:
        raise ValueError("AGENTFLOW_KAFKA_INPUT_TOPICS must contain at least one topic")
    if len(topics) != len(set(topics)):
        raise ValueError("AGENTFLOW_KAFKA_INPUT_TOPICS contains duplicate topics")
    return topics


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_kafka_source_ddl(
    *,
    bootstrap_servers: str,
    topics: Sequence[str],
    group_id: str,
    startup_mode: str = "earliest-offset",
    security_properties: Mapping[str, str] | None = None,
) -> str:
    if not topics:
        raise ValueError("Kafka ingress requires at least one topic")
    if startup_mode not in {"earliest-offset", "group-offsets"}:
        raise ValueError(f"Unsupported Kafka startup mode: {startup_mode}")
    topic_list = ";".join(topics)
    options = [
        ("connector", "kafka"),
        ("topic", topic_list),
        ("properties.bootstrap.servers", bootstrap_servers),
        ("properties.group.id", group_id),
        ("scan.startup.mode", startup_mode),
        ("format", "raw"),
        ("raw.charset", "UTF-8"),
    ]
    options.extend(
        (f"properties.{key}", value) for key, value in sorted((security_properties or {}).items())
    )
    option_sql = ",\n    ".join(
        f"{_sql_literal(key)} = {_sql_literal(value)}" for key, value in options
    )
    return f"""
CREATE TEMPORARY TABLE agentflow_kafka_ingress (
    payload STRING,
    topic STRING METADATA FROM 'topic' VIRTUAL,
    partition_id INT METADATA FROM 'partition' VIRTUAL,
    kafka_offset BIGINT METADATA FROM 'offset' VIRTUAL,
    kafka_timestamp TIMESTAMP_LTZ(3) METADATA FROM 'timestamp' VIRTUAL
) WITH (
    {option_sql}
)
""".strip()


def row_to_envelope(row: Sequence[Any]) -> str:
    payload, topic, partition, offset, timestamp = row
    timestamp_value = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
    return json.dumps(
        {
            "_agentflow_kafka": {
                "version": 1,
                "topic": str(topic),
                "partition": int(partition),
                "offset": int(offset),
                "timestamp": timestamp_value,
            },
            "value": str(payload),
        },
        separators=(",", ":"),
    )


def build_kafka_ingress_stream(
    stream_environment: Any,
    *,
    bootstrap_servers: str,
    topics: Sequence[str],
    group_id: str,
    security_properties: Mapping[str, str] | None = None,
) -> Any:
    from pyflink.common import Types
    from pyflink.table import StreamTableEnvironment

    table_environment = StreamTableEnvironment.create(
        stream_execution_environment=stream_environment
    )
    table_environment.execute_sql(
        build_kafka_source_ddl(
            bootstrap_servers=bootstrap_servers,
            topics=topics,
            group_id=group_id,
            startup_mode=os.getenv("AGENTFLOW_KAFKA_STARTUP_MODE", "earliest-offset"),
            security_properties=security_properties,
        )
    )
    table = table_environment.from_path("agentflow_kafka_ingress")
    return table_environment.to_data_stream(table).map(
        row_to_envelope,
        output_type=Types.STRING(),
    )
