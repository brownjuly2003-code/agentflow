"""S7 — push-driven metric-cache invalidation and webhook-independent scan."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

import src.serving.cache_invalidation as cache_invalidation_module
from src.serving.cache import QueryCache
from src.serving.cache_invalidation import (
    METRICS_INVALIDATE_CHANNEL,
    MetricCacheController,
    journal_scan_fetch,
    publish_metrics_invalidate,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.deleted: list[tuple[str, ...]] = []
        self.published: list[tuple[str, str]] = []
        self._pubsub: FakePubSub | None = None

    async def scan(self, cursor: int, match: str = "*", count: int = 100):
        prefix = match[:-1] if match.endswith("*") else match
        return 0, [key for key in self.data if key.startswith(prefix)]

    async def delete(self, *keys: str) -> None:
        self.deleted.append(keys)
        for key in keys:
            self.data.pop(key, None)

    def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    def pubsub(self) -> FakePubSub:
        self._pubsub = FakePubSub(self)
        return self._pubsub

    def close(self) -> None:
        return None


class FakePubSub:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._queue: list[dict[str, Any]] = []
        self.subscribed: list[str] = []
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        if channel in self.subscribed:
            self.subscribed.remove(channel)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0):
        if self._queue:
            return self._queue.pop(0)
        await asyncio.sleep(min(timeout, 0.01))
        return None

    def push(self, payload: str) -> None:
        self._queue.append(
            {
                "type": "message",
                "channel": METRICS_INVALIDATE_CHANNEL,
                "data": payload,
            }
        )

    async def aclose(self) -> None:
        self.closed = True


class SyncRedisSpy:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.closed = False

    def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    def close(self) -> None:
        self.closed = True


def test_publish_metrics_invalidate_uses_injected_client():
    spy = SyncRedisSpy()
    ok = publish_metrics_invalidate(
        "redis://unused",
        ["evt-1", "evt-2"],
        redis_client=spy,
    )
    assert ok is True
    assert spy.published == [
        (
            METRICS_INVALIDATE_CHANNEL,
            json.dumps({"event_ids": ["evt-1", "evt-2"]}),
        )
    ]
    assert spy.closed is False  # injected client is not closed by the helper


def test_publish_metrics_invalidate_swallows_client_errors():
    class Boom:
        def publish(self, *_a, **_k):
            raise RuntimeError("redis down")

        def close(self) -> None:
            return None

    assert publish_metrics_invalidate("redis://x", ["e"], redis_client=Boom()) is False


@pytest.mark.asyncio
async def test_notify_batch_applied_invalidates_metric_keys():
    redis = FakeRedis()
    redis.data = {
        "metric:revenue:1h:now": json.dumps({"value": 1}),
        "entity:order:1": json.dumps({"id": "1"}),
    }
    cache = QueryCache(redis_client=redis)
    controller = MetricCacheController(cache, redis_client=redis)

    await controller.notify_batch_applied(["evt-a"])

    assert redis.deleted == [("metric:revenue:1h:now",)]
    assert "entity:order:1" in redis.data
    assert "evt-a" in controller.seen_event_ids


@pytest.mark.asyncio
async def test_scan_fallback_invalidates_without_webhook_dispatcher():
    """DoD: invalidation works when webhook_dispatcher_autostart=False."""
    redis = FakeRedis()
    redis.data = {"metric:revenue:1h:now": json.dumps({"value": 9})}
    cache = QueryCache(redis_client=redis)
    journal = [
        {"event_id": "seed-1", "topic": "events.validated"},
    ]

    def fetch() -> list[dict]:
        return list(journal)

    controller = MetricCacheController(
        cache,
        redis_client=redis,
        fetch_pipeline_events=fetch,
        scan_interval_seconds=0.05,
    )
    controller.start()
    # First start marks existing events seen without invalidating.
    await asyncio.sleep(0.02)
    assert redis.deleted == []

    journal.append({"event_id": "new-2", "topic": "events.validated"})
    await asyncio.sleep(0.12)
    await controller.stop()

    assert any("metric:revenue:1h:now" in keys for keys in redis.deleted)
    assert "new-2" in controller.seen_event_ids


@pytest.mark.asyncio
async def test_push_listener_invalidates_on_pubsub_message():
    redis = FakeRedis()
    redis.data = {"metric:error_rate:1h:now": json.dumps({"value": 0.1})}
    cache = QueryCache(redis_client=redis)
    controller = MetricCacheController(cache, redis_client=redis)
    controller.start()
    await asyncio.sleep(0.02)
    assert redis._pubsub is not None
    assert METRICS_INVALIDATE_CHANNEL in redis._pubsub.subscribed

    redis._pubsub.push(json.dumps({"event_ids": ["pushed-1"]}))
    await asyncio.sleep(0.08)
    await controller.stop()

    assert any("metric:error_rate:1h:now" in keys for keys in redis.deleted)
    assert "pushed-1" in controller.seen_event_ids


@pytest.mark.asyncio
async def test_webhook_listener_hook_fires_on_new_events():
    """First-class listener replaces the main.py monkey-patch."""
    from types import SimpleNamespace

    import duckdb

    from src.serving.api.webhook_dispatcher import WebhookDispatcher
    from src.serving.backends.duckdb_backend import DuckDBBackend
    from src.serving.semantic_layer.query import QueryEngine

    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR DEFAULT 'default',
            event_type VARCHAR, processed_at TIMESTAMP
        )
        """
    )
    conn.execute(
        "INSERT INTO pipeline_events VALUES "
        "('e-new', 'events.validated', 'acme', 'order.created', NOW())"
    )
    engine = QueryEngine.__new__(QueryEngine)
    backend = DuckDBBackend(db_path=":memory:", connection=conn)
    engine._duckdb_backend = backend
    engine._backend = backend
    engine._backend_name = backend.name
    engine._conn = conn
    app = SimpleNamespace(state=SimpleNamespace(query_engine=engine))
    dispatcher = WebhookDispatcher(app)
    hits: list[int] = []

    async def listener() -> None:
        hits.append(1)

    dispatcher.add_new_events_listener(listener)
    await dispatcher.dispatch_new_events()
    conn.close()

    assert hits == [1]
    assert "acme:e-new" in dispatcher.seen_event_ids


