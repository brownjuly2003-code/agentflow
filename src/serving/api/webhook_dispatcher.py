from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import httpx
import structlog
from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.serving.api.egress_guard import UnsafeEgressURLError, validate_public_url
from src.serving.api.metrics import WEBHOOK_SETTLE_VIOLATIONS
from src.serving.backends import BackendExecutionError
from src.serving.control_plane import get_control_plane_store
from src.serving.seen_events import BoundedSeenSet

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
    def __init__(
        self,
        app: FastAPI,
        poll_interval_seconds: float = 2.0,
        scan_batch_size: int = 1000,
        seen_cache_size: int = 50_000,
        settle_seconds: int = 3,
    ) -> None:
        self.app = app
        self.poll_interval_seconds = poll_interval_seconds
        self.backoff_seconds = [1.0, 5.0, 25.0]
        # Durable re-drive: how many delivery rounds a (webhook, event) gets
        # before it is parked as 'dead', and how many due rows one re-drive pass
        # processes (bounded so the pass never blocks the loop on a large queue).
        self.max_delivery_attempts = 5
        self.redrive_batch_size = 100
        # Journal scan is incremental and bounded (issue #183): each pass reads
        # at most `scan_batch_size` rows strictly after `_scan_cursor` instead of
        # the whole journal — the unbounded scan is what grew the API process to
        # 1.67 GB over the 4 h S11 soak.
        #
        # `_scan_cursor` is a COMPOSITE keyset — the (processed_at, event_id) of
        # the last contiguously-handled row — not a bare timestamp (audit
        # 2026-07-17 #1). A bare second-granular cursor advanced only to the
        # whole second and re-fetched `WHERE processed_at >= cursor`; a single
        # second holding >= `scan_batch_size` rows then filled every batch with
        # that second's lowest-event_id rows, re-pinned the cursor to the SAME
        # second, and silently dropped every webhook for every event at/after it
        # — permanently, with a healthy-looking cursor. The keyset advances
        # WITHIN a saturated second (`(processed_at, event_id) > cursor`), so the
        # batch size no longer has to exceed the largest same-second cohort for
        # the scan to make progress. The seen-set is capped and is now a
        # secondary safety net (the keyset is the primary dedup): eviction is
        # safe because enqueue is idempotent on its primary key and inline
        # delivery fires only for freshly inserted rows.
        #
        # `settle_seconds` guards the keyset's blind spot: a STRICT cursor is
        # only lossless over seconds no writer will stamp again. ClickHouse
        # `processed_at` is second-granular and event ids are UUIDs (not
        # monotonic), so a cursor advanced into the still-open wall-clock
        # second would permanently exclude any same-second row that becomes
        # visible later with a lower event_id — a silent drop at ORDINARY
        # load, worse than the wedge the keyset fixed. Every journal fetch is
        # therefore bounded to rows settled at least `settle_seconds` on the
        # DB clock; the frontier crosses only closed seconds. The value must
        # exceed writer stamp-to-visibility lag + writer↔DB clock skew
        # (AGENTFLOW_WEBHOOK_SETTLE_SECONDS; 0 opts out, accepting the drop
        # risk — tests only). Worst-case added delivery latency = settle.
        self.settle_seconds = settle_seconds
        self.scan_batch_size = scan_batch_size
        self.seen_event_ids: BoundedSeenSet = BoundedSeenSet(maxlen=seen_cache_size)
        self._scan_cursor: tuple[str, str] | None = None
        self._task: asyncio.Task | None = None
        # Settle-invariant detector (P3 runtime check): the settle watermark
        # only works while `settle_seconds` exceeds writer stamp-to-visibility
        # lag + clock skew; a violation is otherwise silent (a late-visible row
        # behind the frontier is never delivered). Once per interval the
        # dispatcher probes a bounded band immediately BEHIND the keyset frontier
        # for rows it never marked seen and warns + counts them — no per-pass
        # cost, no journal-wide scan, and zero effect on delivery semantics. The
        # probe stays out of open seconds by construction (its upper bound is the
        # frontier, which is already settled), so it runs identically on DuckDB
        # and ClickHouse. Silent when settle is opted out (`settle_seconds == 0`).
        self._settle_check_interval_seconds = 30.0
        self._settle_probe_lookback_seconds = max(60.0, float(settle_seconds) * 20.0)
        self._settle_probe_limit = 200
        # Seeded at construction (not None) so the probe first runs one interval
        # into the dispatcher's life, never on the very first pass — startup
        # warmup does not need a behind-frontier scan, and a single hand-driven
        # dispatch in a test stays a single journal fetch unless it opts in by
        # lowering the interval.
        self._last_settle_check_at: float = time.monotonic()
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
        """Initialize the scan frontier at the journal tail.

        Startup semantics: settled events already in the journal are not
        delivered, and the initialization is O(scan_batch_size), not
        O(journal): the newest settled batch seeds the seen-set and the
        cursor, and everything older is excluded by the cursor's keyset bound
        instead of by enumerating it (issue #183). Rows younger than the
        settle watermark are deliberately NOT seeded — they are delivered
        once settled, so events that raced a restart are not lost; a row the
        pre-restart process already delivered is suppressed by the durable
        enqueue's idempotent primary key, not re-POSTed.
        """
        try:
            events = self._fetch_pipeline_events(newest_first=True, limit=self.scan_batch_size)
        except (duckdb.Error, BackendExecutionError) as exc:
            logger.warning("webhook_seen_init_failed", error=str(exc))
            return
        for event in events:
            event_id = str(event.get("event_id") or "")
            if event_id:
                self.seen_event_ids.add(_seen_event_key(event))
        if events:
            # newest_first — seed the cursor from the newest row whose
            # processed_at parses AND that carries an event_id (both halves of
            # the keyset). If the very newest row is unusable, fall back to the
            # next usable row rather than leaving the cursor None: a None cursor
            # makes the next scan fetch from the oldest journal row, which
            # re-delivers the whole batch we just seeded (audit #185, defensive
            # seed-edge). All rows in this batch are already in the seen-set, so
            # advancing to any of their keys drops nothing.
            for event in events:
                seeded = _cursor_key(event)
                if seeded is not None:
                    self._scan_cursor = seeded
                    break

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
        #
        # The scan is incremental (issue #183): a bounded batch strictly after
        # the (processed_at, event_id) keyset cursor, ASC. The cursor advances
        # over the contiguous prefix of rows that end this pass seen (previously
        # or newly), and freezes at the first row left unseen (an enqueue
        # failure) so that row is re-fetched and retried next pass — the
        # retry-forever semantics the full scan provided, without materializing
        # the whole journal every 2 s. Because the cursor carries event_id, the
        # frontier moves even inside a single second that holds more than one
        # batch of rows (audit 2026-07-17 #1).
        newly_seen = 0
        advance: tuple[str, str] | None = None
        frozen = False
        cursor = self._scan_cursor
        for event in self._fetch_pipeline_events(
            limit=self.scan_batch_size,
            min_processed_at=cursor[0] if cursor is not None else None,
            min_event_id=cursor[1] if cursor is not None else None,
        ):
            event_id = str(event.get("event_id") or "")
            seen_key = _seen_event_key(event)
            # Dedup is keyed on ``seen_key`` (``tenant:event_id``) — the only
            # shape the seen-set ever stores (see mark_existing_events_seen and
            # the add below). A bare-``event_id`` membership test never matched
            # and dropped here as dead (audit #184); cross-tenant collisions on
            # the same event_id must stay distinct, so the namespaced key is the
            # correct and only check.
            if not event_id or seen_key in self.seen_event_ids:
                # Handled earlier (or unidentifiable — nothing to retry): let
                # the cursor move over it so a frontier of already-seen rows
                # cannot pin the scan window.
                if not frozen:
                    advance = _cursor_key(event) or advance
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
                if not frozen:
                    advance = _cursor_key(event) or advance
            else:
                frozen = True

        if advance is not None:
            self._scan_cursor = advance

        # Cheap, sampled runtime check that the settle invariant still holds.
        # Isolated so a probe failure can never disturb delivery.
        try:
            self._check_settle_invariant()
        except Exception as exc:  # pragma: no cover - defensive; probe is read-only
            logger.warning("webhook_settle_probe_error", error=str(exc))

        if newly_seen:
            for listener in self._on_new_events:
                try:
                    await listener()
                except Exception as exc:
                    logger.warning("webhook_new_events_listener_failed", error=str(exc))

    def _check_settle_invariant(self) -> None:
        """Detect a violated settle invariant cheaply, at runtime.

        The operator invariant behind the settle watermark is ``settle_seconds >
        writer stamp-to-visibility lag + writer<->DB clock skew``. When it holds,
        the strict keyset frontier only crosses seconds no writer will stamp
        again. When it is violated, a row becomes visible with a
        ``(processed_at, event_id)`` already behind the frontier; every future
        forward scan excludes it and it is **never delivered** — a silent drop.

        The forward scan cannot see such a row (that is the whole problem), so
        this probe looks the other way: a single bounded ``newest_first`` window
        in the band immediately behind the current frontier
        (``max_processed_at = frontier``), for rows the dispatcher never marked
        seen. Each such row is a concrete never-handed-out delivery and bumps
        ``agentflow_webhook_settle_violations_total`` with a warning.

        Cost control: it runs at most once per ``_settle_check_interval_seconds``
        (not every pass), fetches at most ``_settle_probe_limit`` rows within a
        bounded lookback band, and never materializes the journal — so it adds no
        per-pass cost and cannot regrow the RSS issue #183 fixed. It only reads
        ``fetch_pipeline_events`` (the ClickHouse-safe chokepoint) and the
        in-memory seen-set, so it works on both the DuckDB and ClickHouse serving
        stores. Silent under the ``settle_seconds == 0`` opt-out.

        Residual limits (documented, not silent): membership is tested against
        the bounded seen-set, so a genuine drop whose id was already evicted
        (only under an extreme burst wider than the seen-set within the lookback
        band) could be missed or, if delivered-then-evicted, over-counted; the
        probe is read-only either way and never changes what is delivered. A
        pathologically late arrival stamped older than the lookback band is also
        outside the window — the band is sized for realistic lag near the settle
        boundary.
        """
        if self.settle_seconds <= 0:
            return
        cursor = self._scan_cursor
        if cursor is None:
            return
        now = time.monotonic()
        if (now - self._last_settle_check_at) < self._settle_check_interval_seconds:
            return
        self._last_settle_check_at = now

        frontier_ts, frontier_id = cursor
        frontier_dt = _parse_cursor_timestamp(frontier_ts)
        if frontier_dt is None:
            return
        band_lower = frontier_dt - timedelta(seconds=self._settle_probe_lookback_seconds)
        try:
            behind = self._fetch_pipeline_events(
                limit=self._settle_probe_limit,
                newest_first=True,
                min_processed_at=band_lower,
                max_processed_at=frontier_ts,
                # The band's upper bound is the already-settled frontier, so the
                # watermark is redundant here; disable it so the probe cannot be
                # confused with the forward scan's settle bound.
                settle_seconds=0,
            )
        except Exception as exc:
            logger.warning("webhook_settle_probe_failed", error=str(exc))
            return

        undelivered: list[dict] = []
        for event in behind:
            key = _cursor_key(event)
            if key is None:
                continue
            ev_ts, ev_id = key
            ev_dt = _parse_cursor_timestamp(ev_ts)
            if ev_dt is None:
                continue
            # Keep only rows STRICTLY behind the keyset frontier — the exact set
            # the forward scan `(t > ts OR (t = ts AND id > id))` will never
            # return. Rows at or ahead of the frontier are still deliverable.
            if ev_dt > frontier_dt or (ev_dt == frontier_dt and ev_id >= frontier_id):
                continue
            if _seen_event_key(event) in self.seen_event_ids:
                continue
            undelivered.append(event)

        if undelivered:
            WEBHOOK_SETTLE_VIOLATIONS.inc(len(undelivered))
            sample = undelivered[0]
            logger.warning(
                "webhook_settle_invariant_violation",
                settle_seconds=self.settle_seconds,
                frontier_processed_at=frontier_ts,
                frontier_event_id=frontier_id,
                undelivered_behind_frontier=len(undelivered),
                sample_event_id=str(sample.get("event_id") or ""),
                sample_processed_at=str(sample.get("processed_at") or ""),
            )

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

    def _fetch_pipeline_events(
        self,
        tenant: str | None = None,
        *,
        limit: int | None = None,
        newest_first: bool = False,
        min_processed_at: str | datetime | None = None,
        min_event_id: str | None = None,
        max_processed_at: str | datetime | None = None,
        settle_seconds: int | None = None,
    ) -> list[dict]:
        # Scan the journal through the serving backend, not the embedded DuckDB
        # connection: when serving is ClickHouse (ADR 0006) the events that
        # matter arrive from an out-of-process writer, and this scan is what
        # drives both webhook delivery and metric-cache invalidation.
        # Single chokepoint for the settle watermark: both the poll scan and
        # the startup seeding go through here, so neither can advance the
        # frontier into a second writers may still stamp.
        events: list[dict] = self.app.state.query_engine.fetch_pipeline_events(
            tenant_id=tenant,
            limit=limit,
            newest_first=newest_first,
            min_processed_at=min_processed_at,
            min_event_id=min_event_id,
            max_processed_at=max_processed_at,
            settle_seconds=self.settle_seconds if settle_seconds is None else settle_seconds,
        )
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
        control-plane store; the retry policy stays dispatcher configuration.

        ``delivery_id`` (the per-round id ``deliver``/``_deliver_body`` mints and
        returns in ``result``) is the idempotency token the store uses so a
        retry of this write after a lost commit-ack does not count the same
        outcome twice — the attempts+2 → premature dead-letter bug (P3)."""
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
            delivery_id=result.get("delivery_id"),
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


def _cursor_timestamp(event: dict) -> str | None:
    """Normalize a journal row's ``processed_at`` into a scan-cursor string.

    Returns ``YYYY-MM-DD HH:MM:SS[.ffffff]`` or ``None`` when the value is
    missing or does not round-trip through strict parsing, so a malformed row
    can degrade one cursor advance but never poison the next scan's SQL.

    Sub-second precision is *preserved* when present: the composite keyset the
    cursor feeds compares ``processed_at`` exactly, and flooring a DuckDB
    microsecond timestamp to its whole second would collapse a saturated
    second's rows into one key and let the scan re-wedge there (audit
    2026-07-17 #1). On ClickHouse ``processed_at`` is second-granular, so the
    string is a whole second either way — the same literal shape as before.
    """
    value = event.get("processed_at")
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.microsecond:
            return value.strftime("%Y-%m-%d %H:%M:%S.%f")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.microsecond:
            return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return None


def _parse_cursor_timestamp(text: str) -> datetime | None:
    """Parse a normalized cursor string back into a naive datetime.

    Inverse of :func:`_cursor_timestamp` for the settle-invariant detector's
    in-Python keyset comparison — comparing datetimes (not raw strings) avoids
    any lexicographic edge between whole-second and sub-second stamps of the
    same second. Returns ``None`` on anything that does not round-trip, so a
    malformed row is skipped rather than crashing the probe.
    """
    candidate = text.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    return None


def _cursor_key(event: dict) -> tuple[str, str] | None:
    """Composite keyset cursor ``(processed_at, event_id)`` for a journal row.

    Returns ``None`` when the row cannot anchor a cursor — a missing/malformed
    ``processed_at`` or a missing ``event_id`` — so the caller keeps its prior
    cursor rather than advancing onto an unusable key. Both halves are required:
    the keyset only defeats the same-second cohort wedge when it can order rows
    that share a ``processed_at`` by ``event_id``.
    """
    ts = _cursor_timestamp(event)
    if ts is None:
        return None
    event_id = str(event.get("event_id") or "")
    if not event_id:
        return None
    return (ts, event_id)


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
