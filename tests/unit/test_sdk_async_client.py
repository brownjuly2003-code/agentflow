import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from agentflow import AsyncAgentFlowClient
from agentflow.exceptions import (
    AgentFlowError,
    AuthError,
    DataFreshnessError,
    EntityNotFoundError,
    RateLimitError,
)
from agentflow.retry import RetryPolicy


def _json_response(
    status_code: int,
    payload: dict,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload, headers=headers)


def _install_request_stub(monkeypatch, handler):
    async def _request(self, method, url, **kwargs):
        result = handler(method, str(url), **kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx.AsyncClient, "request", _request)


@pytest.mark.asyncio
async def test_get_order_returns_typed_order(monkeypatch):
    created_at = datetime.now(UTC).isoformat()

    def handler(method, url, **kwargs):
        assert method == "GET"
        assert url == "/v1/entity/order/ORD-1"
        return _json_response(
            200,
            {
                "entity_type": "order",
                "entity_id": "ORD-1",
                "data": {
                    "order_id": "ORD-1",
                    "user_id": "USR-1",
                    "status": "pending",
                    "total_amount": "19.99",
                    "currency": "USD",
                    "created_at": created_at,
                },
                "last_updated": None,
                "freshness_seconds": None,
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")
    order = await client.get_order("ORD-1")

    assert order.order_id == "ORD-1"
    assert order.user_id == "USR-1"
    assert order.is_overdue is False

    await client._http.aclose()


@pytest.mark.asyncio
async def test_get_order_computes_is_overdue(monkeypatch):
    created_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()

    def handler(method, url, **kwargs):
        return _json_response(
            200,
            {
                "entity_type": "order",
                "entity_id": "ORD-2",
                "data": {
                    "order_id": "ORD-2",
                    "user_id": "USR-2",
                    "status": "confirmed",
                    "total_amount": "29.99",
                    "currency": "USD",
                    "created_at": created_at,
                },
                "last_updated": None,
                "freshness_seconds": None,
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")
    order = await client.get_order("ORD-2")

    assert order.is_overdue is True

    await client._http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "entity_type", "entity_id", "payload"),
    [
        (
            "get_user",
            "user",
            "USR-1",
            {
                "user_id": "USR-1",
                "total_orders": 3,
                "total_spent": "145.50",
                "first_order_at": datetime.now(UTC).isoformat(),
                "last_order_at": datetime.now(UTC).isoformat(),
                "preferred_category": "electronics",
            },
        ),
        (
            "get_product",
            "product",
            "PROD-1",
            {
                "product_id": "PROD-1",
                "name": "Headphones",
                "category": "electronics",
                "price": "99.99",
                "in_stock": True,
                "stock_quantity": 42,
            },
        ),
        (
            "get_session",
            "session",
            "SES-1",
            {
                "session_id": "SES-1",
                "user_id": None,
                "started_at": datetime.now(UTC).isoformat(),
                "ended_at": None,
                "duration_seconds": None,
                "event_count": 5,
                "unique_pages": 3,
                "funnel_stage": "browse",
                "is_conversion": False,
            },
        ),
    ],
)
async def test_entity_methods_return_typed_models(
    monkeypatch,
    method_name,
    entity_type,
    entity_id,
    payload,
):
    def handler(method, url, **kwargs):
        assert url == f"/v1/entity/{entity_type}/{entity_id}"
        return _json_response(
            200,
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "data": payload,
                "last_updated": None,
                "freshness_seconds": None,
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")
    entity = await getattr(client, method_name)(entity_id)

    assert getattr(entity, f"{entity_type}_id") == entity_id

    await client._http.aclose()


@pytest.mark.asyncio
async def test_get_metric_supports_custom_window(monkeypatch):
    def handler(method, url, **kwargs):
        assert url == "/v1/metrics/revenue"
        assert kwargs["params"] == {"window": "24h"}
        return _json_response(
            200,
            {
                "metric_name": "revenue",
                "value": 12.5,
                "unit": "USD",
                "window": "24h",
                "computed_at": datetime.now(UTC).isoformat(),
                "components": {"sample": 1},
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")
    metric = await client.get_metric("revenue", "24h")

    assert metric.metric_name == "revenue"
    assert metric.window == "24h"

    await client._http.aclose()


@pytest.mark.asyncio
async def test_query_returns_typed_result(monkeypatch):
    def handler(method, url, **kwargs):
        assert method == "POST"
        assert kwargs["json"] == {"question": "Top products"}
        return _json_response(
            200,
            {
                "answer": [{"product_id": "PROD-1", "revenue": 120.0}],
                "sql": "SELECT * FROM products",
                "metadata": {"rows_returned": 1, "execution_time_ms": 8},
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")
    result = await client.query("Top products")

    assert result.sql == "SELECT * FROM products"
    assert result.metadata["rows_returned"] == 1

    await client._http.aclose()


@pytest.mark.asyncio
async def test_health_returns_typed_status(monkeypatch):
    checked_at = datetime.now(UTC).isoformat()

    def handler(method, url, **kwargs):
        assert url == "/v1/health"
        return _json_response(
            200,
            {
                "status": "healthy",
                "checked_at": checked_at,
                "components": [
                    {
                        "name": "freshness",
                        "status": "healthy",
                        "message": "fresh",
                        "metrics": {"last_event_age_seconds": 12.0, "sla_seconds": 30},
                        "source": "live",
                    }
                ],
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")
    health = await client.health()

    assert health.status == "healthy"
    assert health.freshness_seconds == 12.0

    await client._http.aclose()


@pytest.mark.asyncio
async def test_catalog_returns_typed_response(monkeypatch):
    def handler(method, url, **kwargs):
        assert url == "/v1/catalog"
        return _json_response(
            200,
            {
                "entities": {
                    "order": {
                        "description": "Orders",
                        "fields": {"order_id": "ID"},
                        "primary_key": "order_id",
                    }
                },
                "metrics": {
                    "revenue": {
                        "description": "Revenue",
                        "unit": "USD",
                        "available_windows": ["1h", "24h"],
                    }
                },
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")
    catalog = await client.catalog()

    assert catalog.entities["order"].primary_key == "order_id"
    assert catalog.metrics["revenue"].available_windows == ["1h", "24h"]

    await client._http.aclose()


@pytest.mark.asyncio
async def test_is_fresh_returns_true_when_pipeline_is_healthy(monkeypatch):
    def handler(method, url, **kwargs):
        return _json_response(
            200,
            {
                "status": "healthy",
                "checked_at": datetime.now(UTC).isoformat(),
                "components": [
                    {
                        "name": "freshness",
                        "status": "healthy",
                        "message": "fresh",
                        "metrics": {"last_event_age_seconds": 15.0, "sla_seconds": 30},
                        "source": "live",
                    }
                ],
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")

    assert await client.is_fresh(60) is True

    await client._http.aclose()


@pytest.mark.asyncio
async def test_is_fresh_raises_when_pipeline_is_unhealthy(monkeypatch):
    def handler(method, url, **kwargs):
        return _json_response(
            200,
            {
                "status": "degraded",
                "checked_at": datetime.now(UTC).isoformat(),
                "components": [
                    {
                        "name": "freshness",
                        "status": "degraded",
                        "message": "stale",
                        "metrics": {"last_event_age_seconds": 75.0, "sla_seconds": 30},
                        "source": "live",
                    }
                ],
            },
        )

    _install_request_stub(monkeypatch, handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")

    with pytest.raises(DataFreshnessError):
        await client.is_fresh(60)

    await client._http.aclose()


@pytest.mark.asyncio
async def test_missing_api_key_raises_auth_error(monkeypatch):
    _install_request_stub(
        monkeypatch,
        lambda method, url, **kwargs: _json_response(
            401,
            {"detail": "Invalid or missing API key"},
        ),
    )

    client = AsyncAgentFlowClient("http://example.com", api_key="bad-key")

    with pytest.raises(AuthError):
        await client.health()

    await client._http.aclose()


@pytest.mark.asyncio
async def test_rate_limit_raises_rate_limit_error(monkeypatch):
    _install_request_stub(
        monkeypatch,
        lambda method, url, **kwargs: _json_response(
            429,
            {"detail": "Rate limit exceeded"},
            headers={"Retry-After": "60"},
        ),
    )

    client = AsyncAgentFlowClient(
        "http://example.com",
        api_key="test-key",
        retry_policy=RetryPolicy(max_attempts=1, jitter_factor=0.0),
    )

    with pytest.raises(RateLimitError) as exc_info:
        await client.health()

    assert exc_info.value.retry_after == 60

    await client._http.aclose()


@pytest.mark.asyncio
async def test_missing_entity_raises_entity_not_found(monkeypatch):
    _install_request_stub(
        monkeypatch,
        lambda method, url, **kwargs: _json_response(
            404,
            {"detail": "order/ORD-404 not found"},
        ),
    )

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")

    with pytest.raises(EntityNotFoundError) as exc_info:
        await client.get_order("ORD-404")

    assert exc_info.value.entity_type == "order"
    assert exc_info.value.entity_id == "ORD-404"

    await client._http.aclose()


@pytest.mark.asyncio
async def test_request_error_raises_agentflow_error(monkeypatch):
    _install_request_stub(
        monkeypatch,
        lambda method, url, **kwargs: httpx.ConnectError("boom"),
    )

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")

    with pytest.raises(AgentFlowError):
        await client.health()

    await client._http.aclose()


@pytest.mark.asyncio
async def test_async_context_manager_closes_underlying_client(monkeypatch):
    closed = {"value": False}

    async def _aclose(self):
        closed["value"] = True

    monkeypatch.setattr(httpx.AsyncClient, "aclose", _aclose)

    async with AsyncAgentFlowClient("http://example.com", api_key="test-key"):
        pass

    assert closed["value"] is True
