"""Measure event-to-metric freshness and generate docs/freshness-benchmark.md.

Freshness here is the end-to-end delay between an event entering the pipeline
(`local_pipeline._process_event`: schema validation -> semantic validation ->
enrichment -> DuckDB write, the same code path the demo pipeline runs) and the
moment `GET /v1/metrics/{metric}` served over real HTTP reflects that event in
its value.

The API process serves metrics through a Redis-backed query cache whose
metric keys are invalidated when the webhook dispatcher's poll loop sees new
pipeline events (`src/serving/api/main.py`). That event-driven invalidation —
not the cache TTL — is what bounds staleness, and this benchmark measures it
against the alternatives:

- ``event_driven``   production defaults: cache TTL 30 s, dispatcher poll 2 s.
- ``fast_poll``      same, with the dispatcher poll interval tuned to 0.25 s.
- ``ttl_only``       event-driven invalidation disabled; a plain TTL cache
                     (what "BI on a replica" with a cache would give you).
                     Measured at a shortened TTL so the run stays tractable;
                     staleness scales linearly with TTL (uniform in [0, TTL]).
- ``no_cache``       cache off entirely; every read hits the store, so the
                     measured delay is bounded by this script's poll
                     granularity. Floor / sanity reference.

Methodology notes:

- The API runs in-process (uvicorn in a thread, real localhost TCP socket).
  DuckDB allows only one writer process, so event writes must come from the
  process that owns the database — exactly like the production layout, where
  the stream processor and the serving store share a writer.
- The cache is the production ``QueryCache`` class backed by ``fakeredis``
  (TTL and key semantics honored in-process). Network RTT to a real Redis
  (sub-millisecond on localhost) is excluded; it is negligible against the
  seconds-scale poll/TTL effects being measured.
- Each iteration sleeps a uniformly random delay before injecting the event
  so that injections sample the dispatcher-poll/TTL phase uniformly.

Usage:
    python scripts/benchmark_freshness.py
    python scripts/benchmark_freshness.py --iterations 50 --poll-interval-ms 20
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import random
import socket
import statistics
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "docs" / "freshness-benchmark.md"
RESULTS_PATH = PROJECT_ROOT / ".artifacts" / "freshness" / "current.json"

PRODUCTION_TTL_SECONDS = 30
PRODUCTION_POLL_SECONDS = 2.0
FAST_POLL_SECONDS = 0.25
REFLECT_EPSILON = 0.005
# The metric cache is tenant-scoped: with config/tenants.yaml present an
# unauthenticated request resolves no tenant and bypasses the cache entirely
# (agent_query._tenant_context_required). The benchmark therefore reads as an
# authenticated tenant — the production consumer shape.
API_KEY = "freshness-benchmark-key"  # noqa: S105 - throwaway key for the local run

ArmResult = dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure event-to-metric freshness and write docs/freshness-benchmark.md.",
    )
    parser.add_argument("--iterations", type=int, default=30, help="event_driven/fast_poll arms")
    parser.add_argument("--ttl-only-iterations", type=int, default=12)
    parser.add_argument("--no-cache-iterations", type=int, default=10)
    parser.add_argument("--metric", default="revenue")
    parser.add_argument("--window", default="24h")
    parser.add_argument("--poll-interval-ms", type=int, default=25)
    parser.add_argument(
        "--ttl-only-ttl-seconds",
        type=int,
        default=5,
        help="Shortened TTL for the ttl_only arm (staleness scales linearly with TTL)",
    )
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--burst", type=int, default=500, help="seed events before the run")
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    parser.add_argument("--results-json", default=str(RESULTS_PATH))
    parser.add_argument("--seed", type=int, default=20260606, help="jitter RNG seed")
    return parser.parse_args()


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile; q in [0, 100]."""
    if not values:
        raise ValueError("percentile() of empty list")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(1, round(q / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def summarize(samples_ms: list[float]) -> dict[str, float]:
    return {
        "p50_ms": percentile(samples_ms, 50),
        "p95_ms": percentile(samples_ms, 95),
        "max_ms": max(samples_ms),
        "mean_ms": statistics.fmean(samples_ms),
    }


def is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def resolve_port(requested_port: int) -> int:
    if is_port_available(requested_port):
        return requested_port
    if requested_port != 8001:
        raise RuntimeError(f"Port {requested_port} is already in use.")
    for candidate in range(8002, 8021):
        if is_port_available(candidate):
            return candidate
    raise RuntimeError("Could not find a free port in the 8001-8020 range.")


def read_metric(port: int, metric: str, window: str) -> float:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "GET",
            f"/v1/metrics/{metric}?window={window}",
            headers={"X-API-Key": API_KEY},
        )
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"GET /v1/metrics/{metric} -> {response.status}: {body[:200]!r}")
        payload = json.loads(body)
        value = payload["value"]
        return float(value) if value is not None else 0.0
    finally:
        connection.close()


