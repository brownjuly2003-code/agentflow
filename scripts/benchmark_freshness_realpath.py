#!/usr/bin/env python3
"""Real-path event-to-validation freshness benchmark (Kafka -> Flink -> Kafka).

Unlike ``scripts/benchmark_freshness.py`` -- which measures the in-process
``local_pipeline._process_event`` DuckDB shortcut -- this driver measures the
**real streaming path**: an ``order.created`` event is produced to the Kafka
source topic ``orders.raw``, processed by the live Flink ``stream_processor``
job (schema validation -> enrichment -> deduplication), and emitted to
``events.validated``. One freshness sample is the wall-clock delay from produce
to the validated event landing on ``events.validated``, matched by ``event_id``.

This is the honest "real Kafka->Flink path" number for the freshness headline:
the serving DuckDB metric store is deliberately fed by the in-process shortcut
(production target is a ClickHouse sink), so end-to-end event->metric on the
demo remains the shortcut figure documented in ``docs/freshness-benchmark.md``.
This script measures the streaming hop the shortcut skips, on the real broker
and the real Flink operators.

Prerequisites: the Flink stack is up via
``docker compose -f docker-compose.yml -f docker-compose.flink.yml`` with the
``stream_processor`` job RUNNING, and this process can reach the Kafka HOST
listener (``localhost:19092`` by default). Run from the repo root so the
editable ``src`` package is importable (reuses the canonical event model):

    python scripts/benchmark_freshness_realpath.py --bootstrap localhost:19092 --iterations 30
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from confluent_kafka import Consumer, Producer

DEFAULT_REPORT = ".artifacts/freshness/realpath-current.json"


def build_order_event(amount: Decimal, sequence: int) -> dict:
    """A schema- and semantics-valid order.created event (reuses the repo model).

    Importing the canonical ``OrderEvent`` guarantees the produced payload passes
    the same validation the Flink job applies, so a valid event lands on
    ``events.validated`` rather than the dead-letter topic.
    """
    from src.ingestion.schemas.events import (
        Currency,
        EventType,
        OrderEvent,
        OrderItem,
        OrderStatus,
    )

    event = OrderEvent(
        event_id=str(uuid.uuid4()),
        event_type=EventType.ORDER_CREATED,
        timestamp=datetime.now(UTC),
        source="freshness-realpath-benchmark",
        # Schema pattern: ^ORD-\d{8}-\d{4,}$. The 9-prefixed sequence keeps these
        # ids clear of any seed generator's 4-digit ids.
        order_id=f"ORD-{datetime.now(UTC):%Y%m%d}-9{sequence:05d}",
        user_id=f"USR-{random.randint(10000, 99999)}",  # noqa: S311 - load shape, not crypto
        status=OrderStatus.PENDING,
        items=[OrderItem(product_id="PROD-001", quantity=1, unit_price=amount)],
        total_amount=amount,
        currency=Currency.USD,
    )
    return json.loads(event.model_dump_json())


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def make_validated_consumer(bootstrap: str, topic: str) -> Consumer:
    """A fresh-group consumer positioned at the END of ``topic``.

    A unique group id + ``auto.offset.reset=latest`` means we never replay the
    historical contents of ``events.validated`` -- we only observe events we
    produce during the run. The initial poll loop blocks until the assignment is
    live, then drains anything already buffered so the first sample starts clean.
    """
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            # Docker maps the Kafka HOST listener on IPv4 only; ``localhost``
            # resolves to ``::1`` first on macOS, so force the IPv4 family.
            "broker.address.family": "v4",
            "group.id": f"freshness-realpath-{uuid.uuid4()}",
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([topic])
    deadline = time.time() + 30.0
    while time.time() < deadline and not consumer.assignment():
        consumer.poll(0.5)
    # belt-and-suspenders: drain anything already at the tail
    while consumer.poll(0.2) is not None:
        pass
    return consumer


def wait_for_validated(consumer: Consumer, event_id: str, timeout_s: float) -> float | None:
    """Poll ``events.validated`` until our event_id appears; return the perf_counter."""
    needle = event_id.encode()
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        msg = consumer.poll(0.1)
        if msg is None or msg.error():
            continue
        value = msg.value()
        if value and needle in value:
            return time.perf_counter()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=os.getenv("KAFKA_BOOTSTRAP", "localhost:19092"))
    parser.add_argument("--source-topic", default="orders.raw")
    parser.add_argument("--validated-topic", default="events.validated")
    parser.add_argument("--iterations", type=int, default=30, help="measured samples")
    parser.add_argument("--warmup", type=int, default=3, help="discarded leading samples")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--report-json", default=DEFAULT_REPORT)
    args = parser.parse_args()

    producer = Producer(
        {
            "bootstrap.servers": args.bootstrap,
            "broker.address.family": "v4",
            "linger.ms": 0,
            "acks": "1",
        }
    )
    consumer = make_validated_consumer(args.bootstrap, args.validated_topic)
    if not consumer.assignment():
        print(
            "ERROR: consumer never got an assignment for "
            f"{args.validated_topic!r} on {args.bootstrap!r}",
            file=sys.stderr,
        )
        return 2

    print(
        f"bootstrap={args.bootstrap} source={args.source_topic} "
        f"validated={args.validated_topic} "
        f"warmup={args.warmup} iterations={args.iterations}"
    )

    samples: list[float] = []
    misses = 0
    total = args.warmup + args.iterations
    for i in range(total):
        is_warmup = i < args.warmup
        amount = Decimal(f"{random.randint(100, 999999) / 100:.2f}")
        event = build_order_event(amount, i)
        event_id = event["event_id"]
        payload = json.dumps(event).encode()

        t0 = time.perf_counter()
        producer.produce(args.source_topic, value=payload)
        producer.flush(5)
        reflected = wait_for_validated(consumer, event_id, args.timeout_seconds)

        tag = " (warmup)" if is_warmup else ""
        if reflected is None:
            misses += 1
            print(f"[{i:3d}] MISS  (>{args.timeout_seconds:.0f}s){tag}  id={event_id}")
        else:
            sample_ms = (reflected - t0) * 1000.0
            if not is_warmup:
                samples.append(sample_ms)
            print(f"[{i:3d}] {sample_ms:9.1f} ms{tag}")
        time.sleep(random.uniform(0.2, 0.8))

    consumer.close()
    producer.flush(5)

    if not samples:
        print(
            "\nNO MEASURED SAMPLES -- every event timed out. Is the Flink job "
            "RUNNING and consuming orders.raw? Check http://localhost:8081",
            file=sys.stderr,
        )
        return 1

    summary = {
        "samples": len(samples),
        "misses": misses,
        "p50_ms": round(percentile(samples, 0.50), 1),
        "p95_ms": round(percentile(samples, 0.95), 1),
        "p99_ms": round(percentile(samples, 0.99), 1),
        "min_ms": round(min(samples), 1),
        "max_ms": round(max(samples), 1),
        "mean_ms": round(statistics.mean(samples), 1),
    }
    report = {
        "benchmark": "event-to-validation-freshness-realpath",
        "path": (
            "produce(orders.raw) -> Flink stream_processor "
            "(validate/enrich/dedup) -> events.validated"
        ),
        "generated": datetime.now(UTC).isoformat(),
        "bootstrap": args.bootstrap,
        "source_topic": args.source_topic,
        "validated_topic": args.validated_topic,
        "timeout_seconds": args.timeout_seconds,
        "system": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "summary": summary,
        "samples_ms": [round(s, 1) for s in samples],
    }

    os.makedirs(os.path.dirname(args.report_json) or ".", exist_ok=True)
    with open(args.report_json, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print("\n=== Real-path freshness (produce -> Flink -> events.validated) ===")
    print(f"  samples : {summary['samples']}  (misses: {summary['misses']})")
    print(f"  p50     : {summary['p50_ms']:.1f} ms")
    print(f"  p95     : {summary['p95_ms']:.1f} ms")
    print(f"  p99     : {summary['p99_ms']:.1f} ms")
    print(f"  min/max : {summary['min_ms']:.1f} / {summary['max_ms']:.1f} ms")
    print(f"  mean    : {summary['mean_ms']:.1f} ms")
    print(f"\nwrote {args.report_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
