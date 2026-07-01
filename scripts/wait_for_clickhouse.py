"""Block until the ClickHouse HTTP interface answers /ping (demo bring-up).

Cross-platform replacement for a shell retry loop: `make demo` starts the
ClickHouse container and must not run the pipeline (whose serving sink fails
loudly by design) before the server accepts connections.

Usage: python scripts/wait_for_clickhouse.py [--timeout SECONDS]
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request


def wait_for_clickhouse(base_url: str, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    ping_url = f"{base_url.rstrip('/')}/ping"
    while time.monotonic() < deadline:
        try:
            # scheme is fixed to http:// by the caller (main builds the URL)
            with urllib.request.urlopen(ping_url, timeout=3) as response:  # noqa: S310 # nosec B310 - fixed http scheme
                if response.read().decode("utf-8", errors="replace").strip() == "Ok.":
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1.0)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    host = os.getenv("CLICKHOUSE_HOST", "localhost")
    port = os.getenv("CLICKHOUSE_PORT", "8123")
    base_url = f"http://{host}:{port}"
    print(f"Waiting for ClickHouse at {base_url} ...", flush=True)
    if wait_for_clickhouse(base_url, args.timeout):
        print("ClickHouse is up.")
        return 0
    print(
        f"ClickHouse did not answer /ping within {args.timeout:.0f}s — "
        "is the container running? (docker compose up -d clickhouse)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
