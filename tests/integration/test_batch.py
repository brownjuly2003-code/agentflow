import time
from datetime import UTC, datetime

import httpx
import pytest
from agentflow import AgentFlowClient, AsyncAgentFlowClient
from fastapi.testclient import TestClient

from src.serving.api.auth import TenantKey
from src.serving.api.main import app
from src.serving.semantic_layer.query_engine import QueryEngine

pytestmark = pytest.mark.integration


class _SyncClientAdapter:
    def __init__(self, client: TestClient, api_key: str):
        self._client = client
        self.headers = {"X-API-Key": api_key}

    def request(self, method: str, path: str, **kwargs):
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}) or {})
        return self._client.request(method, path, headers=headers, **kwargs)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _disable_auth(client: TestClient) -> None:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {}
    manager._rate_windows.clear()


def _set_auth(client: TestClient, key: str = "batch-test-key") -> str:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {
        key: TenantKey(
            key=key,
            name="batch-agent",
            tenant="acme",
            rate_limit_rpm=100,
            allowed_entity_types=None,
            created_at=datetime.now(UTC).date(),
        )
    }
    manager._rate_windows.clear()
    return key


def test_batch_returns_results_for_mixed_request_types(client):
    _disable_auth(client)

    response = client.post(
        "/v1/batch",
        json={
            "requests": [
                {
                    "id": "entity-1",
                    "type": "entity",
                    "params": {
                        "entity_type": "order",
                        "entity_id": "ORD-20260404-1001",
                    },
                },
                {
                    "id": "metric-1",
                    "type": "metric",
                    "params": {"name": "revenue", "window": "24h"},
                },
                {
                    "id": "query-1",
                    "type": "query",
                    "params": {"question": "top 2 products today"},
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["duration_ms"] >= 0
    assert [item["id"] for item in payload["results"]] == [
        "entity-1",
        "metric-1",
        "query-1",
    ]

    entity_result, metric_result, query_result = payload["results"]
    assert entity_result["status"] == "ok"
    assert entity_result["data"]["order_id"] == "ORD-20260404-1001"
    assert "_last_updated" not in entity_result["data"]

    assert metric_result["status"] == "ok"
    assert metric_result["data"]["unit"] == "USD"
    assert metric_result["data"]["value"] >= 0

    assert query_result["status"] == "ok"
    assert len(query_result["data"]["answer"]) == 2
    assert query_result["data"]["metadata"]["rows_returned"] == 2


def test_batch_returns_partial_failures_without_failing_whole_response(client):
    _disable_auth(client)

    response = client.post(
        "/v1/batch",
        json={
            "requests": [
                {
                    "id": "ok-entity",
                    "type": "entity",
                    "params": {
                        "entity_type": "order",
                        "entity_id": "ORD-20260404-1001",
                    },
                },
                {
                    "id": "bad-metric",
                    "type": "metric",
                    "params": {"name": "does_not_exist", "window": "1h"},
                },
                {
                    "id": "ok-query",
                    "type": "query",
                    "params": {"question": "revenue today"},
                },
            ]
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["status"] for item in results] == ["ok", "error", "ok"]
    assert "Unknown metric" in results[1]["error"]
    assert results[0]["data"]["order_id"] == "ORD-20260404-1001"
    assert "answer" in results[2]["data"]


def test_batch_rejects_more_than_twenty_requests(client):
    _disable_auth(client)

    response = client.post(
        "/v1/batch",
        json={
            "requests": [
                {
                    "id": f"metric-{index}",
                    "type": "metric",
                    "params": {"name": "revenue", "window": "1h"},
                }
                for index in range(21)
            ]
        },
    )

    assert response.status_code == 422


def test_batch_requires_api_key_when_auth_is_configured(client):
    _set_auth(client)

    response = client.post(
        "/v1/batch",
        json={
            "requests": [
                {
                    "id": "metric-1",
                    "type": "metric",
                    "params": {"name": "revenue", "window": "1h"},
                }
            ]
        },
    )

    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]


def test_batch_executes_items_concurrently_and_reports_wall_time(client, monkeypatch):
    _disable_auth(client)
    original_get_metric = QueryEngine.get_metric

    def delayed_get_metric(self, metric_name: str, window: str = "1h", as_of=None):
        time.sleep(0.2)
        return original_get_metric(self, metric_name, window=window, as_of=as_of)

    monkeypatch.setattr(QueryEngine, "get_metric", delayed_get_metric)

    started_at = time.perf_counter()
    response = client.post(
        "/v1/batch",
        json={
            "requests": [
                {
                    "id": "m1",
                    "type": "metric",
                    "params": {"name": "revenue", "window": "1h"},
                },
                {
                    "id": "m2",
                    "type": "metric",
                    "params": {"name": "order_count", "window": "1h"},
                },
                {
                    "id": "m3",
                    "type": "metric",
                    "params": {"name": "avg_order_value", "window": "1h"},
                },
                {
                    "id": "m4",
                    "type": "metric",
                    "params": {"name": "active_sessions", "window": "1h"},
                },
            ]
        },
    )
    elapsed_ms = (time.perf_counter() - started_at) * 1000

    assert response.status_code == 200
    assert all(item["status"] == "ok" for item in response.json()["results"])
    assert elapsed_ms < 650
    assert response.json()["duration_ms"] < 650


def test_sdk_client_batch_uses_batch_builders(client):
    api_key = _set_auth(client)
    sdk_client = AgentFlowClient("http://testserver", api_key=api_key)
    sdk_client._client = _SyncClientAdapter(client, api_key)

    payload = sdk_client.batch(
        [
            sdk_client.batch_entity(
                "order",
                "ORD-20260404-1001",
                request_id="entity-1",
            ),
            sdk_client.batch_metric(
                "revenue",
                "24h",
                request_id="metric-1",
            ),
            sdk_client.batch_query(
                "top 2 products today",
                request_id="query-1",
            ),
        ]
    )

    assert [item["id"] for item in payload["results"]] == [
        "entity-1",
        "metric-1",
        "query-1",
    ]
    assert all(item["status"] == "ok" for item in payload["results"])


@pytest.mark.asyncio
async def test_async_sdk_client_batch_uses_batch_builders(client):
    api_key = _set_auth(client)
    transport = httpx.ASGITransport(app=client.app)
    sdk_client = AsyncAgentFlowClient("http://testserver", api_key=api_key)
    sdk_client._http = httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-API-Key": api_key},
    )

    try:
        payload = await sdk_client.batch(
            [
                sdk_client.batch_entity(
                    "order",
                    "ORD-20260404-1001",
                    request_id="entity-1",
                ),
                sdk_client.batch_metric(
                    "revenue",
                    "24h",
                    request_id="metric-1",
                ),
                sdk_client.batch_query(
                    "top 2 products today",
                    request_id="query-1",
                ),
            ]
        )
    finally:
        await sdk_client._http.aclose()

    assert [item["id"] for item in payload["results"]] == [
        "entity-1",
        "metric-1",
        "query-1",
    ]
    assert all(item["status"] == "ok" for item in payload["results"])
