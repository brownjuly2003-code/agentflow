"""Shared plumbing for the PostgreSQL control-plane repositories.

The bounded connection pool, the migration runner, the pool-stats collector,
and the record-set replace helper every capability repository (webhook,
alert, outbox/replay, usage/audit) inherits. Split out of the single-module
``postgres.py`` adapter (audit F-08) with bodies moved verbatim;
``postgres.py`` still assembles ``PostgresControlPlaneStore``, keeps
``__init__`` (the ``postgres.psycopg`` seam), and remains the public import
surface.
"""

from __future__ import annotations

import json
import re
import threading
import weakref
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import structlog
from prometheus_client import REGISTRY
from prometheus_client.core import GaugeMetricFamily

from .postgres_schema import _MIGRATION_LOCK_KEY, _MIGRATIONS, _SCHEMA_VERSION_DDL
from .store import ControlPlaneStore

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


class PostgresControlPlaneBase(ControlPlaneStore):
    """Pool and schema plumbing shared by the PostgreSQL capability
    repositories. ``postgres.PostgresControlPlaneStore`` is the assembled
    adapter; its ``__init__`` lives there (so tests can stub
    ``postgres.psycopg`` / ``postgres.psycopg_pool``) and sets the
    attributes declared below."""

    _dsn: str
    _claim_lease_seconds: float
    _schema_ready: bool
    _schema_lock: threading.Lock
    _pool: Any
    _pool_opened: bool

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


def _masked_dsn(dsn: str) -> str:
    """DSN with any password masked, for log lines."""
    masked = re.sub(r"(password=)[^ ]+", r"\1***", dsn)
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1***\2", masked)
