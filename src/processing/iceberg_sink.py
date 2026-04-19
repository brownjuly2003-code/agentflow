from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import yaml  # type: ignore[import-untyped]
from pyiceberg.catalog import load_catalog
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import DayTransform, HourTransform
from pyiceberg.types import (
    BooleanType,
    DoubleType,
    IntegerType,
    NestedField,
    StringType,
    TimestampType,
)

ORDERS_SCHEMA = Schema(
    NestedField(field_id=1, name="event_id", field_type=StringType(), required=True),
    NestedField(field_id=2, name="event_type", field_type=StringType(), required=True),
    NestedField(field_id=3, name="order_id", field_type=StringType(), required=True),
    NestedField(field_id=4, name="user_id", field_type=StringType(), required=True),
    NestedField(field_id=5, name="status", field_type=StringType(), required=True),
    NestedField(field_id=6, name="total_amount", field_type=DoubleType(), required=True),
    NestedField(field_id=7, name="currency", field_type=StringType(), required=True),
    NestedField(field_id=8, name="item_count", field_type=IntegerType(), required=True),
    NestedField(field_id=9, name="unique_products", field_type=IntegerType(), required=True),
    NestedField(field_id=10, name="order_size_bucket", field_type=StringType(), required=True),
    NestedField(field_id=11, name="created_at", field_type=TimestampType(), required=True),
    NestedField(field_id=12, name="payload_json", field_type=StringType(), required=True),
)

PAYMENTS_SCHEMA = Schema(
    NestedField(field_id=1, name="event_id", field_type=StringType(), required=True),
    NestedField(field_id=2, name="event_type", field_type=StringType(), required=True),
    NestedField(field_id=3, name="payment_id", field_type=StringType(), required=True),
    NestedField(field_id=4, name="order_id", field_type=StringType(), required=True),
    NestedField(field_id=5, name="user_id", field_type=StringType(), required=True),
    NestedField(field_id=6, name="amount", field_type=DoubleType(), required=True),
    NestedField(field_id=7, name="currency", field_type=StringType(), required=True),
    NestedField(field_id=8, name="method", field_type=StringType(), required=True),
    NestedField(field_id=9, name="status", field_type=StringType(), required=True),
    NestedField(field_id=10, name="risk_score", field_type=DoubleType(), required=False),
    NestedField(field_id=11, name="risk_level", field_type=StringType(), required=False),
    NestedField(field_id=12, name="created_at", field_type=TimestampType(), required=True),
    NestedField(field_id=13, name="payload_json", field_type=StringType(), required=True),
)

CLICKSTREAM_SCHEMA = Schema(
    NestedField(field_id=1, name="event_id", field_type=StringType(), required=True),
    NestedField(field_id=2, name="event_type", field_type=StringType(), required=True),
    NestedField(field_id=3, name="session_id", field_type=StringType(), required=True),
    NestedField(field_id=4, name="user_id", field_type=StringType(), required=False),
    NestedField(field_id=5, name="page_url", field_type=StringType(), required=True),
    NestedField(field_id=6, name="referrer", field_type=StringType(), required=False),
    NestedField(field_id=7, name="user_agent", field_type=StringType(), required=True),
    NestedField(field_id=8, name="viewport_width", field_type=IntegerType(), required=False),
    NestedField(field_id=9, name="product_id", field_type=StringType(), required=False),
    NestedField(field_id=10, name="is_mobile", field_type=BooleanType(), required=False),
    NestedField(field_id=11, name="page_category", field_type=StringType(), required=False),
    NestedField(field_id=12, name="is_product_page", field_type=BooleanType(), required=False),
    NestedField(field_id=13, name="created_at", field_type=TimestampType(), required=True),
    NestedField(field_id=14, name="payload_json", field_type=StringType(), required=True),
)

INVENTORY_SCHEMA = Schema(
    NestedField(field_id=1, name="event_id", field_type=StringType(), required=True),
    NestedField(field_id=2, name="event_type", field_type=StringType(), required=True),
    NestedField(field_id=3, name="product_id", field_type=StringType(), required=True),
    NestedField(field_id=4, name="name", field_type=StringType(), required=True),
    NestedField(field_id=5, name="category", field_type=StringType(), required=True),
    NestedField(field_id=6, name="price", field_type=DoubleType(), required=True),
    NestedField(field_id=7, name="currency", field_type=StringType(), required=True),
    NestedField(field_id=8, name="in_stock", field_type=BooleanType(), required=True),
    NestedField(field_id=9, name="stock_quantity", field_type=IntegerType(), required=True),
    NestedField(field_id=10, name="created_at", field_type=TimestampType(), required=True),
    NestedField(field_id=11, name="payload_json", field_type=StringType(), required=True),
)

