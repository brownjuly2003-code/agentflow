from datetime import UTC, datetime

import httpx
import pytest

pytest_plugins = ("tests.e2e.conftest",)

from agentflow import AgentFlowClient, AsyncAgentFlowClient
from agentflow.exceptions import AuthError, EntityNotFoundError

pytestmark = pytest.mark.integration


@pytest.fixture
def client(base_url: str, ops_api_key: str):
    sdk_client = AgentFlowClient(base_url=base_url, api_key=ops_api_key)
    try:
        yield sdk_client
    finally:
        sdk_client._client.close()


def _json_response(
    status_code: int,
    payload: dict,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=payload, headers=headers)


def _install_request_stub(monkeypatch, handler):
    def _request(self, method, url, **kwargs):
        result = handler(self, method, str(url), **kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx.Client, "request", _request)


def _install_async_request_stub(monkeypatch, handler):
    async def _request(self, method, url, **kwargs):
        result = handler(self, method, str(url), **kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx.AsyncClient, "request", _request)


def test_sync_client_sends_x_agentflow_version_header(monkeypatch):
    def handler(http_client, method, url, **kwargs):
        assert http_client.headers["X-AgentFlow-Version"] == "2026-01-01"
        return _json_response(
            200,
            {
                "status": "healthy",
                "checked_at": datetime.now(UTC).isoformat(),
                "components": [],
            },
            headers={
                "X-AgentFlow-Version": "2026-01-01",
                "X-AgentFlow-Latest-Version": "2026-04-11",
                "X-AgentFlow-Deprecated": "true",
                "X-AgentFlow-Deprecation-Warning": "deprecated pin",
            },
        )

    _install_request_stub(monkeypatch, handler)

    sdk_client = AgentFlowClient(
        "http://example.com",
        api_key="test-key",
        api_version="2026-01-01",
    )
    sdk_client.health()

    assert sdk_client.last_server_version == "2026-01-01"
    assert sdk_client.last_deprecation_warning == "deprecated pin"


@pytest.mark.asyncio
async def test_async_client_sends_x_agentflow_version_header(monkeypatch):
    def handler(http_client, method, url, **kwargs):
        assert http_client.headers["X-AgentFlow-Version"] == "2026-01-01"
        return _json_response(
            200,
            {
                "status": "healthy",
                "checked_at": datetime.now(UTC).isoformat(),
                "components": [],
            },
            headers={
                "X-AgentFlow-Version": "2026-01-01",
                "X-AgentFlow-Deprecation-Warning": "deprecated pin",
            },
        )

    _install_async_request_stub(monkeypatch, handler)

    sdk_client = AsyncAgentFlowClient(
        "http://example.com",
        api_key="test-key",
        api_version="2026-01-01",
    )
    await sdk_client.health()

    assert sdk_client.last_server_version == "2026-01-01"
    assert sdk_client.last_deprecation_warning == "deprecated pin"
    await sdk_client._http.aclose()


