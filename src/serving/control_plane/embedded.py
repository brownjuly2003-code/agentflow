"""Embedded (DuckDB) control-plane store — the single-replica default profile.

Extracted from ``webhook_dispatcher`` in ADR 0010 rollout slice 1: the table
DDL, SQL shapes and catalog-DDL-lock behavior are byte-compatible with the
pre-port code, so existing deployments and the pinned regression suites see
no behavior change.

"Claims" here are trivially exclusive: this store is only ever used by one
process (the Helm chart refuses multi-replica renders on the embedded
profile), so ``claim_due_webhook_deliveries`` is a plain due-scan without
marking rows in-flight. The PostgreSQL adapter (slice 5) implements the same
contract with ``FOR UPDATE SKIP LOCKED`` plus a lease column.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import structlog

from src.db_concurrency import catalog_ddl_lock
from src.serving.duckdb_connection import connect_duckdb

from .store import AUTO_RESOLVE_NOTE, ControlPlaneStore, OutboxEntry, TriageState, WebhookQueueRow

logger = structlog.get_logger()

# One owning DuckDB connection per usage-db path, kept open for the life of the
# process; callers work through `.cursor()` children of it.
#
# Every authenticated request writes an `api_usage` row from a worker thread,
# and the analytics/admin routers build a throwaway store per request. Opening
# a fresh `duckdb.connect(path)` for each of those races DuckDB's instance
# cache: when the last connection to a file closes while another is opening,
# the file is momentarily attached by two database instances and DuckDB raises
# `BinderException: Unique file handle conflict`. That escaped the auth
# middleware as a 500 on requests which had otherwise succeeded (2026-07-09
# Load Test: 19 of 1712). Holding the connection open removes the
# destroy/recreate window; a cursor is DuckDB's thread-safe unit, the same
# shape `DuckDBPool` uses for the serving database.
_USAGE_CONNECTIONS: dict[str, duckdb.DuckDBPyConnection] = {}
_USAGE_CONNECTIONS_LOCK = threading.Lock()


def _usage_connection(path: str) -> duckdb.DuckDBPyConnection:
    conn = _USAGE_CONNECTIONS.get(path)
    if conn is not None:
        return conn
    with _USAGE_CONNECTIONS_LOCK:
        conn = _USAGE_CONNECTIONS.get(path)
        if conn is None:
            conn = connect_duckdb(path)
            _USAGE_CONNECTIONS[path] = conn
    return conn


def _drop_usage_connection(path: str) -> None:
    """Forget a connection whose instance may be unusable, so the next caller
    reopens it instead of inheriting the failure."""
    with _USAGE_CONNECTIONS_LOCK:
        conn = _USAGE_CONNECTIONS.pop(path, None)
    if conn is not None:
        try:
            conn.close()
        except duckdb.Error:  # pragma: no cover - closing an already-dead handle
            pass


def close_usage_connections() -> None:
    """Close every cached usage-db connection. Tests that delete their temp
    database files call this first — Windows will not unlink an open file."""
    with _USAGE_CONNECTIONS_LOCK:
        connections = list(_USAGE_CONNECTIONS.values())
        _USAGE_CONNECTIONS.clear()
    for conn in connections:
        try:
            conn.close()
        except duckdb.Error:  # pragma: no cover
            pass


try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


def ensure_webhook_deliveries_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Serialize the lazy DDL: the offloaded read handler calls this on a worker
    # thread, and concurrent CREATE on a cold DuckDB catalog conflicts (across
    # tables too). (audit_30 A2 follow-up: #120 offload race)
    with catalog_ddl_lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                delivery_id VARCHAR,
                webhook_id VARCHAR,
                event_id VARCHAR,
                event_type VARCHAR,
                attempt INTEGER,
                status_code INTEGER,
                success BOOLEAN,
                error TEXT,
                delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def ensure_webhook_delivery_queue_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Durable per-(webhook, event) delivery state for re-drive.

    Distinct from ``webhook_deliveries`` (an append-only attempt *log*): this is
    the *state* table whose ``(webhook_id, event_id)`` primary key dedupes
    enqueues and whose ``status`` / ``next_attempt_at`` drive retries that
    survive a process restart. ``body`` stores the canonical payload so a
    delivery can be replayed without re-reading ``pipeline_events``.
    """
    # Serialize the lazy DDL behind the shared catalog lock, exactly like the
    # three #123-locked ``ensure_*`` siblings: the dispatcher creates this table
    # on the shared serving connection from the event loop while an offloaded
    # read handler runs its own ``ensure_*`` on a worker thread, and concurrent
    # CREATE on a cold DuckDB catalog conflicts across *different* tables too.
    # Omitting the lock here left the cross-table "Catalog write-write conflict"
    # the #123 fix set out to remove still reachable on a cold restart.
    # (audit_30 D2/A2 follow-up residual)
    with catalog_ddl_lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_delivery_queue (
                webhook_id VARCHAR NOT NULL,
                event_id VARCHAR NOT NULL,
                tenant VARCHAR,
                event_type VARCHAR,
                body VARCHAR,
                status VARCHAR NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TIMESTAMP,
                last_status_code INTEGER,
                last_error VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (webhook_id, event_id)
            )
            """
        )


def ensure_alert_history_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Moved verbatim from alerts/history.py in ADR 0010 slice 2; same
    # catalog-DDL-lock discipline as its ensure_webhook_* siblings above
    # (audit_30 A2 follow-up: #120 offload race).
    with catalog_ddl_lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_history (
                delivery_id VARCHAR,
                alert_id VARCHAR,
                alert_name VARCHAR,
                metric VARCHAR,
                current_value DOUBLE,
                previous_value DOUBLE,
                change_pct DOUBLE,
                threshold DOUBLE,
                condition VARCHAR,
                metric_window VARCHAR,
                tenant VARCHAR,
                event_type VARCHAR,
                status_code INTEGER,
                success BOOLEAN,
                error TEXT,
                payload JSON,
                triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def ensure_outbox_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Moved verbatim from processing/outbox.py in ADR 0010 slice 3. Unlike its
    # ensure_* siblings above, this one is NOT called lazily by the methods
    # below — only once, from ensure_outbox_schema at OutboxProcessor /
    # EventReplayer construction (see the store module docstring for why).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            payload JSON NOT NULL,
            topic TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP,
            status TEXT DEFAULT 'pending',
            retry_count INTEGER DEFAULT 0,
            next_attempt_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_error TEXT
        )
        """
    )


