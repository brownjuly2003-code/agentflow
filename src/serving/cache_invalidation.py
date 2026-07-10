"""S7 — push-driven metric-cache invalidation.

Two independent feeds keep the Redis metric cache honest:

1. **Push** — the serving bridge publishes after a successful apply
   (``agentflow:cache:metrics_invalidate``). Cross-process and multi-replica
   safe: every API pod that is listening drops its metric keys.
2. **Scan** — a lightweight journal poll that does *not* depend on the webhook
   dispatcher. Covers writers that do not push (node-ingest, seed, outbox
   side-effects) and remains correct when
   ``webhook_dispatcher_autostart=False``.

The historical monkey-patch that wrapped
``WebhookDispatcher.dispatch_new_events`` is gone: webhooks and cache are
first-class subscribers, not a hijacked method.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from collections.abc import Callable, Sequence
from typing import Any

import structlog

from src.serving.cache import QueryCache
from src.serving.seen_events import BoundedSeenSet

logger = structlog.get_logger()

# Stable channel name — bridge process and API pods must agree.
METRICS_INVALIDATE_CHANNEL = "agentflow:cache:metrics_invalidate"

# How often the journal fallback re-scans when no push has landed.
DEFAULT_SCAN_INTERVAL_SECONDS = 2.0

# One scan window: enough to always contain the journal tail between two
# 2-second passes with an order of magnitude to spare (87 eps measured × 2 s
# ≈ 175 rows), small enough to stay O(1) against a journal of any size.
DEFAULT_SCAN_WINDOW_ROWS = 200

# Dedup memory cap. Eviction is harmless here: a re-detected old event only
# causes one redundant invalidate, and the metric cache repopulates on the
# next read. What matters is that push feeds (one entry per applied event)
# can no longer grow the set with the journal (issue #183).
DEFAULT_SEEN_CACHE_SIZE = 10_000


def journal_scan_fetch(
    query_engine: Any, limit: int = DEFAULT_SCAN_WINDOW_ROWS
) -> Callable[[], list[dict]]:
    """Build the journal-scan callable the controller polls.

    ``newest_first`` is essential, not cosmetic: the fallback detects fresh
    events by scanning a bounded window, and only the *tail* window is
    guaranteed to contain them. An ascending scan with a limit reads the
    oldest rows — a window that stops changing once the journal outgrows it,
    which silently killed the fallback on any long-running deployment
    (found while fixing issue #183).
    """

    def _fetch() -> list[dict]:
        return list(query_engine.fetch_pipeline_events(limit=limit, newest_first=True) or [])

    return _fetch


def publish_metrics_invalidate(
    redis_url: str,
    event_ids: Sequence[str] | None = None,
    *,
    redis_client: Any | None = None,
) -> bool:
    """Publish a cache-invalidation signal (sync — safe from the bridge thread).

    Returns ``True`` when the message was published. Failures are logged and
    swallowed: a missing Redis must not take the bridge down (the scan fallback
    on the API side still covers the journal).
    """
    payload = json.dumps({"event_ids": list(event_ids or [])})
    owns_client = redis_client is None
    client = redis_client
    try:
        if client is None:
            try:
                import redis as redis_sync
            except ImportError:  # pragma: no cover - optional dep missing
                logger.warning(
                    "cache_invalidate_publish_unavailable",
                    error="redis package not installed",
                )
                return False
            # Short timeouts: the bridge must not stall an apply on a missing
            # Redis (the API's journal scan is the safety net).
            client = redis_sync.from_url(
                redis_url,
                socket_connect_timeout=0.15,
                socket_timeout=0.15,
            )
        client.publish(METRICS_INVALIDATE_CHANNEL, payload)
        return True
    except Exception as exc:
        logger.warning("cache_invalidate_publish_failed", error=str(exc))
        return False
    finally:
        if owns_client and client is not None:
            try:
                client.close()
            except Exception as exc:  # pragma: no cover - close is best-effort
                logger.debug("cache_invalidate_publish_close_failed", error=str(exc))


class MetricCacheController:
    """Owns push listening + journal-scan fallback for metric-cache drops.

    Constructed once in the API lifespan. Always starts regardless of webhook
    autostart so invalidation is not hostage to a delivery loop.
    """

    def __init__(
        self,
        cache: QueryCache,
        *,
        redis_url: str | None = None,
        scan_interval_seconds: float = DEFAULT_SCAN_INTERVAL_SECONDS,
        fetch_pipeline_events: Callable[[], Sequence[dict]] | None = None,
        redis_client: Any | None = None,
        seen_cache_size: int = DEFAULT_SEEN_CACHE_SIZE,
    ) -> None:
        self._cache = cache
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self._scan_interval = scan_interval_seconds
        self._fetch_pipeline_events = fetch_pipeline_events
        # Prefer an injected client (tests, shared pool). Fall back to the
        # cache's own Redis handle, then to none (push listener no-ops).
        self._redis = redis_client if redis_client is not None else getattr(cache, "_redis", None)
        # Bounded (issue #183): the push path adds every applied event's id,
        # which is one entry per pipeline event forever on an unbounded set.
        self._seen_event_ids: BoundedSeenSet = BoundedSeenSet(maxlen=seen_cache_size)
        self._push_task: asyncio.Task | None = None
        self._scan_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._invalidate_lock = asyncio.Lock()

    @property
    def seen_event_ids(self) -> BoundedSeenSet:
        return self._seen_event_ids

    async def invalidate(self) -> None:
        """Drop all metric:* keys. Serialized so concurrent feeds coalesce."""
        async with self._invalidate_lock:
            await self._cache.invalidate_metrics()

    async def notify_batch_applied(self, event_ids: Sequence[str] | None = None) -> None:
        """In-process push path (DuckDB bridge thread / same-process writers)."""
        if event_ids:
            for event_id in event_ids:
                self._seen_event_ids.add(str(event_id))
        await self.invalidate()

    async def scan_once(self) -> int:
        """One journal pass: mark new event_ids seen and invalidate if any.

        Used by the background fallback loop and by tests that assert
        invalidation without webhooks (S7). Returns the number of newly
        seen event_ids.
        """
        if self._fetch_pipeline_events is None:
            return 0
        new_count = 0
        for event in self._fetch_pipeline_events():
            event_id = str(event.get("event_id") or "")
            if not event_id or event_id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(event_id)
            new_count += 1
        if new_count:
            await self.invalidate()
        return new_count

    def start(self) -> None:
        if self._push_task is None or self._push_task.done():
            self._stop.clear()
            self._push_task = asyncio.create_task(self._run_push_listener())
        if self._fetch_pipeline_events is not None and (
            self._scan_task is None or self._scan_task.done()
        ):
            self._mark_existing_seen()
            self._scan_task = asyncio.create_task(self._run_scan_fallback())

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._push_task, self._scan_task):
            if task is None or task.done():
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._push_task = None
        self._scan_task = None

    def _mark_existing_seen(self) -> None:
        if self._fetch_pipeline_events is None:
            return
        try:
            for event in self._fetch_pipeline_events():
                event_id = str(event.get("event_id") or "")
                if event_id:
                    self._seen_event_ids.add(event_id)
        except Exception as exc:
            logger.warning("cache_invalidate_seen_init_failed", error=str(exc))

    async def _run_push_listener(self) -> None:
        if self._redis is None:
            logger.info("cache_invalidate_push_listener_skipped", reason="no_redis")
            return
        try:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(METRICS_INVALIDATE_CHANNEL)
        except Exception as exc:
            logger.warning("cache_invalidate_push_subscribe_failed", error=str(exc))
            return
        logger.info("cache_invalidate_push_listener_started", channel=METRICS_INVALIDATE_CHANNEL)
        try:
            while not self._stop.is_set():
                try:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                except Exception as exc:
                    logger.warning("cache_invalidate_push_read_failed", error=str(exc))
                    await asyncio.sleep(1.0)
                    continue
                if message is None:
                    # redis-py async yields None on timeout; yield the loop.
                    await asyncio.sleep(0.05)
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                event_ids = _parse_event_ids(data)
                if event_ids:
                    for event_id in event_ids:
                        self._seen_event_ids.add(event_id)
                await self.invalidate()
                logger.debug(
                    "cache_invalidate_push_applied",
                    event_count=len(event_ids),
                )
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await pubsub.unsubscribe(METRICS_INVALIDATE_CHANNEL)
                close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
                if close is not None:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
            except Exception as exc:  # pragma: no cover - teardown best-effort
                logger.debug("cache_invalidate_push_teardown_failed", error=str(exc))

    async def _run_scan_fallback(self) -> None:
        while not self._stop.is_set():
            try:
                await self.scan_once()
            except Exception as exc:
                logger.warning("cache_invalidate_scan_failed", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._scan_interval)
            except TimeoutError:
                continue


def _parse_event_ids(data: Any) -> list[str]:
    if data is None:
        return []
    if isinstance(data, bytes):
        data = data.decode()
    if not isinstance(data, str):
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    raw_ids = payload.get("event_ids") or []
    if not isinstance(raw_ids, list):
        return []
    return [str(item) for item in raw_ids if item]
