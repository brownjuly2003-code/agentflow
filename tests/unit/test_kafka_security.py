from __future__ import annotations

import pytest

from src.processing.kafka_security import (
    confluent_kafka_consumer_config,
    confluent_kafka_security_config,
    flink_kafka_security_properties,
)


def test_production_kafka_auth_fails_closed_when_disabled() -> None:
    with pytest.raises(RuntimeError, match="Kafka authentication"):
        confluent_kafka_security_config(
            {
                "AGENTFLOW_PROFILE": "production",
                "AGENTFLOW_KAFKA_AUTH_ENABLED": "false",
            }
        )


def test_sasl_tls_config_is_translated_for_both_clients() -> None:
    environment = {
        "AGENTFLOW_PROFILE": "production",
        "AGENTFLOW_KAFKA_AUTH_ENABLED": "true",
        "AGENTFLOW_KAFKA_SECURITY_PROTOCOL": "SASL_SSL",
        "AGENTFLOW_KAFKA_SASL_MECHANISM": "SCRAM-SHA-512",
        "AGENTFLOW_KAFKA_USERNAME": "agentflow",
        "AGENTFLOW_KAFKA_PASSWORD": 'secret"with\\chars',
        "AGENTFLOW_KAFKA_CA_PATH": "/etc/agentflow/kafka/ca.pem",
    }

    confluent = confluent_kafka_security_config(environment)
    flink = flink_kafka_security_properties(environment)

    assert confluent == {
        "security.protocol": "SASL_SSL",
        "sasl.mechanisms": "SCRAM-SHA-512",
        "sasl.username": "agentflow",
        "sasl.password": 'secret"with\\chars',
        "ssl.ca.location": "/etc/agentflow/kafka/ca.pem",
    }
    assert flink["security.protocol"] == "SASL_SSL"
    assert flink["sasl.mechanism"] == "SCRAM-SHA-512"
    assert 'username="agentflow"' in flink["sasl.jaas.config"]
    assert 'password="secret\\"with\\\\chars"' in flink["sasl.jaas.config"]
    assert flink["ssl.truststore.location"] == "/etc/agentflow/kafka/ca.pem"
    assert flink["ssl.truststore.type"] == "PEM"


def test_enabled_auth_requires_credentials() -> None:
    with pytest.raises(RuntimeError, match="AGENTFLOW_KAFKA_USERNAME"):
        flink_kafka_security_properties(
            {
                "AGENTFLOW_KAFKA_AUTH_ENABLED": "true",
                "AGENTFLOW_KAFKA_PASSWORD": "secret",
            }
        )


def test_consumer_config_combines_delivery_and_security_settings() -> None:
    result = confluent_kafka_consumer_config(
        bootstrap_servers="kafka:9093",
        group_id="agentflow-lake",
        offset_reset="earliest",
        environment={
            "AGENTFLOW_KAFKA_AUTH_ENABLED": "true",
            "AGENTFLOW_KAFKA_USERNAME": "agentflow",
            "AGENTFLOW_KAFKA_PASSWORD": "secret",
        },
    )

    assert result["bootstrap.servers"] == "kafka:9093"
    assert result["group.id"] == "agentflow-lake"
    assert result["enable.auto.commit"] is False
    assert result["auto.offset.reset"] == "earliest"
    assert result["security.protocol"] == "SASL_SSL"
