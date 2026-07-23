"""Normalize raw Debezium records into the AgentFlow CDC contract."""

import fnmatch
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_SOURCE_BY_CONNECTOR: dict[str, str] = {
    "postgresql": "postgres_cdc",
    "mysql": "mysql_cdc",
}

_OPERATION_BY_DEBEZIUM_CODE: dict[str, str] = {
    "r": "snapshot",
    "c": "insert",
    "u": "update",
    "d": "delete",
}

_TABLE_MAPPINGS: dict[str, dict[str, Any]] = {
    "orders_v2": {
        "entity_type": "order",
        "key_column": "order_id",
        "event_types": {
            "snapshot": "order.snapshot",
            "insert": "order.created",
            "update": "order.updated",
            "delete": "order.deleted",
        },
    },
    "users_enriched": {
        "entity_type": "user",
        "key_column": "user_id",
        "event_types": {
            "snapshot": "user.snapshot",
            "insert": "user.updated",
            "update": "user.updated",
            "delete": "user.deleted",
        },
    },
    "products_current": {
        "entity_type": "product",
        "key_column": "product_id",
        "event_types": {
            "snapshot": "product.snapshot",
            "insert": "product.updated",
            "update": "product.updated",
            "delete": "product.deleted",
        },
    },
    "sessions_aggregated": {
        "entity_type": "session",
        "key_column": "session_id",
        "event_types": {
            "snapshot": "session.snapshot",
            "insert": "session.updated",
            "update": "session.updated",
            "delete": "session.deleted",
        },
    },
}

_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "processing" / "flink_jobs" / "cdc_sources.json"
)


class TenantResolutionError(ValueError):
    """Raised when a non-demo CDC record has no unambiguous tenant mapping."""


def is_debezium_event(event: dict[str, Any]) -> bool:
    return all(key in event for key in ("before", "after", "source", "op"))


def normalize_debezium_event(
    event: dict[str, Any],
    topic: str | None = None,
    *,
    kafka_metadata: dict[str, Any] | None = None,
    profile: str | None = None,
    registry_path: Path | str | None = None,
) -> dict[str, Any]:
    source = event.get("source") or {}
    if not isinstance(source, dict):
        raise ValueError("Debezium record source is not an object")

    connector = source.get("connector")
    table = source.get("table")
    op_code = event.get("op")
    source_name = _SOURCE_BY_CONNECTOR.get(connector) if isinstance(connector, str) else None
    table_mapping = _TABLE_MAPPINGS.get(table) if isinstance(table, str) else None
    operation = _OPERATION_BY_DEBEZIUM_CODE.get(op_code) if isinstance(op_code, str) else None

    if source_name is None:
        raise ValueError(f"Unsupported CDC connector: {connector}")
    if table_mapping is None:
        raise ValueError(f"Unmapped CDC source table: {table}")
    if operation is None:
        raise ValueError(f"Unsupported Debezium operation: {event.get('op')}")

    row = event.get("before") if operation == "delete" else event.get("after")
    if not isinstance(row, dict):
        raise ValueError("Debezium record does not contain a row image")

    key_column = table_mapping["key_column"]
    entity_id = row.get(key_column)
    if entity_id is None:
        raise ValueError(f"CDC row image missing key column: {key_column}")

    effective_kafka_metadata = _normalize_kafka_metadata(kafka_metadata, topic, event)
    effective_profile = profile or os.getenv("AGENTFLOW_PROFILE") or "demo"
    tenant = _resolve_tenant(
        connector=connector,
        kafka_metadata=effective_kafka_metadata,
        profile=effective_profile,
        registry_path=registry_path,
    )
    metadata = _source_metadata(source, effective_kafka_metadata)
    stable_key = {
        "entity_id": str(entity_id),
        "operation": operation,
        "position": metadata["position"],
        "source": source_name,
        "table": table,
        "tenant": tenant,
    }

    # Keep the row image available both as CDC evidence (`before`/`after`) and
    # as canonical top-level fields. The serving materializer consumes fields
    # such as order_id/user_id directly; without this projection a normalized
    # order passed CDC validation but failed later with a missing serving key.
    normalized = dict(row)
    normalized.update(
        {
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(stable_key, sort_keys=True))),
            "event_type": table_mapping["event_types"][operation],
            "operation": operation,
            "timestamp": _event_timestamp(event, source),
            "source": source_name,
            "tenant": tenant,
            "entity_type": table_mapping["entity_type"],
            "entity_id": str(entity_id),
            "before": event.get("before"),
            "after": event.get("after"),
            "source_metadata": metadata,
        }
    )
    return normalized


