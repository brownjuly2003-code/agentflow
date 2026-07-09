"""Live coverage for the serving bridge (S6): real Kafka, real ClickHouse.

This is the half of S6 that the unit suite cannot assert: that the bridge, given
an event on a real ``events.validated`` topic, lands it in the ClickHouse store
the API actually serves from — and that a replay of the same event does not
apply it twice.

Flink is deliberately absent. The bridge's contract starts at
``events.validated``; that Flink fills that topic is proven separately by
``scripts/benchmark_freshness_realpath.py`` and the ``flink-smoke`` gate. Here
we produce the event Flink would have produced, in the shape Flink produces it
(already enriched, carrying ``_enriched``/``_partition_key``).

Gated on ``CLICKHOUSE_LIVE_HOST`` (CI's test-integration job provides one) and
on Docker for the Kafka container.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime

import duckdb
import pytest
from confluent_kafka import Consumer, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from src.processing.bridge_consumer import VALIDATED_TOPIC, ServingBridge
from src.processing.clickhouse_sink import ClickHouseSink
from src.processing.local_pipeline import _ensure_tables
from src.processing.transformations.enrichment import enrich_order
from src.serving.backends.clickhouse_backend import ClickHouseBackend

LIVE_HOST = os.getenv("CLICKHOUSE_LIVE_HOST")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.skipif(
        not LIVE_HOST,
        reason="CLICKHOUSE_LIVE_HOST not configured (live ClickHouse required)",
    ),
]


@pytest.fixture(scope="module")
def backend() -> ClickHouseBackend:
    instance = ClickHouseBackend(
        host=LIVE_HOST or "localhost",
        port=int(os.getenv("CLICKHOUSE_LIVE_PORT", "8123")),
        user=os.getenv("CLICKHOUSE_LIVE_USER", "agentflow"),
        password=os.getenv("CLICKHOUSE_LIVE_PASSWORD", "agentflow"),
        database=os.getenv("CLICKHOUSE_LIVE_DATABASE", "agentflow"),
    )
    instance.ensure_schema()
    return instance


def _flink_shaped_order() -> dict:
    """The payload Flink writes to `events.validated` for an order.created.

    The ids must satisfy the canonical schema (`order_id` matches
    `^ORD-\\d{8}-\\d{4,}$`) — the bridge revalidates, and an id that only *looks*
    unique would be dead-lettered rather than applied. The 9-prefixed sequence
    keeps these clear of the demo seed's 4-digit ids.
    """
    suffix = uuid.uuid4().int % 100000
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "order.created",
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "integration-test",
        "order_id": f"ORD-{datetime.now(UTC):%Y%m%d}-9{suffix:05d}",
        "user_id": f"USR-9{suffix:05d}",
        "status": "confirmed",
        "items": [
            {"product_id": "PROD-001", "quantity": 2, "unit_price": "79.99"},
            {"product_id": "PROD-003", "quantity": 1, "unit_price": "49.99"},
        ],
        "total_amount": "209.97",
        "currency": "USD",
    }
    event = enrich_order(event)
    event["_enriched"] = {
        "processing_time": datetime.now(UTC).isoformat(),
        "pipeline_latency_ms": 12,
        "processor_version": "1.0.0",
    }
    event["_partition_key"] = event["user_id"]
    return event


def _ensure_topic(bootstrap_servers: str) -> None:
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    futures = admin.create_topics(
        [NewTopic(VALIDATED_TOPIC, num_partitions=1, replication_factor=1)]
    )
    for future in futures.values():
        try:
            future.result(10)
        except Exception as exc:  # pragma: no cover - broker decides the error class
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise


def _publish(bootstrap_servers: str, event: dict) -> None:
    producer = Producer({"bootstrap.servers": bootstrap_servers})
    producer.produce(
        VALIDATED_TOPIC, key=event["event_id"], value=json.dumps(event).encode("utf-8")
    )
    producer.flush(10)


def _consumer(bootstrap_servers: str, group_id: str) -> Consumer:
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([VALIDATED_TOPIC])
    return consumer


def _drain_until_applied(bridge: ServingBridge, event_id: str, timeout: float = 60.0) -> None:
    """Poll until the bridge reports *this* event applied.

    The topic is shared: `test_kafka_pipeline` publishes its own events to
    `events.validated` against the same session-scoped broker, and a consumer
    reading from `earliest` sees them too. So never assert on a batch's
    aggregate counters — only on whether **this** ``event_id`` was applied.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = bridge.run_once()
        if result is not None and event_id in result.applied_event_ids:
            return
    raise AssertionError(f"bridge never applied {event_id} within {timeout}s")


