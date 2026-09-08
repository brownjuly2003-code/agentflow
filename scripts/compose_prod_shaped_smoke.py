"""Smoke the production-shaped local compose stack through a real request.

The stack's only proof of life used to be the container healthcheck on
``/health/ready`` (audit F-09). That answers before authentication is wired and
says nothing about whether a caller can actually read data, so the stack could
report healthy while every ``/v1`` route fail-closed with 503 for want of an
auth contract. This asserts the contract instead:

* ``/health/ready`` answers 2xx -- the serving store is reachable;
* ``/v1/catalog`` without a key is refused with **401**, not 503. A 503 means
  the stack loaded no keys at all, which is the failure this smoke exists to
  catch: fail-closed, but for the wrong reason;
* ``/v1/catalog`` with the demo key answers 200.

It smokes a local demo stack with a published demo key, so nothing here is a
secret. Point it at anything else and it is still only a reachability check --
it is not, and must not be cited as, production acceptance evidence.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_API_KEY = "demo-key"


class HttpResponse(Protocol):
    status: int

    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *args: object) -> None: ...


Opener = Callable[[Request, float], HttpResponse]


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _require_http_url(base_url: str) -> str:
    """Return the base URL without a trailing slash, rejecting other schemes.

    urllib opens `file:` and custom schemes as readily as http, and this script
    takes its target from the command line.
    """
    base = base_url.rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError(f"base URL must be http:// or https://, got {base_url!r}")
    return base


def _status(
    opener: Opener,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float,
) -> int | str:
    """Return the HTTP status, or a string describing a transport failure.

    ``urlopen`` raises on 4xx/5xx, but a refusal *is* the expected answer for
    two of the three checks, so the status is recovered from the exception
    rather than treated as an error.
    """
    # noqa justified: every URL reaching here is built from a base string
    # _require_http_url has already restricted to http/https.
    request = Request(url, headers=dict(headers or {}))  # noqa: S310
    try:
        with opener(request, timeout) as response:
            return int(response.status)
    except HTTPError as exc:
        return int(exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        return f"no response: {exc}"


def run_smoke(
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str = DEFAULT_API_KEY,
    timeout: float = 10.0,
    opener: Opener | None = None,
) -> list[CheckResult]:
    # Resolved per call, not bound as a default: a default argument would
    # capture urlopen at import time and quietly ignore any substitute,
    # including the one the tests install.
    opener = urlopen if opener is None else opener
    base = _require_http_url(base_url)
    results: list[CheckResult] = []

    ready = _status(opener, f"{base}/health/ready", timeout=timeout)
    results.append(
        CheckResult(
            name="readiness",
            ok=isinstance(ready, int) and 200 <= ready < 300,
            detail=f"GET /health/ready -> {ready} (want 2xx)",
        )
    )

    anonymous = _status(opener, f"{base}/v1/catalog", timeout=timeout)
    if anonymous == 503:
        detail = (
            "GET /v1/catalog without a key -> 503. The stack has no API keys "
            "loaded, so every route is refused for the wrong reason: fix the "
            "auth contract in docker-compose.prod.yml, do not treat this as a "
            "passing fail-closed check."
        )
    else:
        detail = f"GET /v1/catalog without a key -> {anonymous} (want 401)"
    results.append(CheckResult(name="anonymous_refused", ok=anonymous == 401, detail=detail))

    authenticated = _status(
        opener,
        f"{base}/v1/catalog",
        headers={"X-API-Key": api_key},
        timeout=timeout,
    )
    results.append(
        CheckResult(
            name="authenticated_read",
            ok=authenticated == 200,
            detail=f"GET /v1/catalog with a key -> {authenticated} (want 200)",
        )
    )

    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help="published demo key of the prod-shaped local stack (DEMO_API_KEY)",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    if not args.api_key:
        parser.error("--api-key must not be empty")
    try:
        _require_http_url(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results = run_smoke(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    for result in results:
        print(f"[{'PASS' if result.ok else 'FAIL'}] {result.name}: {result.detail}")

    failed = [result for result in results if not result.ok]
    if failed:
        print(f"prod-shaped-local smoke FAILED ({len(failed)} of {len(results)} checks)")
        return 1
    print(f"prod-shaped-local smoke PASSED ({len(results)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
