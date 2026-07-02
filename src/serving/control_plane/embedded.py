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
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from src.db_concurrency import catalog_ddl_lock

from .store import ControlPlaneStore, WebhookQueueRow

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
        conn_provider: Callable[[], duckdb.DuckDBPyConnection],
        *,
        alert_rules_path_provider: Callable[[], Path] | None = None,
    ) -> None:
        self._conn_provider = conn_provider
        self._alert_rules_path_provider = alert_rules_path_provider

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
    def _conn(self) -> duckdb.DuckDBPyConnection:
        return self._conn_provider()

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
