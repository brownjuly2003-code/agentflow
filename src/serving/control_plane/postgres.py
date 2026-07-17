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
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import weakref
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily

from .store import (
    AUTO_RESOLVE_NOTE,
    CONTROL_PLANE_PG_DSN_ENV,
    ControlPlaneStore,
    OutboxEntry,
    TriageState,
    UsageRow,
    WebhookQueueRow,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

try:
    import psycopg_pool
except ImportError:  # pragma: no cover
    psycopg_pool = None  # type: ignore[assignment]

logger = structlog.get_logger()

# Errors worth a bounded retry: a broken/unavailable server connection
# (OperationalError) or an exhausted pool checkout (PoolTimeout). Everything
# else — integrity, syntax, programming errors — must surface immediately.
_TRANSIENT_ERRORS: tuple[type[Exception], ...] = tuple(
    error
    for error in (
        getattr(psycopg, "OperationalError", None),
        getattr(psycopg_pool, "PoolTimeout", None),
    )
    if error is not None
)

# How long a claimed webhook-queue / outbox row stays invisible to other
# claimants before it self-expires back to due. Long enough for a full
# delivery burst (3 HTTP attempts x timeout + backoff) per row across a
# claimed batch; short enough that a crashed pod's backlog resumes within
# minutes. Overridable per store via the constructor.
DEFAULT_CLAIM_LEASE_SECONDS = 300.0

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS webhook_delivery_queue (
        webhook_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        tenant TEXT,
        event_type TEXT,
        body TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TIMESTAMPTZ,
        last_status_code INTEGER,
        last_error TEXT,
        lease_expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (webhook_id, event_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS webhook_delivery_queue_due_idx
        ON webhook_delivery_queue (created_at) WHERE status = 'pending'
    """,
    """
    CREATE TABLE IF NOT EXISTS webhook_deliveries (
        delivery_id TEXT,
        webhook_id TEXT,
        event_id TEXT,
        event_type TEXT,
        attempt INTEGER,
        status_code INTEGER,
        success BOOLEAN,
        error TEXT,
        delivered_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS webhook_deliveries_webhook_idx
        ON webhook_deliveries (webhook_id, delivered_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS alert_history (
        delivery_id TEXT,
        alert_id TEXT,
        alert_name TEXT,
        metric TEXT,
        current_value DOUBLE PRECISION,
        previous_value DOUBLE PRECISION,
        change_pct DOUBLE PRECISION,
        threshold DOUBLE PRECISION,
        condition TEXT,
        metric_window TEXT,
        tenant TEXT,
        event_type TEXT,
        status_code INTEGER,
        success BOOLEAN,
        error TEXT,
        payload TEXT,
        triggered_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS alert_history_alert_idx
        ON alert_history (alert_id, triggered_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS webhook_registrations (
        id TEXT PRIMARY KEY,
        position INTEGER NOT NULL,
        record TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alert_rules (
        id TEXT PRIMARY KEY,
        position INTEGER NOT NULL,
        record TEXT NOT NULL,
        tick_lease_expires_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS outbox (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        topic TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        sent_at TIMESTAMPTZ,
        status TEXT DEFAULT 'pending',
        retry_count INTEGER DEFAULT 0,
        next_attempt_at TIMESTAMPTZ DEFAULT now(),
        last_error TEXT,
        lease_expires_at TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS outbox_due_idx
        ON outbox (created_at) WHERE status = 'pending'
    """,
    """
    CREATE TABLE IF NOT EXISTS dead_letter_events (
        event_id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        event_type TEXT,
        payload TEXT,
        failure_reason TEXT,
        failure_detail TEXT,
        received_at TIMESTAMPTZ,
        retry_count INTEGER DEFAULT 0,
        last_retried_at TIMESTAMPTZ,
        status TEXT DEFAULT 'failed'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ops_exception_triage (
        item_id TEXT PRIMARY KEY,
        tenant_id TEXT,
        source TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        first_seen_at TIMESTAMPTZ,
        last_seen_at TIMESTAMPTZ,
        resolved_at TIMESTAMPTZ,
        note TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_usage (
        tenant TEXT,
        key_name TEXT,
        endpoint TEXT,
        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
        key_id TEXT,
        key_slot TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS api_usage_ts_idx ON api_usage (ts)
    """,
    """
    CREATE TABLE IF NOT EXISTS api_sessions (
        request_id TEXT PRIMARY KEY,
        tenant TEXT,
        key_name TEXT,
        endpoint TEXT,
        method TEXT,
        status_code INTEGER,
        duration_ms DOUBLE PRECISION,
        cache_hit BOOLEAN,
        entity_type TEXT,
        metric_name TEXT,
        query_engine TEXT,
        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
        entity_id TEXT,
        query_text TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS api_sessions_ts_idx ON api_sessions (ts)
    """,
)

# --- versioned migrations (audit P1-1) ---------------------------------------
#
# The ledger table is created outside the migration list (it must exist to
# read the current version). Each migration is (version, description,
# statements); versions are dense and monotonic from 1 — enforced at import,
# because a gap or duplicate silently skips or repeats DDL. Migration 1 is
# the pre-versioning baseline: pure IF NOT EXISTS, so a store that predates
# the ledger upgrades by a no-op pass and gets stamped. Later migrations may
# use ALTER and rely on running exactly once.

_SCHEMA_VERSION_DDL = """
    CREATE TABLE IF NOT EXISTS control_plane_schema_version (
        version INTEGER PRIMARY KEY,
        description TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
"""

_MIGRATIONS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (1, "baseline: six control-plane state classes (ADR 0010 slice 5)", _SCHEMA_STATEMENTS),
)

if tuple(version for version, _, _ in _MIGRATIONS) != tuple(range(1, len(_MIGRATIONS) + 1)):
    raise RuntimeError(
        "_MIGRATIONS versions must be dense and monotonic starting at 1: "
        f"{[version for version, _, _ in _MIGRATIONS]}"
    )

# Transaction-scoped advisory lock serializing concurrent replicas' migration
# runs. Any fixed 64-bit value works; this one spells 'AGFLOWCP'.
_MIGRATION_LOCK_KEY = 0x41474C4F57435031 % (2**63)

# Pool shape defaults. min_size 1 keeps an idle replica cheap; max_size 10 is
# the per-process connection budget (spelled out in helm/values.yaml and the
# compose files via AGENTFLOW_CONTROLPLANE_PG_POOL_MAX); the checkout timeout
# bounds how long a caller blocks before _TRANSIENT_ERRORS retry/raise.
DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 10
DEFAULT_POOL_TIMEOUT_SECONDS = 10.0

# Live pools for the stats collector below. Weak: a store (and its pool) must
# be collectable when a test drops it without close(), and the collector must
# never keep a closed pool alive just to report zeros about it.
_LIVE_POOLS: weakref.WeakSet[Any] = weakref.WeakSet()


class _PoolStatsCollector:
    """Prometheus collector summing live control-plane pool stats.

    Registered once at module import; reports zeros until a pool opens. In
    production there is exactly one pool per process — summing keeps the
    numbers honest in test processes that hold several stores.
    """

    def collect(self) -> Iterable[GaugeMetricFamily]:
        connections = GaugeMetricFamily(
            "agentflow_pg_pool_connections",
            "Control-plane PostgreSQL pool connections, by state.",
            labels=["state"],
        )
        waiting = GaugeMetricFamily(
            "agentflow_pg_pool_requests_waiting",
            "Callers blocked waiting for a pooled control-plane connection.",
        )
        ceiling = GaugeMetricFamily(
            "agentflow_pg_pool_max_size",
            "Configured control-plane pool connection budget.",
        )
        pool_size = available = requests_waiting = max_size = 0
        for pool in list(_LIVE_POOLS):
            stats = pool.get_stats()
            pool_size += stats.get("pool_size", 0)
            available += stats.get("pool_available", 0)
            requests_waiting += stats.get("requests_waiting", 0)
            max_size += stats.get("pool_max", 0)
        connections.add_metric(["used"], pool_size - available)
        connections.add_metric(["idle"], available)
        waiting.add_metric([], requests_waiting)
        ceiling.add_metric([], max_size)
        yield connections
        yield waiting
        yield ceiling


REGISTRY.register(_PoolStatsCollector())  # type: ignore[arg-type]


def _window_to_interval(window: str) -> str:
    # Same grammar as the embedded adapter's parser; the '<n> minutes/hours/
    # days' strings it produces are valid PostgreSQL interval literals too,
    # but parsing here (rather than passing user input through) keeps the
    # ValueError contract for malformed windows.
    match = re.fullmatch(r"(\d+)([mhd])", window.strip())
    if match is None:
        raise ValueError("Invalid window. Use formats like 15m, 1h, or 7d.")
    value, unit = match.groups()
    if unit == "m":
        return f"{value} minutes"
    if unit == "h":
        return f"{value} hours"
    return f"{value} days"


class PostgresControlPlaneStore(ControlPlaneStore):
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

    # --- connection / schema plumbing ----------------------------------------

    def ping(self) -> None:
        """Reach the database, so `/health/ready` fails when it cannot be reached.

        Deliberately goes through `_connect()`, which lazily applies the schema:
        a replica pointed at a PostgreSQL it can open but not migrate is not
        ready either.
        """
        with self._connect() as conn:
            conn.execute("SELECT 1")

    def _connect(self) -> AbstractContextManager[Any]:
        # One checkout = one transaction: pool.connection() keeps psycopg's
        # connection context-manager semantics — commit on clean exit, roll
        # back on exception — and then returns the connection to the pool,
        # which is exactly the invariant-8 semantics the port requires.
        self._ensure_schema()
        # Annotated hop: with psycopg_pool absent (optional dependency), mypy
        # sees the module as Any and warn_return_any would flag a bare return.
        connection: AbstractContextManager[Any] = self._pool.connection()
        return connection

    def _open_pool(self) -> None:
        # Called under self._schema_lock. wait=False: the background workers
        # fill min_size; the first checkout blocks (bounded by the pool
        # timeout) rather than the whole boot.
        if not self._pool_opened:
            self._pool.open(wait=False)
            self._pool_opened = True
            _LIVE_POOLS.add(self._pool)

    def close(self) -> None:
        """Release the pool and its connections. Idempotent; the lifespan
        shutdown and test fixtures call this so worker threads and server
        slots do not outlive the store."""
        self._pool.close()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            self._open_pool()
            with self._pool.connection() as conn:
                # All pending migrations apply in ONE transaction, serialized
                # across replicas by a transaction-scoped advisory lock: the
                # loser blocks here, then reads the winner's version rows and
                # applies nothing. Failure rolls back DDL and ledger together,
                # so a half-applied migration cannot be recorded as done.
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_KEY,))
                conn.execute(_SCHEMA_VERSION_DDL)
                row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM control_plane_schema_version"
                ).fetchone()
                current = int(row[0]) if row is not None else 0
                for version, description, statements in _MIGRATIONS:
                    if version <= current:
                        continue
                    for statement in statements:
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO control_plane_schema_version (version, description)"
                        " VALUES (%s, %s)",
                        (version, description),
                    )
                    logger.info(
                        "control_plane_migration_applied",
                        version=version,
                        description=description,
                    )
            # Once per store lifetime: the write methods below must never
            # recreate a table mid-scenario (see the module docstring).
            self._schema_ready = True

    # --- webhook durable delivery queue --------------------------------------

    def enqueue_webhook_delivery(
        self,
        *,
        webhook_id: str,
        event_id: str,
        tenant: str,
        event_type: str,
        body: str,
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO webhook_delivery_queue
                    (webhook_id, event_id, tenant, event_type, body, status, attempts,
                     next_attempt_at, lease_expires_at, created_at, updated_at)
                VALUES (
                    %s, %s, %s, %s, %s, 'pending', 0, now(),
                    now() + make_interval(secs => %s), now(), now()
                )
                ON CONFLICT (webhook_id, event_id) DO NOTHING
                """,
                (
                    webhook_id,
                    event_id,
                    tenant,
                    event_type,
                    body,
                    self._claim_lease_seconds,
                ),
            )
            # Insert-win detection (ADR 0010 §2): rowcount is 1 only for the
            # caller whose INSERT actually landed — the enqueue winner, who
            # alone inline-delivers. The lease stamped above keeps the row
            # invisible to claim_due_webhook_deliveries until outcome clears
            # it or the lease expires (crashed winner → redrive).
            return bool(cursor.rowcount == 1)

    def claim_due_webhook_deliveries(self, *, limit: int) -> list[WebhookQueueRow]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH due AS (
                    SELECT webhook_id, event_id, created_at
                    FROM webhook_delivery_queue
                    WHERE status = 'pending'
                      AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                      AND (lease_expires_at IS NULL OR lease_expires_at <= now())
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE webhook_delivery_queue queue
                SET lease_expires_at = now() + make_interval(secs => %s),
                    updated_at = now()
                FROM due
                WHERE queue.webhook_id = due.webhook_id
                  AND queue.event_id = due.event_id
                RETURNING queue.webhook_id, queue.event_id, queue.tenant,
                          queue.event_type, queue.body, due.created_at
                """,
                (limit, self._claim_lease_seconds),
            ).fetchall()
        # UPDATE .. RETURNING does not guarantee row order; re-establish the
        # oldest-first contract the dispatcher relies on.
        rows.sort(key=lambda row: row[5])
        return [
            WebhookQueueRow(
                webhook_id=webhook_id,
                event_id=event_id,
                tenant=tenant,
                event_type=event_type,
                body=body,
            )
            for webhook_id, event_id, tenant, event_type, body, _created_at in rows
        ]

    def record_webhook_delivery_outcome(
        self,
        *,
        webhook_id: str,
        event_id: str,
        success: bool,
        status_code: int | None,
        error: str | None,
        max_attempts: int,
        backoff_seconds: Sequence[float],
    ) -> None:
        # Bounded retry on transient connection errors, same shape as
        # record_api_usage: without it, a POST that succeeded but then hit a
        # momentary DB blip on this outcome write never clears the enqueue
        # lease, stranding the row pending+leased for the full claim lease
        # window instead of a fast redrive (audit finding #4).
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._connect() as conn:
                    if success:
                        conn.execute(
                            """
                            UPDATE webhook_delivery_queue
                            SET status = 'delivered', last_status_code = %s,
                                last_error = NULL, lease_expires_at = NULL, updated_at = now()
                            WHERE webhook_id = %s AND event_id = %s
                            """,
                            (status_code, webhook_id, event_id),
                        )
                        return
                    row = conn.execute(
                        "SELECT attempts FROM webhook_delivery_queue "
                        "WHERE webhook_id = %s AND event_id = %s FOR UPDATE",
                        (webhook_id, event_id),
                    ).fetchone()
                    attempts = (row[0] if row else 0) + 1
                    if attempts >= max_attempts:
                        conn.execute(
                            """
                            UPDATE webhook_delivery_queue
                            SET status = 'dead', attempts = %s, last_status_code = %s,
                                last_error = %s, next_attempt_at = NULL,
                                lease_expires_at = NULL, updated_at = now()
                            WHERE webhook_id = %s AND event_id = %s
                            """,
                            (attempts, status_code, error, webhook_id, event_id),
                        )
                        return
                    delay = backoff_seconds[min(attempts - 1, len(backoff_seconds) - 1)]
                    conn.execute(
                        """
                        UPDATE webhook_delivery_queue
                        SET status = 'pending', attempts = %s, last_status_code = %s,
                            last_error = %s,
                            next_attempt_at = now() + make_interval(secs => %s),
                            lease_expires_at = NULL, updated_at = now()
                        WHERE webhook_id = %s AND event_id = %s
                        """,
                        (
                            attempts,
                            status_code,
                            error,
                            delay,
                            webhook_id,
                            event_id,
                        ),
                    )
                    return
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                time.sleep(0.01 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def park_webhook_delivery(self, *, webhook_id: str, event_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE webhook_delivery_queue
                SET status = 'dead', last_error = %s, next_attempt_at = NULL,
                    lease_expires_at = NULL, updated_at = now()
                WHERE webhook_id = %s AND event_id = %s
                """,
                (error, webhook_id, event_id),
            )

    # --- webhook delivery attempt log ----------------------------------------

    def log_webhook_delivery(
        self,
        *,
        delivery_id: str,
        webhook_id: str,
        event_id: str,
        event_type: str,
        attempt: int,
        status_code: int | None,
        success: bool,
        error: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO webhook_deliveries (
                    delivery_id, webhook_id, event_id, event_type, attempt,
                    status_code, success, error, delivered_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    delivery_id,
                    webhook_id,
                    event_id,
                    event_type,
                    attempt,
                    status_code,
                    success,
                    error,
                ),
            )

    def get_webhook_delivery_logs(self, webhook_id: str, *, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            result = conn.execute(
                """
                SELECT delivery_id, webhook_id, event_id, event_type, attempt,
                       status_code, success, error, delivered_at
                FROM webhook_deliveries
                WHERE webhook_id = %s
                ORDER BY delivered_at DESC
                LIMIT %s
                """,
                (webhook_id, limit),
            )
            columns = [description.name for description in result.description]
            return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]

    # --- alert delivery history -----------------------------------------------

    def log_alert_delivery(
        self,
        *,
        delivery_id: str,
        alert_id: str,
        alert_name: str,
        tenant: str,
        metric: str,
        current_value: float | None,
        previous_value: float | None,
        change_pct: float | None,
        threshold: float,
        condition: str,
        window: str,
        event_type: str,
        status_code: int | None,
        success: bool,
        error: str | None,
        payload: dict,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_history (
                    delivery_id, alert_id, alert_name, metric, current_value,
                    previous_value, change_pct, threshold, condition, metric_window,
                    tenant, event_type, status_code, success, error, payload,
                    triggered_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, now())
                """,
                (
                    delivery_id,
                    alert_id,
                    alert_name,
                    metric,
                    current_value,
                    previous_value,
                    change_pct,
                    threshold,
                    condition,
                    window,
                    tenant,
                    event_type,
                    status_code,
                    success,
                    error,
                    json.dumps(payload, sort_keys=True),
                ),
            )

    def get_alert_delivery_history(self, alert_id: str, *, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            result = conn.execute(
                """
                SELECT delivery_id, alert_id, alert_name, metric, current_value,
                       previous_value, change_pct, threshold, condition,
                       metric_window AS window,
                       tenant, event_type, status_code, success, error, payload,
                       triggered_at
                FROM alert_history
                WHERE alert_id = %s
                ORDER BY triggered_at DESC
                LIMIT %s
                """,
                (alert_id, limit),
            )
            columns = [description.name for description in result.description]
            records = [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
        for record in records:
            payload = record.get("payload")
            if isinstance(payload, str):
                try:
                    record["payload"] = json.loads(payload)
                except json.JSONDecodeError:
                    pass
        return records

    # --- webhook registration repository ---------------------------------------

    def load_webhook_registrations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record FROM webhook_registrations ORDER BY position ASC"
            ).fetchall()
        return [json.loads(record) for (record,) in rows]

    def save_webhook_registrations(self, registrations: list[dict]) -> None:
        self._replace_record_set("webhook_registrations", registrations)

    # --- alert rule repository (mutable runtime state) ------------------------

    def load_alert_rules(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT record FROM alert_rules ORDER BY position ASC").fetchall()
        return [json.loads(record) for (record,) in rows]

    def save_alert_rules(self, rules: list[dict]) -> None:
        self._replace_record_set("alert_rules", rules)

    def _replace_record_set(self, table: str, records: list[dict]) -> None:
        # Full-set save with the YAML file's replace semantics: rows missing
        # from the incoming set disappear, existing rows are updated in place
        # (alert_rules keeps its tick_lease_expires_at — a CRUD save must not
        # release another replica's in-flight evaluation claim), new rows
        # append. One transaction, so a concurrent reader never sees a
        # half-written set.
        ids: list[str] = []
        for record in records:
            record_id = record.get("id")
            if not record_id:
                raise ValueError(f"{table} records require a non-empty 'id'.")
            ids.append(str(record_id))
        # ``table`` is one of two module literals (see the call sites above);
        # every value binds via %s.
        delete_missing_sql = f"DELETE FROM {table} WHERE id != ALL(%s)"  # nosec B608
        # table is a module literal (same rationale as above)
        delete_all_sql = f"DELETE FROM {table}"  # nosec B608
        upsert_sql = (
            # table is a module literal (same rationale as above)
            f"INSERT INTO {table} (id, position, record) VALUES (%s, %s, %s) "  # nosec B608
            "ON CONFLICT (id) DO UPDATE "
            "SET position = EXCLUDED.position, record = EXCLUDED.record"
        )
        with self._connect() as conn:
            if ids:
                conn.execute(delete_missing_sql, (ids,))
            else:
                conn.execute(delete_all_sql)
            for position, (record_id, record) in enumerate(zip(ids, records, strict=True)):
                conn.execute(
                    upsert_sql,
                    (record_id, position, json.dumps(record, sort_keys=True)),
                )

    def claim_alert_tick(self, rule_id: str, *, lease_seconds: float) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE alert_rules
                SET tick_lease_expires_at = now() + make_interval(secs => %s)
                WHERE id = %s
                  AND (tick_lease_expires_at IS NULL OR tick_lease_expires_at <= now())
                """,
                (lease_seconds, rule_id),
            )
            # rowcount 0 = another replica holds this rule's tick (or the rule
            # row is gone — either way, nothing to evaluate here).
            return bool(cursor.rowcount == 1)

    def complete_alert_tick(self, rule_id: str, *, record: dict | None) -> None:
        with self._connect() as conn:
            if record is None:
                conn.execute(
                    "UPDATE alert_rules SET tick_lease_expires_at = NULL WHERE id = %s",
                    (rule_id,),
                )
                return
            # State advance and claim release in the same transaction
            # (ADR 0010 §2).
            conn.execute(
                """
                UPDATE alert_rules
                SET record = %s, tick_lease_expires_at = NULL
                WHERE id = %s
                """,
                (json.dumps(record, sort_keys=True), rule_id),
            )

    # --- replay outbox + dead-letter (invariant 8: one transaction) -----------

    def ensure_outbox_schema(self) -> None:
        self._ensure_schema()

    def claim_due_outbox_entries(self, *, limit: int = 100) -> list[OutboxEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH due AS (
                    SELECT id, created_at
                    FROM outbox
                    WHERE status = 'pending'
                      AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                      AND (lease_expires_at IS NULL OR lease_expires_at <= now())
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE outbox
                SET lease_expires_at = now() + make_interval(secs => %s)
                FROM due
                WHERE outbox.id = due.id
                RETURNING outbox.id, outbox.event_id, outbox.payload, outbox.topic,
                          outbox.retry_count, due.created_at
                """,
                (limit, self._claim_lease_seconds),
            ).fetchall()
        rows.sort(key=lambda row: row[5])
        return [
            OutboxEntry(
                id=row_id, event_id=event_id, payload=payload, topic=topic, retry_count=retry_count
            )
            for row_id, event_id, payload, topic, retry_count, _created_at in rows
        ]

    def get_pending_outbox_entry(self, outbox_id: str) -> OutboxEntry | None:
        # Claim-by-id: the replay path inline-delivers the row it just
        # inserted, so it must own it — if a background claimant on another
        # replica got there first (rowcount 0), the replay stays pending and
        # that claimant delivers it. At-least-once end to end, never twice
        # from this seam.
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE outbox
                SET lease_expires_at = now() + make_interval(secs => %s)
                WHERE id = %s
                  AND status = 'pending'
                  AND (lease_expires_at IS NULL OR lease_expires_at <= now())
                RETURNING id, event_id, payload, topic, retry_count
                """,
                (self._claim_lease_seconds, outbox_id),
            ).fetchone()
        if row is None:
            return None
        row_id, event_id, payload, topic, retry_count = row
        return OutboxEntry(
            id=row_id, event_id=event_id, payload=payload, topic=topic, retry_count=retry_count
        )

    def mark_outbox_sent(self, *, outbox_id: str, event_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = 'sent', sent_at = now(), last_error = NULL,
                    lease_expires_at = NULL
                WHERE id = %s
                """,
                (outbox_id,),
            )
            conn.execute(
                "UPDATE dead_letter_events SET status = 'replayed' WHERE event_id = %s",
                (event_id,),
            )
        # Both updates share the method's transaction (invariant 8): the
        # context manager commits them together or rolls both back.

    def schedule_outbox_retry(
        self,
        *,
        outbox_id: str,
        event_id: str,
        retry_count: int,
        error_message: str,
        max_retries: int,
    ) -> None:
        status = "pending"
        retry_delay_seconds = 2**retry_count
        is_kafka_error = (
            error_message.startswith("KafkaError{")
            or "Kafka message(s) were not delivered" in error_message
        )
        if is_kafka_error:
            retry_delay_seconds = max(retry_delay_seconds, 30)
        is_failed = retry_count >= max_retries
        if is_failed:
            status = "failed"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = %s, retry_count = %s,
                    next_attempt_at = CASE WHEN %s THEN NULL
                                            ELSE now() + make_interval(secs => %s) END,
                    last_error = %s, lease_expires_at = NULL
                WHERE id = %s
                """,
                (status, retry_count, is_failed, retry_delay_seconds, error_message, outbox_id),
            )
            if status == "failed":
                conn.execute(
                    "UPDATE dead_letter_events SET status = 'failed' WHERE event_id = %s",
                    (event_id,),
                )

    def enqueue_outbox_replay(
        self,
        *,
        outbox_id: str,
        event_id: str,
        payload: dict,
        topic: str,
        retry_count: int,
        replayed_at: datetime,
    ) -> None:
        encoded_payload = json.dumps(payload)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE dead_letter_events
                SET payload = %s, status = 'replay_pending', retry_count = %s,
                    last_retried_at = %s
                WHERE event_id = %s
                """,
                (encoded_payload, retry_count, replayed_at, event_id),
            )
            conn.execute(
                """
                INSERT INTO outbox (
                    id, event_id, payload, topic, created_at, sent_at, status,
                    retry_count, next_attempt_at, last_error
                )
                VALUES (%s, %s, %s, %s, %s, NULL, 'pending', 0, %s, NULL)
                """,
                (outbox_id, event_id, encoded_payload, topic, replayed_at, replayed_at),
            )

    def get_dead_letter_event_for_replay(self, event_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_id, payload, retry_count FROM dead_letter_events WHERE event_id = %s",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return {"event_id": row[0], "payload": row[1], "retry_count": row[2]}

    def dismiss_dead_letter_event(self, event_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE dead_letter_events SET status = 'dismissed' WHERE event_id = %s",
                (event_id,),
            )

    def dead_letter_event_exists(self, event_id: str, tenant_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT event_id
                FROM dead_letter_events
                WHERE event_id = %s AND COALESCE(tenant_id, 'default') = %s
                """,
                (event_id, tenant_id),
            ).fetchone()
        return row is not None

    def get_dead_letter_event(self, event_id: str, tenant_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT event_id, event_type, payload, failure_reason, failure_detail,
                       received_at, retry_count, last_retried_at, status
                FROM dead_letter_events
                WHERE event_id = %s AND COALESCE(tenant_id, 'default') = %s
                """,
                (event_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "event_id": row[0],
            "event_type": row[1],
            "payload": row[2],
            "failure_reason": row[3],
            "failure_detail": row[4],
            "received_at": row[5],
            "retry_count": int(row[6] or 0),
            "last_retried_at": row[7],
            "status": row[8],
        }

    def list_dead_letter_events(
        self,
        *,
        tenant_id: str,
        reason: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict], int]:
        # Two literal SQL branches instead of an interpolated filter clause —
        # the same shape as the embedded adapter (and nothing for a SQL
        # linter to squint at).
        if reason is not None:
            count_sql = (
                "SELECT COUNT(*) FROM dead_letter_events "
                "WHERE status = 'failed' AND COALESCE(tenant_id, 'default') = %s "
                "AND failure_reason = %s"
            )
            page_sql = (
                "SELECT event_id, event_type, failure_reason, failure_detail, "
                "received_at, retry_count, last_retried_at, status "
                "FROM dead_letter_events "
                "WHERE status = 'failed' AND COALESCE(tenant_id, 'default') = %s "
                "AND failure_reason = %s "
                "ORDER BY received_at DESC, event_id ASC LIMIT %s OFFSET %s"
            )
            count_params: tuple = (tenant_id, reason)
        else:
            count_sql = (
                "SELECT COUNT(*) FROM dead_letter_events "
                "WHERE status = 'failed' AND COALESCE(tenant_id, 'default') = %s"
            )
            page_sql = (
                "SELECT event_id, event_type, failure_reason, failure_detail, "
                "received_at, retry_count, last_retried_at, status "
                "FROM dead_letter_events "
                "WHERE status = 'failed' AND COALESCE(tenant_id, 'default') = %s "
                "ORDER BY received_at DESC, event_id ASC LIMIT %s OFFSET %s"
            )
            count_params = (tenant_id,)
        offset = (page - 1) * page_size
        with self._connect() as conn:
            total_row = conn.execute(count_sql, count_params).fetchone()
            total = int(total_row[0]) if total_row and total_row[0] is not None else 0
            rows = conn.execute(page_sql, (*count_params, page_size, offset)).fetchall()
        items = [
            {
                "event_id": row[0],
                "event_type": row[1],
                "failure_reason": row[2],
                "failure_detail": row[3],
                "received_at": row[4],
                "retry_count": int(row[5] or 0),
                "last_retried_at": row[6],
                "status": row[7],
            }
            for row in rows
        ]
        return items, total

    def get_dead_letter_stats(self, tenant_id: str) -> dict:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT failure_reason, COUNT(*)
                FROM dead_letter_events
                WHERE status = 'failed'
                  AND COALESCE(tenant_id, 'default') = %s
                GROUP BY failure_reason
                ORDER BY failure_reason
                """,
                (tenant_id,),
            ).fetchall()
            last_24h_row = conn.execute(
                """
                SELECT COUNT(*)
                FROM dead_letter_events
                WHERE status = 'failed'
                  AND COALESCE(tenant_id, 'default') = %s
                  AND received_at >= now() - INTERVAL '24 hours'
                """,
                (tenant_id,),
            ).fetchone()
            trend_rows = conn.execute(
                """
                SELECT DATE_TRUNC('hour', received_at) AS hour_bucket, COUNT(*)
                FROM dead_letter_events
                WHERE status = 'failed'
                  AND COALESCE(tenant_id, 'default') = %s
                  AND received_at >= now() - INTERVAL '24 hours'
                GROUP BY hour_bucket
                ORDER BY hour_bucket
                """,
                (tenant_id,),
            ).fetchall()
        return {
            "counts": {str(reason): int(count) for reason, count in rows if reason is not None},
            "last_24h": int(last_24h_row[0]) if last_24h_row and last_24h_row[0] is not None else 0,
            "trend": [
                {
                    "hour": hour.isoformat() if hasattr(hour, "isoformat") else str(hour),
                    "count": int(count),
                }
                for hour, count in trend_rows
            ],
        }

    def list_dead_letter_events_for_inbox(self, tenant_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, event_type, failure_reason, failure_detail,
                       received_at, retry_count, last_retried_at, status
                FROM dead_letter_events
                WHERE COALESCE(tenant_id, 'default') = %s
                ORDER BY received_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [
            {
                "event_id": row[0],
                "event_type": row[1],
                "failure_reason": row[2],
                "failure_detail": row[3],
                "received_at": row[4],
                "retry_count": int(row[5] or 0),
                "last_retried_at": row[6],
                "status": row[7],
            }
            for row in rows
        ]

    def list_stuck_replay_dead_letter_events(
        self, tenant_id: str, *, older_than_seconds: float
    ) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, event_type, failure_reason, failure_detail,
                       received_at, retry_count, last_retried_at, status
                FROM dead_letter_events
                WHERE COALESCE(tenant_id, 'default') = %s
                  AND status = 'replay_pending'
                  AND last_retried_at IS NOT NULL
                  AND last_retried_at < %s
                ORDER BY last_retried_at ASC
                """,
                (tenant_id, cutoff),
            ).fetchall()
        return [
            {
                "event_id": row[0],
                "event_type": row[1],
                "failure_reason": row[2],
                "failure_detail": row[3],
                "received_at": row[4],
                "retry_count": int(row[5] or 0),
                "last_retried_at": row[6],
                "status": row[7],
            }
            for row in rows
        ]

    def count_dead_letter_manual_actions(self, tenant_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM dead_letter_events
                WHERE COALESCE(tenant_id, 'default') = %s
                  AND status IN ('replayed', 'dismissed')
                """,
                (tenant_id,),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # --- exception-inbox triage overlay ---------------------------------------

    def ensure_triage_schema(self) -> None:
        self._ensure_schema()

    def list_triage_states(self, *, tenant_id: str, source: str | None = None) -> list[TriageState]:
        select = (
            "SELECT item_id, tenant_id, source, status, first_seen_at, "
            "last_seen_at, resolved_at, note FROM ops_exception_triage "
            "WHERE tenant_id = %s"
        )
        with self._connect() as conn:
            if source is not None:
                rows = conn.execute(select + " AND source = %s", (tenant_id, source)).fetchall()
            else:
                rows = conn.execute(select, (tenant_id,)).fetchall()
        return [
            TriageState(
                item_id=row[0],
                tenant_id=row[1],
                source=row[2],
                status=row[3],
                first_seen_at=row[4],
                last_seen_at=row[5],
                resolved_at=row[6],
                note=row[7],
            )
            for row in rows
        ]

    def upsert_triage_finding(
        self, *, item_id: str, tenant_id: str, source: str, seen_at: datetime
    ) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT status FROM ops_exception_triage WHERE item_id = %s",
                (item_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO ops_exception_triage
                        (item_id, tenant_id, source, status, first_seen_at, last_seen_at,
                         resolved_at, note)
                    VALUES (%s, %s, %s, 'open', %s, %s, NULL, NULL)
                    """,
                    (item_id, tenant_id, source, seen_at, seen_at),
                )
                return
            (status,) = existing
            if status != "resolved":
                conn.execute(
                    "UPDATE ops_exception_triage SET last_seen_at = %s WHERE item_id = %s",
                    (seen_at, item_id),
                )
                return
            # Resolved: reopen only if this occurrence is strictly after
            # resolved_at — compared in SQL, same reasoning as the embedded
            # adapter (keeps both adapters' comparison semantics identical
            # regardless of whether the caller's `seen_at` is naive or aware).
            conn.execute(
                """
                UPDATE ops_exception_triage
                SET status = 'open', last_seen_at = %s, resolved_at = NULL, note = NULL
                WHERE item_id = %s AND resolved_at IS NOT NULL AND %s > resolved_at
                """,
                (seen_at, item_id, seen_at),
            )

    def auto_resolve_missing_triage_findings(
        self,
        *,
        tenant_id: str,
        source: str,
        seen_item_ids: Sequence[str],
        resolved_at: datetime,
    ) -> None:
        seen = set(seen_item_ids)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT item_id FROM ops_exception_triage
                WHERE tenant_id = %s AND source = %s AND status != 'resolved'
                """,
                (tenant_id, source),
            ).fetchall()
            for (item_id,) in rows:
                if item_id in seen:
                    continue
                conn.execute(
                    """
                    UPDATE ops_exception_triage
                    SET status = 'resolved', resolved_at = %s, note = %s
                    WHERE item_id = %s AND tenant_id = %s
                    """,
                    (resolved_at, AUTO_RESOLVE_NOTE, item_id, tenant_id),
                )

    def set_triage_state(
        self, *, item_id: str, tenant_id: str, status: str, note: str | None = None
    ) -> bool:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM ops_exception_triage WHERE item_id = %s AND tenant_id = %s",
                (item_id, tenant_id),
            ).fetchone()
            if existing is None:
                return False
            resolved_at = datetime.now(UTC) if status == "resolved" else None
            conn.execute(
                """
                UPDATE ops_exception_triage
                SET status = %s, resolved_at = %s, note = COALESCE(%s, note)
                WHERE item_id = %s AND tenant_id = %s
                """,
                (status, resolved_at, note, item_id, tenant_id),
            )
            return True

    def count_triage_manual_actions(self, tenant_id: str) -> int:
        # Excludes rows auto-resolved by `auto_resolve_missing_triage_findings`
        # (note == AUTO_RESOLVE_NOTE) — the KPI counts human decisions only.
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM ops_exception_triage
                WHERE tenant_id = %s
                  AND (status = 'acknowledged'
                       OR (status = 'resolved' AND (note IS NULL OR note != %s)))
                """,
                (tenant_id, AUTO_RESOLVE_NOTE),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # --- webhook dead deliveries for the exception inbox ----------------------

    def list_dead_webhook_deliveries(self, tenant_id: str | None = None) -> list[dict]:
        select = (
            "SELECT webhook_id, event_id, tenant, event_type, body, attempts, "
            "last_status_code, last_error, created_at, updated_at "
            "FROM webhook_delivery_queue WHERE status = 'dead'"
        )
        with self._connect() as conn:
            if tenant_id is not None:
                rows = conn.execute(
                    select + " AND tenant = %s ORDER BY updated_at DESC", (tenant_id,)
                ).fetchall()
            else:
                rows = conn.execute(select + " ORDER BY updated_at DESC").fetchall()
        return [
            {
                "webhook_id": row[0],
                "event_id": row[1],
                "tenant": row[2],
                "event_type": row[3],
                "body": row[4],
                "attempts": row[5],
                "last_status_code": row[6],
                "last_error": row[7],
                "created_at": row[8],
                "updated_at": row[9],
            }
            for row in rows
        ]

    # --- API usage accounting -------------------------------------------------

    def ensure_usage_schema(self) -> None:
        self._ensure_schema()

    def record_api_usage(
        self,
        *,
        tenant: str,
        key_name: str,
        endpoint: str,
        key_id: str | None,
        key_slot: str,
    ) -> None:
        # Bounded retry on transient connection errors, then raise — the
        # caller (record_usage) skips its audit publish on failure, exactly
        # like the embedded adapter's file-lock retry loop.
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO api_usage (tenant, key_name, endpoint, key_id, key_slot)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (tenant, key_name, endpoint, key_id, key_slot),
                    )
                return
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                time.sleep(0.01 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def record_api_usage_batch(self, rows: Sequence[UsageRow]) -> None:
        # One checkout, one executemany, ONE transaction (audit P1-1): the
        # base-class fallback of per-row record_api_usage calls would cost a
        # checkout and a commit per row — a 256-row batch was up to 256
        # connections on the pre-pool shape. psycopg batches the executemany
        # into pipelined server round trips inside the single transaction the
        # connection context manager owns, so the batch lands atomically:
        # every row shares one xmin, and a failed batch persists nothing.
        # Same failure contract as record_api_usage — raise after bounded
        # retries; the caller drops the batch and counts it.
        if not rows:
            return
        params = [
            (row.tenant, row.key_name, row.endpoint, row.key_id, row.key_slot) for row in rows
        ]
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._connect() as conn, conn.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO api_usage (tenant, key_name, endpoint, key_id, key_slot)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        params,
                    )
                return
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                time.sleep(0.01 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def get_usage_by_tenant(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tenant, COUNT(*) AS requests_last_24h
                FROM api_usage
                WHERE ts >= now() - INTERVAL '24 hours'
                GROUP BY tenant
                ORDER BY tenant
                """
            ).fetchall()
        return [
            {"tenant": tenant, "requests_last_24h": int(requests_last_24h)}
            for tenant, requests_last_24h in rows
        ]

    def get_usage_by_key(self) -> dict[tuple[str, str], int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tenant, key_name, COUNT(*) AS requests_last_24h
                FROM api_usage
                WHERE ts >= now() - INTERVAL '24 hours'
                GROUP BY tenant, key_name
                """
            ).fetchall()
        return {
            (tenant, key_name): int(requests_last_24h)
            for tenant, key_name, requests_last_24h in rows
        }

    def get_old_key_usage_by_key_id(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key_id, COUNT(*) AS requests_last_hour
                FROM api_usage
                WHERE key_slot = 'previous'
                  AND ts >= now() - INTERVAL '1 hour'
                  AND key_id IS NOT NULL
                GROUP BY key_id
                """
            ).fetchall()
        return {key_id: int(count) for key_id, count in rows}

    # --- API session analytics ------------------------------------------------

    def record_api_session(self, request_id: str, record: dict) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO api_sessions (
                        request_id, tenant, key_name, endpoint, method, status_code,
                        duration_ms, cache_hit, entity_type, entity_id, metric_name,
                        query_engine, query_text
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (request_id) DO UPDATE SET
                        tenant = EXCLUDED.tenant,
                        key_name = EXCLUDED.key_name,
                        endpoint = EXCLUDED.endpoint,
                        method = EXCLUDED.method,
                        status_code = EXCLUDED.status_code,
                        duration_ms = EXCLUDED.duration_ms,
                        cache_hit = EXCLUDED.cache_hit,
                        entity_type = EXCLUDED.entity_type,
                        entity_id = EXCLUDED.entity_id,
                        metric_name = EXCLUDED.metric_name,
                        query_engine = EXCLUDED.query_engine,
                        query_text = EXCLUDED.query_text
                    """,
                    (
                        request_id,
                        record["tenant"],
                        record["key_name"],
                        record["endpoint"],
                        record["method"],
                        record["status_code"],
                        record["duration_ms"],
                        record["cache_hit"],
                        record["entity_type"],
                        record["entity_id"],
                        record["metric_name"],
                        record["query_engine"],
                        record["query_text"],
                    ),
                )
        except psycopg.Error as exc:
            # Best-effort telemetry, same contract as the embedded adapter:
            # log and return rather than failing the request path.
            logger.warning(
                "analytics_session_write_skipped",
                stage="insert",
                dsn=_masked_dsn(self._dsn),
                request_id=request_id,
                tenant=record.get("tenant"),
                endpoint=record.get("endpoint"),
                error=str(exc),
                exc_info=True,
            )

    def get_usage_analytics(self, *, window: str = "24h", tenant: str | None = None) -> dict:
        interval = _window_to_interval(window)
        # Two literal SQL branches instead of an interpolated tenant clause —
        # the same shape as the embedded adapter.
        select_head = (
            "SELECT tenant, COUNT(*) AS total_requests, "
            "ROUND(AVG(CASE WHEN status_code >= 400 THEN 1.0 ELSE 0.0 END), 4) AS error_rate, "
            "ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 4) AS cache_hit_rate, "
            "ROUND(AVG(duration_ms)::numeric, 3) AS avg_duration_ms "
            "FROM api_sessions "
            "WHERE tenant IS NOT NULL AND ts >= now() - CAST(%s AS INTERVAL) "
        )
        if tenant:
            tenants_sql = select_head + "AND tenant = %s GROUP BY tenant ORDER BY tenant"
            params: tuple = (interval, tenant)
        else:
            tenants_sql = select_head + "GROUP BY tenant ORDER BY tenant"
            params = (interval,)
        with self._connect() as conn:
            rows = conn.execute(tenants_sql, params).fetchall()
            tenants = []
            for tenant_name, total_requests, error_rate, cache_hit_rate, avg_duration_ms in rows:
                top_endpoints = conn.execute(
                    """
                    SELECT endpoint
                    FROM api_sessions
                    WHERE tenant = %s
                      AND ts >= now() - CAST(%s AS INTERVAL)
                    GROUP BY endpoint
                    ORDER BY COUNT(*) DESC, endpoint
                    LIMIT 3
                    """,
                    (tenant_name, interval),
                ).fetchall()
                tenants.append(
                    {
                        "tenant": tenant_name,
                        "total_requests": int(total_requests),
                        "error_rate": float(error_rate or 0.0),
                        "cache_hit_rate": float(cache_hit_rate or 0.0),
                        "top_endpoints": [item[0] for item in top_endpoints],
                        "avg_duration_ms": float(avg_duration_ms or 0.0),
                    }
                )
        return {"window": window, "tenants": tenants}

    def get_top_queries(self, *, limit: int = 10, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT query_text, COUNT(*) AS frequency
                FROM api_sessions
                WHERE query_text IS NOT NULL
                  AND ts >= now() - CAST(%s AS INTERVAL)
                GROUP BY query_text
                ORDER BY frequency DESC, query_text
                LIMIT %s
                """,
                (interval, limit),
            ).fetchall()
        return {
            "window": window,
            "queries": [
                {"query": query_text, "count": int(frequency)} for query_text, frequency in rows
            ],
        }

    def get_top_entities(self, *, limit: int = 10, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT entity_type, entity_id, COUNT(*) AS frequency
                FROM api_sessions
                WHERE entity_id IS NOT NULL
                  AND ts >= now() - CAST(%s AS INTERVAL)
                GROUP BY entity_type, entity_id
                ORDER BY frequency DESC, entity_type, entity_id
                LIMIT %s
                """,
                (interval, limit),
            ).fetchall()
        return {
            "window": window,
            "entities": [
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "count": int(frequency),
                }
                for entity_type, entity_id, frequency in rows
            ],
        }

    def get_latency_analytics(self, *, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    endpoint,
                    COUNT(*) AS requests,
                    ROUND((percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms))::numeric,
                          3) AS p50_ms,
                    ROUND((percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms))::numeric,
                          3) AS p95_ms,
                    ROUND((percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms))::numeric,
                          3) AS p99_ms
                FROM api_sessions
                WHERE ts >= now() - CAST(%s AS INTERVAL)
                GROUP BY endpoint
                ORDER BY endpoint
                """,
                (interval,),
            ).fetchall()
        return {
            "window": window,
            "endpoints": [
                {
                    "endpoint": endpoint,
                    "requests": int(requests),
                    "p50_ms": float(p50_ms or 0.0),
                    "p95_ms": float(p95_ms or 0.0),
                    "p99_ms": float(p99_ms or 0.0),
                }
                for endpoint, requests, p50_ms, p95_ms, p99_ms in rows
            ],
        }

    def get_anomalies(self, *, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        with self._connect() as conn:
            rows = conn.execute(
                """
                WITH hourly AS (
                    SELECT
                        tenant,
                        date_trunc('hour', ts) AS hour_bucket,
                        COUNT(*) AS requests
                    FROM api_sessions
                    WHERE tenant IS NOT NULL
                      AND ts >= now() - CAST(%s AS INTERVAL)
                    GROUP BY tenant, hour_bucket
                ),
                latest AS (
                    SELECT tenant, MAX(hour_bucket) AS current_hour
                    FROM hourly
                    GROUP BY tenant
                ),
                current_hour AS (
                    SELECT
                        hourly.tenant,
                        hourly.hour_bucket,
                        hourly.requests AS current_hour_requests
                    FROM hourly
                    JOIN latest
                      ON latest.tenant = hourly.tenant
                     AND latest.current_hour = hourly.hour_bucket
                ),
                historical AS (
                    SELECT
                        current_hour.tenant,
                        ROUND(AVG(hourly.requests), 1) AS hourly_average
                    FROM current_hour
                    JOIN hourly
                      ON hourly.tenant = current_hour.tenant
                     AND hourly.hour_bucket < current_hour.hour_bucket
                    GROUP BY current_hour.tenant
                ),
                scored AS (
                    SELECT
                        current_hour.tenant,
                        current_hour.current_hour_requests,
                        historical.hourly_average,
                        ROUND(
                            current_hour.current_hour_requests
                            / NULLIF(historical.hourly_average, 0),
                            2
                        ) AS spike_ratio
                    FROM current_hour
                    JOIN historical
                      ON historical.tenant = current_hour.tenant
                )
                SELECT tenant, current_hour_requests, hourly_average, spike_ratio
                FROM scored
                WHERE spike_ratio > 3
                ORDER BY spike_ratio DESC, tenant
                """,
                (interval,),
            ).fetchall()
        return {
            "window": window,
            "anomalies": [
                {
                    "tenant": tenant,
                    "current_hour_requests": int(current_hour_requests),
                    "hourly_average": float(hourly_average or 0.0),
                    "spike_ratio": float(spike_ratio or 0.0),
                }
                for tenant, current_hour_requests, hourly_average, spike_ratio in rows
            ],
        }

    def get_queries_per_second_last_minute(self) -> float:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM api_sessions
                    WHERE ts >= now() - INTERVAL '1 minute'
                    """
                ).fetchone()
        except psycopg.Error:
            # Same degrade-to-zero contract as the embedded adapter's
            # duckdb.Error guard: the admin tile shows 0.0 over failing.
            return 0.0
        requests_last_minute = row[0] if row else 0
        return round(float(requests_last_minute) / 60.0, 2)


def _masked_dsn(dsn: str) -> str:
    """DSN with any password masked, for log lines."""
    masked = re.sub(r"(password=)[^ ]+", r"\1***", dsn)
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", masked)


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