def _drain_expecting_no_apply(
    bridge: ServingBridge, event_id: str, backend: ClickHouseBackend, timeout: float = 60.0
) -> None:
    """Poll until the replayed ``event_id`` has been read past, asserting it is
    never re-applied. Other events on the shared topic may legitimately apply."""
    deadline = time.monotonic() + timeout
    saw_duplicate = False
    while time.monotonic() < deadline and not saw_duplicate:
        result = bridge.run_once()
        if result is None:
            continue
        assert event_id not in result.applied_event_ids, "a replayed event must never re-apply"
        if result.duplicates:
            saw_duplicate = True
    assert saw_duplicate, f"bridge never collapsed the replay of {event_id} within {timeout}s"
    assert _journal_rows(backend, event_id) == 1


def _journal_rows(backend: ClickHouseBackend, event_id: str) -> int:
    rows = backend.execute(
        "SELECT COUNT(*) AS c FROM pipeline_events "
        f"WHERE event_id = '{event_id}' AND topic = '{VALIDATED_TOPIC}'"
    )
    return int(rows[0]["c"])


def _order_rows(backend: ClickHouseBackend, order_id: str) -> list[dict]:
    return backend.execute(
        f"SELECT order_id, user_id, total_amount FROM orders_v2 WHERE order_id = '{order_id}'"
    )


class TestServingBridgeLive:
    def test_validated_event_reaches_the_clickhouse_serving_store(self, kafka_bootstrap, backend):
        event = _flink_shaped_order()
        _ensure_topic(kafka_bootstrap)
        _publish(kafka_bootstrap, event)

        lake = duckdb.connect(":memory:")
        _ensure_tables(lake)
        consumer = _consumer(kafka_bootstrap, f"bridge-live-{uuid.uuid4()}")
        bridge = ServingBridge(consumer, sink=ClickHouseSink(backend), lake_conn=lake)
        try:
            _drain_until_applied(bridge, event["event_id"])
        finally:
            consumer.close()
            lake.close()

        orders = _order_rows(backend, event["order_id"])
        assert len(orders) == 1, orders
        assert orders[0]["user_id"] == event["user_id"]
        assert _journal_rows(backend, event["event_id"]) == 1

    def test_replayed_event_is_not_applied_twice(self, kafka_bootstrap, backend):
        """At-least-once in, effectively-once out: the same event_id delivered
        again (Flink duplicate past its 10-minute dedup TTL, or an offset
        replay) must not write a second order version or a second journal row."""
        event = _flink_shaped_order()
        _ensure_topic(kafka_bootstrap)
        _publish(kafka_bootstrap, event)

        lake = duckdb.connect(":memory:")
        _ensure_tables(lake)
        sink = ClickHouseSink(backend)

        first = _consumer(kafka_bootstrap, f"bridge-live-{uuid.uuid4()}")
        try:
            _drain_until_applied(ServingBridge(first, sink=sink, lake_conn=lake), event["event_id"])
        finally:
            first.close()

        assert _journal_rows(backend, event["event_id"]) == 1

        # Same event, published again, consumed by a fresh group reading from
        # earliest — exactly what a Flink duplicate or a rewound offset looks
        # like. The scratch lake is fresh too, so only the ClickHouse journal
        # guard can catch this.
        _publish(kafka_bootstrap, event)
        replay_lake = duckdb.connect(":memory:")
        _ensure_tables(replay_lake)
        second = _consumer(kafka_bootstrap, f"bridge-live-{uuid.uuid4()}")
        try:
            replay = ServingBridge(second, sink=sink, lake_conn=replay_lake)
            _drain_expecting_no_apply(replay, event["event_id"], backend)
        finally:
            second.close()
            replay_lake.close()
            lake.close()

        assert len(_order_rows(backend, event["order_id"])) == 1
