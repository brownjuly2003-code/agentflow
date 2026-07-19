#!/usr/bin/env python3
"""S10: sustained throughput on the real Kafka→Flink→bridge path.

Measures how many ``order.created`` events the single-node Mac stand can
push end-to-end into the serving store (ClickHouse via the serving bridge),
and samples event→entity latency under that load.

Path under test (same as S8, different question):

    produce(orders.raw) → Flink stream_processor → events.validated
      → serving bridge → ClickHouse

Outputs
-------
- produce rate (events/s the driver actually put on Kafka)
- Flink hop rate (events/s observed on ``events.validated``)
- bridge apply rate (events/s from Prometheus ``agentflow_bridge_events_applied_total``)
- lag at end / peak lag sample
- optional latency samples: produce → ``GET /v1/entity/order/{id}``

Prerequisites: same stand as S8 (compose Flink+Kafka+CH+Redis, bridge process
with metrics on ``:9108``, API optional for latency samples).

Usage (repo root on Mac)::

    .venv/bin/python scripts/benchmark_throughput_realpath.py \\
      --bootstrap 127.0.0.1:19092 --count 500 --bridge-metrics http://127.0.0.1:9108/metrics
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

from confluent_kafka import Consumer, Producer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = PROJECT_ROOT / ".artifacts" / "throughput" / "realpath-current.json"
DEFAULT_REPORT = PROJECT_ROOT / "docs" / "perf" / "throughput-realpath.md"


def build_order_event(amount: Decimal, sequence: int) -> dict:
    from src.ingestion.schemas.events import (
        Currency,
        EventType,
        OrderEvent,
        OrderItem,
        OrderStatus,
    )

    # Schema: ^ORD-\d{8}-\d{4,}$. Embed unix-seconds + sequence so re-runs
    # never collide with a previous stand's orders (which would fake latency).
    stamp = int(time.time()) % 100_000
    event = OrderEvent(
        event_id=str(uuid.uuid4()),
        event_type=EventType.ORDER_CREATED,
        timestamp=datetime.now(UTC),
        source="throughput-realpath-benchmark",
        order_id=f"ORD-{datetime.now(UTC):%Y%m%d}-{stamp:05d}{sequence:04d}",
        user_id=f"USR-{random.randint(10000, 99999)}",  # noqa: S311
        status=OrderStatus.PENDING,
        items=[OrderItem(product_id="PROD-001", quantity=1, unit_price=amount)],
        total_amount=amount,
        currency=Currency.RUB,
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


def fetch_text(url: str, timeout: float = 5.0) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read().decode("utf-8", errors="replace")
        if response.status != 200:
            raise RuntimeError(f"GET {url} -> {response.status}: {body[:200]!r}")
        return body
    finally:
        conn.close()


def parse_prom_counter(
    text: str,
    metric: str,
    labels_substr: str | None = None,
    *,
    default: float | None = None,
) -> float:
    """Sum matching sample lines for a Prometheus counter/gauge (no labels or filter).

    Counters with labels (e.g. consumed{topic=...}) only appear after the first
    sample; treat missing as ``default`` when set so a freshly started bridge
    scrapes as zeros rather than hard-failing the benchmark.
    """
    total = 0.0
    found = False
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line.startswith(metric):
            continue
        # metric or metric{...}
        name_end = line.find("{")
        if name_end == -1:
            name, _, rest = line.partition(" ")
            if name != metric:
                continue
        else:
            name = line[:name_end]
            if name != metric:
                continue
            labels = line[name_end : line.find("}") + 1]
            if labels_substr is not None and labels_substr not in labels:
                continue
            rest = line[line.find("}") + 1 :].strip()
        try:
            total += float(rest.split()[0])
            found = True
        except (ValueError, IndexError):
            continue
    if not found:
        if default is not None:
            return default
        raise RuntimeError(f"metric {metric!r} not found in scrape")
    return total


def read_bridge_snapshot(metrics_url: str) -> dict[str, float]:
    text = fetch_text(metrics_url)
    # Probe that the bridge metrics endpoint is live (any agentflow_bridge_*).
    if "agentflow_bridge_" not in text:
        raise RuntimeError("bridge metrics endpoint returned no agentflow_bridge_* series")
    return {
        "consumed": parse_prom_counter(
            text,
            "agentflow_bridge_events_consumed_total",
            'topic="events.validated"',
            default=0.0,
        ),
        "applied": parse_prom_counter(text, "agentflow_bridge_events_applied_total", default=0.0),
        "duplicates": parse_prom_counter(
            text, "agentflow_bridge_events_duplicate_total", default=0.0
        ),
        "apply_failures": parse_prom_counter(
            text, "agentflow_bridge_apply_failures_total", default=0.0
        ),
        "lag": parse_prom_counter(text, "agentflow_bridge_consumer_lag", default=0.0),
    }


def wait_for_entity(
    *,
    api_base: str,
    api_key: str,
    order_id: str,
    timeout_s: float,
    poll_s: float,
) -> float | None:
    """Poll entity until 200. Returns perf_counter at hit, or None on timeout.

    ``timeout_s`` is wall time from *now*, not from produce time (latency
    samples pass produce-time separately when computing elapsed).
    """
    parsed = urlparse(api_base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = f"/v1/entity/order/{order_id}"
    deadline = time.perf_counter() + max(timeout_s, 0.0)
    while True:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("GET", path, headers={"X-API-Key": api_key})
            response = conn.getresponse()
            response.read()
            if response.status == 200:
                return time.perf_counter()
        except OSError:
            pass
        finally:
            conn.close()
        if poll_s <= 0 or time.perf_counter() >= deadline:
            break
        time.sleep(poll_s)
    return None


def make_validated_consumer(bootstrap: str, topic: str) -> Consumer:
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "broker.address.family": "v4",
            "group.id": f"throughput-realpath-{uuid.uuid4()}",
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([topic])
    deadline = time.time() + 30.0
    while time.time() < deadline and not consumer.assignment():
        consumer.poll(0.5)
    while consumer.poll(0.2) is not None:
        pass
    return consumer


def format_rate(eps: float) -> str:
    if eps >= 100:
        return f"{eps:.0f} events/s"
    if eps >= 10:
        return f"{eps:.1f} events/s"
    return f"{eps:.2f} events/s"


def format_duration(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    return f"{ms:.0f} ms"


def build_markdown(report: dict) -> str:
    s = report["summary"]
    gen = report["generated"]
    lat = report.get("latency") or {}
    lines = [
        "# Real-path throughput (S10): Kafka → Flink → bridge → ClickHouse",
        "",
        f"> Generated by `scripts/benchmark_throughput_realpath.py`. Measured: `{gen}`.",
        "> Machine-readable: `.artifacts/throughput/realpath-current.json`.",
        "",
        "## What is measured",
        "",
        "Sustained (or burst) produce of schema-valid `order.created` events onto",
        "`orders.raw`, through the live Flink `stream_processor` job, the serving",
        "bridge, and into ClickHouse. Counters come from the bridge Prometheus",
        "endpoint (`agentflow_bridge_events_*`). Latency samples poll",
        "`GET /v1/entity/order/{id}` for a subset of events.",
        "",
        "```",
        report["path"],
        "```",
        "",
        "This is **D2 / S10**: throughput on the real path, reported next to the",
        "S8 latency number (3.02 s p50 event→metric). It is not the in-process",
        "DuckDB shortcut and not HTTP load-test RPS of the API.",
        "",
        "## System under test",
        "",
        f"- Platform: `{report['system']['platform']}`",
        f"- Python: `{report['system']['python']}`",
        f"- Kafka bootstrap: `{report['bootstrap']}`",
        f"- Bridge metrics: `{report['bridge_metrics_url']}`",
        f"- Count / pace: {report['count']} events"
        + (
            f", target pace {report['pace_eps']} events/s"
            if report.get("pace_eps")
            else ", unpaced burst"
        ),
        f"- Latency samples: {report.get('latency_samples', 0)}",
        "",
        "## Results",
        "",
        "| Arm | Value |",
        "|-----|------:|",
        f"| Events produced | {s['produced']} |",
        f"| Produce wall time | {s['produce_wall_s']:.2f} s |",
        f"| **Produce rate** | **{format_rate(s['produce_eps'])}** |",
        f"| Validated seen (Flink hop) | {s['validated_seen']} |",
        f"| Flink hop rate (during produce+drain) | {format_rate(s['flink_eps'])} |",
        f"| Bridge applied delta | {s['applied_delta']} |",
        f"| Bridge duplicates delta | {s['duplicates_delta']} |",
        f"| Bridge apply failures delta | {s['apply_failures_delta']} |",
        (
            f"| **Bridge apply rate** (produce start → catch-up) | "
            f"**{format_rate(s['bridge_apply_eps'])}** |"
        ),
        f"| Catch-up wall time | {s['catchup_wall_s']:.2f} s |",
        (
            f"| Lag start → end / peak sampled | "
            f"{s['lag_start']:.0f} → {s['lag_end']:.0f} / {s['lag_peak']:.0f} |"
        ),
        "",
    ]
    if lat.get("samples"):
        lines += [
            "### Latency under load (produce → entity)",
            "",
            "| Metric | Value |",
            "|--------|------:|",
            f"| n | {lat['samples']} |",
            f"| p50 | {format_duration(lat['p50_ms'])} |",
            f"| p95 | {format_duration(lat['p95_ms'])} |",
            f"| min / max | {format_duration(lat['min_ms'])} / {format_duration(lat['max_ms'])} |",
            f"| mean | {format_duration(lat['mean_ms'])} |",
            "",
        ]
    lines += [
        "## Reading the numbers",
        "",
        "- Produce rate is what the driver put on Kafka; it is not the product",
        "  ceiling if the bridge or Flink is slower.",
        "- **Bridge apply rate** is the product-relevant sustained number for",
        "  event→serving on this stand: every applied event is in ClickHouse",
        "  (idempotent journal). The S6 design notes a serialized-writer ceiling",
        "  of a few hundred events/s via `_process_event` + scratch DuckDB.",
        "- Flink hop rate sits between produce and bridge when the bridge is the",
        "  bottleneck (validated topic grows lag, bridge lag rises).",
        "- Latency samples under load should be read next to the unloaded S8",
        "  metric p50 (3.02 s); entity is a lighter read than a full metric SQL.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "# stack + bridge as in docs/serving-bridge.md / _NEXT_SESSION.md",
        "python scripts/benchmark_throughput_realpath.py \\",
        "  --bootstrap 127.0.0.1:19092 --count 500 \\",
        "  --bridge-metrics http://127.0.0.1:9108/metrics \\",
        "  --api-base http://127.0.0.1:8000 --api-key <key> --latency-samples 10",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", default=os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:19092"))
    parser.add_argument("--source-topic", default="orders.raw")
    parser.add_argument("--validated-topic", default="events.validated")
    parser.add_argument("--count", type=int, default=500, help="events to produce")
    parser.add_argument(
        "--pace-eps",
        type=float,
        default=0.0,
        help="target produce rate (0 = unpaced burst)",
    )
    parser.add_argument(
        "--bridge-metrics",
        default=os.getenv("AGENTFLOW_BRIDGE_METRICS_URL", "http://127.0.0.1:9108/metrics"),
    )
    parser.add_argument(
        "--api-base", default=os.getenv("AGENTFLOW_API_BASE", "http://127.0.0.1:8000")
    )
    parser.add_argument("--api-key", default=os.getenv("DEMO_API_KEY", "s8-freshness-key"))
    parser.add_argument("--latency-samples", type=int, default=10)
    parser.add_argument("--latency-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--catchup-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--report-json", default=str(DEFAULT_JSON))
    parser.add_argument("--report-md", default=str(DEFAULT_REPORT))
    parser.add_argument("--no-md", action="store_true")
    args = parser.parse_args()

    try:
        baseline = read_bridge_snapshot(args.bridge_metrics)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: bridge metrics unavailable at {args.bridge_metrics}: {exc}", file=sys.stderr)
        return 2

    producer = Producer(
        {
            "bootstrap.servers": args.bootstrap,
            "broker.address.family": "v4",
            "linger.ms": 5,
            "acks": "1",
            "compression.type": "lz4",
            "batch.num.messages": 1000,
        }
    )
    consumer = make_validated_consumer(args.bootstrap, args.validated_topic)
    if not consumer.assignment():
        print("ERROR: no assignment on events.validated", file=sys.stderr)
        return 2

    print(
        f"bootstrap={args.bootstrap} count={args.count} pace={args.pace_eps or 'burst'} "
        f"bridge_applied0={baseline['applied']:.0f} lag0={baseline['lag']:.0f}",
        flush=True,
    )

    # Latency sample indices evenly spaced through the run
    latency_indices: set[int] = set()
    if args.latency_samples > 0 and args.count > 0:
        step = max(1, args.count // args.latency_samples)
        latency_indices = {min(args.count - 1, i * step) for i in range(args.latency_samples)}

    produced = 0
    validated_seen = 0
    latency_ms: list[float] = []
    lag_peak = baseline["lag"]
    pending_latency: dict[str, tuple[float, str]] = {}  # event_id -> (t0, order_id)

    # Delivery errors surface ONLY via callback: without one librdkafka expires
    # undeliverable messages silently (message.timeout.ms) and `produced` counts
    # events that never reached the broker — the gate math is then meaningless.
    delivery_failures = 0
    first_delivery_error: str | None = None

    def _on_delivery(err: object, _msg: object) -> None:
        nonlocal delivery_failures, first_delivery_error
        if err is not None:
            delivery_failures += 1
            if first_delivery_error is None:
                first_delivery_error = str(err)

    t_produce0 = time.perf_counter()
    next_pace = t_produce0
    for i in range(args.count):
        amount = Decimal(f"{2000 + (i % 500)}.{random.randint(10, 99)}")  # noqa: S311
        event = build_order_event(amount, i)
        payload = json.dumps(event).encode()
        want_lat = i in latency_indices
        if want_lat:
            pending_latency[event["event_id"]] = (time.perf_counter(), event["order_id"])

        producer.produce(args.source_topic, value=payload, on_delivery=_on_delivery)
        produced += 1
        if produced % 50 == 0:
            producer.poll(0)
            if delivery_failures:
                print(
                    f"FATAL: {delivery_failures} events failed delivery after retries "
                    f"(first: {first_delivery_error}); aborting — a run with lost "
                    "produce cannot judge the gate",
                    file=sys.stderr,
                )
                return 3

        if args.pace_eps > 0:
            next_pace += 1.0 / args.pace_eps
            sleep_for = next_pace - time.perf_counter()
            if sleep_for > 0:
                time.sleep(sleep_for)

        # Drain validated consumer opportunistically
        while True:
            msg = consumer.poll(0)
            if msg is None or msg.error():
                break
            validated_seen += 1

        if produced % 100 == 0:
            try:
                snap = read_bridge_snapshot(args.bridge_metrics)
                lag_peak = max(lag_peak, snap["lag"])
                print(
                    f"  produced={produced} validated_seen={validated_seen} "
                    f"applied={snap['applied']:.0f} lag={snap['lag']:.0f}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  produced={produced} (metrics warn: {exc})", flush=True)

    unflushed = producer.flush(120)
    if unflushed or delivery_failures:
        print(
            f"FATAL: produce lane lost events (delivery_failures={delivery_failures}, "
            f"still_in_queue={unflushed}, first: {first_delivery_error}); aborting",
            file=sys.stderr,
        )
        return 3
    t_produce1 = time.perf_counter()
    produce_wall = t_produce1 - t_produce0

    # Catch-up: wait until bridge applied advances by ~produced; sample entity latency in-band.
    t_catch0 = time.perf_counter()
    catch_deadline = t_catch0 + args.catchup_timeout_seconds
    final = baseline
    while time.perf_counter() < catch_deadline:
        while True:
            msg = consumer.poll(0.05)
            if msg is None or msg.error():
                break
            validated_seen += 1
        # Single-shot entity probes for latency samples still pending
        for event_id, (t0, order_id) in list(pending_latency.items()):
            reflected = wait_for_entity(
                api_base=args.api_base,
                api_key=args.api_key,
                order_id=order_id,
                timeout_s=0.0,  # one attempt this iteration
                poll_s=0.0,
            )
            if reflected is not None:
                sample = (reflected - t0) * 1000.0
                latency_ms.append(sample)
                del pending_latency[event_id]
                print(f"  latency order={order_id} {sample:.0f} ms", flush=True)
            elif time.perf_counter() - t0 > args.latency_timeout_seconds:
                print(f"  latency MISS order={order_id}", flush=True)
                del pending_latency[event_id]
        try:
            final = read_bridge_snapshot(args.bridge_metrics)
            lag_peak = max(lag_peak, final["lag"])
            applied_delta = final["applied"] - baseline["applied"]
            processed = applied_delta + (final["duplicates"] - baseline["duplicates"])
            if (
                processed >= produced * 0.99
                and final["lag"] <= max(5.0, baseline["lag"])
                and not pending_latency
            ):
                break
            if processed >= produced * 0.99 and final["lag"] <= max(5.0, baseline["lag"]):
                # applied done; keep looping only for remaining latency probes
                if not pending_latency:
                    break
            print(
                f"  catch-up applied_delta={applied_delta:.0f}/{produced} "
                f"dup_delta={final['duplicates'] - baseline['duplicates']:.0f} "
                f"lag={final['lag']:.0f} lat_pending={len(pending_latency)}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  catch-up metrics warn: {exc}", flush=True)
        time.sleep(0.25)
    for _event_id, (_t0, order_id) in pending_latency.items():
        print(f"  latency MISS order={order_id}", flush=True)
    t_catch1 = time.perf_counter()

    consumer.close()

    applied_delta = final["applied"] - baseline["applied"]
    dup_delta = final["duplicates"] - baseline["duplicates"]
    fail_delta = final["apply_failures"] - baseline["apply_failures"]
    catchup_wall = t_catch1 - t_produce0  # produce start → catch-up done
    produce_eps = produced / produce_wall if produce_wall > 0 else 0.0
    bridge_apply_eps = applied_delta / catchup_wall if catchup_wall > 0 else 0.0
    flink_eps = validated_seen / catchup_wall if catchup_wall > 0 else 0.0

    summary = {
        "produced": produced,
        "produce_wall_s": round(produce_wall, 3),
        "produce_eps": round(produce_eps, 2),
        "validated_seen": validated_seen,
        "flink_eps": round(flink_eps, 2),
        "applied_delta": int(applied_delta),
        "duplicates_delta": int(dup_delta),
        "apply_failures_delta": int(fail_delta),
        "bridge_apply_eps": round(bridge_apply_eps, 2),
        "catchup_wall_s": round(catchup_wall, 3),
        "lag_start": baseline["lag"],
        "lag_end": final["lag"],
        "lag_peak": lag_peak,
    }
    latency_block: dict | None = None
    if latency_ms:
        latency_block = {
            "samples": len(latency_ms),
            "p50_ms": round(percentile(latency_ms, 0.50), 1),
            "p95_ms": round(percentile(latency_ms, 0.95), 1),
            "min_ms": round(min(latency_ms), 1),
            "max_ms": round(max(latency_ms), 1),
            "mean_ms": round(statistics.mean(latency_ms), 1),
            "samples_ms": [round(x, 1) for x in latency_ms],
        }

    report = {
        "benchmark": "throughput-realpath-s10",
        "path": (
            "produce(orders.raw) → Flink stream_processor → events.validated "
            "→ serving bridge → ClickHouse"
        ),
        "generated": datetime.now(UTC).isoformat(),
        "bootstrap": args.bootstrap,
        "source_topic": args.source_topic,
        "validated_topic": args.validated_topic,
        "bridge_metrics_url": args.bridge_metrics,
        "count": args.count,
        "pace_eps": args.pace_eps or None,
        "latency_samples": args.latency_samples,
        "system": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "baseline": baseline,
        "final": final,
        "summary": summary,
        "latency": latency_block,
    }

    json_path = Path(args.report_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if not args.no_md:
        md_path = Path(args.report_md)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(build_markdown(report), encoding="utf-8")
        print(f"\nwrote {md_path}", flush=True)

    print("\n=== S10 real-path throughput ===")
    print(f"  produced     : {produced} in {produce_wall:.2f}s → {format_rate(produce_eps)}")
    print(f"  flink hop    : {validated_seen} → {format_rate(flink_eps)}")
    print(
        f"  bridge apply : +{int(applied_delta)} (dup +{int(dup_delta)}, fail +{int(fail_delta)}) "
        f"in {catchup_wall:.2f}s → {format_rate(bridge_apply_eps)}"
    )
    print(f"  lag          : {baseline['lag']:.0f} → {final['lag']:.0f} (peak {lag_peak:.0f})")
    if latency_block:
        print(
            f"  entity p50   : {format_duration(latency_block['p50_ms'])} "
            f"(n={latency_block['samples']})"
        )
    print(f"\nwrote {json_path}")
    return 0 if applied_delta > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