def build_order_event(amount: Decimal, sequence: int) -> dict:
    """A schema- and semantics-valid order.created event with a controlled total."""
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
        source="freshness-benchmark",
        # Schema pattern: ^ORD-\d{8}-\d{4,}$. The 9-prefixed sequence keeps
        # benchmark orders clear of the seed generator's 4-digit ids.
        order_id=f"ORD-{datetime.now(UTC):%Y%m%d}-9{sequence:05d}",
        user_id=f"USR-{random.randint(10000, 99999)}",  # noqa: S311 - load shape, not crypto
        status=OrderStatus.PENDING,
        items=[
            OrderItem(product_id="PROD-001", quantity=1, unit_price=amount),
        ],
        total_amount=amount,
        currency=Currency.USD,
    )
    return json.loads(event.model_dump_json())


def measure_iteration(
    *,
    conn: Any,
    port: int,
    metric: str,
    window: str,
    amount: Decimal,
    sequence: int,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> float | None:
    """One event -> reflected-in-metric measurement. Returns ms, or None on timeout."""
    from src.processing.local_pipeline import _process_event

    baseline = read_metric(port, metric, window)
    event = build_order_event(amount, sequence)
    target = baseline + float(amount) - REFLECT_EPSILON

    started = time.perf_counter()
    success, reason = _process_event(conn, event)
    if not success:
        raise RuntimeError(f"pipeline rejected the benchmark event: {reason}")

    deadline = started + timeout_seconds
    while time.perf_counter() < deadline:
        value = read_metric(port, metric, window)
        if value >= target:
            return (time.perf_counter() - started) * 1000
        time.sleep(poll_interval_seconds)
    return None


def run_arm(
    *,
    name: str,
    iterations: int,
    conn: Any,
    port: int,
    metric: str,
    window: str,
    poll_interval_seconds: float,
    timeout_seconds: float,
    jitter_range: tuple[float, float],
    sequence_offset: int,
) -> ArmResult:
    samples_ms: list[float] = []
    timeouts = 0
    # Prime the cache so iteration 1 starts from the same steady state as the rest.
    read_metric(port, metric, window)
    for i in range(iterations):
        time.sleep(random.uniform(*jitter_range))  # noqa: S311 - phase sampling, not crypto
        amount = Decimal(f"{700 + i}.37")
        elapsed_ms = measure_iteration(
            conn=conn,
            port=port,
            metric=metric,
            window=window,
            amount=amount,
            sequence=sequence_offset + i,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
        )
        if elapsed_ms is None:
            timeouts += 1
            print(f"[{name}] iteration {i + 1}/{iterations}: TIMEOUT", flush=True)
            continue
        samples_ms.append(elapsed_ms)
        print(f"[{name}] iteration {i + 1}/{iterations}: {elapsed_ms:.0f} ms", flush=True)
    result: ArmResult = {
        "arm": name,
        "iterations": iterations,
        "timeouts": timeouts,
        "samples_ms": [round(value, 1) for value in samples_ms],
    }
    if samples_ms:
        result.update(summarize(samples_ms))
    return result


def format_ms(value: float) -> str:
    if value >= 1000:
        return f"{value / 1000:.2f} s"
    return f"{value:.0f} ms"


def build_report(
    *,
    generated_at: str,
    system_info: dict[str, str],
    metric: str,
    window: str,
    poll_interval_ms: int,
    ttl_only_ttl_seconds: int,
    arms: list[ArmResult],
) -> str:
    by_name = {arm["arm"]: arm for arm in arms}
    lines = [
        "# Event-to-Metric Freshness Benchmark",
        "",
        "> Generated by `python scripts/benchmark_freshness.py`. Re-running overwrites",
        "> this file. Machine-readable results: `.artifacts/freshness/current.json`.",
        "",
        f"Generated: `{generated_at}`",
        "",
        "## What is measured",
        "",
        "The end-to-end delay between an event entering the pipeline (schema",
        "validation -> semantic validation -> enrichment -> store write, via",
        "`local_pipeline._process_event` — the production demo-pipeline code path)",
        f"and `GET /v1/metrics/{metric}?window={window}` reflecting that event in its",
        "value over real localhost HTTP.",
        "",
        "Metric reads are authenticated (tenant-scoped cache path — unauthenticated",
        "requests bypass the metric cache when multi-tenancy is configured) and",
        "served through the production `QueryCache` (Redis semantics via in-process",
        "`fakeredis`; localhost RTT to a real Redis is sub-millisecond and",
        "excluded). Cache invalidation is driven by the webhook dispatcher poll",
        "loop seeing new pipeline events — the same wiring as",
        "`src/serving/api/main.py` production defaults.",
        "",
        "## System Under Test",
        "",
        f"- OS: `{system_info['os']}`",
        f"- CPU: `{system_info['cpu']}` ({system_info['cpu_count']} logical cores)",
        f"- Python: `{system_info['python']}`",
        f"- Reader poll granularity: `{poll_interval_ms} ms`",
        "",
        "## Results",
        "",
        "| Arm | Cache | Invalidation | Iterations | p50 | p95 | max |",
        "|-----|-------|--------------|------------|-----|-----|-----|",
    ]

    arm_rows = [
        (
            "event_driven",
            f"TTL {PRODUCTION_TTL_SECONDS} s",
            f"event-driven, {PRODUCTION_POLL_SECONDS:.0f} s poll (production default)",
        ),
        (
            "fast_poll",
            f"TTL {PRODUCTION_TTL_SECONDS} s",
            f"event-driven, {FAST_POLL_SECONDS:.2f} s poll (tuned)",
        ),
        (
            "ttl_only",
            f"TTL {ttl_only_ttl_seconds} s (shortened)",
            "none — TTL expiry only",
        ),
        (
            "no_cache",
            "off",
            "n/a — every read hits the store",
        ),
    ]
    for arm_name, cache_text, invalidation_text in arm_rows:
        arm = by_name.get(arm_name)
        if arm is None:
            continue
        if arm.get("samples_ms"):
            p50 = format_ms(arm["p50_ms"])
            p95 = format_ms(arm["p95_ms"])
            peak = format_ms(arm["max_ms"])
        else:
            p50 = p95 = peak = "n/a"
        timeouts_suffix = f" ({arm['timeouts']} timeouts)" if arm["timeouts"] else ""
        lines.append(
            f"| {arm_name} | {cache_text} | {invalidation_text} "
            f"| {arm['iterations']}{timeouts_suffix} | {p50} | {p95} | {peak} |"
        )

    event_driven = by_name.get("event_driven", {})
    ttl_only = by_name.get("ttl_only", {})
    lines += [
        "",
        "## Reading the numbers",
        "",
        (
            "- `event_driven` is the production configuration: staleness is bounded "
            f"by the {PRODUCTION_POLL_SECONDS:.0f} s dispatcher poll, not the "
            f"{PRODUCTION_TTL_SECONDS} s cache TTL."
        ),
    ]
    if event_driven.get("samples_ms") and ttl_only.get("samples_ms"):
        scaled_p50_ms = ttl_only["p50_ms"] * PRODUCTION_TTL_SECONDS / ttl_only_ttl_seconds
        lines.append(
            f"- A TTL-only cache at the production TTL ({PRODUCTION_TTL_SECONDS} s) "
            f"would sit at ~U(0, TTL) staleness — p50 ≈ {PRODUCTION_TTL_SECONDS / 2:.0f} s "
            f"(linear scaling of the measured ttl_only arm: "
            f"{format_ms(ttl_only['p50_ms'])} at TTL {ttl_only_ttl_seconds} s ⇒ "
            f"≈ {format_ms(scaled_p50_ms)} at TTL {PRODUCTION_TTL_SECONDS} s). "
            f"Event-driven invalidation measured "
            f"{format_ms(event_driven['p50_ms'])} p50 / {format_ms(event_driven['p95_ms'])} p95 "
            "on the same pipeline."
        )
    lines += [
        (
            "- `fast_poll` shows the same wiring with the dispatcher poll tuned to "
            f"{FAST_POLL_SECONDS:.2f} s — freshness is a configuration knob, not an "
            "architectural ceiling."
        ),
        (
            "- `no_cache` is the floor: with the cache off every read hits the store "
            "directly, so the measured delay collapses to this script's "
            f"{poll_interval_ms} ms read granularity plus one query."
        ),
        (
            "- Caveat (found by this benchmark): the dispatcher only scans for new "
            "events for tenants that have at least one **active webhook** — with "
            "zero webhooks registered the metric cache is never invalidated and "
            "cached reads degrade to pure TTL staleness. The benchmark registers a "
            "sentinel webhook whose filter matches nothing to enable the scan "
            "without generating deliveries."
        ),
        "",
        "## Reproduce",
        "",
        "```bash",
        'pip install -e ".[load]"',
        "python scripts/benchmark_freshness.py",
        "```",
        "",
        "Each iteration: read the metric, inject one schema-valid `order.created`",
        "event with a unique total through the pipeline, then poll the metric every",
        f"{poll_interval_ms} ms until the value reflects the new order; the elapsed",
        "time is one freshness sample. Iterations sleep a uniformly random delay",
        "before injecting so samples cover the poll/TTL phase uniformly.",
    ]
    return "\n".join(lines) + "\n"


def collect_system_info() -> dict[str, str]:
    import platform

    return {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine() or "unknown",
        "cpu_count": str(os.cpu_count() or 0),
        "python": platform.python_version(),
    }


def register_sentinel_webhook(port: int) -> None:
    """Register one active webhook with a filter no event matches.

    The dispatcher's poll loop only scans pipeline_events for tenants that
    have at least one active webhook (`dispatch_new_events` iterates
    webhooks_by_tenant) — with zero webhooks registered, new events are never
    seen and the metric cache is never invalidated, leaving reads on pure
    TTL staleness. A sentinel webhook whose event_types filter matches
    nothing turns the scan on without producing any deliveries.
    """
    body = json.dumps(
        {
            "url": "http://127.0.0.1:9/freshness-sentinel",
            "filters": {"event_types": ["freshness.benchmark.nonmatch"]},
        }
    )
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "POST",
            "/v1/webhooks",
            body=body,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = response.read()
        if response.status != 201:
            raise RuntimeError(f"POST /v1/webhooks -> {response.status}: {payload[:200]!r}")
    finally:
        connection.close()


def wait_for_api(port: int, timeout_seconds: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request("GET", "/v1/catalog", headers={"X-API-Key": API_KEY})
            response = connection.getresponse()
            response.read()
            connection.close()
            if response.status == 200:
                return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for the in-process API on port {port}.")


def main() -> int:
    args = parse_args()
    random.seed(args.seed)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    system_info = collect_system_info()
    report_path = Path(args.report_path)
    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path
    results_path = Path(args.results_json)
    if not results_path.is_absolute():
        results_path = PROJECT_ROOT / results_path

    with tempfile.TemporaryDirectory(prefix="agentflow-freshness-") as temp_dir:
        temp_path = Path(temp_dir)
        db_path = temp_path / "freshness.duckdb"

        os.environ["DUCKDB_PATH"] = str(db_path)
        # Authenticated tenant reads (see API_KEY note above) with the rate
        # limiter opened up: the reflection poll alone exceeds the default
        # 120 rpm.
        os.environ["AGENTFLOW_API_KEYS"] = f"{API_KEY}:freshness-benchmark"
        os.environ["AGENTFLOW_API_KEYS_FILE"] = ""
        os.environ["AGENTFLOW_ADMIN_KEY"] = ""
        os.environ["AGENTFLOW_RATE_LIMIT_RPM"] = "1000000"
        os.environ["AGENTFLOW_USAGE_DB_PATH"] = str(temp_path / "freshness_api_usage.duckdb")
        os.environ["AGENTFLOW_WEBHOOKS_FILE"] = str(temp_path / "webhooks.yaml")
        # No REDIS_URL: the auth manager then disables its Redis rate limiter
        # outright (manager.py resolved_redis_url is None) instead of probing a
        # dead server on every request, and the lifespan query cache degrades
        # to no-cache until the benchmark swaps in the fakeredis-backed one.
        os.environ.pop("REDIS_URL", None)

        # Import after the environment is pinned. The API and the event writer
        # must share one process: DuckDB is single-writer-process by design.
        import duckdb
        import fakeredis.aioredis
        import uvicorn

        from src.processing import local_pipeline
        from src.serving.api.main import app
        from src.serving.cache import QueryCache

        print(f"[seed] local pipeline burst {args.burst} -> {db_path}", flush=True)
        local_pipeline.run(burst=args.burst)

        port = resolve_port(args.port)
        config = uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        try:
            wait_for_api(port)
            register_sentinel_webhook(port)
            print(f"[api] ready on 127.0.0.1:{port}", flush=True)

            conn = duckdb.connect(str(db_path))
            dispatcher = app.state.webhook_dispatcher
            lifespan_cache = app.state.query_cache
            app.state.cache_ttl_seconds = PRODUCTION_TTL_SECONDS

            arms: list[ArmResult] = []
            poll_interval_seconds = args.poll_interval_ms / 1000

            # --- arm 1: production defaults -----------------------------------
            app.state.query_cache = QueryCache(redis_client=fakeredis.aioredis.FakeRedis())
            dispatcher.poll_interval_seconds = PRODUCTION_POLL_SECONDS
            arms.append(
                run_arm(
                    name="event_driven",
                    iterations=args.iterations,
                    conn=conn,
                    port=port,
                    metric=args.metric,
                    window=args.window,
                    poll_interval_seconds=poll_interval_seconds,
                    timeout_seconds=args.timeout_seconds,
                    jitter_range=(0.3, 0.3 + PRODUCTION_POLL_SECONDS),
                    sequence_offset=0,
                )
            )

            # --- arm 2: tuned dispatcher poll ----------------------------------
            app.state.query_cache = QueryCache(redis_client=fakeredis.aioredis.FakeRedis())
            dispatcher.poll_interval_seconds = FAST_POLL_SECONDS
            # The dispatcher picks the new interval up after finishing the sleep
            # it is already in; let one production-length tick drain first.
            time.sleep(PRODUCTION_POLL_SECONDS + 0.5)
            arms.append(
                run_arm(
                    name="fast_poll",
                    iterations=args.iterations,
                    conn=conn,
                    port=port,
                    metric=args.metric,
                    window=args.window,
                    poll_interval_seconds=poll_interval_seconds,
                    timeout_seconds=args.timeout_seconds,
                    jitter_range=(0.1, 0.1 + FAST_POLL_SECONDS),
                    sequence_offset=1000,
                )
            )
            dispatcher.poll_interval_seconds = PRODUCTION_POLL_SECONDS

            # --- arm 3: TTL-only (event-driven invalidation off) ---------------
            ttl_cache = QueryCache(redis_client=fakeredis.aioredis.FakeRedis())

            async def _invalidate_noop() -> None:
                return None

            ttl_cache.invalidate_metrics = _invalidate_noop  # type: ignore[method-assign]
            app.state.query_cache = ttl_cache
            app.state.cache_ttl_seconds = args.ttl_only_ttl_seconds
            arms.append(
                run_arm(
                    name="ttl_only",
                    iterations=args.ttl_only_iterations,
                    conn=conn,
                    port=port,
                    metric=args.metric,
                    window=args.window,
                    poll_interval_seconds=poll_interval_seconds,
                    timeout_seconds=args.timeout_seconds,
                    jitter_range=(0.5, 0.5 + args.ttl_only_ttl_seconds),
                    sequence_offset=2000,
                )
            )
            app.state.cache_ttl_seconds = PRODUCTION_TTL_SECONDS

            # --- arm 4: no cache ------------------------------------------------
            app.state.query_cache = None
            arms.append(
                run_arm(
                    name="no_cache",
                    iterations=args.no_cache_iterations,
                    conn=conn,
                    port=port,
                    metric=args.metric,
                    window=args.window,
                    poll_interval_seconds=poll_interval_seconds,
                    timeout_seconds=args.timeout_seconds,
                    jitter_range=(0.1, 0.5),
                    sequence_offset=3000,
                )
            )

            # Restore the lifespan-owned cache so shutdown closes what it opened.
            app.state.query_cache = lifespan_cache
            conn.close()
        finally:
            server.should_exit = True
            server_thread.join(timeout=15)

    report = build_report(
        generated_at=generated_at,
        system_info=system_info,
        metric=args.metric,
        window=args.window,
        poll_interval_ms=args.poll_interval_ms,
        ttl_only_ttl_seconds=args.ttl_only_ttl_seconds,
        arms=arms,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(report)

    results_payload = {
        "generated_at": generated_at,
        "source": "scripts/benchmark_freshness.py",
        "metric": args.metric,
        "window": args.window,
        "poll_interval_ms": args.poll_interval_ms,
        "production_ttl_seconds": PRODUCTION_TTL_SECONDS,
        "production_poll_seconds": PRODUCTION_POLL_SECONDS,
        "fast_poll_seconds": FAST_POLL_SECONDS,
        "ttl_only_ttl_seconds": args.ttl_only_ttl_seconds,
        "system": system_info,
        "arms": arms,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(results_payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote freshness report to {report_path}")
    print(f"Wrote freshness results to {results_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
