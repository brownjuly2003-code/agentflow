"""PostgreSQL control-plane store — the scale profile (ADR 0010 slice 5).

All six state classes from the ADR's inventory live in ordinary PostgreSQL
tables, and the claim semantics the port only satisfies degenerately on the
embedded adapter become real here:

- ``enqueue_webhook_delivery`` wins by ``INSERT .. ON CONFLICT DO NOTHING``
  rowcount — exactly one replica inline-delivers a fresh enqueue. The winner
  also stamps ``lease_expires_at`` on insert so a concurrent redrive claim
  cannot steal the row mid-inline (same lease window as ``claim_due_*``;
  outcome or lease expiry releases it for redrive).
- ``claim_due_webhook_deliveries`` / ``claim_due_outbox_entries`` take rows
  with ``FOR UPDATE SKIP LOCKED`` and stamp a lease
  (``lease_expires_at``): N replicas work-steal without leader election, and
  a crashed owner's rows become due again when the lease runs out.
- ``claim_alert_tick`` single-flights each alert rule's evaluation via a
  lease column on the rule row; ``complete_alert_tick`` releases the claim
  and persists that rule's advanced runtime state in the same transaction.
- ``mark_outbox_sent`` / ``schedule_outbox_retry`` / ``enqueue_outbox_replay``
  keep the outbox↔dead-letter flip in one transaction (invariant 8) — here it
  is simply *a* transaction, no manual BEGIN/ROLLBACK choreography.

Design constraints inherited from the embedded adapter, kept deliberately:

- **Connections come from one bounded pool** (audit P1-1). Every method
  checks a connection out of a ``psycopg_pool.ConnectionPool`` with a fixed
  ``max_size`` and a checkout timeout, so the store's PostgreSQL footprint
  is capped per process no matter the request rate — the previous
  connection-per-call shape meant a usage batch of 256 rows could open 256
  connections. Pool pressure is observable (``agentflow_pg_pool_*`` gauges).
- **Every method is one transaction** — ``pool.connection()`` keeps the
  ``psycopg.connect()`` context-manager semantics: commit on clean exit,
  rollback on any exception, then the connection returns to the pool. This
  is what makes the invariant-8 methods atomic without adapter-specific
  ceremony.
- **Schema changes are versioned migrations** (audit P1-1), not a pile of
  ``IF NOT EXISTS`` that cannot express an ALTER. ``_MIGRATIONS`` is a
  monotonic list; ``control_plane_schema_version`` records what ran and
  when; concurrent replicas serialize on a transaction-scoped advisory
  lock. Migration 1 is the pre-versioning baseline, so a store provisioned
  before this table existed upgrades by running a no-op DDL pass and
  getting stamped — no data is touched.
- **JSON payloads are stored as TEXT** holding the caller's JSON string,
  not ``jsonb`` — the port contract says payloads come back "as stored
  (string or dict), the caller decodes", and the embedded adapter returns
  strings; keeping strings here means callers see one shape on both
  profiles.
- **Schema DDL runs once per store instance** (first use), never lazily
  inside the write methods — the same fault-injection rule the port
  docstring pins for the outbox tables: a test that drops a table
  mid-scenario to simulate a failed transaction must see the failure, not a
  silently recreated table.

``psycopg`` (v3) and ``psycopg_pool`` are optional dependencies imported at
module load with a ``None`` fallback, exactly like ``redis`` in the rate
limiter: importing this module is safe without them, constructing the store
is not (install the ``postgres`` extra: ``pip install .[postgres]``).

Audit F-08 split the former single-module adapter into bounded capability
repositories — ``postgres_webhook``, ``postgres_alert``,
``postgres_outbox_replay``, ``postgres_usage_audit`` over the shared
``postgres_base`` pool/schema plumbing, with the DDL and migration ledger in
``postgres_schema`` — method bodies moved verbatim. This module stays the
assembly point and the only public import surface; ``__init__`` stays here
so the constructor's optional-dependency guards keep reading
``postgres.psycopg`` / ``postgres.psycopg_pool``, the seam tests stub.
"""

from __future__ import annotations

import os
import threading

import structlog

from .postgres_alert import PostgresAlertRepository
from .postgres_base import (
    DEFAULT_CLAIM_LEASE_SECONDS,
    DEFAULT_POOL_MAX_SIZE,
    DEFAULT_POOL_MIN_SIZE,
    DEFAULT_POOL_TIMEOUT_SECONDS,
)
from .postgres_outbox_replay import PostgresOutboxReplayRepository
from .postgres_schema import _MIGRATIONS, _SCHEMA_STATEMENTS
from .postgres_usage_audit import PostgresUsageAuditRepository
from .postgres_webhook import PostgresWebhookRepository
from .store import CONTROL_PLANE_PG_DSN_ENV

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

try:
    import psycopg_pool
