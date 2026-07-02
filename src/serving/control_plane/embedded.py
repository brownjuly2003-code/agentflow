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

from .store import ControlPlaneStore, OutboxEntry, WebhookQueueRow

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
