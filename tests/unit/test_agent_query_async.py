import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI

from src.serving.api.routers.agent_query import router as agent_router
from src.serving.semantic_layer.catalog import DataCatalog


class SlowEngine:
    def __init__(self, delay_seconds: float):
        self.delay_seconds = delay_seconds

    def get_entity(
        self,
        entity_type: str,
        entity_id: str,
        tenant_id: str | None = None,
    ) -> dict:
        time.sleep(self.delay_seconds)
        return {
            "id": entity_id,
            "entity_type": entity_type,
            "tenant_id": tenant_id,
        }

    def get_metric(
        self,
        metric_name: str,
        window: str = "1h",
        as_of=None,
        tenant_id: str | None = None,
    ) -> dict:
        time.sleep(self.delay_seconds)
        return {
            "value": 42.0,
            "unit": "USD",
            "components": {
                "metric_name": metric_name,
                "window": window,
                "tenant_id": tenant_id,
                "as_of": as_of.isoformat() if as_of is not None else None,
            },
        }

    def execute_nl_query(
        self,
        question: str,
        context: dict | None = None,
        tenant_id: str | None = None,
    ) -> dict:
        time.sleep(self.delay_seconds)
        return {
            "sql": "SELECT * FROM orders LIMIT 1",
            "data": [{"question": question, "tenant_id": tenant_id, "context": context}],
            "row_count": 1,
            "execution_time_ms": int(self.delay_seconds * 1000),
            "freshness_seconds": 0,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "url", "json_payload"),
    [
        ("GET", "/v1/entity/order/ORD-20260401-0001", None),
        ("GET", "/v1/metrics/revenue?window=1h", None),
        ("POST", "/v1/query", {"question": "top orders"}),
    ],
    ids=["entity", "metric", "query"],
)
async def test_hot_path_endpoints_do_not_block_event_loop(
    method: str,
    url: str,
    json_payload: dict | None,
):
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.state.query_engine = SlowEngine(delay_seconds=0.3)
    app.include_router(agent_router, prefix="/v1")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        started_at = time.perf_counter()
        responses = await asyncio.gather(
            *[client.request(method, url, json=json_payload) for _ in range(4)]
        )
        elapsed = time.perf_counter() - started_at

    assert all(response.status_code == 200 for response in responses)
    assert elapsed < 0.9, f"Event loop blocked: {elapsed:.2f}s (expected < 0.9s)"


@pytest.mark.asyncio
async def test_get_metric_rejects_window_not_in_available_windows():
    # Pre-fix any window was accepted and silently computed as 1h (active_sessions
    # always 30m) while the response echoed the requested window — a wrong value
    # under a confident label, plus cache-key pollution. (audit_30_06_26.md A1)
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.state.query_engine = SlowEngine(delay_seconds=0.0)
    app.include_router(agent_router, prefix="/v1")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad = await client.get("/v1/metrics/revenue?window=2h")
        good = await client.get("/v1/metrics/revenue?window=1h")
        bad_active = await client.get("/v1/metrics/active_sessions?window=24h")
        good_active = await client.get("/v1/metrics/active_sessions?window=now")

    assert bad.status_code == 422  # 2h is not a declared window for revenue
    assert good.status_code == 200
    assert bad_active.status_code == 422  # active_sessions only supports "now"
    assert good_active.status_code == 200  # "now" is active_sessions' declared window
