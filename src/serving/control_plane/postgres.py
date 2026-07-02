"""PostgreSQL control-plane store — the scale profile (ADR 0010 slice 5).

All six state classes from the ADR's inventory live in ordinary PostgreSQL
tables, and the claim semantics the port only satisfies degenerately on the
embedded adapter become real here:

- ``enqueue_webhook_delivery`` wins by ``INSERT .. ON CONFLICT DO NOTHING``
  rowcount — exactly one replica inline-delivers a fresh enqueue.
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

- **One connection per method call, no pool** — mirrors the pre-port
  usage/session code opening a fresh file connection per request; pooling is
  explicitly out of ADR 0010's scope and noted as a follow-up.
- **Every method is one transaction** — the ``_connect`` context manager
  commits on success and rolls back on any exception, which is what makes
  the invariant-8 methods atomic without adapter-specific ceremony.
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

``psycopg`` (v3) is an optional dependency imported at module load with a
``None`` fallback, exactly like ``redis`` in the rate limiter: importing this
module is safe without it, constructing the store is not.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from .store import (
    CONTROL_PLANE_PG_DSN_ENV,
    ControlPlaneStore,
    OutboxEntry,
    WebhookQueueRow,
)

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

logger = structlog.get_logger()

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
    ) -> None:
        if psycopg is None:  # pragma: no cover - exercised via monkeypatch
            raise RuntimeError(
                "AGENTFLOW_CONTROLPLANE_STORE=postgres requires the optional "
                "'psycopg' dependency (pip install psycopg[binary])."
            )
        if not dsn:
            raise ValueError("PostgresControlPlaneStore requires a non-empty DSN.")
        self._dsn = dsn
        self._claim_lease_seconds = float(claim_lease_seconds)
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    # --- connection / schema plumbing ----------------------------------------

    def _connect(self) -> AbstractContextManager[Any]:
        # One connection = one transaction: psycopg's connection context
        # manager commits on clean exit and rolls back on exception, which is
        # exactly the invariant-8 semantics the port requires.
        self._ensure_schema()
        # Annotated hop: with psycopg absent (optional dependency), mypy sees
        # the module as Any and warn_return_any would flag a bare return.
        connection: AbstractContextManager[Any] = psycopg.connect(self._dsn)
        return connection

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with psycopg.connect(self._dsn) as conn:
                for statement in _SCHEMA_STATEMENTS:
                    conn.execute(statement)
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
                     next_attempt_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', 0, now(), now(), now())
                ON CONFLICT (webhook_id, event_id) DO NOTHING
                """,
                (webhook_id, event_id, tenant, event_type, body),
            )
            # Insert-win detection (ADR 0010 §2): rowcount is 1 only for the
            # caller whose INSERT actually landed — the enqueue winner, who
            # alone inline-delivers.
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
        with self._connect() as conn:
            if success:
                conn.execute(
                    """
                    UPDATE webhook_delivery_queue
                    SET status = 'delivered', last_status_code = %s, last_error = NULL,
                        lease_expires_at = NULL, updated_at = now()
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
                    last_error = %s, next_attempt_at = %s,
                    lease_expires_at = NULL, updated_at = now()
                WHERE webhook_id = %s AND event_id = %s
                """,
                (
                    attempts,
                    status_code,
                    error,
                    datetime.now(UTC) + timedelta(seconds=delay),
                    webhook_id,
                    event_id,
                ),
            )

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
        next_attempt_at: datetime | None = datetime.now(UTC) + timedelta(
            seconds=retry_delay_seconds
        )
        if retry_count >= max_retries:
            status = "failed"
            next_attempt_at = None
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE outbox
                SET status = %s, retry_count = %s, next_attempt_at = %s,
                    last_error = %s, lease_expires_at = NULL
                WHERE id = %s
                """,
                (status, retry_count, next_attempt_at, error_message, outbox_id),
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
            except psycopg.OperationalError as exc:
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
    return PostgresControlPlaneStore(dsn, claim_lease_seconds=lease_seconds)
