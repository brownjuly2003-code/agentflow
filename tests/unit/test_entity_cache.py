from __future__ import annotations

import json
from decimal import Decimal
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.serving.api.routers.agent_query import router as agent_router
from src.serving.cache import (
    ENTITY_TTL_SECONDS,
    QueryCache,
    cache_entity_key,
    invalidate_entity,
)
from src.serving.semantic_layer.catalog import DataCatalog


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.deleted: list[tuple[str, ...]] = []
        self.set_calls: list[tuple[str, object, str]] = []

    async def get(self, key: str):
        return self.data.get(key)

    async def setex(self, key: str, ttl, value: str) -> None:
        self.set_calls.append((key, ttl, value))
        self.data[key] = value

    async def delete(self, *keys: str) -> None:
        self.deleted.append(keys)
        for key in keys:
            self.data.pop(key, None)

    async def aclose(self) -> None:
        return None


class EntityEngineStub:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {
            "order_id": "ORD-20260401-0001",
            "status": "paid",
            "_last_updated": "2026-04-10T12:00:00+00:00",
        }
        self.calls: list[tuple[str, str, datetime | None, str | None]] = []

    def get_entity(
        self,
        entity_type: str,
        entity_id: str,
        tenant_id: str | None = None,
    ) -> dict:
        self.calls.append((entity_type, entity_id, None, tenant_id))
        return dict(self.payload)

    def get_entity_at(
        self,
        entity_type: str,
        entity_id: str,
        as_of: datetime,
        tenant_id: str | None = None,
    ) -> dict:
        self.calls.append((entity_type, entity_id, as_of, tenant_id))
        return dict(self.payload)


def _build_client(cache: QueryCache, engine: EntityEngineStub) -> TestClient:
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.state.query_engine = engine
    app.state.query_cache = cache

    @app.middleware("http")
    async def inject_tenant(request: Request, call_next):
        request.state.tenant_key = SimpleNamespace(tenant="acme")
        return await call_next(request)

    app.include_router(agent_router, prefix="/v1")
    return TestClient(app)


def test_entity_endpoint_returns_miss_then_hit_header_and_populates_cache() -> None:
    redis_client = FakeRedis()
    engine = EntityEngineStub()
    client = _build_client(QueryCache(redis_client=redis_client), engine)

    miss = client.get("/v1/entity/order/ORD-20260401-0001")
    hit = client.get("/v1/entity/order/ORD-20260401-0001")

    cache_key = cache_entity_key("acme", "order", "ORD-20260401-0001")
    assert miss.status_code == 200
    assert miss.headers["X-Cache"] == "MISS"
    assert hit.status_code == 200
    assert hit.headers["X-Cache"] == "HIT"
    assert engine.calls == [("order", "ORD-20260401-0001", None, "acme")]
    key, ttl, cached_payload = redis_client.set_calls[0]
    assert key == cache_key
    assert int(ttl.total_seconds()) == ENTITY_TTL_SECONDS
    assert json.loads(cached_payload)["payload"]["entity_id"] == "ORD-20260401-0001"


def test_entity_endpoint_does_not_cache_historical_queries() -> None:
    redis_client = FakeRedis()
    engine = EntityEngineStub()
    client = _build_client(QueryCache(redis_client=redis_client), engine)

    first = client.get("/v1/entity/order/ORD-20260401-0001?as_of=2026-04-10T11:30:00Z")
    second = client.get("/v1/entity/order/ORD-20260401-0001?as_of=2026-04-10T11:30:00Z")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "X-Cache" not in first.headers
    assert "X-Cache" not in second.headers
    assert len(engine.calls) == 2
    assert redis_client.data == {}


def test_entity_endpoint_caches_decimal_payloads() -> None:
    redis_client = FakeRedis()
    engine = EntityEngineStub(
        payload={
            "order_id": "ORD-20260401-0001",
            "status": "paid",
            "total_amount": Decimal("159.98"),
            "_last_updated": "2026-04-10T12:00:00+00:00",
        }
    )
    client = _build_client(QueryCache(redis_client=redis_client), engine)

    miss = client.get("/v1/entity/order/ORD-20260401-0001")
    hit = client.get("/v1/entity/order/ORD-20260401-0001")

    cache_key = cache_entity_key("acme", "order", "ORD-20260401-0001")
    assert miss.status_code == 200
    assert miss.headers["X-Cache"] == "MISS"
    assert hit.status_code == 200
    assert hit.headers["X-Cache"] == "HIT"
    assert engine.calls == [("order", "ORD-20260401-0001", None, "acme")]
    assert json.loads(redis_client.data[cache_key])["payload"]["data"]["total_amount"] == 159.98


@pytest.mark.asyncio
async def test_invalidate_entity_deletes_only_scoped_entity_key() -> None:
    redis_client = FakeRedis()
    target_key = cache_entity_key("acme", "order", "ORD-20260401-0001")
    other_key = cache_entity_key("demo", "order", "ORD-20260401-0001")
    redis_client.data[target_key] = json.dumps({"payload": {"entity_id": "ORD-20260401-0001"}})
    redis_client.data[other_key] = json.dumps({"payload": {"entity_id": "ORD-20260401-0001"}})
    cache = QueryCache(redis_client=redis_client)

    await invalidate_entity(cache, "acme", "order", "ORD-20260401-0001")

    assert redis_client.deleted == [(target_key,)]
    assert target_key not in redis_client.data
    assert other_key in redis_client.data
