from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import httpx
import structlog
from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.db_concurrency import catalog_ddl_lock
from src.serving.api.egress_guard import UnsafeEgressURLError, validate_public_url

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

logger = structlog.get_logger()

DEFAULT_WEBHOOKS_CONFIG_PATH = Path(os.getenv("AGENTFLOW_WEBHOOKS_FILE", "config/webhooks.yaml"))


class WebhookFilters(BaseModel):
    event_types: list[str] | None = None
    entity_ids: list[str] | None = None
    min_amount: float | None = None


class WebhookRegistration(BaseModel):
    id: str
    url: str
    secret: str
    tenant: str
    filters: WebhookFilters = Field(default_factory=WebhookFilters)
    created_at: datetime
    active: bool = True


class WebhookConfig(BaseModel):
    webhooks: list[WebhookRegistration] = Field(default_factory=list)


def get_webhook_config_path(app: FastAPI) -> Path:
    configured = getattr(app.state, "webhook_config_path", None)
    return Path(configured) if configured else DEFAULT_WEBHOOKS_CONFIG_PATH


def load_webhooks(path: Path) -> list[WebhookRegistration]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = yaml.safe_load(raw) if yaml is not None else json.loads(raw)
    config = WebhookConfig.model_validate(data or {})
    return config.webhooks


