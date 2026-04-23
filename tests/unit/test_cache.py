import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.serving.api.routers.agent_query as agent_query_module
import src.serving.cache as cache_module
from src.serving.api.routers.agent_query import router as agent_router
from src.serving.cache import QueryCache
from src.serving.semantic_layer.catalog import DataCatalog


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.deleted: list[tuple[str, ...]] = []
        self.set_calls: list[tuple[str, object, str]] = []
        self.raise_on_get: Exception | None = None
        self.raise_on_setex: Exception | None = None
        self.raise_on_keys: Exception | None = None
        self.closed = False

    async def get(self, key: str):
        if self.raise_on_get is not None:
            raise self.raise_on_get
        return self.data.get(key)

    async def setex(self, key: str, ttl, value: str):
        if self.raise_on_setex is not None:
            raise self.raise_on_setex
        self.set_calls.append((key, ttl, value))
        self.data[key] = value

    async def keys(self, pattern: str):
        if self.raise_on_keys is not None:
            raise self.raise_on_keys
        prefix = pattern[:-1] if pattern.endswith("*") else pattern
        return [key for key in self.data if key.startswith(prefix)]

    async def delete(self, *keys: str):
        self.deleted.append(keys)
        for key in keys:
            self.data.pop(key, None)

    async def aclose(self):
        self.closed = True


class ClosingRedis:
    async def aclose(self):
        raise RuntimeError("Event loop is closed")


class LoggerSpy:
    def __init__(self):
        self.debug_calls: list[tuple[str, dict]] = []
        self.warning_calls: list[tuple[str, dict]] = []

    def debug(self, event: str, **kwargs):
        self.debug_calls.append((event, kwargs))

    def warning(self, event: str, **kwargs):
        self.warning_calls.append((event, kwargs))


class EngineStub:
    def __init__(self, result: dict | None = None):
        self.calls: list[tuple[str, str, datetime | None]] = []
        self.result = result or {
            "value": 42.0,
            "unit": "USD",
            "components": {"sample": 1},
        }

    def get_metric(
        self,
        metric_name: str,
        window: str = "1h",
        as_of: datetime | None = None,
    ) -> dict:
        self.calls.append((metric_name, window, as_of))
        return dict(self.result)


def _build_client(cache: QueryCache, engine: EngineStub) -> TestClient:
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.state.query_engine = engine
    app.state.query_cache = cache
    app.state.cache_ttl_seconds = 30
    app.include_router(agent_router, prefix="/v1")
    return TestClient(app)


@pytest.mark.asyncio
async def test_query_cache_get_deserializes_payload():
    redis_client = FakeRedis()
    key = QueryCache.metric_key("revenue", "1h")
    redis_client.data[key] = json.dumps({"value": 12.5, "unit": "USD"})
    cache = QueryCache(redis_client=redis_client)

    result = await cache.get(key)

    assert result == {"value": 12.5, "unit": "USD"}


@pytest.mark.asyncio
async def test_query_cache_set_serializes_payload_with_ttl():
    redis_client = FakeRedis()
    cache = QueryCache(redis_client=redis_client)

    await cache.set("metric:revenue:1h:now", {"value": 99.0}, ttl=45)

    key, ttl, value = redis_client.set_calls[0]
    assert key == "metric:revenue:1h:now"
    assert int(ttl.total_seconds()) == 45
    assert json.loads(value) == {"value": 99.0}


@pytest.mark.asyncio
async def test_query_cache_invalidate_metrics_deletes_metric_keys():
    redis_client = FakeRedis()
    redis_client.data = {
        "metric:revenue:1h:now": json.dumps({"value": 1}),
        "metric:error_rate:1h:now": json.dumps({"value": 0.1}),
        "entity:order:1": json.dumps({"value": "ignored"}),
    }
    cache = QueryCache(redis_client=redis_client)

    await cache.invalidate_metrics()

    assert redis_client.deleted == [("metric:revenue:1h:now", "metric:error_rate:1h:now")]
    assert "entity:order:1" in redis_client.data


def test_metric_key_uses_now_when_as_of_is_missing():
    assert QueryCache.metric_key("revenue", "24h") == "metric:revenue:24h:now"


def test_metric_endpoint_returns_cached_response_with_hit_header(monkeypatch):
    logger = LoggerSpy()
    monkeypatch.setattr(agent_query_module, "logger", logger)
    redis_client = FakeRedis()
    computed_at = datetime(2026, 4, 10, 12, 0, tzinfo=UTC).isoformat()
    redis_client.data["metric:revenue:1h:now"] = json.dumps(
        {
            "metric_name": "revenue",
            "value": 123.4,
            "unit": "USD",
            "window": "1h",
            "computed_at": computed_at,
            "components": {"source": "cache"},
            "meta": {
                "as_of": None,
                "is_historical": False,
                "freshness_seconds": None,
            },
        }
    )
    engine = EngineStub()
    client = _build_client(QueryCache(redis_client=redis_client), engine)

    response = client.get("/v1/metrics/revenue?window=1h")

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "HIT"
    assert response.json()["value"] == 123.4
    assert engine.calls == []
    assert logger.debug_calls == [("metric_cache_hit", {"key": "metric:revenue:1h:now"})]


def test_metric_endpoint_returns_miss_header_and_populates_cache():
    redis_client = FakeRedis()
    engine = EngineStub(result={"value": 77.7, "unit": "USD", "components": None})
    client = _build_client(QueryCache(redis_client=redis_client), engine)

    response = client.get("/v1/metrics/revenue?window=24h")

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert engine.calls[0][:2] == ("revenue", "24h")
    cached = json.loads(redis_client.data["metric:revenue:24h:now"])
    assert cached["value"] == 77.7
    assert cached["window"] == "24h"


def test_metric_endpoint_warns_and_serves_uncached_when_redis_is_unavailable(monkeypatch):
    logger = LoggerSpy()
    monkeypatch.setattr(cache_module, "logger", logger)
    redis_client = FakeRedis()
    redis_client.raise_on_get = RuntimeError("redis down")
    redis_client.raise_on_setex = RuntimeError("redis down")
    engine = EngineStub()
    client = _build_client(QueryCache(redis_client=redis_client), engine)

    response = client.get("/v1/metrics/revenue?window=1h")

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert response.json()["value"] == 42.0
    assert len(engine.calls) == 1
    assert logger.warning_calls == [
        ("query_cache_unavailable", {"operation": "get", "error": "redis down"}),
        ("query_cache_unavailable", {"operation": "set", "error": "redis down"}),
    ]


@pytest.mark.asyncio
async def test_query_cache_close_closes_underlying_client():
    redis_client = FakeRedis()
    cache = QueryCache(redis_client=redis_client)

    await cache.close()

    assert redis_client.closed is True


@pytest.mark.asyncio
async def test_query_cache_close_ignores_closed_event_loop_runtime_error():
    cache = QueryCache(redis_client=ClosingRedis())

    await cache.close()