def ensure_dead_letter_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Moved verbatim from processing/event_replayer.py in ADR 0010 slice 3;
    # same catalog-DDL-lock discipline as the ensure_* siblings above (the
    # deadletter router's read handlers call this lazily per offloaded scan —
    # audit_30 A2 follow-up: #120 offload race).
    with catalog_ddl_lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dead_letter_events (
                event_id TEXT PRIMARY KEY,
                tenant_id TEXT DEFAULT 'default',
                event_type TEXT,
                payload JSON,
                failure_reason TEXT,
                failure_detail TEXT,
                received_at TIMESTAMP,
                retry_count INTEGER DEFAULT 0,
                last_retried_at TIMESTAMP,
                status TEXT DEFAULT 'failed'
            )
            """
        )
        conn.execute(
            "ALTER TABLE dead_letter_events "
            "ADD COLUMN IF NOT EXISTS tenant_id TEXT DEFAULT 'default'"
        )


def ensure_triage_table(conn: duckdb.DuckDBPyConnection) -> None:
    """``ops_exception_triage`` (ops-surfaces-spec.md §4.2) — control-plane
    state class 7, extending ADR 0010's inventory. Overlay for
    ``webhook_delivery``/``reconciliation`` findings only; dead-letter items
    get no overlay row (I6)."""
    with catalog_ddl_lock:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ops_exception_triage (
                item_id TEXT PRIMARY KEY,
                tenant_id TEXT,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                first_seen_at TIMESTAMP,
                last_seen_at TIMESTAMP,
                resolved_at TIMESTAMP,
                note TEXT
            )
            """
        )


def ensure_api_usage_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Moved verbatim from auth/usage_table.py in ADR 0010 slice 4. Runs on a
    # dedicated per-call connection (never the shared query_engine conn — see
    # the store module docstring), so unlike its ensure_* siblings above it
    # needs no catalog_ddl_lock.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage (
            tenant TEXT,
            key_name TEXT,
            endpoint TEXT,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info('api_usage')").fetchall()}
    if "key_id" not in columns:
        conn.execute("ALTER TABLE api_usage ADD COLUMN key_id TEXT")
    if "key_slot" not in columns:
        conn.execute("ALTER TABLE api_usage ADD COLUMN key_slot TEXT")