@pytest.mark.asyncio
async def test_async_client_filters_by_contract_version(monkeypatch):
    calls: list[str] = []

    def handler(http_client, method, url, **kwargs):
        calls.append(f"{method} {url}")
        if url == "/v1/entity/order/ORD-1":
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
                        "created_at": "2026-04-11T10:00:00Z",
                        "discount_amount": "2.50",
                    },
                },
            )
        if url == "/v1/contracts/order/1":
            return _json_response(
                200,
                {
                    "entity": "order",
                    "version": "1",
                    "released": "2026-04-11",
                    "status": "stable",
                    "fields": [
                        {"name": "order_id", "type": "string", "required": True},
                        {"name": "status", "type": "string", "required": True},
                        {"name": "total_amount", "type": "float", "required": True},
                        {"name": "currency", "type": "string", "required": True},
                        {"name": "user_id", "type": "string", "required": True},
                        {"name": "created_at", "type": "datetime", "required": True},
                    ],
                },
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    _install_async_request_stub(monkeypatch, handler)

    sdk_client = AsyncAgentFlowClient(
        "http://example.com",
        api_key="test-key",
        contract_version="order:v1",
    )
    order = await sdk_client.get_order("ORD-1")

    assert order.order_id == "ORD-1"
    assert calls == [
        "GET /v1/entity/order/ORD-1",
        "GET /v1/contracts/order/1",
    ]
    await sdk_client._http.aclose()


def test_get_entity_with_as_of_sends_query_param(monkeypatch):
    def handler(http_client, method, url, **kwargs):
        assert url == "/v1/entity/order/ORD-1"
        assert kwargs["params"] == {"as_of": "2026-04-25T12:00:00Z"}
        return _json_response(
            200,
            {
                "entity_type": "order",
                "entity_id": "ORD-1",
                "data": {"order_id": "ORD-1"},
                "meta": {
                    "as_of": "2026-04-25T12:00:00Z",
                    "is_historical": True,
                    "freshness_seconds": None,
                },
            },
        )

    _install_request_stub(monkeypatch, handler)

    sdk_client = AgentFlowClient("http://example.com", api_key="test-key")
    entity = sdk_client.get_entity(
        "order",
        "ORD-1",
        as_of=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
    )

    assert entity.meta is not None
    assert entity.meta.is_historical is True


def test_metric_response_exposes_meta_fields(monkeypatch):
    def handler(http_client, method, url, **kwargs):
        assert kwargs["params"] == {
            "window": "24h",
            "as_of": "2026-04-25T12:00:00Z",
        }
        return _json_response(
            200,
            {
                "metric_name": "revenue",
                "value": 12.5,
                "unit": "USD",
                "window": "24h",
                "computed_at": "2026-04-25T12:00:00Z",
                "meta": {
                    "as_of": "2026-04-25T12:00:00Z",
                    "is_historical": True,
                    "freshness_seconds": None,
                },
            },
        )

    _install_request_stub(monkeypatch, handler)

    sdk_client = AgentFlowClient("http://example.com", api_key="test-key")
    metric = sdk_client.get_metric("revenue", "24h", as_of="2026-04-25T12:00:00Z")

    assert metric.meta is not None
    assert metric.meta.as_of == "2026-04-25T12:00:00Z"
    assert metric.meta.is_historical is True


def test_catalog_exposes_streaming_and_audit_sources(client: AgentFlowClient):
    catalog = client.catalog()

    assert catalog.entities["order"].contract_version
    assert catalog.metrics["revenue"].contract_version
    assert catalog.streaming_sources["events"].transport == "sse"
    assert catalog.audit_sources["lineage"].path == "/v1/lineage/{entity_type}/{entity_id}"


def test_explain_query_returns_typed_result(client: AgentFlowClient):
    explanation = client.explain_query("Show me top 3 products")

    assert explanation.question == "Show me top 3 products"
    assert explanation.sql
    assert explanation.tables_accessed


def test_search_returns_typed_results(client: AgentFlowClient):
    results = client.search("revenue", limit=3)

    assert results.query == "revenue"
    assert len(results.results) <= 3
    assert results.results[0].endpoint


def test_get_lineage_returns_typed_result(client: AgentFlowClient):
    lineage = client.get_lineage("order", "ORD-20260404-1001")

    assert lineage.entity_type == "order"
    assert lineage.entity_id == "ORD-20260404-1001"
    assert lineage.lineage


def test_get_order_returns_typed_response(client: AgentFlowClient):
    order = client.get_order("ORD-20260404-1001")

    assert order.order_id == "ORD-20260404-1001"
    assert order.user_id == "USR-10001"
    assert order.total_amount > 0


def test_get_user_returns_typed_response(client: AgentFlowClient):
    user = client.get_user("USR-10001")

    assert user.user_id == "USR-10001"
    assert user.total_orders >= 1
    assert user.total_spent > 0


def test_query_returns_sql_and_rows(client: AgentFlowClient):
    result = client.query("Show me top 3 products", limit=3)

    assert result.sql
    assert isinstance(result.answer, list)
    assert len(result.answer) == 3
    assert result.metadata["rows_returned"] == 3


def test_paginate_returns_page_lists(client: AgentFlowClient):
    pages = list(client.paginate("Show me top 10 products", page_size=4))

    assert len(pages) == 3
    assert sum(len(page) for page in pages) == 10
    assert all(isinstance(page, list) for page in pages)
    assert all(isinstance(row, dict) for page in pages for row in page)


def test_invalid_api_key_raises_auth_error(base_url: str):
    sdk_client = AgentFlowClient(base_url=base_url, api_key="invalid")
    try:
        with pytest.raises(AuthError):
            sdk_client.get_order("ORD-20260404-1001")
    finally:
        sdk_client._client.close()


def test_missing_entity_raises_not_found(client: AgentFlowClient):
    with pytest.raises(EntityNotFoundError) as exc_info:
        client.get_order("ORD-99999999-0000")

    assert exc_info.value.entity_type == "order"
    assert exc_info.value.entity_id == "ORD-99999999-0000"
