"""Small authenticated client used by the analytics-retention CronJob."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

_ADMIN_KEY_ENV = "AGENTFLOW_ADMIN_KEY"


class AnalyticsRetentionClientError(RuntimeError):
    """The retention request could not be completed safely."""


def run_retention(
    *,
    url: str,
    retention_days: int | None = None,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    resolved_env = os.environ if env is None else env
    admin_key = resolved_env.get(_ADMIN_KEY_ENV, "").strip()
    if not admin_key:
        raise AnalyticsRetentionClientError(f"{_ADMIN_KEY_ENV} is required")
    if retention_days is not None and retention_days < 1:
        raise AnalyticsRetentionClientError("retention_days must be at least 1")

    payload: dict[str, int | bool] = {"dry_run": dry_run}
    if retention_days is not None:
        payload["retention_days"] = retention_days

    owns_client = client is None
    resolved_client = httpx.Client(timeout=30.0) if client is None else client
    try:
        try:
            response = resolved_client.post(
                url,
                headers={"X-Admin-Key": admin_key},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise AnalyticsRetentionClientError(f"request failed ({type(exc).__name__})") from None

        if response.is_error:
            raise AnalyticsRetentionClientError(f"HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError:
            raise AnalyticsRetentionClientError("response was not valid JSON") from None
        if not isinstance(result, dict):
            raise AnalyticsRetentionClientError("response JSON was not an object")
        return result
    finally:
        if owns_client:
            resolved_client.close()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prune stored query analytics through the API")
    parser.add_argument("--url", required=True)
    parser.add_argument("--retention-days", type=_positive_int)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_retention(
            url=args.url,
            retention_days=args.retention_days,
            dry_run=args.dry_run,
            env=env,
            client=client,
        )
    except AnalyticsRetentionClientError as exc:
        print(f"analytics retention failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
