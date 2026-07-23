"""Wait for an HTTP endpoint to become ready within a bounded deadline."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


class HttpResponse(Protocol):
    status: int

    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *args: object) -> None: ...


Opener = Callable[[str, float], HttpResponse]


def wait_for_http(
    *,
    url: str,
    timeout: float,
    interval: float,
    label: str,
    opener: Opener = urlopen,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Return whether *url* responds with a 2xx or 3xx status before timeout."""

    deadline = monotonic() + timeout
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            print(f"{label} did not become ready within {timeout:g}s: {url}")
            return False
        request_timeout = min(5.0, remaining)
        try:
            with opener(url, request_timeout) as response:
                if 200 <= response.status < 400:
                    print(f"{label} is ready: {url}")
                    return True
        except (HTTPError, URLError, TimeoutError, OSError):
            pass

        now = monotonic()
        if now >= deadline:
            print(f"{label} did not become ready within {timeout:g}s: {url}")
            return False
        sleep(min(interval, deadline - now))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--label", default="service")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ready = wait_for_http(
        url=args.url,
        timeout=args.timeout,
        interval=args.interval,
        label=args.label,
    )
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
