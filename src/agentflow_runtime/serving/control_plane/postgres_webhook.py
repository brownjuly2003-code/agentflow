"""Webhook repository of the PostgreSQL control-plane adapter.

The lease-claimed durable delivery queue, the delivery attempt log, the
record-set registration repository, and the dead-delivery reads — the
``WebhookRepository`` capability surface (audit F-08 split; bodies verbatim
from the pre-split ``postgres.py``).
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence

import structlog

from .postgres_base import _TRANSIENT_ERRORS, PostgresControlPlaneBase
from .store import WebhookQueueRow

logger = structlog.get_logger()


class PostgresWebhookRepository(PostgresControlPlaneBase):
    """``WebhookRepository`` capability of the PostgreSQL adapter."""

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
        delivery_id: str | None = None,
    ) -> None:
        # Bounded retry on transient connection errors, same shape as
        # record_api_usage: without it, a POST that succeeded but then hit a
        # momentary DB blip on this outcome write never clears the enqueue
        # lease, stranding the row pending+leased for the full claim lease
        # window instead of a fast redrive (audit finding #4).
        #
        # That retry is exactly what could count one failure twice (P3): attempt
        # 0's UPDATE commits on the server but the commit-ack is lost, so the
        # except-branch retries and attempt 1 re-reads the already-bumped
        # attempts and bumps it again — attempts+2, a premature dead-letter.
        # delivery_id makes the round idempotent: the row records the last
        # applied outcome id under FOR UPDATE, and a repeat is a no-op. Because
        # the guard and the increment read the same locked row inside one
        # transaction, the retry sees attempt 0's committed stamp (skip) or its
        # rollback (apply once) — never a double bump.
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT attempts, last_outcome_id FROM webhook_delivery_queue "
                        "WHERE webhook_id = %s AND event_id = %s FOR UPDATE",
                        (webhook_id, event_id),
                    ).fetchone()
                    if delivery_id is not None and row is not None and row[1] == delivery_id:
                        # This delivery round's outcome already landed (a retry
                        # after a lost commit-ack). No-op.
                        return
                    if success:
                        conn.execute(
                            """
                            UPDATE webhook_delivery_queue
                            SET status = 'delivered', last_status_code = %s,
                                last_error = NULL, last_outcome_id = %s,
                                lease_expires_at = NULL, updated_at = now()
                            WHERE webhook_id = %s AND event_id = %s
                            """,
                            (status_code, delivery_id, webhook_id, event_id),
                        )
                        return
                    attempts = (row[0] if row else 0) + 1
                    if attempts >= max_attempts:
                        conn.execute(
                            """
                            UPDATE webhook_delivery_queue
                            SET status = 'dead', attempts = %s, last_status_code = %s,
                                last_error = %s, last_outcome_id = %s, next_attempt_at = NULL,
                                lease_expires_at = NULL, updated_at = now()
                            WHERE webhook_id = %s AND event_id = %s
                            """,
                            (attempts, status_code, error, delivery_id, webhook_id, event_id),
                        )
                        return
                    delay = backoff_seconds[min(attempts - 1, len(backoff_seconds) - 1)]
                    conn.execute(
                        """
                        UPDATE webhook_delivery_queue
                        SET status = 'pending', attempts = %s, last_status_code = %s,
                            last_error = %s, last_outcome_id = %s,
                            next_attempt_at = now() + make_interval(secs => %s),
                            lease_expires_at = NULL, updated_at = now()
                        WHERE webhook_id = %s AND event_id = %s
                        """,
                        (
                            attempts,
                            status_code,
                            error,
                            delivery_id,
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

    # --- webhook registration repository ---------------------------------------

    def load_webhook_registrations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record FROM webhook_registrations ORDER BY position ASC"
            ).fetchall()
        return [json.loads(record) for (record,) in rows]

    def save_webhook_registrations(self, registrations: list[dict]) -> None:
        self._replace_record_set("webhook_registrations", registrations)

    # --- webhook dead deliveries for the exception inbox ----------------------

    def list_dead_webhook_deliveries(
        self, tenant_id: str | None = None, *, limit: int | None = None
    ) -> list[dict]:
        select = (
            "SELECT webhook_id, event_id, tenant, event_type, body, attempts, "
            "last_status_code, last_error, created_at, updated_at "
            "FROM webhook_delivery_queue WHERE status = 'dead'"
        )
        suffix = f" LIMIT {int(limit)}" if limit is not None else ""
        with self._connect() as conn:
            if tenant_id is not None:
                rows = conn.execute(
                    select + " AND tenant = %s ORDER BY updated_at DESC" + suffix, (tenant_id,)
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
