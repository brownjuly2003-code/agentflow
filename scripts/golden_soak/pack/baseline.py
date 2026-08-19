#!/usr/bin/env python3
"""Pre-traffic baseline: canary + soak namespaces must be exactly zero.

Read-only. Prints one compact PASS/FAIL line. Does not mutate data.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


CANARY_SOURCE = "golden-4h-soak-rv-20260819-07"
SOAK_SOURCE = "golden-4h-soak-rv-20260819-07"
CANARY_EVENT_PREFIX = "f8b2c3d4-e5f6-4a71-b829-"
SOAK_EVENT_PREFIX = "f8b2c3d4-e5f6-4a71-b829-"
# Canonical OrderEvent pattern ^ORD-\d{8}-\d{4,}$ — numeric prefixes only.
CANARY_ORDER_PREFIX = "ORD-20260819-0700"
SOAK_ORDER_PREFIX = "ORD-20260819-0700"
SOURCES = (SOAK_SOURCE,)
EVENT_PREFIXES = (SOAK_EVENT_PREFIX,)
ORDER_PREFIXES = (SOAK_ORDER_PREFIX,)


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise SystemExit(f"missing_env={name}")
    return value


def _ch_count(sql: str) -> int:
    host = _env("CLICKHOUSE_HOST")
    port = _env("CLICKHOUSE_PORT", "8123")
    db = _env("CLICKHOUSE_DATABASE", "agentflow")
    url = f"http://{host}:{port}/?database={db}"
    req = urllib.request.Request(url, data=sql.encode("utf-8"), method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8").strip()
    if not body:
        return 0
    return int(body.splitlines()[0].strip())


def _api_entity_exists(order_id: str) -> bool:
    base = _env("TASK_API_BASE").rstrip("/")
    key = _env("DEMO_API_KEY")
    req = urllib.request.Request(
        f"{base}/v1/entity/order/{order_id}",
        headers={"X-API-Key": key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def _kafka_prefix_counts(bootstrap: str, group: str) -> tuple[int, int]:
    from confluent_kafka import Consumer, KafkaError, TopicPartition

    topics = ["events.validated", "events.deadletter"]
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    validated = 0
    deadletter = 0
    try:
        # Bounded snapshot: assign all partitions from beginning, read until
        # high-water or idle budget exhausted.
        md = consumer.list_topics(timeout=15)
        tps: list[TopicPartition] = []
        for topic in topics:
            tmeta = md.topics.get(topic)
            if tmeta is None or tmeta.error is not None:
                continue
            for p in tmeta.partitions:
                tps.append(TopicPartition(topic, p, 0))
        if not tps:
            return 0, 0
        consumer.assign(tps)
        # Seek to beginning explicitly.
        for tp in tps:
            low, high = consumer.get_watermark_offsets(tp, timeout=10)
            tp.offset = low
        consumer.assign(tps)

        idle_rounds = 0
        deadline = time.time() + 90
        while time.time() < deadline and idle_rounds < 8:
            messages = consumer.consume(num_messages=500, timeout=1.0)
            if not messages:
                idle_rounds += 1
                continue
            idle_rounds = 0
            for msg in messages:
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    raise RuntimeError(str(msg.error()))
                try:
                    payload = json.loads(msg.value().decode("utf-8"))
                except Exception:
                    continue
                eid = str(payload.get("event_id") or "")
                if not any(eid.startswith(p) for p in EVENT_PREFIXES):
                    continue
                if msg.topic() == "events.validated":
                    validated += 1
                elif msg.topic() == "events.deadletter":
                    deadletter += 1
    finally:
        consumer.close()
    return validated, deadletter


def _iceberg_source_count() -> int:
    from pyiceberg.expressions import EqualTo, Or, Reference, literal

    from src.processing.iceberg_sink import IcebergSink

    config = _env("AGENTFLOW_ICEBERG_CONFIG", "/app/config/iceberg.yaml")
    sink = IcebergSink(config)
    table = sink.catalog.load_table(sink._identifier("validated_events"))
    filt = Or(
        EqualTo(Reference("source"), literal(CANARY_SOURCE)),
        EqualTo(Reference("source"), literal(SOAK_SOURCE)),
    )
    # Stream only source column; stay memory-safe.
    total = 0
    scan = table.scan(row_filter=filt, selected_fields=("source",))
    try:
        for batch in scan.to_arrow_batch_reader():
            total += int(batch.num_rows)
    except Exception:
        # Fallback for older pyiceberg: full arrow (should be zero at baseline).
        arrow = scan.to_arrow()
        total = int(arrow.num_rows)
    return total


def main() -> int:
    bootstrap = _env("KAFKA_BOOTSTRAP_SERVERS", "kafka.agentflow.svc.cluster.local:9092")
    group = _env(
        "KAFKA_BASELINE_GROUP",
        "agentflow-golden-4h-baseline-20260802-01",
    )

    counts: dict[str, Any] = {}
    try:
        kv, kd = _kafka_prefix_counts(bootstrap, group)
        counts["kafka_validated"] = kv
        counts["kafka_deadletter"] = kd
    except Exception as exc:  # noqa: BLE001
        print(f"result=FAIL reason=kafka_error detail={type(exc).__name__}", flush=True)
        return 1

    try:
        counts["iceberg"] = _iceberg_source_count()
    except Exception as exc:  # noqa: BLE001
        print(f"result=FAIL reason=iceberg_error detail={type(exc).__name__}", flush=True)
        return 1

    # ClickHouse pipeline_events by event prefix; orders_v2 by order prefix.
    try:
        ch_pipeline = 0
        for pfx in EVENT_PREFIXES:
            ch_pipeline += _ch_count(
                "SELECT count() FROM pipeline_events "
                f"WHERE event_id LIKE '{pfx}%' FORMAT TabSeparated"
            )
        counts["ch_pipeline"] = ch_pipeline
        ch_orders = 0
        for pfx in ORDER_PREFIXES:
            ch_orders += _ch_count(
                "SELECT count() FROM orders_v2 "
                f"WHERE order_id LIKE '{pfx}%' FORMAT TabSeparated"
            )
        counts["ch_orders"] = ch_orders
    except Exception as exc:  # noqa: BLE001
        print(f"result=FAIL reason=clickhouse_error detail={type(exc).__name__}", flush=True)
        return 1

    # Representative first/last order IDs for both namespaces (seq 1 and large).
    api_hits = 0
    sample_orders = [
        f"{CANARY_ORDER_PREFIX}{1:07d}",
        f"{CANARY_ORDER_PREFIX}{2000:07d}",
        f"{SOAK_ORDER_PREFIX}{1:07d}",
        f"{SOAK_ORDER_PREFIX}{1440000:07d}",
    ]
    try:
        for oid in sample_orders:
            if _api_entity_exists(oid):
                api_hits += 1
        counts["api_entity_hits"] = api_hits
    except Exception as exc:  # noqa: BLE001
        print(f"result=FAIL reason=api_error detail={type(exc).__name__}", flush=True)
        return 1

    all_zero = (
        counts["kafka_validated"] == 0
        and counts["kafka_deadletter"] == 0
        and counts["iceberg"] == 0
        and counts["ch_pipeline"] == 0
        and counts["ch_orders"] == 0
        and counts["api_entity_hits"] == 0
    )
    if all_zero:
        print(
            "result=PASS baseline_all_zero=1 "
            f"kafka_validated={counts['kafka_validated']} "
            f"kafka_deadletter={counts['kafka_deadletter']} "
            f"iceberg={counts['iceberg']} "
            f"ch_pipeline={counts['ch_pipeline']} "
            f"ch_orders={counts['ch_orders']} "
            f"api_entity_hits={counts['api_entity_hits']}",
            flush=True,
        )
        return 0

    print(
        "result=FAIL baseline_all_zero=0 "
        f"kafka_validated={counts['kafka_validated']} "
        f"kafka_deadletter={counts['kafka_deadletter']} "
        f"iceberg={counts['iceberg']} "
        f"ch_pipeline={counts['ch_pipeline']} "
        f"ch_orders={counts['ch_orders']} "
        f"api_entity_hits={counts['api_entity_hits']}",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
