"""Enforce the query-analytics retention window (audit F-18).

`api_sessions` had no expiry: a row written on the first day of a deployment
was still there years later. `QueryAnalyticsPolicy.retention_days` states how
long analytics may be kept; this script is what makes the statement true, so
run it on a schedule (cron, a Kubernetes CronJob) against the same store the
API writes to.

    python scripts/prune_query_analytics.py                    # policy default
    python scripts/prune_query_analytics.py --retention-days 7
    python scripts/prune_query_analytics.py --dry-run
    python scripts/prune_query_analytics.py --erase-tenant acme   # erasure request

The store is resolved exactly the way the API resolves it -- embedded DuckDB
unless `AGENTFLOW_CONTROL_PLANE_STORE=postgres` -- so the prune cannot
silently clean a different database than the one being written to.

Retention applies to `api_sessions`, the per-request analytics table that can
carry question text or a fingerprint. `api_usage` holds tenant/key/endpoint
counters with no user content and is deliberately left alone: it is the record
of how much a tenant used, which is a billing and abuse-investigation surface
with a different lifetime.

`--erase-tenant` serves the other kind of deletion: a tenant asking for their
analytics to go now. That is erasure rather than retention, so it deletes every
`api_sessions` row for the tenant whatever its age, and never runs together
with a window.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # pragma: no cover - path-invoked script bootstrap
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentflow_runtime.serving.api.query_analytics_policy import (  # noqa: E402
    QueryAnalyticsPolicy,
    QueryAnalyticsPolicyError,
)
from agentflow_runtime.serving.control_plane import (  # noqa: E402
    EmbeddedControlPlaneStore,
    control_plane_store_kind,
)
from agentflow_runtime.serving.control_plane.capabilities import (  # noqa: E402
    UsageAuditRepository,
)


def resolve_store(env: dict[str, str] | None = None) -> UsageAuditRepository:
    """Return the control-plane store the API would write analytics to."""
    env = dict(os.environ) if env is None else env
    if control_plane_store_kind() == "embedded":
        # Same usage-db path AuthManager binds its own private store to, so
        # the prune reaches the file the analytics writes land in.
        usage_db_path = env.get("AGENTFLOW_USAGE_DB_PATH", "agentflow_api.duckdb")
        return EmbeddedControlPlaneStore(usage_db_path_provider=lambda: usage_db_path)
    # Imported here, not at module scope: psycopg is an optional dependency and
    # the embedded path must keep working without it (the `redis` pattern the
    # package docstring describes).
    from agentflow_runtime.serving.control_plane.postgres import resolve_postgres_store_from_env

    return resolve_postgres_store_from_env()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="override the policy's retention window (whole days, at least 1)",
    )
    parser.add_argument(
        "--erase-tenant",
        default=None,
        metavar="TENANT",
        help=(
            "delete every analytics row for one tenant regardless of age "
            "(an erasure request, not retention)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the store and window without deleting anything",
    )
    args = parser.parse_args(argv)
    if args.retention_days is not None and args.retention_days < 1:
        parser.error("--retention-days must be at least 1")
    if args.erase_tenant is not None:
        if not args.erase_tenant.strip():
            parser.error("--erase-tenant needs a tenant identifier")
        if args.retention_days is not None:
            # Refuse rather than pick one: an operator who passed both is
            # asking for two different deletions and should say which.
            parser.error("--erase-tenant and --retention-days are separate operations")
    return args


def main(
    argv: list[str] | None = None,
    store: UsageAuditRepository | None = None,
) -> int:
    args = parse_args(argv)
    if args.erase_tenant is not None:
        tenant = args.erase_tenant.strip()
        kind = control_plane_store_kind()
        if args.dry_run:
            print(
                f"dry run: would delete every api_sessions row for tenant "
                f"{tenant!r} from {kind} store"
            )
            return 0
        resolved = resolve_store() if store is None else store
        deleted = resolved.delete_tenant_api_sessions(tenant=tenant)
        print(f"erased {deleted} api_sessions rows for tenant {tenant!r} from {kind} store")
        return 0

    try:
        retention_days = (
            args.retention_days
            if args.retention_days is not None
            else QueryAnalyticsPolicy.from_env().retention_days
        )
    except QueryAnalyticsPolicyError as exc:
        print(f"query-analytics policy is unusable: {exc}")
        return 2

    kind = control_plane_store_kind()
    if args.dry_run:
        print(f"dry run: would delete api_sessions older than {retention_days}d from {kind} store")
        return 0

    resolved = resolve_store() if store is None else store
    deleted = resolved.prune_api_sessions(older_than_days=retention_days)
    print(f"pruned {deleted} api_sessions rows older than {retention_days}d from {kind} store")
    return 0


if __name__ == "__main__":
    sys.exit(main())
