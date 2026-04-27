"""Normalize raw Debezium records into the AgentFlow CDC contract."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from src.ingestion.tenant_router import TenantRouter

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


def is_debezium_event(event: dict[str, Any]) -> bool:
    return all(key in event for key in ("before", "after", "source", "op"))


def normalize_debezium_event(event: dict[str, Any], topic: str | None = None) -> dict[str, Any]:
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

    metadata = _source_metadata(source)
    # Resolution order: explicit `topic` arg, then `event["topic"]` if a Kafka
    # wrapper populated it, then `source.database`/`source.schema` (Postgres
    # WAL exposes the database name; useful when topic is not propagated),
    # then `source.name` (connector name — last resort, often non-tenant).
    # See Codex review P1: Debezium value-only deserializer drops topic, so
    # without an explicit topic argument all events fall to `default`.
    tenant_hint = (
        topic
        or event.get("topic")
        or _topic_from_source(source)
        or source.get("name")
    )
    tenant = _tenant_from_topic(tenant_hint)
    stable_key = {
        "entity_id": str(entity_id),
        "operation": operation,
        "position": metadata["position"],
        "source": source_name,
        "table": table,
    }

    return {
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


def _event_timestamp(event: dict[str, Any], source: dict[str, Any]) -> str:
    ts_ms = source.get("ts_ms") or event.get("ts_ms")
    if ts_ms is None:
        return datetime.now(UTC).isoformat()
    return datetime.fromtimestamp(int(ts_ms) / 1000, UTC).isoformat()


def _source_metadata(source: dict[str, Any]) -> dict[str, Any]:
    connector = source.get("connector")
    position = _source_position(source)
    return {
        "connector": connector,
        "database": source.get("db"),
        "schema": source.get("schema"),
        "table": source.get("table"),
        "snapshot": source.get("snapshot"),
        "position": position,
    }


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


def _tenant_from_topic(topic: object) -> str:
    if not isinstance(topic, str) or not topic:
        return "default"
    router = TenantRouter()
    for tenant in router.load().tenants:
        prefix = tenant.kafka_topic_prefix
        if topic == prefix or topic.startswith(f"{prefix}."):
            return tenant.id
    return "default"


def _topic_from_source(source: dict[str, Any]) -> str | None:
    """Reconstruct a Kafka topic prefix from Debezium source metadata.

    Postgres exposes `db` + `schema` + `table`; MySQL exposes `db` + `table`.
    Many connectors set `topic.prefix` to `cdc.<db>` so even without the live
    Kafka topic we can match TenantRouter prefixes when tenants split per db.
    """
    db = source.get("db")
    if not isinstance(db, str) or not db:
        return None
    return f"cdc.{db}"
