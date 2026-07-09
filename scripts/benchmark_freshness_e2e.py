#!/usr/bin/env python3
"""S8: end-to-end event → metric freshness on the real streaming path.

Measures wall-clock delay from producing an ``order.created`` event to
Kafka ``orders.raw`` until ``GET /v1/metrics/{metric}`` (default: revenue)
reflects that order's amount, over the full production-shaped path:

    produce(orders.raw)
      → Flink stream_processor (validate / enrich / dedup)
      → events.validated
      → serving bridge (standalone ClickHouse process)
      → ClickHouse serving store
      → metric cache invalidation (Redis push + journal scan)
      → GET /v1/metrics/revenue

This is the honest *event → live metric* number on the real path. It is
distinct from:

- ``scripts/benchmark_freshness.py`` — in-process DuckDB shortcut
  (local_pipeline → store, no Kafka/Flink/bridge);
- ``scripts/benchmark_freshness_realpath.py`` — streaming hop only
  (produce → events.validated), no serving/metric.

Prerequisites (Mac stand, see ``_NEXT_SESSION.md`` / ``docs/serving-bridge.md``):

  docker compose -f docker-compose.yml -f docker-compose.flink.yml \\
    up -d --scale flink-taskmanager=1 flink-job-runner clickhouse redis
  # JM RUNNING, flink-version 2.3.0, stream_processor job running

  SERVING_BACKEND=clickhouse CLICKHOUSE_HOST=127.0.0.1 \\
    KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092 \\
    .venv/bin/python -m src.processing.bridge_consumer &

  SERVING_BACKEND=clickhouse CLICKHOUSE_HOST=127.0.0.1 \\
    AGENTFLOW_DEMO_MODE=true AGENTFLOW_SEED_ON_BOOT=true \\
    REDIS_URL=redis://127.0.0.1:6379 AGENTFLOW_NODE_EMITTER_ENABLED=false \\
    .venv/bin/python -m uvicorn src.serving.api.main:app --host 127.0.0.1 --port 8000 &

Usage (from repo root, Mac):

    .venv/bin/python scripts/benchmark_freshness_e2e.py \\
      --bootstrap 127.0.0.1:19092 --api-base http://127.0.0.1:8000 \\
      --iterations 20 --warmup 2
"""

from __future__ import annotations

import argparse
import http.client
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
from pathlib import Path
from urllib.parse import urlparse

from confluent_kafka import Producer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = PROJECT_ROOT / ".artifacts" / "freshness" / "e2e-realpath-current.json"
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "perf" / "freshness-e2e-realpath.md"
REFLECT_EPSILON = 0.005
DEFAULT_API_KEY = "demo-key"  # noqa: S105 — demo mode default


