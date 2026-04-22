"""Client-side benchmark harness for the /v1/entity endpoint.

Complements `scripts/run_benchmark.py`, which exercises the whole surface
via Locust. This script is scoped to the entity path and is the cheapest
way to verify whether a change moves p50/p95/p99. Pair it with `py-spy`
attached to the running uvicorn process to get a server-side flamegraph
(see `docs/perf/README.md`).

Example:

    # terminal 1: start the API
    make demo

    # terminal 2: run the harness
    python scripts/profile_entity.py \\
        --host http://localhost:8000 \\
        --entity-type order \\
        --entity-id ORD-20260401-7829 \\
        --iterations 2000 \\
        --concurrency 16 \\
        --api-key af-prod-agent-ops-def456

The output is a single JSON blob with aggregate latency stats; feed it
through `jq` or compare by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass


@dataclass
class RequestResult:
    status_code: int
    elapsed_ms: float


async def _run_single(client, url: str, headers: dict[str, str]) -> RequestResult:
    start = time.perf_counter()
    response = await client.get(url, headers=headers)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return RequestResult(status_code=response.status_code, elapsed_ms=elapsed_ms)


async def _worker(client, url, headers, queue: asyncio.Queue, results: list[RequestResult]) -> None:
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        try:
            results.append(await _run_single(client, url, headers))
        except Exception as exc:  # noqa: BLE001 - bubble up summary after collection
            results.append(RequestResult(status_code=-1, elapsed_ms=0.0))
            print(f"request failed: {exc}", file=sys.stderr)
        finally:
            queue.task_done()


async def run(args: argparse.Namespace) -> dict[str, object]:
    try:
        import httpx
    except ImportError as exc:
        raise SystemExit("httpx is required; it ships as a core dependency.") from exc

    url = f"{args.host.rstrip('/')}/v1/entity/{args.entity_type}/{args.entity_id}"
    headers: dict[str, str] = {}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    timeout = httpx.Timeout(args.request_timeout)
    limits = httpx.Limits(
        max_connections=args.concurrency * 2,
        max_keepalive_connections=args.concurrency,
    )

    async with httpx.AsyncClient(timeout=timeout, limits=limits, http2=False) as client:
        # Warmup
        for _ in range(max(args.warmup, 0)):
            await _run_single(client, url, headers)

        queue: asyncio.Queue = asyncio.Queue()
        for _ in range(args.iterations):
            queue.put_nowait(1)
        for _ in range(args.concurrency):
            queue.put_nowait(None)

        results: list[RequestResult] = []
        workers = [
            asyncio.create_task(_worker(client, url, headers, queue, results))
            for _ in range(args.concurrency)
        ]

        wall_start = time.perf_counter()
        await queue.join()
        for worker in workers:
            worker.cancel()
        elapsed_wall = time.perf_counter() - wall_start

    successes = [r.elapsed_ms for r in results if 200 <= r.status_code < 300]
    non_2xx = [r for r in results if not (200 <= r.status_code < 300)]

    if not successes:
        raise SystemExit(
            f"No successful responses from {url}. "
            f"Received {len(non_2xx)} non-2xx responses (first status: "
            f"{non_2xx[0].status_code if non_2xx else 'n/a'})."
        )

    successes.sort()

    def percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        idx = max(0, min(len(values) - 1, int(round((pct / 100) * len(values))) - 1))
        return values[idx]

    return {
        "url": url,
        "iterations": args.iterations,
        "concurrency": args.concurrency,
        "warmup": args.warmup,
        "wall_seconds": round(elapsed_wall, 3),
        "success_count": len(successes),
        "failure_count": len(non_2xx),
        "throughput_rps": round(len(successes) / elapsed_wall, 2) if elapsed_wall > 0 else 0.0,
        "p50_ms": round(percentile(successes, 50), 2),
        "p95_ms": round(percentile(successes, 95), 2),
        "p99_ms": round(percentile(successes, 99), 2),
        "max_ms": round(successes[-1], 2),
        "mean_ms": round(statistics.fmean(successes), 2),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="http://localhost:8000")
    parser.add_argument("--entity-type", required=True)
    parser.add_argument("--entity-id", required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--request-timeout", type=float, default=10.0)
    parser.add_argument("--api-key", default=None, help="Value to send as X-API-Key header.")
    parser.add_argument("--output", default=None, help="Optional path to write JSON summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = asyncio.run(run(args))
    text = json.dumps(summary, indent=2)
    print(text)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