def _event_timestamp(event: dict[str, Any], source: dict[str, Any]) -> str:
    ts_ms = source.get("ts_ms") or event.get("ts_ms")
    if ts_ms is None:
        return datetime.now(UTC).isoformat()
    return datetime.fromtimestamp(int(ts_ms) / 1000, UTC).isoformat()


def _source_metadata(
    source: dict[str, Any],
    kafka_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    connector = source.get("connector")
    position = _source_position(source)
    metadata = {
        "connector": connector,
        "database": source.get("db"),
        "schema": source.get("schema"),
        "table": source.get("table"),
        "snapshot": source.get("snapshot"),
        "position": position,
    }
    if kafka_metadata is not None:
        metadata["kafka"] = kafka_metadata
    return metadata


def _source_position(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("connector") == "postgresql":
        return {
            "lsn": source.get("lsn"),
            "tx_id": source.get("txId"),
        }
    if source.get("connector") == "mysql":
        return {
            "file": source.get("file"),
            "pos": source.get("pos"),
            "row": source.get("row"),
        }
    return {}


def _normalize_kafka_metadata(
    kafka_metadata: dict[str, Any] | None,
    topic: str | None,
    event: dict[str, Any],
) -> dict[str, Any] | None:
    if kafka_metadata is not None:
        normalized = {
            "topic": kafka_metadata.get("topic"),
            "partition": kafka_metadata.get("partition"),
            "offset": kafka_metadata.get("offset"),
            "timestamp": kafka_metadata.get("timestamp"),
        }
        return normalized
    topic_hint = topic or event.get("topic")
    if isinstance(topic_hint, str) and topic_hint:
        return {
            "topic": topic_hint,
            "partition": None,
            "offset": None,
            "timestamp": None,
        }
    return None


def _load_registry(registry_path: Path | str | None) -> dict[str, Any]:
    configured = registry_path or os.getenv("AGENTFLOW_CDC_SOURCES_FILE")
    path = Path(configured) if configured is not None else _DEFAULT_REGISTRY_PATH
    try:
        registry: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TenantResolutionError(
            f"tenant_resolution_failed: cannot load CDC source registry {path}: {exc}"
        ) from exc
    if (
        not isinstance(registry, dict)
        or registry.get("version") != 1
        or not isinstance(registry.get("sources"), list)
    ):
        raise TenantResolutionError(
            f"tenant_resolution_failed: unsupported CDC source registry {path}"
        )
    return cast(dict[str, Any], registry)


def _resolve_tenant(
    *,
    connector: object,
    kafka_metadata: dict[str, Any] | None,
    profile: str,
    registry_path: Path | str | None,
) -> str:
    topic = kafka_metadata.get("topic") if kafka_metadata is not None else None
    matches: set[str] = set()
    if isinstance(connector, str) and isinstance(topic, str) and topic:
        for source in _load_registry(registry_path)["sources"]:
            if source.get("connector") != connector:
                continue
            pattern = source.get("topic_pattern")
            tenant_id = source.get("tenant_id")
            if (
                isinstance(pattern, str)
                and isinstance(tenant_id, str)
                and tenant_id
                and fnmatch.fnmatchcase(topic, pattern)
            ):
                matches.add(tenant_id)

    if len(matches) == 1:
        tenant = next(iter(matches))
        if profile != "demo" and tenant == "default":
            raise TenantResolutionError(
                "tenant_resolution_failed: production mapping cannot target tenant 'default'"
            )
        return tenant
    if len(matches) > 1:
        raise TenantResolutionError(
            f"tenant_resolution_failed: ambiguous mapping for connector={connector!r}, "
            f"topic={topic!r}"
        )
    if profile == "demo":
        return "default"
    raise TenantResolutionError(
        f"tenant_resolution_failed: no mapping for connector={connector!r}, topic={topic!r}"
    )
