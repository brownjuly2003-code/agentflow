"""Webhook repository of the embedded (DuckDB) control-plane adapter.

The durable delivery queue, the delivery attempt log, the YAML-backed
registration repository, and the dead-delivery reads for the exception
inbox — the ``WebhookRepository`` capability surface (audit F-08 split;
bodies verbatim from the pre-split ``embedded.py``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import duckdb
import structlog

from agentflow_runtime.db_concurrency import catalog_ddl_lock

from .embedded_base import EmbeddedControlPlaneBase
from .store import WebhookQueueRow

logger = structlog.get_logger()

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
                last_outcome_id VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (webhook_id, event_id)
            )
            """
        )
        # Idempotency token for the outcome write (P3): the delivery_id of the
        # last outcome applied to this row, so a retry after a lost commit-ack
        # is a no-op instead of a second attempts bump. ADD COLUMN IF NOT EXISTS
        # upgrades a queue table created before this column existed (same
        # pattern as ensure_dead_letter_table's tenant_id backfill).
        conn.execute(
            "ALTER TABLE webhook_delivery_queue ADD COLUMN IF NOT EXISTS last_outcome_id VARCHAR"
        )


class EmbeddedWebhookRepository(EmbeddedControlPlaneBase):
    """``WebhookRepository`` capability of the embedded adapter."""

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
        delivery_id: str | None = None,
    ) -> None:
        conn = self._conn
        now = datetime.now(UTC)
        # Read the current attempts AND the last outcome id in one shot so the
        # idempotency guard and the failure-branch increment share one snapshot.
        row = conn.execute(
            "SELECT attempts, last_outcome_id FROM webhook_delivery_queue "
            "WHERE webhook_id = ? AND event_id = ?",
            [webhook_id, event_id],
        ).fetchone()
        # Idempotency (P3): this exact delivery round's outcome already landed —
        # a retry after a lost commit-ack. No-op so attempts is not bumped twice.
        if delivery_id is not None and row is not None and row[1] == delivery_id:
            return
        if success:
            conn.execute(
                "UPDATE webhook_delivery_queue SET status = 'delivered', "
                "last_status_code = ?, last_error = NULL, last_outcome_id = ?, updated_at = ? "
                "WHERE webhook_id = ? AND event_id = ?",
                [status_code, delivery_id, now, webhook_id, event_id],
            )
            return
        attempts = (row[0] if row else 0) + 1
        if attempts >= max_attempts:
            conn.execute(
                "UPDATE webhook_delivery_queue SET status = 'dead', attempts = ?, "
                "last_status_code = ?, last_error = ?, last_outcome_id = ?, "
                "next_attempt_at = NULL, updated_at = ? "
                "WHERE webhook_id = ? AND event_id = ?",
                [attempts, status_code, error, delivery_id, now, webhook_id, event_id],
            )
            return
        delay = backoff_seconds[min(attempts - 1, len(backoff_seconds) - 1)]
        conn.execute(
            "UPDATE webhook_delivery_queue SET status = 'pending', attempts = ?, "
            "last_status_code = ?, last_error = ?, last_outcome_id = ?, "
            "next_attempt_at = ?, updated_at = ? "
            "WHERE webhook_id = ? AND event_id = ?",
            [
                attempts,
                status_code,
                error,
                delivery_id,
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

    # --- webhook dead deliveries for the exception inbox ----------------------

    def list_dead_webhook_deliveries(
        self, tenant_id: str | None = None, *, limit: int | None = None
    ) -> list[dict]:
        conn = self._conn
        ensure_webhook_delivery_queue_table(conn)
        select = (
            "SELECT webhook_id, event_id, tenant, event_type, body, attempts, "
            "last_status_code, last_error, created_at, updated_at "
            "FROM webhook_delivery_queue WHERE status = 'dead'"
        )
        suffix = f" LIMIT {int(limit)}" if limit is not None else ""
        if tenant_id is not None:
            rows = conn.execute(
                select + " AND tenant = ? ORDER BY updated_at DESC" + suffix, [tenant_id]
            ).fetchall()
        else:
            rows = conn.execute(select + " ORDER BY updated_at DESC" + suffix).fetchall()
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