def save_webhooks(path: Path, webhooks: list[WebhookRegistration]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = WebhookConfig(webhooks=webhooks).model_dump(mode="json")
    content = (
        yaml.safe_dump(payload, sort_keys=False)
        if yaml is not None
        else json.dumps(payload, indent=2)
    )
    path.write_text(content, encoding="utf-8")


def create_webhook(
    path: Path,
    *,
    url: str,
    tenant: str,
    filters: WebhookFilters,
) -> WebhookRegistration:
    webhooks = load_webhooks(path)
    registration = WebhookRegistration(
        id=str(uuid.uuid4()),
        url=url,
        secret=secrets.token_urlsafe(32),
        tenant=tenant,
        filters=filters,
        created_at=datetime.now(UTC),
    )
    webhooks.append(registration)
    save_webhooks(path, webhooks)
    return registration


def list_webhooks(path: Path, tenant: str) -> list[WebhookRegistration]:
    return [
        webhook for webhook in load_webhooks(path) if webhook.tenant == tenant and webhook.active
    ]


def get_webhook(path: Path, webhook_id: str, tenant: str) -> WebhookRegistration | None:
    for webhook in load_webhooks(path):
        if webhook.id == webhook_id and webhook.tenant == tenant and webhook.active:
            return webhook
    return None


def deactivate_webhook(path: Path, webhook_id: str, tenant: str) -> bool:
    webhooks = load_webhooks(path)
    changed = False
    for webhook in webhooks:
        if webhook.id == webhook_id and webhook.tenant == tenant and webhook.active:
            webhook.active = False
            changed = True
            break
    if changed:
        save_webhooks(path, webhooks)
    return changed


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


def get_delivery_logs(conn: duckdb.DuckDBPyConnection, webhook_id: str) -> list[dict]:
    ensure_webhook_deliveries_table(conn)
    cursor = conn.execute(
        """
        SELECT delivery_id, webhook_id, event_id, event_type, attempt,
               status_code, success, error, delivered_at
        FROM webhook_deliveries
        WHERE webhook_id = ?
        ORDER BY delivered_at DESC
        LIMIT 20
        """,
        [webhook_id],
    )
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def ensure_webhook_delivery_queue_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Durable per-(webhook, event) delivery state for re-drive.

    Distinct from ``webhook_deliveries`` (an append-only attempt *log*): this is
    the *state* table whose ``(webhook_id, event_id)`` primary key dedupes
    enqueues and whose ``status`` / ``next_attempt_at`` drive retries that
    survive a process restart. ``body`` stores the canonical payload so a
    delivery can be replayed without re-reading ``pipeline_events``.
    """
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


class WebhookDispatcher:
    def __init__(self, app: FastAPI, poll_interval_seconds: float = 2.0) -> None:
        self.app = app
        self.poll_interval_seconds = poll_interval_seconds
        self.backoff_seconds = [1.0, 5.0, 25.0]
        # Durable re-drive: how many delivery rounds a (webhook, event) gets
        # before it is parked as 'dead', and how many due rows one re-drive pass
        # processes (bounded so the pass never blocks the loop on a large queue).
        self.max_delivery_attempts = 5
        self.redrive_batch_size = 100
        self.seen_event_ids: set[str] = set()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self.mark_existing_events_seen()
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def run(self) -> None:
        while True:
            try:
                await self.dispatch_new_events()
            except Exception as exc:
                logger.warning("webhook_dispatcher_error", error=str(exc))
            # Re-drive durably-queued deliveries that failed earlier (or were
            # left pending by a crash/restart). This is the half the in-memory
            # seen-set could not provide: a failed delivery is retried instead of
            # silently dropped (audit_28_06_26.md #3).
            try:
                await self.process_delivery_queue()
            except Exception as exc:
                logger.warning("webhook_redrive_error", error=str(exc))
            await asyncio.sleep(self.poll_interval_seconds)

    def mark_existing_events_seen(self) -> None:
        try:
            for event in self._fetch_pipeline_events():
                event_id = str(event.get("event_id") or "")
                if event_id:
                    self.seen_event_ids.add(_seen_event_key(event))
        except duckdb.Error as exc:
            logger.warning("webhook_seen_init_failed", error=str(exc))

    async def dispatch_new_events(self) -> None:
        path = get_webhook_config_path(self.app)
        webhooks = [webhook for webhook in load_webhooks(path) if webhook.active]
        webhooks_by_tenant: dict[str, list[WebhookRegistration]] = {}
        for webhook in webhooks:
            webhooks_by_tenant.setdefault(webhook.tenant, []).append(webhook)

        # Scan ALL new pipeline events, not just tenants with registered
        # webhooks: marking events seen is what drives metric-cache
        # invalidation (main.py wraps this method and invalidates on growth),
        # and that must work with zero webhooks registered. Delivery stays
        # tenant-scoped below.
        for event in self._fetch_pipeline_events():
            event_id = str(event.get("event_id") or "")
            seen_key = _seen_event_key(event)
            if not event_id or event_id in self.seen_event_ids or seen_key in self.seen_event_ids:
                continue

            tenant = str(event.get("tenant_id") or "default")
            enqueued_all = True
            for webhook in webhooks_by_tenant.get(tenant, []):
                if not _matches_filters(event, webhook.filters):
                    continue
                # Record the delivery durably *before* attempting it, then attempt
                # inline (low latency for the happy path). A failure leaves a
                # 'pending' row that process_delivery_queue re-drives — surviving
                # all-retries-failed and a process restart, which the in-memory
                # seen-set alone could not (audit #3). Each webhook is isolated:
                # one webhook's exception must neither abort the scan (skipping
                # later webhooks) nor mark the event seen before it was durably
                # enqueued. (audit_30_06_26.md C2)
                try:
                    inserted = self._enqueue_delivery(webhook, event)
                except Exception as exc:
                    logger.warning(
                        "webhook_enqueue_failed",
                        webhook_id=webhook.id,
                        event_id=event_id,
                        error=str(exc),
                    )
                    enqueued_all = False
                    continue
                if not inserted:
                    # Already enqueued on an earlier scan (this event stayed unseen
                    # because some other webhook's enqueue failed); its durable row
                    # is re-driven by process_delivery_queue — don't re-POST inline.
                    continue
                try:
                    result = await self.deliver(webhook, event)
                    self._record_delivery_outcome(webhook.id, event_id, result)
                except Exception as exc:
                    # Durable row is already 'pending'; let process_delivery_queue
                    # re-drive it instead of unwinding the whole scan.
                    logger.warning(
                        "webhook_inline_delivery_failed",
                        webhook_id=webhook.id,
                        event_id=event_id,
                        error=str(exc),
                    )

            # Mark the event seen only once every matching webhook is durably
            # enqueued. This also drives metric-cache invalidation (main.py wraps
            # this method and invalidates on seen-set growth), so it still runs
            # for events with zero matching webhooks (enqueued_all stays True).
            if enqueued_all:
                self.seen_event_ids.add(seen_key)

    async def deliver(self, webhook: WebhookRegistration, event: dict) -> dict:
        """Deliver one event now (the ``/test`` endpoint and the inline dispatch
        path). Computes the canonical body from ``event`` and posts it.
        """
        event_type = str(event.get("event_type") or event.get("topic") or "unknown")
        event_id = str(event.get("event_id") or "")
        return await self._deliver_body(
            webhook, body=_event_body(event), event_id=event_id, event_type=event_type
        )

    async def _deliver_body(
        self,
        webhook: WebhookRegistration,
        *,
        body: bytes,
        event_id: str,
        event_type: str,
    ) -> dict:
        """Post a pre-serialised body to one webhook with the retry burst and
        per-attempt logging. Shared by :meth:`deliver` and the durable re-drive
        (:meth:`process_delivery_queue`), which replays the stored body verbatim.
        """
        conn = self.app.state.query_engine._conn
        ensure_webhook_deliveries_table(conn)

        delivery_id = str(uuid.uuid4())
        if not event_id:
            event_id = delivery_id
        headers = {
            "Content-Type": "application/json",
            "X-AgentFlow-Event": event_type,
            "X-AgentFlow-Signature": _signature(webhook.secret, body),
            "X-AgentFlow-Delivery": delivery_id,
        }

        attempts = 0
        success = False
        status_code: int | None = None
        error: str | None = None

        # Re-validate at delivery time too (not only at registration): a hostname
        # that resolved to a public IP when the webhook was created could now
        # point at an internal address (DNS rebinding). Fail the delivery instead
        # of fetching an internal target. (audit_28_06_26.md #2)
        try:
            await asyncio.to_thread(validate_public_url, webhook.url)
        except UnsafeEgressURLError as exc:
            error = f"unsafe egress URL: {exc}"
            _log_delivery(
                conn,
                delivery_id=delivery_id,
                webhook_id=webhook.id,
                event_id=event_id,
                event_type=event_type,
                attempt=0,
                status_code=None,
                success=False,
                error=error,
            )
            return {
                "delivery_id": delivery_id,
                "webhook_id": webhook.id,
                "event_id": event_id,
                "event_type": event_type,
                "success": False,
                "status_code": None,
                "error": error,
                "attempts": 0,
            }

        async with httpx.AsyncClient(timeout=5.0) as client:
            for attempt in range(1, 4):
                attempts = attempt
                error = None
                try:
                    response = await client.post(
                        webhook.url,
                        content=body,
                        headers=headers,
                    )
                    status_code = response.status_code
                    success = 200 <= response.status_code < 300
                    _log_delivery(
                        conn,
                        delivery_id=delivery_id,
                        webhook_id=webhook.id,
                        event_id=event_id,
                        event_type=event_type,
                        attempt=attempt,
                        status_code=status_code,
                        success=success,
                        error=None,
                    )
                    if response.status_code < 500:
                        break
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    status_code = None
                    success = False
                    error = str(exc)
                    _log_delivery(
                        conn,
                        delivery_id=delivery_id,
                        webhook_id=webhook.id,
                        event_id=event_id,
                        event_type=event_type,
                        attempt=attempt,
                        status_code=None,
                        success=False,
                        error=error,
                    )

                if attempt < 3:
                    delay = self.backoff_seconds[min(attempt - 1, len(self.backoff_seconds) - 1)]
                    await asyncio.sleep(delay)

        return {
            "delivery_id": delivery_id,
            "webhook_id": webhook.id,
            "event_id": event_id,
            "event_type": event_type,
            "success": success,
            "status_code": status_code,
            "error": error,
            "attempts": attempts,
        }

    def _fetch_pipeline_events(self, tenant: str | None = None) -> list[dict]:
        conn = self.app.state.query_engine._conn
        columns = [
            row[1] for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()
        ]
        if not columns:
            return []
        if tenant is not None and "tenant_id" not in columns and tenant != "default":
            return []
        if "processed_at" in columns:
            order_by = "processed_at"
        elif "created_at" in columns:
            order_by = "created_at"
        else:
            order_by = "event_id"
        # order_by is chosen from a fixed column allowlist
        sql = "SELECT * FROM pipeline_events"  # nosec B608
        params: list[str] = []
        if tenant is not None and "tenant_id" in columns:
            sql = f"{sql} WHERE COALESCE(tenant_id, 'default') = ?"
            params.append(tenant)
        sql = f"{sql} ORDER BY {order_by} ASC, event_id ASC"
        cursor = conn.execute(sql, params)
        result_columns = [description[0] for description in cursor.description]
        return [dict(zip(result_columns, row, strict=False)) for row in cursor.fetchall()]

    def _enqueue_delivery(self, webhook: WebhookRegistration, event: dict) -> bool:
        """Durably record a (webhook, event) delivery as ``pending`` (idempotent
        on the primary key — a re-scan of the same event never duplicates it).

        Returns ``True`` only when a new row is inserted, so the caller can
        inline-deliver exactly the fresh rows and never re-POST a (webhook,
        event) that was already enqueued on an earlier scan."""
        event_id = str(event.get("event_id") or "")
        if not event_id:
            return False
        conn = self.app.state.query_engine._conn
        ensure_webhook_delivery_queue_table(conn)
        existing = conn.execute(
            "SELECT 1 FROM webhook_delivery_queue WHERE webhook_id = ? AND event_id = ?",
            [webhook.id, event_id],
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
            [
                webhook.id,
                event_id,
                str(event.get("tenant_id") or "default"),
                str(event.get("event_type") or event.get("topic") or "unknown"),
                _event_body(event).decode("utf-8"),
                now,
                now,
                now,
            ],
        )
        return True

    def _record_delivery_outcome(self, webhook_id: str, event_id: str, result: dict) -> None:
        """Advance a queue row from the outcome of one delivery round: success →
        ``delivered``; failure → bump attempts and re-schedule (back to
        ``pending`` with a backoff ``next_attempt_at``), or park as ``dead`` once
        ``max_delivery_attempts`` is reached."""
        if not event_id:
            return
        conn = self.app.state.query_engine._conn
        now = datetime.now(UTC)
        status_code = result.get("status_code")
        if result.get("success"):
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
        error = result.get("error")
        if attempts >= self.max_delivery_attempts:
            conn.execute(
                "UPDATE webhook_delivery_queue SET status = 'dead', attempts = ?, "
                "last_status_code = ?, last_error = ?, next_attempt_at = NULL, updated_at = ? "
                "WHERE webhook_id = ? AND event_id = ?",
                [attempts, status_code, error, now, webhook_id, event_id],
            )
            return
        delay = self.backoff_seconds[min(attempts - 1, len(self.backoff_seconds) - 1)]
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

    async def process_delivery_queue(self) -> None:
        """Re-drive due ``pending`` deliveries. A webhook that has since been
        removed/deactivated parks its row as ``dead`` rather than retrying
        forever. Bounded by ``redrive_batch_size`` so one pass can't stall the
        loop on a large backlog."""
        conn = self.app.state.query_engine._conn
        ensure_webhook_delivery_queue_table(conn)
        path = get_webhook_config_path(self.app)
        now = datetime.now(UTC)
        due = conn.execute(
            "SELECT webhook_id, event_id, tenant, event_type, body "
            "FROM webhook_delivery_queue "
            "WHERE status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY created_at ASC LIMIT ?",
            [now, self.redrive_batch_size],
        ).fetchall()
        for webhook_id, event_id, tenant, event_type, body in due:
            webhook = get_webhook(path, webhook_id, str(tenant or "default"))
            if webhook is None:
                conn.execute(
                    "UPDATE webhook_delivery_queue SET status = 'dead', "
                    "last_error = 'webhook inactive or removed', next_attempt_at = NULL, "
                    "updated_at = ? WHERE webhook_id = ? AND event_id = ?",
                    [datetime.now(UTC), webhook_id, event_id],
                )
                continue
            result = await self._deliver_body(
                webhook,
                body=(body or "").encode("utf-8"),
                event_id=event_id,
                event_type=event_type or "unknown",
            )
            self._record_delivery_outcome(webhook_id, event_id, result)


def _log_delivery(
    conn: duckdb.DuckDBPyConnection,
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


def _matches_filters(event: dict, filters: WebhookFilters) -> bool:
    event_type = str(event.get("event_type") or event.get("topic") or "")
    if filters.event_types:
        if not any(_event_type_matches(event_type, value) for value in filters.event_types):
            return False

    if filters.entity_ids:
        entity_values = {
            str(event.get(key))
            for key in ("entity_id", "order_id", "user_id", "product_id", "session_id")
            if event.get(key) is not None
        }
        if not entity_values.intersection(filters.entity_ids):
            return False

    if filters.min_amount is not None:
        if not event_type.startswith("order"):
            return False
        amount = (
            event.get("total_amount")
            if event.get("total_amount") is not None
            else event.get("amount")
        )
        if amount is None:
            return False
        try:
            if float(str(amount)) < filters.min_amount:
                return False
        except (TypeError, ValueError):
            return False

    return True


def _seen_event_key(event: dict) -> str:
    event_id = str(event.get("event_id") or "")
    tenant_id = str(event.get("tenant_id") or "default")
    return f"{tenant_id}:{event_id}"


def _event_type_matches(event_type: str, requested: str) -> bool:
    return event_type == requested or event_type.startswith(f"{requested}.")


def _event_body(event: dict) -> bytes:
    return json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _json_default(value: object) -> str | float:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)