def ensure_api_sessions_table(conn: duckdb.DuckDBPyConnection) -> None:
    # Moved verbatim from api/analytics.py in ADR 0010 slice 4 (that module's
    # own path-based `ensure_analytics_table` stays put — it is independently
    # pinned by main.py's boot call and a middleware test's monkeypatch — so
    # this is a second, conn-based copy for the store's own methods).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_sessions (
            request_id TEXT PRIMARY KEY,
            tenant TEXT,
            key_name TEXT,
            endpoint TEXT,
            method TEXT,
            status_code INTEGER,
            duration_ms FLOAT,
            cache_hit BOOLEAN,
            entity_type TEXT,
            metric_name TEXT,
            query_engine TEXT,
            ts TIMESTAMP DEFAULT NOW()
        )
        """
    )
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('api_sessions')").fetchall()
    }
    for column_name, column_type in (
        ("entity_id", "TEXT"),
        ("query_text", "TEXT"),
    ):
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE api_sessions ADD COLUMN {column_name} {column_type}")


def _window_to_interval(window: str) -> str:
    # Moved verbatim from api/analytics.py in ADR 0010 slice 4 — DuckDB
    # interval-literal syntax is an adapter detail; a future PostgreSQL
    # adapter parses `window` into its own interval syntax.
    match = re.fullmatch(r"(\d+)([mhd])", window.strip())
    if match is None:
        raise ValueError("Invalid window. Use formats like 15m, 1h, or 7d.")
    value, unit = match.groups()
    if unit == "m":
        return f"{value} minutes"
    if unit == "h":
        return f"{value} hours"
    return f"{value} days"


class EmbeddedControlPlaneStore(ControlPlaneStore):
    """Control-plane state on the embedded serving DuckDB connection (queue,
    log and history tables) plus the YAML-backed alert-rule repository.

    ``conn_provider`` is resolved per call (not captured once): tests and the
    lifespan may swap ``app.state.query_engine``, and the store must follow
    the live connection exactly like the pre-port ``_conn`` lookups did.
    ``alert_rules_path_provider`` is resolved the same way — the alert config
    path is per-app configurable (``app.state.alert_config_path``) and tests
    swap it per case.
    """

    def __init__(
        self,
        conn_provider: Callable[[], duckdb.DuckDBPyConnection] | None = None,
        *,
        alert_rules_path_provider: Callable[[], Path] | None = None,
        usage_db_path_provider: Callable[[], Path | str] | None = None,
        webhook_registrations_path_provider: Callable[[], Path] | None = None,
    ) -> None:
        self._conn_provider = conn_provider
        self._alert_rules_path_provider = alert_rules_path_provider
        self._usage_db_path_provider = usage_db_path_provider
        self._webhook_registrations_path_provider = webhook_registrations_path_provider
        # Set once by _ensure_usage_db_connection's IOException fallback and
        # then sticky for the rest of this store's lifetime — mirrors the
        # pre-port code permanently reassigning `AuthManager.db_path` in
        # place (module docstring: usage/session state is never on the
        # shared conn_provider connection, so this override never touches
        # the app's query engine).
        self._usage_db_path_override: Path | None = None

    @property
    def _alert_rules_path(self) -> Path:
        if self._alert_rules_path_provider is None:
            raise RuntimeError(
                "EmbeddedControlPlaneStore was constructed without an "
                "alert_rules_path_provider; alert-rule repository methods "
                "are unavailable."
            )
        return self._alert_rules_path_provider()

    @property
    def _webhook_registrations_path(self) -> Path:
        if self._webhook_registrations_path_provider is None:
            raise RuntimeError(
                "EmbeddedControlPlaneStore was constructed without a "
                "webhook_registrations_path_provider; webhook-registration "
                "repository methods are unavailable."
            )
        return self._webhook_registrations_path_provider()

    @property
    def _conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn_provider is None:
            raise RuntimeError(
                "EmbeddedControlPlaneStore was constructed without a "
                "conn_provider; webhook/alert/outbox methods are unavailable."
            )
        return self._conn_provider()

    @property
    def _usage_db_path(self) -> Path:
        if self._usage_db_path_override is not None:
            return self._usage_db_path_override
        if self._usage_db_path_provider is None:
            raise RuntimeError(
                "EmbeddedControlPlaneStore was constructed without a "
                "usage_db_path_provider; usage/session methods are "
                "unavailable."
            )
        return Path(self._usage_db_path_provider())

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
        conn = self._conn
        ensure_webhook_delivery_queue_table(conn)
        existing = conn.execute(
            "SELECT 1 FROM webhook_delivery_queue WHERE webhook_id = ? AND event_id = ?",
            [webhook_id, event_id],
        ).fetchone()
        if existing is not None:
            return False
        now = datetime.now(UTC)
        conn.execute(
            """
            INSERT INTO webhook_delivery_queue
                (webhook_id, event_id, tenant, event_type, body, status, attempts,
                 next_attempt_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            [webhook_id, event_id, tenant, event_type, body, now, now, now],
        )
        return True

    def claim_due_webhook_deliveries(self, *, limit: int) -> list[WebhookQueueRow]:
        conn = self._conn
        ensure_webhook_delivery_queue_table(conn)
        rows = conn.execute(
            "SELECT webhook_id, event_id, tenant, event_type, body "
            "FROM webhook_delivery_queue "
            "WHERE status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY created_at ASC LIMIT ?",
            [datetime.now(UTC), limit],
        ).fetchall()
        return [
            WebhookQueueRow(
                webhook_id=webhook_id,
                event_id=event_id,
                tenant=tenant,
                event_type=event_type,
                body=body,
            )
            for webhook_id, event_id, tenant, event_type, body in rows
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
        conn = self._conn
        now = datetime.now(UTC)
        if success:
            conn.execute(
                "UPDATE webhook_delivery_queue SET status = 'delivered', "
                "last_status_code = ?, last_error = NULL, updated_at = ? "
                "WHERE webhook_id = ? AND event_id = ?",
                [status_code, now, webhook_id, event_id],
            )
            return
        row = conn.execute(
            "SELECT attempts FROM webhook_delivery_queue WHERE webhook_id = ? AND event_id = ?",
            [webhook_id, event_id],
        ).fetchone()
        attempts = (row[0] if row else 0) + 1
        if attempts >= max_attempts:
            conn.execute(
                "UPDATE webhook_delivery_queue SET status = 'dead', attempts = ?, "
                "last_status_code = ?, last_error = ?, next_attempt_at = NULL, updated_at = ? "
                "WHERE webhook_id = ? AND event_id = ?",
                [attempts, status_code, error, now, webhook_id, event_id],
            )
            return
        delay = backoff_seconds[min(attempts - 1, len(backoff_seconds) - 1)]
        conn.execute(
            "UPDATE webhook_delivery_queue SET status = 'pending', attempts = ?, "
            "last_status_code = ?, last_error = ?, next_attempt_at = ?, updated_at = ? "
            "WHERE webhook_id = ? AND event_id = ?",
            [
                attempts,
                status_code,
                error,
                now + timedelta(seconds=delay),
                now,
                webhook_id,
                event_id,
            ],
        )

    def park_webhook_delivery(self, *, webhook_id: str, event_id: str, error: str) -> None:
        self._conn.execute(
            "UPDATE webhook_delivery_queue SET status = 'dead', "
            "last_error = ?, next_attempt_at = NULL, updated_at = ? "
            "WHERE webhook_id = ? AND event_id = ?",
            [error, datetime.now(UTC), webhook_id, event_id],
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
        conn = self._conn
        ensure_webhook_deliveries_table(conn)
        conn.execute(
            """
            INSERT INTO webhook_deliveries (
                delivery_id, webhook_id, event_id, event_type, attempt,
                status_code, success, error, delivered_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                delivery_id,
                webhook_id,
                event_id,
                event_type,
                attempt,
                status_code,
                success,
                error,
                datetime.now(UTC),
            ],
        )

    def get_webhook_delivery_logs(self, webhook_id: str, *, limit: int = 20) -> list[dict]:
        # A dedicated cursor per read — not the shared connection — keeps
        # concurrent reads on worker threads (run_in_threadpool) from colliding
        # on the connection. (audit_30_06_26.md A2)
        cursor = self._conn.cursor()
        try:
            ensure_webhook_deliveries_table(cursor)
            result = cursor.execute(
                """
                SELECT delivery_id, webhook_id, event_id, event_type, attempt,
                       status_code, success, error, delivered_at
                FROM webhook_deliveries
                WHERE webhook_id = ?
                ORDER BY delivered_at DESC
                LIMIT ?
                """,
                [webhook_id, limit],
            )
            columns = [description[0] for description in result.description]
            return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
        finally:
            cursor.close()

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
        conn = self._conn
        ensure_alert_history_table(conn)
        conn.execute(
            """
            INSERT INTO alert_history (
                delivery_id, alert_id, alert_name, metric, current_value,
                previous_value, change_pct, threshold, condition, metric_window,
                tenant, event_type, status_code, success, error, payload, triggered_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
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
                datetime.now(UTC),
            ],
        )

    def get_alert_delivery_history(self, alert_id: str, *, limit: int = 20) -> list[dict]:
        # A dedicated cursor per read — not the shared connection — keeps
        # concurrent reads on worker threads (run_in_threadpool) from colliding
        # on the connection. (audit_30_06_26.md A2)
        cursor = self._conn.cursor()
        try:
            ensure_alert_history_table(cursor)
            result = cursor.execute(
                """
                SELECT delivery_id, alert_id, alert_name, metric, current_value,
                       previous_value, change_pct, threshold, condition,
                       metric_window AS window,
                       tenant, event_type, status_code, success, error, payload, triggered_at
                FROM alert_history
                WHERE alert_id = ?
                ORDER BY triggered_at DESC
                LIMIT ?
                """,
                [alert_id, limit],
            )
            columns = [description[0] for description in result.description]
            records = [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
        finally:
            cursor.close()
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
        # Byte-compatible with the pre-port webhook_dispatcher.load_webhooks
        # YAML round-trip (ADR 0010 slice 5) — existing config/webhooks.yaml
        # files keep working unchanged.
        path = self._webhook_registrations_path
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        data = yaml.safe_load(raw) if yaml is not None else json.loads(raw)
        return list((data or {}).get("webhooks", []))

    def save_webhook_registrations(self, registrations: list[dict]) -> None:
        path = self._webhook_registrations_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"webhooks": registrations}
        content = (
            yaml.safe_dump(payload, sort_keys=False)
            if yaml is not None
            else json.dumps(payload, indent=2)
        )
        path.write_text(content, encoding="utf-8")

    # --- alert rule repository (mutable runtime state) ------------------------

    def load_alert_rules(self) -> list[dict]:
        path = self._alert_rules_path
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        data = yaml.safe_load(raw) if yaml is not None else json.loads(raw)
        return list((data or {}).get("alerts", []))

    def save_alert_rules(self, rules: list[dict]) -> None:
        path = self._alert_rules_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"alerts": rules}
        content = (
            yaml.safe_dump(payload, sort_keys=False)
            if yaml is not None
            else json.dumps(payload, indent=2)
        )
        path.write_text(content, encoding="utf-8", newline="\n")

    def claim_alert_tick(self, rule_id: str, *, lease_seconds: float) -> bool:
        # One process, one dispatcher loop: every claim is granted — the same
        # degenerate exclusivity as claim_due_webhook_deliveries above. The
        # PostgreSQL adapter takes a real lease here (ADR 0010 §2).
        return True

    def complete_alert_tick(self, rule_id: str, *, record: dict | None) -> None:
        if record is None:
            # Nothing advanced and embedded claims hold no lease to release.
            return
        rules = self.load_alert_rules()
        for index, existing in enumerate(rules):
            if existing.get("id") == rule_id:
                rules[index] = record
                break
        else:
            rules.append(record)
        self.save_alert_rules(rules)

    # --- replay outbox + dead-letter (invariant 8: one transaction) -----------

    def ensure_outbox_schema(self) -> None:
        ensure_outbox_table(self._conn)
        ensure_dead_letter_table(self._conn)

    def claim_due_outbox_entries(self, *, limit: int = 100) -> list[OutboxEntry]:
        rows = self._conn.execute(
            """
            SELECT id, event_id, payload, topic, retry_count
            FROM outbox
            WHERE status = 'pending'
              AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
            ORDER BY created_at
            LIMIT ?
            """,
            [datetime.now(UTC), limit],
        ).fetchall()
        return [
            OutboxEntry(
                id=row_id, event_id=event_id, payload=payload, topic=topic, retry_count=retry_count
            )
            for row_id, event_id, payload, topic, retry_count in rows
        ]

    def get_pending_outbox_entry(self, outbox_id: str) -> OutboxEntry | None:
        row = self._conn.execute(
            """
            SELECT id, event_id, payload, topic, retry_count
            FROM outbox
            WHERE id = ?
              AND status = 'pending'
            """,
            [outbox_id],
        ).fetchone()
        if row is None:
            return None
        row_id, event_id, payload, topic, retry_count = row
        return OutboxEntry(
            id=row_id, event_id=event_id, payload=payload, topic=topic, retry_count=retry_count
        )

    def mark_outbox_sent(self, *, outbox_id: str, event_id: str) -> None:
        conn = self._conn
        sent_at = datetime.now(UTC)
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(
                """
                UPDATE outbox
                SET status = 'sent',
                    sent_at = ?,
                    last_error = NULL
                WHERE id = ?
                """,
                [sent_at, outbox_id],
            )
            conn.execute(
                "UPDATE dead_letter_events SET status = 'replayed' WHERE event_id = ?",
                [event_id],
            )
            conn.execute("COMMIT")
        # rollback must preserve the original replay failure
        except Exception:  # nosec B110
            # Transaction rollback must happen before unexpected errors propagate.
            conn.execute("ROLLBACK")
            raise

    def schedule_outbox_retry(
        self,
        *,
        outbox_id: str,
        event_id: str,
        retry_count: int,
        error_message: str,
        max_retries: int,
    ) -> None:
        conn = self._conn
        status = "pending"
        retry_delay_seconds = 2**retry_count
        is_kafka_error = (
            error_message.startswith("KafkaError{")
            or "Kafka message(s) were not delivered" in error_message
        )
        if is_kafka_error:
            retry_delay_seconds = max(retry_delay_seconds, 30)
        next_attempt_at: datetime | None = datetime.now(UTC) + timedelta(
            seconds=retry_delay_seconds
        )
        conn.execute("BEGIN TRANSACTION")
        try:
            if retry_count >= max_retries:
                status = "failed"
                next_attempt_at = None
            conn.execute(
                """
                UPDATE outbox
                SET status = ?,
                    retry_count = ?,
                    next_attempt_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                [status, retry_count, next_attempt_at, error_message, outbox_id],
            )
            if status == "failed":
                conn.execute(
                    "UPDATE dead_letter_events SET status = 'failed' WHERE event_id = ?",
                    [event_id],
                )
            conn.execute("COMMIT")
        # rollback must preserve the original retry scheduling failure
        except Exception:  # nosec B110
            # Transaction rollback must happen before unexpected errors propagate.
            conn.execute("ROLLBACK")
            raise

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
        conn = self._conn
        encoded_payload = json.dumps(payload)
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(
                """
                UPDATE dead_letter_events
                SET payload = ?, status = 'replay_pending', retry_count = ?, last_retried_at = ?
                WHERE event_id = ?
                """,
                [encoded_payload, retry_count, replayed_at, event_id],
            )
            conn.execute(
                """
                INSERT INTO outbox (
                    id,
                    event_id,
                    payload,
                    topic,
                    created_at,
                    sent_at,
                    status,
                    retry_count,
                    next_attempt_at,
                    last_error
                )
                VALUES (?, ?, ?, ?, ?, NULL, 'pending', 0, ?, NULL)
                """,
                [outbox_id, event_id, encoded_payload, topic, replayed_at, replayed_at],
            )
            conn.execute("COMMIT")
        # rollback must preserve the original replay failure
        except Exception:  # nosec B110
            # Transaction rollback must happen before unexpected errors propagate.
            conn.execute("ROLLBACK")
            raise

    def get_dead_letter_event_for_replay(self, event_id: str) -> dict | None:
        row = self._conn.execute(
            """
            SELECT
                event_id,
                payload,
                retry_count
            FROM dead_letter_events
            WHERE event_id = ?
            """,
            [event_id],
        ).fetchone()
        if row is None:
            return None
        return {"event_id": row[0], "payload": row[1], "retry_count": row[2]}

    def dismiss_dead_letter_event(self, event_id: str) -> None:
        self._conn.execute(
            "UPDATE dead_letter_events SET status = 'dismissed' WHERE event_id = ?",
            [event_id],
        )

    def dead_letter_event_exists(self, event_id: str, tenant_id: str) -> bool:
        cursor = self._conn.cursor()
        try:
            ensure_dead_letter_table(cursor)
            row = cursor.execute(
                """
                SELECT event_id
                FROM dead_letter_events
                WHERE event_id = ? AND COALESCE(tenant_id, 'default') = ?
                """,
                [event_id, tenant_id],
            ).fetchone()
        finally:
            cursor.close()
        return row is not None

    def get_dead_letter_event(self, event_id: str, tenant_id: str) -> dict | None:
        cursor = self._conn.cursor()
        try:
            ensure_dead_letter_table(cursor)
            row = cursor.execute(
                """
                SELECT
                    event_id,
                    event_type,
                    payload,
                    failure_reason,
                    failure_detail,
                    received_at,
                    retry_count,
                    last_retried_at,
                    status
                FROM dead_letter_events
                WHERE event_id = ?
                  AND COALESCE(tenant_id, 'default') = ?
                """,
                [event_id, tenant_id],
            ).fetchone()
        finally:
            cursor.close()
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
        cursor = self._conn.cursor()
        try:
            ensure_dead_letter_table(cursor)
            params: list[object]
            if reason is not None:
                params = [tenant_id, reason]
                total_row = cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM dead_letter_events
                    WHERE status = 'failed'
                      AND COALESCE(tenant_id, 'default') = ?
                      AND failure_reason = ?
                    """,
                    params,
                ).fetchone()
            else:
                params = [tenant_id]
                total_row = cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM dead_letter_events
                    WHERE status = 'failed'
                      AND COALESCE(tenant_id, 'default') = ?
                    """,
                    params,
                ).fetchone()
            total = int(total_row[0]) if total_row and total_row[0] is not None else 0
            offset = (page - 1) * page_size
            if reason is not None:
                rows = cursor.execute(
                    """
                    SELECT
                        event_id,
                        event_type,
                        failure_reason,
                        failure_detail,
                        received_at,
                        retry_count,
                        last_retried_at,
                        status
                    FROM dead_letter_events
                    WHERE status = 'failed'
                      AND COALESCE(tenant_id, 'default') = ?
                      AND failure_reason = ?
                    ORDER BY received_at DESC, event_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    [tenant_id, reason, page_size, offset],
                ).fetchall()
            else:
                rows = cursor.execute(
                    """
                    SELECT
                        event_id,
                        event_type,
                        failure_reason,
                        failure_detail,
                        received_at,
                        retry_count,
                        last_retried_at,
                        status
                    FROM dead_letter_events
                    WHERE status = 'failed'
                      AND COALESCE(tenant_id, 'default') = ?
                    ORDER BY received_at DESC, event_id ASC
                    LIMIT ? OFFSET ?
                    """,
                    [tenant_id, page_size, offset],
                ).fetchall()
        finally:
            cursor.close()
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
        cursor = self._conn.cursor()
        try:
            ensure_dead_letter_table(cursor)
            rows = cursor.execute(
                """
                SELECT failure_reason, COUNT(*)
                FROM dead_letter_events
                WHERE status = 'failed'
                  AND COALESCE(tenant_id, 'default') = ?
                GROUP BY failure_reason
                ORDER BY failure_reason
                """,
                [tenant_id],
            ).fetchall()
            last_24h_row = cursor.execute(
                """
                SELECT COUNT(*)
                FROM dead_letter_events
                WHERE status = 'failed'
                  AND COALESCE(tenant_id, 'default') = ?
                  AND received_at >= NOW() - INTERVAL '24 hours'
                """,
                [tenant_id],
            ).fetchone()
            trend_rows = cursor.execute(
                """
                SELECT DATE_TRUNC('hour', received_at) AS hour_bucket, COUNT(*)
                FROM dead_letter_events
                WHERE status = 'failed'
                  AND COALESCE(tenant_id, 'default') = ?
                  AND received_at >= NOW() - INTERVAL '24 hours'
                GROUP BY hour_bucket
                ORDER BY hour_bucket
                """,
                [tenant_id],
            ).fetchall()
        finally:
            cursor.close()
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
        cursor = self._conn.cursor()
        try:
            ensure_dead_letter_table(cursor)
            rows = cursor.execute(
                """
                SELECT
                    event_id,
                    event_type,
                    failure_reason,
                    failure_detail,
                    received_at,
                    retry_count,
                    last_retried_at,
                    status
                FROM dead_letter_events
                WHERE COALESCE(tenant_id, 'default') = ?
                ORDER BY received_at DESC
                """,
                [tenant_id],
            ).fetchall()
        finally:
            cursor.close()
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
        cursor = self._conn.cursor()
        try:
            ensure_dead_letter_table(cursor)
            cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
            rows = cursor.execute(
                """
                SELECT
                    event_id,
                    event_type,
                    failure_reason,
                    failure_detail,
                    received_at,
                    retry_count,
                    last_retried_at,
                    status
                FROM dead_letter_events
                WHERE COALESCE(tenant_id, 'default') = ?
                  AND status = 'replay_pending'
                  AND last_retried_at IS NOT NULL
                  AND last_retried_at < ?
                ORDER BY last_retried_at ASC
                """,
                [tenant_id, cutoff],
            ).fetchall()
        finally:
            cursor.close()
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
        cursor = self._conn.cursor()
        try:
            ensure_dead_letter_table(cursor)
            row = cursor.execute(
                """
                SELECT COUNT(*)
                FROM dead_letter_events
                WHERE COALESCE(tenant_id, 'default') = ?
                  AND status IN ('replayed', 'dismissed')
                """,
                [tenant_id],
            ).fetchone()
        finally:
            cursor.close()
        return int(row[0]) if row and row[0] is not None else 0

    # --- exception-inbox triage overlay ---------------------------------------

    def ensure_triage_schema(self) -> None:
        ensure_triage_table(self._conn)

    def list_triage_states(self, *, tenant_id: str, source: str | None = None) -> list[TriageState]:
        cursor = self._conn.cursor()
        try:
            ensure_triage_table(cursor)
            select = (
                "SELECT item_id, tenant_id, source, status, first_seen_at, "
                "last_seen_at, resolved_at, note FROM ops_exception_triage "
                "WHERE tenant_id = ?"
            )
            if source is not None:
                rows = cursor.execute(select + " AND source = ?", [tenant_id, source]).fetchall()
            else:
                rows = cursor.execute(select, [tenant_id]).fetchall()
        finally:
            cursor.close()
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
        conn = self._conn
        ensure_triage_table(conn)
        existing = conn.execute(
            "SELECT status FROM ops_exception_triage WHERE item_id = ?",
            [item_id],
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO ops_exception_triage
                    (item_id, tenant_id, source, status, first_seen_at, last_seen_at,
                     resolved_at, note)
                VALUES (?, ?, ?, 'open', ?, ?, NULL, NULL)
                """,
                [item_id, tenant_id, source, seen_at, seen_at],
            )
            return
        (status,) = existing
        if status != "resolved":
            conn.execute(
                "UPDATE ops_exception_triage SET last_seen_at = ? WHERE item_id = ?",
                [seen_at, item_id],
            )
            return
        # Resolved: reopen only if this occurrence is strictly after
        # resolved_at — the comparison runs in SQL (not Python) so DuckDB's
        # own aware-to-local-naive coercion applies identically to both
        # sides, whether the caller passed an aware or naive `seen_at`.
        conn.execute(
            """
            UPDATE ops_exception_triage
            SET status = 'open', last_seen_at = ?, resolved_at = NULL, note = NULL
            WHERE item_id = ? AND resolved_at IS NOT NULL AND CAST(? AS TIMESTAMP) > resolved_at
            """,
            [seen_at, item_id, seen_at],
        )

    def auto_resolve_missing_triage_findings(
        self,
        *,
        tenant_id: str,
        source: str,
        seen_item_ids: Sequence[str],
        resolved_at: datetime,
    ) -> None:
        conn = self._conn
        ensure_triage_table(conn)
        seen = set(seen_item_ids)
        rows = conn.execute(
            """
            SELECT item_id FROM ops_exception_triage
            WHERE tenant_id = ? AND source = ? AND status != 'resolved'
            """,
            [tenant_id, source],
        ).fetchall()
        for (item_id,) in rows:
            if item_id in seen:
                continue
            conn.execute(
                """
                UPDATE ops_exception_triage
                SET status = 'resolved', resolved_at = ?, note = ?
                WHERE item_id = ? AND tenant_id = ?
                """,
                [resolved_at, AUTO_RESOLVE_NOTE, item_id, tenant_id],
            )

    def set_triage_state(
        self, *, item_id: str, tenant_id: str, status: str, note: str | None = None
    ) -> bool:
        conn = self._conn
        ensure_triage_table(conn)
        existing = conn.execute(
            "SELECT 1 FROM ops_exception_triage WHERE item_id = ? AND tenant_id = ?",
            [item_id, tenant_id],
        ).fetchone()
        if existing is None:
            return False
        resolved_at = datetime.now(UTC) if status == "resolved" else None
        conn.execute(
            """
            UPDATE ops_exception_triage
            SET status = ?, resolved_at = ?, note = COALESCE(?, note)
            WHERE item_id = ? AND tenant_id = ?
            """,
            [status, resolved_at, note, item_id, tenant_id],
        )
        return True

    def count_triage_manual_actions(self, tenant_id: str) -> int:
        # Excludes rows auto-resolved by `auto_resolve_missing_triage_findings`
        # (note == AUTO_RESOLVE_NOTE) — the KPI counts human decisions only.
        conn = self._conn
        ensure_triage_table(conn)
        row = conn.execute(
            """
            SELECT COUNT(*) FROM ops_exception_triage
            WHERE tenant_id = ?
              AND (status = 'acknowledged'
                   OR (status = 'resolved' AND (note IS NULL OR note != ?)))
            """,
            [tenant_id, AUTO_RESOLVE_NOTE],
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # --- webhook dead deliveries for the exception inbox ----------------------

    def list_dead_webhook_deliveries(self, tenant_id: str | None = None) -> list[dict]:
        conn = self._conn
        ensure_webhook_delivery_queue_table(conn)
        select = (
            "SELECT webhook_id, event_id, tenant, event_type, body, attempts, "
            "last_status_code, last_error, created_at, updated_at "
            "FROM webhook_delivery_queue WHERE status = 'dead'"
        )
        if tenant_id is not None:
            rows = conn.execute(
                select + " AND tenant = ? ORDER BY updated_at DESC", [tenant_id]
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

    def _usage_cursor(self) -> duckdb.DuckDBPyConnection:
        """A cursor on the process-wide connection for this store's usage db.

        Drop-in for the old per-call ``connect_duckdb``: callers still own the
        handle and still ``close()`` it, but closing a cursor leaves the owning
        connection — and therefore the DuckDB instance — alive. The path is
        resolved on every call so the Windows fallback in
        ``ensure_usage_schema`` (which swaps ``_usage_db_path_override``
        mid-flight) lands on the new file.
        """
        path = str(self._usage_db_path)
        try:
            return _usage_connection(path).cursor()
        except duckdb.Error:
            _drop_usage_connection(path)
            raise

    def ensure_usage_schema(self) -> None:
        # Moved verbatim from auth/usage_table.py's ensure_usage_table
        # (ADR 0010 slice 4), including the Windows file-lock fallback: if
        # the configured usage db path can't be opened, fall back to a
        # per-process temp file and stick with it for this store's lifetime.
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.IOException as exc:
                if (
                    os.getenv("AGENTFLOW_USAGE_DB_PATH") is None
                    and self._usage_db_path.name == "agentflow_api.duckdb"
                ):
                    fallback_path = (
                        Path(os.getenv("TEMP", "."))
                        / f"agentflow_api_{os.getpid()}_{time.time_ns()}.duckdb"
                    )
                    logger.warning(
                        "usage_db_path_fallback",
                        original=str(self._usage_db_path),
                        fallback=str(fallback_path),
                        error=str(exc),
                    )
                    self._usage_db_path_override = fallback_path
                    conn = self._usage_cursor()
                else:
                    if attempt == 9:
                        raise
                    time.sleep(0.01 * (attempt + 1))
                    continue
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                ensure_api_usage_table(conn)
                return
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()

    def record_api_usage(
        self,
        *,
        tenant: str,
        key_name: str,
        endpoint: str,
        key_id: str | None,
        key_slot: str,
    ) -> None:
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                conn.execute(
                    """
                    INSERT INTO api_usage (tenant, key_name, endpoint, key_id, key_slot)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [tenant, key_name, endpoint, key_id, key_slot],
                )
                return
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()

    def get_usage_by_tenant(self) -> list[dict]:
        conn = self._usage_cursor()
        try:
            rows = conn.execute(
                """
                SELECT tenant, COUNT(*) AS requests_last_24h
                FROM api_usage
                WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                GROUP BY tenant
                ORDER BY tenant
                """
            ).fetchall()
        finally:
            conn.close()
        return [
            {"tenant": tenant, "requests_last_24h": requests_last_24h}
            for tenant, requests_last_24h in rows
        ]

    def get_usage_by_key(self) -> dict[tuple[str, str], int]:
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                rows = conn.execute(
                    """
                    SELECT tenant, key_name, COUNT(*) AS requests_last_24h
                    FROM api_usage
                    WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                    GROUP BY tenant, key_name
                    """
                ).fetchall()
                return {
                    (tenant, key_name): requests_last_24h
                    for tenant, key_name, requests_last_24h in rows
                }
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()
        return {}

    def get_old_key_usage_by_key_id(self) -> dict[str, int]:
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                rows = conn.execute(
                    """
                    SELECT key_id, COUNT(*) AS requests_last_hour
                    FROM api_usage
                    WHERE key_slot = 'previous'
                      AND ts >= CURRENT_TIMESTAMP - INTERVAL '1 hour'
                      AND key_id IS NOT NULL
                    GROUP BY key_id
                    """
                ).fetchall()
                return dict(rows)
            except duckdb.Error:
                if attempt == 9:
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()
        return {}

    # --- API session analytics ------------------------------------------------

    def record_api_session(self, request_id: str, record: dict) -> None:
        for attempt in range(10):
            try:
                conn = self._usage_cursor()
            except duckdb.Error as exc:
                if attempt == 9:
                    logger.warning(
                        "analytics_session_write_skipped",
                        stage="connect",
                        db_path=str(self._usage_db_path),
                        request_id=request_id,
                        tenant=record.get("tenant"),
                        endpoint=record.get("endpoint"),
                        attempts=attempt + 1,
                        error=str(exc),
                        exc_info=True,
                    )
                    return
                time.sleep(0.01 * (attempt + 1))
                continue

            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO api_sessions (
                        request_id,
                        tenant,
                        key_name,
                        endpoint,
                        method,
                        status_code,
                        duration_ms,
                        cache_hit,
                        entity_type,
                        entity_id,
                        metric_name,
                        query_engine,
                        query_text
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
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
                    ],
                )
                return
            except duckdb.Error as exc:
                if attempt == 9:
                    logger.warning(
                        "analytics_session_write_skipped",
                        stage="insert",
                        db_path=str(self._usage_db_path),
                        request_id=request_id,
                        tenant=record.get("tenant"),
                        endpoint=record.get("endpoint"),
                        attempts=attempt + 1,
                        error=str(exc),
                        exc_info=True,
                    )
                    return
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()

    def get_usage_analytics(self, *, window: str = "24h", tenant: str | None = None) -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            if tenant:
                rows = conn.execute(
                    """
                    SELECT
                        tenant,
                        COUNT(*) AS total_requests,
                        ROUND(AVG(CASE WHEN status_code >= 400 THEN 1.0 ELSE 0.0 END), 4)
                            AS error_rate,
                        ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 4)
                            AS cache_hit_rate,
                        ROUND(AVG(duration_ms), 3) AS avg_duration_ms
                    FROM api_sessions
                    WHERE tenant IS NOT NULL
                      AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                      AND tenant = ?
                    GROUP BY tenant
                    ORDER BY tenant
                    """,
                    [interval, tenant],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        tenant,
                        COUNT(*) AS total_requests,
                        ROUND(AVG(CASE WHEN status_code >= 400 THEN 1.0 ELSE 0.0 END), 4)
                            AS error_rate,
                        ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 4)
                            AS cache_hit_rate,
                        ROUND(AVG(duration_ms), 3) AS avg_duration_ms
                    FROM api_sessions
                    WHERE tenant IS NOT NULL
                      AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                    GROUP BY tenant
                    ORDER BY tenant
                    """,
                    [interval],
                ).fetchall()
            tenants = []
            for tenant_name, total_requests, error_rate, cache_hit_rate, avg_duration_ms in rows:
                top_endpoints = conn.execute(
                    """
                    SELECT endpoint
                    FROM api_sessions
                    WHERE tenant = ?
                      AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                    GROUP BY endpoint
                    ORDER BY COUNT(*) DESC, endpoint
                    LIMIT 3
                    """,
                    [tenant_name, interval],
                ).fetchall()
                tenants.append(
                    {
                        "tenant": tenant_name,
                        "total_requests": total_requests,
                        "error_rate": float(error_rate or 0.0),
                        "cache_hit_rate": float(cache_hit_rate or 0.0),
                        "top_endpoints": [item[0] for item in top_endpoints],
                        "avg_duration_ms": float(avg_duration_ms or 0.0),
                    }
                )
            return {"window": window, "tenants": tenants}
        finally:
            conn.close()

    def get_top_queries(self, *, limit: int = 10, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            rows = conn.execute(
                """
                SELECT query_text, COUNT(*) AS frequency
                FROM api_sessions
                WHERE query_text IS NOT NULL
                  AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                GROUP BY query_text
                ORDER BY frequency DESC, query_text
                LIMIT ?
                """,
                [interval, limit],
            ).fetchall()
            return {
                "window": window,
                "queries": [
                    {"query": query_text, "count": frequency} for query_text, frequency in rows
                ],
            }
        finally:
            conn.close()

    def get_top_entities(self, *, limit: int = 10, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            rows = conn.execute(
                """
                SELECT entity_type, entity_id, COUNT(*) AS frequency
                FROM api_sessions
                WHERE entity_id IS NOT NULL
                  AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                GROUP BY entity_type, entity_id
                ORDER BY frequency DESC, entity_type, entity_id
                LIMIT ?
                """,
                [interval, limit],
            ).fetchall()
            return {
                "window": window,
                "entities": [
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "count": frequency,
                    }
                    for entity_type, entity_id, frequency in rows
                ],
            }
        finally:
            conn.close()

    def get_latency_analytics(self, *, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            rows = conn.execute(
                """
                SELECT
                    endpoint,
                    COUNT(*) AS requests,
                    ROUND(quantile_cont(duration_ms, 0.50), 3) AS p50_ms,
                    ROUND(quantile_cont(duration_ms, 0.95), 3) AS p95_ms,
                    ROUND(quantile_cont(duration_ms, 0.99), 3) AS p99_ms
                FROM api_sessions
                WHERE ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
                GROUP BY endpoint
                ORDER BY endpoint
                """,
                [interval],
            ).fetchall()
            return {
                "window": window,
                "endpoints": [
                    {
                        "endpoint": endpoint,
                        "requests": requests,
                        "p50_ms": float(p50_ms or 0.0),
                        "p95_ms": float(p95_ms or 0.0),
                        "p99_ms": float(p99_ms or 0.0),
                    }
                    for endpoint, requests, p50_ms, p95_ms, p99_ms in rows
                ],
            }
        finally:
            conn.close()

    def get_anomalies(self, *, window: str = "24h") -> dict:
        interval = _window_to_interval(window)
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            rows = conn.execute(
                """
                WITH hourly AS (
                    SELECT
                        tenant,
                        date_trunc('hour', ts) AS hour_bucket,
                        COUNT(*) AS requests
                    FROM api_sessions
                    WHERE tenant IS NOT NULL
                      AND ts >= CURRENT_TIMESTAMP - CAST(? AS INTERVAL)
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
                [interval],
            ).fetchall()
            return {
                "window": window,
                "anomalies": [
                    {
                        "tenant": tenant,
                        "current_hour_requests": current_hour_requests,
                        "hourly_average": float(hourly_average or 0.0),
                        "spike_ratio": float(spike_ratio or 0.0),
                    }
                    for tenant, current_hour_requests, hourly_average, spike_ratio in rows
                ],
            }
        finally:
            conn.close()

    def get_queries_per_second_last_minute(self) -> float:
        conn = self._usage_cursor()
        try:
            ensure_api_sessions_table(conn)
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM api_sessions
                WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '1 minute'
                """
            ).fetchone()
            requests_last_minute = row[0] if row else 0
        except duckdb.Error:
            return 0.0
        finally:
            conn.close()
        return round(float(requests_last_minute) / 60.0, 2)
