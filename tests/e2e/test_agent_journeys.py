from __future__ import annotations

import httpx
import pytest
from agentflow import AsyncAgentFlowClient

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


@pytest.mark.asyncio
async def test_support_agent_journey(base_url: str, support_api_key: str):
    async with AsyncAgentFlowClient(
        base_url=base_url,
        api_key=support_api_key,
        timeout=30.0,
    ) as client:
        order = await client.get_order("ORD-20260404-1001")
        assert order.order_id == "ORD-20260404-1001"

        user = await client.get_user(order.user_id)
        assert user.user_id == "USR-10001"

        metric = await client.get_metric("active_sessions", window="1h")
        assert metric.value >= 0


@pytest.mark.asyncio
async def test_ops_agent_journey(base_url: str, ops_api_key: str):
    headers = {"X-API-Key": ops_api_key}

    async with AsyncAgentFlowClient(
        base_url=base_url,
        api_key=ops_api_key,
        timeout=30.0,
    ) as client:
        health = await client.health()
        assert health.status in {"healthy", "degraded", "unhealthy", "ok"}

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0) as http:
        deadletter = await http.get("/v1/deadletter")
        slo = await http.get("/v1/slo")

    assert deadletter.status_code == 200
    assert "items" in deadletter.json()
    assert slo.status_code == 200
    assert "slos" in slo.json()


@pytest.mark.asyncio
async def test_merch_agent_journey(base_url: str, ops_api_key: str):
    async with AsyncAgentFlowClient(
        base_url=base_url,
        api_key=ops_api_key,
        timeout=30.0,
    ) as client:
        result = await client.query("Show me top 10 products", limit=5)
        assert result.sql
        assert isinstance(result.answer, list)
        assert len(result.answer) == 5

        pages = []
        async for page in client.paginate("Show me top 10 products", page_size=5):
            pages.append(page)

    assert len(pages) == 2
    assert sum(len(page) for page in pages) == 10