def build_order_event(amount: Decimal, sequence: int) -> dict:
    """Schema- and semantics-valid order.created (canonical model)."""
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
        source="freshness-e2e-benchmark",
        # Schema: ^ORD-\d{8}-\d{4,}$. 8-prefix keeps clear of seed / realpath 9-prefix.
        order_id=f"ORD-{datetime.now(UTC):%Y%m%d}-8{sequence:05d}",
        user_id=f"USR-{random.randint(10000, 99999)}",  # noqa: S311
        status=OrderStatus.PENDING,
        items=[OrderItem(product_id="PROD-001", quantity=1, unit_price=amount)],
        total_amount=amount,
        currency=Currency.RUB,
    )
    return json.loads(event.model_dump_json())


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile; q in [0, 1]."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def read_metric(api_base: str, metric: str, window: str, api_key: str) -> float:
    parsed = urlparse(api_base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = f"/v1/metrics/{metric}?window={window}"
    conn = http.client.HTTPConnection(host, port, timeout=10)
    try:
        conn.request("GET", path, headers={"X-API-Key": api_key})
        response = conn.getresponse()
        body = response.read()
        # Demo key defaults to 60 rpm; polling at 50 ms burns it in seconds.
        # Back off on 429 so a long-running e2e still measures path latency.
        if response.status == 429:
            raise RuntimeError(f"GET {path} -> 429 rate limited: {body[:200]!r}")
        if response.status != 200:
            raise RuntimeError(
                f"GET {path} -> {response.status}: {body[:300]!r}"
            )
        payload = json.loads(body)
        value = payload.get("value")
        return float(value) if value is not None else 0.0
    finally:
        conn.close()


def wait_for_metric(
    *,
    api_base: str,
    metric: str,
    window: str,
    api_key: str,
    target: float,
    timeout_s: float,
    poll_interval_s: float,
    t0: float,
) -> float | None:
    deadline = t0 + timeout_s
    while time.perf_counter() < deadline:
        try:
            value = read_metric(api_base, metric, window, api_key)
        except Exception as exc:  # noqa: BLE001 — transient while stack warms
            print(f"  warn: metric read failed: {exc}", flush=True)
            time.sleep(poll_interval_s)
            continue
        if value + REFLECT_EPSILON >= target:
            return time.perf_counter()
        time.sleep(poll_interval_s)
    return None


def format_duration(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    return f"{ms:.0f} ms"


def build_markdown(report: dict) -> str:
    s = report["summary"]
    path = report["path"]
    gen = report["generated"]
    samples = s["samples"]
    misses = s["misses"]
    lines = [
        "# Event → Metric Freshness on the Real Path (S8)",
        "",
        f"> Generated by `scripts/benchmark_freshness_e2e.py`. Measured: `{gen}`.",
        f"> Machine-readable: `.artifacts/freshness/e2e-realpath-current.json`.",
        "",
        "## What is measured",
        "",
        "One sample is the wall-clock delay from producing an `order.created`",
        "event to Kafka `orders.raw` until `GET /v1/metrics/revenue` reflects",
        "that order's amount on the **full** real path:",
        "",
        "```",
        path,
        "```",
        "",
        "This is the product axis claim (*event → live metric*) on the real",
        "streaming + bridge + serving path — not the in-process DuckDB shortcut",
        "and not the streaming-hop-only figure.",
        "",
        "## System under test",
        "",
        f"- Host platform: `{report['system']['platform']}`",
        f"- Python: `{report['system']['python']}`",
        f"- Kafka bootstrap: `{report['bootstrap']}`",
        f"- API: `{report['api_base']}` (metric `{report['metric']}`, window `{report['window']}`)",
        f"- Source topic: `{report['source_topic']}`",
        f"- Poll interval: {report['poll_interval_ms']} ms · timeout: {report['timeout_seconds']} s",
        f"- Warmup discarded: {report['warmup']} · measured iterations: {report['iterations']}",
        "",
        "## Results",
        "",
        f"| Metric | Real path (this run) | In-process DuckDB shortcut* | Streaming hop only** | Entity real-path (S6 live) |",
        f"|--------|---------------------:|----------------------------:|---------------------:|---------------------------:|",
        f"| p50    | **{format_duration(s['p50_ms'])}** | 1.06 s | 2.50 s | 3.26 s (entity, n≈1) |",
        f"| p95    | {format_duration(s['p95_ms'])} | 1.99 s | 10.11 s | — |",
        f"| p99    | {format_duration(s['p99_ms'])} | — | 15.42 s | — |",
        f"| min    | {format_duration(s['min_ms'])} | — | 0.31 s | — |",
        f"| max    | {format_duration(s['max_ms'])} | 2.02 s | 16.09 s | — |",
        f"| mean   | {format_duration(s['mean_ms'])} | — | 3.33 s | — |",
        f"| n / misses | {samples} / {misses} | 30 / 0 | 30 / 0 | — |",
        "",
        "\\* `docs/freshness-benchmark.md` — `local_pipeline` → DuckDB → metric (pre-S7 poll-era).",
        "",
        "\\*\\* `docs/perf/freshness-realpath-2026-06-30.md` — produce → `events.validated` only.",
        "",
        "## Reading the numbers",
        "",
        "- The real-path p50 includes Kafka produce, Flink Beam UDF hop, bridge",
        "  apply into ClickHouse, Redis push (or journal-scan fallback) cache",
        "  invalidation, and a metric SQL read — everything the product promise",
        "  actually costs on a single-node Colima stand.",
        "- The in-process 1.06 s figure remains valid for the **demo/shortcut**",
        "  path; do not present it as the production Kafka→Flink→bridge number.",
        "- S6's 3.26 s entity sample was a single live probe of the same path",
        "  stopping at `GET /v1/entity`; this run measures the metric arm and",
        "  reports full distribution.",
        "- N2 (ClickHouse naive DateTime = UTC) is required for sensible",
        "  windowed metric SQL on non-UTC hosts; it is already in main.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "# stack + bridge + API as in docs/serving-bridge.md / _NEXT_SESSION.md",
        "python scripts/benchmark_freshness_e2e.py \\",
        "  --bootstrap 127.0.0.1:19092 --api-base http://127.0.0.1:8000 \\",
        "  --iterations 20 --warmup 2",
        "```",
        "",
        "## Samples (ms)",
        "",
        "```",
        json.dumps(report.get("samples_ms", []), indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap",
        default=os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:19092"),
    )
    parser.add_argument("--source-topic", default="orders.raw")
    parser.add_argument(
        "--api-base",
        default=os.getenv("AGENTFLOW_API_BASE", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("DEMO_API_KEY", DEFAULT_API_KEY),
    )
    parser.add_argument("--metric", default="revenue")
    parser.add_argument("--window", default="24h")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--poll-interval-ms", type=int, default=50)
    parser.add_argument("--report-json", default=str(DEFAULT_JSON))
    parser.add_argument("--report-md", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-md", action="store_true", help="skip markdown report")
    args = parser.parse_args()

    poll_s = args.poll_interval_ms / 1000.0

    # Sanity: API reachable
    try:
        baseline0 = read_metric(args.api_base, args.metric, args.window, args.api_key)
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: cannot read metric from {args.api_base}: {exc}\n"
            "Is the API up with SERVING_BACKEND=clickhouse and demo mode?",
            file=sys.stderr,
        )
        return 2

    producer = Producer(
        {
            "bootstrap.servers": args.bootstrap,
            "broker.address.family": "v4",
            "linger.ms": 0,
            "acks": "1",
        }
    )

    print(
        f"bootstrap={args.bootstrap} topic={args.source_topic} "
        f"api={args.api_base} metric={args.metric}/{args.window} "
        f"baseline={baseline0} warmup={args.warmup} iterations={args.iterations}",
        flush=True,
    )

    samples: list[float] = []
    misses = 0
    total = args.warmup + args.iterations
    for i in range(total):
        is_warmup = i < args.warmup
        # Distinct amounts so cumulative SUM is unambiguous even with concurrent seed noise
        amount = Decimal(f"{1000 + i * 17}.{random.randint(10, 99)}")  # noqa: S311
        event = build_order_event(amount, i)
        event_id = event["event_id"]
        payload = json.dumps(event).encode()

        try:
            baseline = read_metric(args.api_base, args.metric, args.window, args.api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i:3d}] baseline read failed: {exc}", flush=True)
            misses += 1
            continue
        target = baseline + float(amount)

        t0 = time.perf_counter()
        producer.produce(args.source_topic, value=payload)
        producer.flush(5)

        reflected = wait_for_metric(
            api_base=args.api_base,
            metric=args.metric,
            window=args.window,
            api_key=args.api_key,
            target=target,
            timeout_s=args.timeout_seconds,
            poll_interval_s=poll_s,
            t0=t0,
        )

        tag = " (warmup)" if is_warmup else ""
        if reflected is None:
            misses += 1
            print(
                f"[{i:3d}] MISS  (>{args.timeout_seconds:.0f}s){tag}  "
                f"id={event_id} amount={amount} baseline={baseline}",
                flush=True,
            )
        else:
            sample_ms = (reflected - t0) * 1000.0
            if not is_warmup:
                samples.append(sample_ms)
            print(
                f"[{i:3d}] {sample_ms:9.1f} ms{tag}  amount={amount} "
                f"baseline={baseline:.2f} → target={target:.2f}",
                flush=True,
            )
        # Jitter so samples do not all land on the same phase of any residual poll
        time.sleep(random.uniform(0.15, 0.6))  # noqa: S311

    producer.flush(5)

    if not samples:
        print(
            "\nNO MEASURED SAMPLES — every event timed out.\n"
            "Check: Flink stream_processor RUNNING, bridge consuming "
            "events.validated, API SERVING_BACKEND=clickhouse.",
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
    path_desc = (
        "produce(orders.raw) → Flink stream_processor → events.validated "
        "→ serving bridge → ClickHouse → (Redis push invalidation) "
        f"→ GET /v1/metrics/{args.metric}"
    )
    report = {
        "benchmark": "event-to-metric-freshness-e2e-realpath",
        "path": path_desc,
        "generated": datetime.now(UTC).isoformat(),
        "bootstrap": args.bootstrap,
        "source_topic": args.source_topic,
        "api_base": args.api_base,
        "metric": args.metric,
        "window": args.window,
        "timeout_seconds": args.timeout_seconds,
        "poll_interval_ms": args.poll_interval_ms,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "system": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "summary": summary,
        "samples_ms": [round(s, 1) for s in samples],
    }

    json_path = Path(args.report_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.no_md:
        md_path = Path(args.report_md)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(build_markdown(report), encoding="utf-8")
        print(f"\nwrote {md_path}", flush=True)

    print("\n=== S8 real-path event → metric freshness ===")
    print(f"  samples : {summary['samples']}  (misses: {summary['misses']})")
    print(f"  p50     : {format_duration(summary['p50_ms'])}")
    print(f"  p95     : {format_duration(summary['p95_ms'])}")
    print(f"  p99     : {format_duration(summary['p99_ms'])}")
    print(f"  min/max : {format_duration(summary['min_ms'])} / {format_duration(summary['max_ms'])}")
    print(f"  mean    : {format_duration(summary['mean_ms'])}")
    print(f"\nwrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
