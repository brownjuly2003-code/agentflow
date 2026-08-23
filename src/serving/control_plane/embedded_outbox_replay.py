"""Outbox/replay repository of the embedded (DuckDB) control-plane adapter.

The replay outbox, the dead-letter store, and the exception-inbox triage
overlay — the ``OutboxReplayRepository`` capability surface (audit F-08
split; bodies verbatim from the pre-split ``embedded.py``). Invariant 8
(outbox↔dead-letter flips in one transaction) lives here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import duckdb
import structlog

from src.db_concurrency import catalog_ddl_lock

from .embedded_base import EmbeddedControlPlaneBase
from .store import AUTO_RESOLVE_NOTE, OutboxEntry, TriageState

logger = structlog.get_logger()


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


class EmbeddedOutboxReplayRepository(EmbeddedControlPlaneBase):
    """``OutboxReplayRepository`` capability of the embedded adapter."""

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
        # DuckDB TIMESTAMP is timezone-naive. Binding an aware datetime makes
        # DuckDB convert it to the host timezone before dropping tzinfo, which
        # shifts retry scheduling on non-UTC hosts. Store a UTC-naive value,
        # matching every read/comparison of this column.
        next_attempt_at: datetime | None = datetime.now(UTC).replace(tzinfo=None) + timedelta(
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

    def list_dead_letter_events_for_inbox(
        self, tenant_id: str, *, limit: int | None = None
    ) -> list[dict]:
        cursor = self._conn.cursor()
        try:
            ensure_dead_letter_table(cursor)
            select = (
                "SELECT event_id, event_type, failure_reason, failure_detail, "
                "received_at, retry_count, last_retried_at, status "
                "FROM dead_letter_events "
                "WHERE COALESCE(tenant_id, 'default') = ? "
                "ORDER BY received_at DESC"
            )
            # suffix is empty or "LIMIT <int>" — never caller-shaped text
            suffix = f" LIMIT {int(limit)}" if limit is not None else ""
            rows = cursor.execute(select + suffix, [tenant_id]).fetchall()
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