DEAD_LETTER_SCHEMA = Schema(
    NestedField(field_id=1, name="event_id", field_type=StringType(), required=False),
    NestedField(field_id=2, name="event_type", field_type=StringType(), required=False),
    NestedField(field_id=3, name="reason", field_type=StringType(), required=True),
    NestedField(field_id=4, name="source_topic", field_type=StringType(), required=True),
    NestedField(field_id=5, name="received_at", field_type=TimestampType(), required=True),
    NestedField(field_id=6, name="payload_json", field_type=StringType(), required=True),
)


class IcebergSink:
    def __init__(self, config_path: str | Path = "config/iceberg.yaml"):
        self.config_path = Path(config_path)
        config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        self._config = config["iceberg"]
        self.namespace = self._config["namespace"]
        self.table_configs = {table["name"]: table for table in self._config["tables"]}
        catalog_type = self._config["catalog_type"]
        catalog_properties = {
            "type": catalog_type,
            "uri": self._resolve_catalog_uri(self._config["catalog_uri"]),
            "warehouse": self._resolve_warehouse(self._config["warehouse"]),
        }
        catalog_properties.update(self._config.get("catalog_properties", {}))
        self.catalog = load_catalog(
            self._config.get("catalog_name", "agentflow"),
            **catalog_properties,
        )
        self.catalog.create_namespace_if_not_exists(self.namespace)

    def create_tables_if_not_exist(self) -> None:
        for table_name in self.table_configs:
            identifier = self._identifier(table_name)
            if self.catalog.table_exists(identifier):
                continue
            self.catalog.create_table(
                identifier,
                schema=self._schema_for_table(table_name),
                partition_spec=self._partition_spec_for_table(table_name),
            )

    def write_batch(self, table_name: str, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        self.create_tables_if_not_exist()
        table = self.catalog.load_table(self._identifier(table_name))
        normalized_records = [
            self._normalize_record(table_name, record)
            for record in records
        ]
        arrow_table = pa.Table.from_pylist(
            normalized_records,
            schema=table.schema().as_arrow(),
        )
        table.append(arrow_table)
        return len(normalized_records)

    def row_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table_name in self.table_configs:
            identifier = self._identifier(table_name)
            if not self.catalog.table_exists(identifier):
                counts[table_name] = 0
                continue
            table = self.catalog.load_table(identifier)
            counts[table_name] = table.scan().count()
        return counts

    def _identifier(self, table_name: str) -> tuple[str, str]:
        return self.namespace, table_name

    def _resolve_catalog_uri(self, value: str) -> str:
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        raw_path = value[len(prefix):]
        catalog_path = Path(raw_path)
        if not catalog_path.is_absolute():
            catalog_path = (self.config_path.parent / catalog_path).resolve()
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        return f"{prefix}{catalog_path.as_posix()}"

    def _resolve_warehouse(self, value: str) -> str:
        if "://" in value or value.startswith("file:"):
            return value
        warehouse_path = Path(value)
        if not warehouse_path.is_absolute():
            warehouse_path = (self.config_path.parent / warehouse_path).resolve()
        warehouse_path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            return f"file:{warehouse_path.as_posix()}"
        return warehouse_path.as_posix()

    def _schema_for_table(self, table_name: str) -> Schema:
        schemas = {
            "orders": ORDERS_SCHEMA,
            "payments": PAYMENTS_SCHEMA,
            "clickstream": CLICKSTREAM_SCHEMA,
            "inventory": INVENTORY_SCHEMA,
            "dead_letter": DEAD_LETTER_SCHEMA,
        }
        return schemas[table_name]

    def _partition_spec_for_table(self, table_name: str) -> PartitionSpec:
        schema = self._schema_for_table(table_name)
        fields: list[PartitionField] = []
        for index, expression in enumerate(
            self.table_configs[table_name].get("partition_by", []),
            start=1,
        ):
            source_name: str
            transform: DayTransform | HourTransform
            if expression.startswith("days(") and expression.endswith(")"):
                source_name = expression[5:-1]
                transform = DayTransform()
                suffix = "day"
            elif expression.startswith("hours(") and expression.endswith(")"):
                source_name = expression[6:-1]
                transform = HourTransform()
                suffix = "hour"
            else:
                msg = f"Unsupported partition transform: {expression}"
                raise ValueError(msg)
            source_field = schema.find_field(source_name)
            fields.append(
                PartitionField(
                    source_id=source_field.field_id,
                    field_id=1000 + index,
                    transform=transform,
                    name=f"{source_name}_{suffix}",
                )
            )
        return PartitionSpec(*fields)

    def _normalize_record(self, table_name: str, record: dict[str, Any]) -> dict[str, Any]:
        if table_name == "orders":
            return self._normalize_order(record)
        if table_name == "payments":
            return self._normalize_payment(record)
        if table_name == "clickstream":
            return self._normalize_clickstream(record)
        if table_name == "inventory":
            return self._normalize_inventory(record)
        if table_name == "dead_letter":
            return self._normalize_dead_letter(record)
        msg = f"Unsupported table: {table_name}"
        raise ValueError(msg)

    def _normalize_order(self, record: dict[str, Any]) -> dict[str, Any]:
        derived = record.get("_derived", {})
        items = record.get("items", [])
        return {
            "event_id": str(record["event_id"]),
            "event_type": str(record["event_type"]),
            "order_id": str(record["order_id"]),
            "user_id": str(record["user_id"]),
            "status": str(record["status"]),
            "total_amount": float(record["total_amount"]),
            "currency": str(record.get("currency", "USD")),
            "item_count": int(
                derived.get(
                    "item_count",
                    sum(item.get("quantity", 0) for item in items),
                )
            ),
            "unique_products": int(
                derived.get(
                    "unique_products",
                    len({item.get("product_id") for item in items if item.get("product_id")}),
                )
            ),
            "order_size_bucket": str(derived.get("order_size_bucket", "unknown")),
            "created_at": self._coerce_timestamp(record.get("timestamp")),
            "payload_json": self._dump_payload(record),
        }

    def _normalize_payment(self, record: dict[str, Any]) -> dict[str, Any]:
        derived = record.get("_derived", {})
        return {
            "event_id": str(record["event_id"]),
            "event_type": str(record["event_type"]),
            "payment_id": str(record["payment_id"]),
            "order_id": str(record["order_id"]),
            "user_id": str(record["user_id"]),
            "amount": float(record["amount"]),
            "currency": str(record.get("currency", "USD")),
            "method": str(record["method"]),
            "status": str(record["status"]),
            "risk_score": (
                float(derived["risk_score"])
                if "risk_score" in derived
                else None
            ),
            "risk_level": (
                str(derived["risk_level"])
                if "risk_level" in derived
                else None
            ),
            "created_at": self._coerce_timestamp(record.get("timestamp")),
            "payload_json": self._dump_payload(record),
        }

    def _normalize_clickstream(self, record: dict[str, Any]) -> dict[str, Any]:
        derived = record.get("_derived", {})
        return {
            "event_id": str(record["event_id"]),
            "event_type": str(record["event_type"]),
            "session_id": str(record["session_id"]),
            "user_id": (
                str(record["user_id"])
                if record.get("user_id") is not None
                else None
            ),
            "page_url": str(record["page_url"]),
            "referrer": (
                str(record["referrer"])
                if record.get("referrer") is not None
                else None
            ),
            "user_agent": str(record["user_agent"]),
            "viewport_width": (
                int(record["viewport_width"])
                if record.get("viewport_width") is not None
                else None
            ),
            "product_id": (
                str(record["product_id"])
                if record.get("product_id") is not None
                else None
            ),
            "is_mobile": derived.get("is_mobile"),
            "page_category": derived.get("page_category"),
            "is_product_page": derived.get("is_product_page"),
            "created_at": self._coerce_timestamp(record.get("timestamp")),
            "payload_json": self._dump_payload(record),
        }

    def _normalize_inventory(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": str(record["event_id"]),
            "event_type": str(record["event_type"]),
            "product_id": str(record["product_id"]),
            "name": str(record["name"]),
            "category": str(record["category"]),
            "price": float(record["price"]),
            "currency": str(record.get("currency", "USD")),
            "in_stock": bool(record["in_stock"]),
            "stock_quantity": int(record["stock_quantity"]),
            "created_at": self._coerce_timestamp(record.get("timestamp")),
            "payload_json": self._dump_payload(record),
        }

    def _normalize_dead_letter(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": (
                str(record["event_id"])
                if record.get("event_id") is not None
                else None
            ),
            "event_type": (
                str(record["event_type"])
                if record.get("event_type") is not None
                else None
            ),
            "reason": str(record["reason"]),
            "source_topic": str(record.get("source_topic", "events.deadletter")),
            "received_at": self._coerce_timestamp(
                record.get("received_at", datetime.now(UTC))
            ),
            "payload_json": (
                str(record["payload_json"])
                if "payload_json" in record
                else self._dump_payload(record.get("payload", record))
            ),
        }

    def _coerce_timestamp(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            timestamp = value
        elif value is None:
            timestamp = datetime.now(UTC)
        else:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return timestamp
        return timestamp.astimezone(UTC).replace(tzinfo=None)

    def _dump_payload(self, payload: Any) -> str:
        return json.dumps(payload, default=str, sort_keys=True)