# --- bounded scan window / bounded seen-set (issue #183) ----------------------


def _duckdb_engine_with_journal(row_count: int):
    import duckdb

    from src.serving.backends.duckdb_backend import DuckDBBackend
    from src.serving.semantic_layer.query import QueryEngine

    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR DEFAULT 'default',
            event_type VARCHAR, processed_at TIMESTAMP
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO pipeline_events
        SELECT 'evt-' || i, 'events.validated', 'default', 'order.created',
               TIMESTAMP '2026-07-10 00:00:00' + INTERVAL 1 SECOND * i
        FROM range({row_count}) t(i)
        """
    )
    engine = QueryEngine.__new__(QueryEngine)
    backend = DuckDBBackend(db_path=":memory:", connection=conn)
    engine._duckdb_backend = backend
    engine._backend = backend
    engine._backend_name = backend.name
    engine._conn = conn
    return conn, engine


@pytest.mark.asyncio
async def test_scan_fallback_sees_new_events_when_journal_outgrows_the_window():
    """Regression (issue #183): the lifespan wired the fallback with an
    ascending limited scan — the oldest rows — a window that stops changing
    once the journal outgrows it, silently killing scan-driven invalidation.
    ``journal_scan_fetch`` must read the tail window instead."""
    redis = FakeRedis()
    redis.data = {"metric:revenue:1h:now": json.dumps({"value": 9})}
    cache = QueryCache(redis_client=redis)
    conn, engine = _duckdb_engine_with_journal(row_count=250)
    try:
        controller = MetricCacheController(
            cache,
            redis_client=redis,
            fetch_pipeline_events=journal_scan_fetch(engine, limit=200),
        )
        controller._mark_existing_seen()
        assert await controller.scan_once() == 0  # steady journal — no drop

        conn.execute(
            "INSERT INTO pipeline_events VALUES "
            "('evt-fresh', 'events.validated', 'default', 'order.created', "
            "TIMESTAMP '2026-07-10 01:00:00')"
        )

        assert await controller.scan_once() == 1
        assert any("metric:revenue:1h:now" in keys for keys in redis.deleted)
        assert "evt-fresh" in controller.seen_event_ids
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_push_path_seen_ids_stay_bounded():
    redis = FakeRedis()
    cache = QueryCache(redis_client=redis)
    controller = MetricCacheController(cache, redis_client=redis, seen_cache_size=5)

    await controller.notify_batch_applied([f"evt-{i}" for i in range(20)])

    assert len(controller.seen_event_ids) == 5  # capped — one entry per event forever was the leak
    assert "evt-19" in controller.seen_event_ids


def test_parse_event_ids_tolerates_garbage():
    assert cache_invalidation_module._parse_event_ids(None) == []
    assert cache_invalidation_module._parse_event_ids(b'{"event_ids":["a"]}') == ["a"]
    assert cache_invalidation_module._parse_event_ids("{not-json") == []
    assert cache_invalidation_module._parse_event_ids('{"event_ids":"x"}') == []
