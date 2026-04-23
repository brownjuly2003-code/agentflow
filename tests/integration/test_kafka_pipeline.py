"""Integration tests for the Kafka-backed pipeline path."""

import json
import time
import uuid
from datetime import UTC, datetime

import duckdb
import pytest
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from fastapi.testclient import TestClient

from src.processing.local_pipeline import _ensure_tables, _process_event
from src.serving.api.main import app

RAW_TOPIC = "events.raw"
VALIDATED_TOPIC = "events.validated"
DEADLETTER_TOPIC = "events.deadletter"


def _build_valid_order_event(order_id: str | None = None) -> dict:
    order_suffix = order_id or f"ORD-{datetime.now(UTC).strftime('%Y%m%d')}-9001"
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "order.created",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "integration-test",
        "order_id": order_suffix,
        "user_id": "USR-90001",
        "status": "confirmed",
        "items": [
            {"product_id": "PROD-001", "quantity": 2, "unit_price": "79.99"},
            {"product_id": "PROD-003", "quantity": 1, "unit_price": "49.99"},
        ],
        "total_amount": "209.97",
        "currency": "USD",
    }


def _build_invalid_order_event() -> dict:
    event = _build_valid_order_event(order_id=f"ORD-{datetime.now(UTC).strftime('%Y%m%d')}-9002")
    event["total_amount"] = "1.00"
    return event


def _ensure_topics(bootstrap_servers: str) -> None:
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    futures = admin.create_topics(
        [
            NewTopic(RAW_TOPIC, num_partitions=1, replication_factor=1),
            NewTopic(VALIDATED_TOPIC, num_partitions=1, replication_factor=1),
            NewTopic(DEADLETTER_TOPIC, num_partitions=1, replication_factor=1),
        ]
    )
    for future in futures.values():
        try:
            future.result(10)
        except Exception as exc:  # pragma: no cover - broker decides exact error class
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise


def _publish_event(bootstrap_servers: str, topic: str, event: dict) -> None:
    producer = Producer({"bootstrap.servers": bootstrap_servers})
    producer.produce(topic, key=event["event_id"], value=json.dumps(event).encode("utf-8"))
    producer.flush(10)


def _pump_one_event(bootstrap_servers: str, db_path: str, event_id: str) -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": f"kafka-pipeline-{uuid.uuid4()}",
            "auto.offset.reset": "earliest",
        }
    )
    producer = Producer({"bootstrap.servers": bootstrap_servers})
    consumer.subscribe([RAW_TOPIC])

    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                raise AssertionError(str(message.error()))

            event = json.loads(message.value().decode("utf-8"))
            if event.get("event_id") != event_id:
                continue
            conn = duckdb.connect(db_path)
            try:
                _ensure_tables(conn)
                is_valid, _ = _process_event(conn, event)
            finally:
                conn.close()

            output_topic = VALIDATED_TOPIC if is_valid else DEADLETTER_TOPIC
            producer.produce(
                output_topic,
                key=event["event_id"],
                value=json.dumps(event).encode("utf-8"),
            )
            producer.flush(10)
            return
    finally:
        consumer.close()

    raise AssertionError("Timed out waiting for an event on events.raw")


def _consume_event(bootstrap_servers: str, topic: str, event_id: str) -> dict:
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": f"kafka-assert-{uuid.uuid4()}",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic])

    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                raise AssertionError(str(message.error()))

            payload = json.loads(message.value().decode("utf-8"))
            if payload.get("event_id") == event_id:
                return payload
    finally:
        consumer.close()

    raise AssertionError(f"Timed out waiting for event {event_id} on {topic}")


@pytest.mark.integration
@pytest.mark.requires_docker
class TestKafkaPipeline:
    def test_valid_order_event_reaches_validated_topic(self, kafka_bootstrap, tmp_path):
        db_path = str(tmp_path / "kafka-valid.duckdb")
        event = _build_valid_order_event()

        _ensure_topics(kafka_bootstrap)
        _publish_event(kafka_bootstrap, RAW_TOPIC, event)
        _pump_one_event(kafka_bootstrap, db_path, event["event_id"])

        received = _consume_event(kafka_bootstrap, VALIDATED_TOPIC, event["event_id"])

        assert received["event_id"] == event["event_id"]

        conn = duckdb.connect(db_path)
        try:
            row = conn.execute(
                "SELECT topic FROM pipeline_events WHERE event_id = ?",
                [event["event_id"]],
            ).fetchone()
        finally:
            conn.close()

        assert row == (VALIDATED_TOPIC,)

    def test_invalid_event_goes_to_deadletter(self, kafka_bootstrap, tmp_path):
        db_path = str(tmp_path / "kafka-deadletter.duckdb")
        event = _build_invalid_order_event()

        _ensure_topics(kafka_bootstrap)
        _publish_event(kafka_bootstrap, RAW_TOPIC, event)
        _pump_one_event(kafka_bootstrap, db_path, event["event_id"])

        received = _consume_event(kafka_bootstrap, DEADLETTER_TOPIC, event["event_id"])

        assert received["event_id"] == event["event_id"]

        conn = duckdb.connect(db_path)
        try:
            row = conn.execute(
                "SELECT topic FROM pipeline_events WHERE event_id = ?",
                [event["event_id"]],
            ).fetchone()
        finally:
            conn.close()

        assert row == (DEADLETTER_TOPIC,)

    def test_api_serves_data_after_kafka_ingestion(self, kafka_bootstrap, tmp_path, monkeypatch):
        db_path = str(tmp_path / "kafka-api.duckdb")
        event = _build_valid_order_event(order_id="ORD-20260410-9003")

        _ensure_topics(kafka_bootstrap)
        _publish_event(kafka_bootstrap, RAW_TOPIC, event)
        _pump_one_event(kafka_bootstrap, db_path, event["event_id"])
        _consume_event(kafka_bootstrap, VALIDATED_TOPIC, event["event_id"])

        monkeypatch.setenv("DUCKDB_PATH", db_path)

        with TestClient(app) as client:
            response = client.get(f"/v1/entity/order/{event['order_id']}")

        assert response.status_code == 200
        data = response.json()
        assert data["entity_id"] == event["order_id"]
        assert data["data"]["user_id"] == event["user_id"]
        assert float(data["data"]["total_amount"]) == pytest.approx(209.97)
