from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import httpx
import structlog
from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.serving.api.egress_guard import UnsafeEgressURLError, validate_public_url
from src.serving.backends import BackendExecutionError
from src.serving.control_plane import get_control_plane_store

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


# The registration CRUD helpers below take ``app`` and resolve the
# control-plane store inside (ADR 0010 slice 5) — the same move the alert-rule
# helpers made in slice 2: registrations were the last control-plane state
# read from a per-pod file (config/webhooks.yaml) instead of the store, the
# exact split-brain the ADR's inventory calls the sharpest. The embedded
# adapter keeps the YAML file (via ``get_webhook_config_path``), so the
# single-replica profile and its on-disk format do not change.


def load_webhooks(app: FastAPI) -> list[WebhookRegistration]:
    records = get_control_plane_store(app).load_webhook_registrations()
    return WebhookConfig.model_validate({"webhooks": records}).webhooks


def save_webhooks(app: FastAPI, webhooks: list[WebhookRegistration]) -> None:
    payload = WebhookConfig(webhooks=webhooks).model_dump(mode="json")
    get_control_plane_store(app).save_webhook_registrations(payload["webhooks"])


def create_webhook(
    app: FastAPI,
    *,
    url: str,
    tenant: str,
    filters: WebhookFilters,
) -> WebhookRegistration:
    webhooks = load_webhooks(app)
    registration = WebhookRegistration(
        id=str(uuid.uuid4()),
        url=url,
        secret=secrets.token_urlsafe(32),
        tenant=tenant,
        filters=filters,
        created_at=datetime.now(UTC),
    )
    webhooks.append(registration)
    save_webhooks(app, webhooks)
    return registration


def list_webhooks(app: FastAPI, tenant: str) -> list[WebhookRegistration]:
    return [
        webhook for webhook in load_webhooks(app) if webhook.tenant == tenant and webhook.active
    ]


def get_webhook(app: FastAPI, webhook_id: str, tenant: str) -> WebhookRegistration | None:
    for webhook in load_webhooks(app):
        if webhook.id == webhook_id and webhook.tenant == tenant and webhook.active:
            return webhook
    return None


def deactivate_webhook(app: FastAPI, webhook_id: str, tenant: str) -> bool:
    webhooks = load_webhooks(app)
    changed = False
    for webhook in webhooks:
        if webhook.id == webhook_id and webhook.tenant == tenant and webhook.active:
            webhook.active = False
            changed = True
            break
    if changed:
        save_webhooks(app, webhooks)
    return changed


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
        # S7: first-class subscribers notified when the journal scan marks new
        # events seen. Replaces the historical monkey-patch over
        # ``dispatch_new_events`` in main.py. Cache invalidation is owned by
        # ``MetricCacheController`` (push + independent scan); this hook is
        # kept for co-located side effects that want the webhook scan's
        # timing without wrapping methods.
        self._on_new_events: list[Callable[[], Awaitable[None]]] = []

    def add_new_events_listener(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Register a side-effect that runs when the seen-set grows this pass."""
        self._on_new_events.append(callback)

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
        except (duckdb.Error, BackendExecutionError) as exc:
            logger.warning("webhook_seen_init_failed", error=str(exc))

    async def dispatch_new_events(self) -> None:
        webhooks = [webhook for webhook in load_webhooks(self.app) if webhook.active]
        webhooks_by_tenant: dict[str, list[WebhookRegistration]] = {}
        for webhook in webhooks:
            webhooks_by_tenant.setdefault(webhook.tenant, []).append(webhook)

        # Scan ALL new pipeline events, not just tenants with registered
        # webhooks: marking events seen still runs with zero webhooks so
        # subscribers (via ``add_new_events_listener``) see journal growth.
        # Delivery stays tenant-scoped below. Metric-cache invalidation is
        # owned by MetricCacheController (S7) and does not require this loop.
        newly_seen = 0
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
            # enqueued. Still runs for events with zero matching webhooks
            # (enqueued_all stays True) so the scan progresses and listeners fire.
            if enqueued_all:
                self.seen_event_ids.add(seen_key)
                newly_seen += 1

        if newly_seen:
            for listener in self._on_new_events:
                try:
                    await listener()
                except Exception as exc:
                    logger.warning("webhook_new_events_listener_failed", error=str(exc))

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
        store = get_control_plane_store(self.app)

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
            store.log_webhook_delivery(
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
                    store.log_webhook_delivery(
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
                    store.log_webhook_delivery(
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
        # Scan the journal through the serving backend, not the embedded DuckDB
        # connection: when serving is ClickHouse (ADR 0006) the events that
        # matter arrive from an out-of-process writer, and this scan is what
        # drives both webhook delivery and metric-cache invalidation.
        events: list[dict] = self.app.state.query_engine.fetch_pipeline_events(tenant_id=tenant)
        return events

    def _enqueue_delivery(self, webhook: WebhookRegistration, event: dict) -> bool:
        """Durably record a (webhook, event) delivery as ``pending`` (idempotent
        on the primary key — a re-scan of the same event never duplicates it).

        Returns ``True`` only when a new row is inserted, so the caller can
        inline-deliver exactly the fresh rows and never re-POST a (webhook,
        event) that was already enqueued on an earlier scan."""
        event_id = str(event.get("event_id") or "")
        if not event_id:
            return False
        return get_control_plane_store(self.app).enqueue_webhook_delivery(
            webhook_id=webhook.id,
            event_id=event_id,
            tenant=str(event.get("tenant_id") or "default"),
            event_type=str(event.get("event_type") or event.get("topic") or "unknown"),
            body=_event_body(event).decode("utf-8"),
        )

    def _record_delivery_outcome(self, webhook_id: str, event_id: str, result: dict) -> None:
        """Advance a queue row from the outcome of one delivery round: success →
        ``delivered``; failure → bump attempts and re-schedule (back to
        ``pending`` with a backoff ``next_attempt_at``), or park as ``dead`` once
        ``max_delivery_attempts`` is reached. The transition itself lives in the
        control-plane store; the retry policy stays dispatcher configuration."""
        if not event_id:
            return
        get_control_plane_store(self.app).record_webhook_delivery_outcome(
            webhook_id=webhook_id,
            event_id=event_id,
            success=bool(result.get("success")),
            status_code=result.get("status_code"),
            error=result.get("error"),
            max_attempts=self.max_delivery_attempts,
            backoff_seconds=self.backoff_seconds,
        )

    async def process_delivery_queue(self) -> None:
        """Re-drive due ``pending`` deliveries. A webhook that has since been
        removed/deactivated parks its row as ``dead`` rather than retrying
        forever. Bounded by ``redrive_batch_size`` so one pass can't stall the
        loop on a large backlog."""
        store = get_control_plane_store(self.app)
        for row in store.claim_due_webhook_deliveries(limit=self.redrive_batch_size):
            webhook = get_webhook(self.app, row.webhook_id, str(row.tenant or "default"))
            if webhook is None:
                store.park_webhook_delivery(
                    webhook_id=row.webhook_id,
                    event_id=row.event_id,
                    error="webhook inactive or removed",
                )
                continue
            result = await self._deliver_body(
                webhook,
                body=(row.body or "").encode("utf-8"),
                event_id=row.event_id,
                event_type=row.event_type or "unknown",
            )
            self._record_delivery_outcome(row.webhook_id, row.event_id, result)


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
