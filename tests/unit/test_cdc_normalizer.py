import uuid
from datetime import UTC, datetime

import pytest

from src.ingestion.cdc.normalizer import is_debezium_event, normalize_debezium_event


def test_normalizes_postgres_insert_to_canonical_cdc_event():
    raw = {
        "before": None,
        "after": {
            "order_id": "ORD-CDC-1",
            "user_id": "USR-1",
            "status": "confirmed",
            "total_amount": "EJo=",
            "currency": "USD",
        },
        "source": {
            "connector": "postgresql",
            "name": "cdc.postgres",
            "db": "agentflow_demo",
            "schema": "public",
            "table": "orders_v2",
            "lsn": 26721944,
            "txId": 753,
            "snapshot": "false",
            "ts_ms": 1777245326123,
        },
        "op": "c",
        "ts_ms": 1777245326609,
    }

    event = normalize_debezium_event(raw)

    assert uuid.UUID(event["event_id"])
    assert event == {
        **event,
        "event_type": "order.created",
        "operation": "insert",
        "timestamp": datetime.fromtimestamp(1777245326123 / 1000, UTC).isoformat(),
        "source": "postgres_cdc",
        "entity_type": "order",
        "entity_id": "ORD-CDC-1",
        "before": None,
        "after": raw["after"],
        "source_metadata": {
            "connector": "postgresql",
            "database": "agentflow_demo",
            "schema": "public",
            "table": "orders_v2",
            "snapshot": "false",
            "position": {"lsn": 26721944, "tx_id": 753},
        },
    }


def test_normalizes_mysql_snapshot_to_canonical_cdc_event():
    raw = {
        "before": None,
        "after": {
            "product_id": "PROD-CDC-1",
            "name": "CDC Widget",
            "category": "test",
            "price": "A+c=",
            "in_stock": 1,
            "stock_quantity": 10,
        },
        "source": {
            "connector": "mysql",
            "name": "cdc.mysql",
            "db": "agentflow_demo",
            "table": "products_current",
            "file": "mysql-bin.000003",
            "pos": 158,
            "row": 0,
            "snapshot": "first",
            "ts_ms": 1777244957000,
        },
        "op": "r",
        "ts_ms": 1777244957271,
    }

    event = normalize_debezium_event(raw)

    assert event["event_type"] == "product.snapshot"
    assert event["operation"] == "snapshot"
    assert event["source"] == "mysql_cdc"
    assert event["entity_type"] == "product"
    assert event["entity_id"] == "PROD-CDC-1"
    assert event["source_metadata"]["position"] == {
        "file": "mysql-bin.000003",
        "pos": 158,
        "row": 0,
    }


def test_normalizes_delete_from_before_image():
    raw = {
        "before": {"order_id": "ORD-CDC-2", "status": "cancelled"},
        "after": None,
        "source": {
            "connector": "postgresql",
            "db": "agentflow_demo",
            "schema": "public",
            "table": "orders_v2",
            "lsn": 26730000,
            "txId": 754,
            "ts_ms": 1777245400000,
        },
        "op": "d",
    }

    event = normalize_debezium_event(raw)

    assert event["event_type"] == "order.deleted"
    assert event["operation"] == "delete"
    assert event["entity_id"] == "ORD-CDC-2"
    assert event["before"] == raw["before"]
    assert event["after"] is None


def test_event_id_is_stable_for_same_source_position():
    raw = {
        "before": None,
        "after": {"product_id": "PROD-CDC-2"},
        "source": {
            "connector": "mysql",
            "db": "agentflow_demo",
            "table": "products_current",
            "file": "mysql-bin.000003",
            "pos": 412,
            "row": 0,
            "ts_ms": 1777244972000,
        },
        "op": "c",
    }

    assert normalize_debezium_event(raw)["event_id"] == normalize_debezium_event(raw)["event_id"]


def test_rejects_unmapped_source_table():
    raw = {
        "before": None,
        "after": {"id": "1"},
        "source": {
            "connector": "mysql",
            "db": "agentflow_demo",
            "table": "unknown_table",
        },
        "op": "c",
    }

    with pytest.raises(ValueError, match="Unmapped CDC source table"):
        normalize_debezium_event(raw)


def test_detects_debezium_envelope():
    assert is_debezium_event({"before": None, "after": {}, "source": {}, "op": "c"})
    assert not is_debezium_event({"event_id": "evt-1", "event_type": "order.created"})
