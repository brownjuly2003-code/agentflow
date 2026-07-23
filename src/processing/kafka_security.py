"""Fail-closed Kafka authentication settings for production consumers."""

from __future__ import annotations

import os
from collections.abc import Mapping

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}
_LOGIN_MODULES = {
    "PLAIN": "org.apache.kafka.common.security.plain.PlainLoginModule",
    "SCRAM-SHA-256": "org.apache.kafka.common.security.scram.ScramLoginModule",
    "SCRAM-SHA-512": "org.apache.kafka.common.security.scram.ScramLoginModule",
}


def _auth_enabled(environment: Mapping[str, str]) -> bool:
    raw = environment.get("AGENTFLOW_KAFKA_AUTH_ENABLED", "false").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise RuntimeError("AGENTFLOW_KAFKA_AUTH_ENABLED must be a boolean")


def _security_values(environment: Mapping[str, str]) -> tuple[str, str, str, str, str]:
    enabled = _auth_enabled(environment)
    production = environment.get("AGENTFLOW_PROFILE", "").strip().lower() == "production"
    if not enabled:
        if production:
            raise RuntimeError(
                "Kafka authentication must be enabled when AGENTFLOW_PROFILE=production"
            )
        return "", "", "", "", ""

    protocol = environment.get("AGENTFLOW_KAFKA_SECURITY_PROTOCOL", "SASL_SSL").strip().upper()
    mechanism = environment.get("AGENTFLOW_KAFKA_SASL_MECHANISM", "SCRAM-SHA-512").strip().upper()
    username = environment.get("AGENTFLOW_KAFKA_USERNAME", "")
    password = environment.get("AGENTFLOW_KAFKA_PASSWORD", "")
    ca_path = environment.get("AGENTFLOW_KAFKA_CA_PATH", "").strip()

    if production and protocol != "SASL_SSL":
        raise RuntimeError("production Kafka authentication requires SASL_SSL")
    if protocol not in {"SASL_SSL", "SASL_PLAINTEXT"}:
        raise RuntimeError(f"unsupported Kafka security protocol: {protocol}")
    if mechanism not in _LOGIN_MODULES:
        raise RuntimeError(f"unsupported Kafka SASL mechanism: {mechanism}")
    if not username:
        raise RuntimeError("AGENTFLOW_KAFKA_USERNAME is required when Kafka auth is enabled")
    if not password:
        raise RuntimeError("AGENTFLOW_KAFKA_PASSWORD is required when Kafka auth is enabled")
    return protocol, mechanism, username, password, ca_path


def confluent_kafka_security_config(
    environment: Mapping[str, str] = os.environ,
) -> dict[str, str]:
    protocol, mechanism, username, password, ca_path = _security_values(environment)
    if not protocol:
        return {}
    result = {
        "security.protocol": protocol,
        "sasl.mechanisms": mechanism,
        "sasl.username": username,
        "sasl.password": password,
    }
    if ca_path:
        result["ssl.ca.location"] = ca_path
    return result


def confluent_kafka_consumer_config(
    *,
    bootstrap_servers: str,
    group_id: str,
    offset_reset: str,
    environment: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    config: dict[str, object] = {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "enable.auto.commit": False,
        "auto.offset.reset": offset_reset,
    }
    config.update(confluent_kafka_security_config(environment))
    return config


def flink_kafka_security_properties(
    environment: Mapping[str, str] = os.environ,
) -> dict[str, str]:
    protocol, mechanism, username, password, ca_path = _security_values(environment)
    if not protocol:
        return {}

    def _escape_jaas(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    login_module = _LOGIN_MODULES[mechanism]
    result = {
        "security.protocol": protocol,
        "sasl.mechanism": mechanism,
        "sasl.jaas.config": (
            f'{login_module} required username="{_escape_jaas(username)}" '
            f'password="{_escape_jaas(password)}";'
        ),
    }
    if ca_path:
        result["ssl.truststore.location"] = ca_path
        result["ssl.truststore.type"] = "PEM"
    return result