except ImportError:  # pragma: no cover
    psycopg_pool = None  # type: ignore[assignment]

logger = structlog.get_logger()

__all__ = [
    "DEFAULT_CLAIM_LEASE_SECONDS",
    "DEFAULT_POOL_MAX_SIZE",
    "DEFAULT_POOL_MIN_SIZE",
    "DEFAULT_POOL_TIMEOUT_SECONDS",
    "PostgresAlertRepository",
    "PostgresControlPlaneStore",
    "PostgresOutboxReplayRepository",
    "PostgresUsageAuditRepository",
    "PostgresWebhookRepository",
    "_MIGRATIONS",
    "_SCHEMA_STATEMENTS",
    "resolve_postgres_store_from_env",
]


class PostgresControlPlaneStore(
    PostgresWebhookRepository,
    PostgresAlertRepository,
    PostgresOutboxReplayRepository,
    PostgresUsageAuditRepository,
):
    """Control-plane state in PostgreSQL behind the ``ControlPlaneStore``
    port. See the module docstring for the concurrency and storage-shape
    contract."""

    def __init__(
        self,
        dsn: str,
        *,
        claim_lease_seconds: float = DEFAULT_CLAIM_LEASE_SECONDS,
        pool_min_size: int = DEFAULT_POOL_MIN_SIZE,
        pool_max_size: int = DEFAULT_POOL_MAX_SIZE,
        pool_timeout_seconds: float = DEFAULT_POOL_TIMEOUT_SECONDS,
    ) -> None:
        if psycopg is None:  # pragma: no cover - exercised via monkeypatch
            raise RuntimeError(
                "AGENTFLOW_CONTROLPLANE_STORE=postgres requires the optional "
                "'psycopg' dependency (pip install psycopg[binary,pool])."
            )
        if psycopg_pool is None:  # pragma: no cover - exercised via monkeypatch
            raise RuntimeError(
                "AGENTFLOW_CONTROLPLANE_STORE=postgres requires the optional "
                "'psycopg_pool' dependency (pip install psycopg[binary,pool])."
            )
        if not dsn:
            raise ValueError("PostgresControlPlaneStore requires a non-empty DSN.")
        if not 1 <= pool_min_size <= pool_max_size:
            raise ValueError(
                "Pool sizes must satisfy 1 <= min <= max, got "
                f"min={pool_min_size} max={pool_max_size}."
            )
        self._dsn = dsn
        self._claim_lease_seconds = float(claim_lease_seconds)
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        # No I/O yet (open=False): constructing a store must not require a
        # reachable server — connectivity failures belong to the first call,
        # where the bounded retries and /health/ready can see them.
        self._pool = psycopg_pool.ConnectionPool(
            dsn,
            min_size=pool_min_size,
            max_size=pool_max_size,
            timeout=float(pool_timeout_seconds),
            open=False,
            name="agentflow-control-plane",
        )
        self._pool_opened = False


def resolve_postgres_store_from_env() -> PostgresControlPlaneStore:
    """Build the scale-profile store from the environment (the selection
    seam ``get_control_plane_store`` calls for ``postgres``). Fails loudly on
    a missing DSN — silently falling back to embedded would re-open the
    split-brain the render gate exists to prevent."""
    dsn = (os.getenv(CONTROL_PLANE_PG_DSN_ENV) or "").strip()
    if not dsn:
        raise ValueError(
            "AGENTFLOW_CONTROLPLANE_STORE=postgres requires "
            f"{CONTROL_PLANE_PG_DSN_ENV} to hold a PostgreSQL DSN."
        )
    lease_env = (os.getenv("AGENTFLOW_CONTROLPLANE_LEASE_SECONDS") or "").strip()
    if lease_env:
        try:
            lease_seconds = float(lease_env)
        except ValueError:
            raise ValueError(
                "AGENTFLOW_CONTROLPLANE_LEASE_SECONDS must be a number of seconds, "
                f"got {lease_env!r}."
            ) from None
    else:
        lease_seconds = DEFAULT_CLAIM_LEASE_SECONDS

    def _int_env(name: str, default: int) -> int:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"{name} must be an integer, got {raw!r}.") from None

    def _float_env(name: str, default: float) -> float:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"{name} must be a number of seconds, got {raw!r}.") from None

    return PostgresControlPlaneStore(
        dsn,
        claim_lease_seconds=lease_seconds,
        pool_min_size=_int_env("AGENTFLOW_CONTROLPLANE_PG_POOL_MIN", DEFAULT_POOL_MIN_SIZE),
        pool_max_size=_int_env("AGENTFLOW_CONTROLPLANE_PG_POOL_MAX", DEFAULT_POOL_MAX_SIZE),
        pool_timeout_seconds=_float_env(
            "AGENTFLOW_CONTROLPLANE_PG_POOL_TIMEOUT_SECONDS", DEFAULT_POOL_TIMEOUT_SECONDS
        ),
    )
