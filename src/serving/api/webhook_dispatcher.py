from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import httpx
import structlog
from pydantic import BaseModel, Field

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None

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


def get_webhook_config_path(app) -> Path:
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


class WebhookDispatcher:
    def __init__(self, app, poll_interval_seconds: float = 2.0) -> None:
        self.app = app
        self.poll_interval_seconds = poll_interval_seconds
        self.backoff_seconds = [1.0, 5.0, 25.0]
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

        for tenant in sorted(webhooks_by_tenant):
            events = self._fetch_pipeline_events(tenant=tenant)
            for event in events:
                event_id = str(event.get("event_id") or "")
                seen_key = _seen_event_key(event)
                if not event_id or event_id in self.seen_event_ids or seen_key in self.seen_event_ids:
                    continue
                self.seen_event_ids.add(seen_key)

                for webhook in webhooks_by_tenant[tenant]:
                    if _matches_filters(event, webhook.filters):
                        await self.deliver(webhook, event)

    async def deliver(self, webhook: WebhookRegistration, event: dict) -> dict:
        conn = self.app.state.query_engine._conn
        ensure_webhook_deliveries_table(conn)

        delivery_id = str(uuid.uuid4())
        event_type = str(event.get("event_type") or event.get("topic") or "unknown")
        event_id = str(event.get("event_id") or delivery_id)
        body = _event_body(event)
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
        sql = f"SELECT * FROM pipeline_events"  # nosec B608 - order_by is chosen from a fixed column allowlist
        params: list[str] = []
        if tenant is not None and "tenant_id" in columns:
            sql = f"{sql} WHERE COALESCE(tenant_id, 'default') = ?"
            params.append(tenant)
        sql = f"{sql} ORDER BY {order_by} ASC, event_id ASC"
        cursor = conn.execute(sql, params)
        result_columns = [description[0] for description in cursor.description]
        return [dict(zip(result_columns, row, strict=False)) for row in cursor.fetchall()]


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
