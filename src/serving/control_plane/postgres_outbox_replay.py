"""Outbox/replay repository of the PostgreSQL control-plane adapter.

The lease-claimed replay outbox, the dead-letter store, and the
exception-inbox triage overlay — the ``OutboxReplayRepository`` capability
surface (audit F-08 split; bodies verbatim from the pre-split
``postgres.py``). Invariant 8 (outbox↔dead-letter flips in one transaction)
lives here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import structlog

from .postgres_base import PostgresControlPlaneBase
from .store import AUTO_RESOLVE_NOTE, OutboxEntry, TriageState

logger = structlog.get_logger()


class PostgresOutboxReplayRepository(PostgresControlPlaneBase):
    """``OutboxReplayRepository`` capability of the PostgreSQL adapter."""

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

    def list_dead_letter_events_for_inbox(
        self, tenant_id: str, *, limit: int | None = None
    ) -> list[dict]:
        select = (
            "SELECT event_id, event_type, failure_reason, failure_detail, "
            "received_at, retry_count, last_retried_at, status "
            "FROM dead_letter_events "
            "WHERE COALESCE(tenant_id, 'default') = %s "
            "ORDER BY received_at DESC"
        )
        # suffix is empty or "LIMIT <int>" — never caller-shaped text
        suffix = f" LIMIT {int(limit)}" if limit is not None else ""
        with self._connect() as conn:
            rows = conn.execute(select + suffix, (tenant_id,)).fetchall()
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
