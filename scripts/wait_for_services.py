"""Wait for the AgentFlow HTTP API to report healthy or degraded status."""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def wait(base_url: str, timeout: int, interval: float) -> None:
    deadline = time.monotonic() + timeout
    health_url = f"{base_url.rstrip('/')}/v1/health"
    last_error = "service did not answer"

    while time.monotonic() < deadline:
        try:
            response = httpx.get(health_url, timeout=15.0)
            if response.status_code == 200:
                payload = response.json()
                status = payload.get("status", "unknown")
                print(f"Services ready at {health_url} with status={status}")
                return
            last_error = f"unexpected status {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(interval)

    print(
        f"Timeout waiting for services at {health_url}: {last_error}",
        file=sys.stderr,
    )
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--interval", type=float, default=1.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    wait(args.url, args.timeout, args.interval)
