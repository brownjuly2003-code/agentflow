from __future__ import annotations

import json
import time
from queue import Empty

import pytest

pytestmark = pytest.mark.integration


def test_health_endpoint_returns_live_status(api_client):
    response = api_client.get("/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"healthy", "degraded", "unhealthy", "ok"}
    assert payload["components"]


def test_entity_lookup_returns_order_payload(api_client, support_headers):
    response = api_client.get(
        "/v1/entity/order/ORD-20260404-1001",
        headers=support_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["entity_type"] == "order"
    assert payload["data"]["order_id"] == "ORD-20260404-1001"
    assert payload["data"]["user_id"] == "USR-10001"


def test_metric_endpoint_returns_numeric_value(api_client, ops_headers):
    response = api_client.get("/v1/metrics/revenue", params={"window": "24h"}, headers=ops_headers)

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["value"], (int, float))
    assert payload["metric_name"] == "revenue"


def test_nl_query_returns_sql_and_rows(api_client, ops_headers):
    response = api_client.post(
        "/v1/query",
        headers=ops_headers,
        json={"question": "Show me top 3 products"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sql"]
    assert payload["metadata"]["rows_returned"] == 3
    assert len(payload["rows"]) == 3


def test_auth_rejects_request_without_api_key(api_client):
    response = api_client.get("/v1/entity/order/ORD-20260404-1001")

    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]


def test_rate_limit_returns_429_after_threshold(api_client, rate_limit_api_key: str):
    headers = {"X-API-Key": rate_limit_api_key}
    statuses = [
        api_client.get("/v1/metrics/revenue", params={"window": "1h"}, headers=headers).status_code
        for _ in range(125)
    ]

    assert statuses[:120] == [200] * 120
    assert statuses[120:] == [429] * 5


def test_batch_request_returns_three_results(api_client, ops_headers):
    response = api_client.post(
        "/v1/batch",
        headers=ops_headers,
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
    assert len(payload["results"]) == 3
    assert [item["status"] for item in payload["results"]] == ["ok", "ok", "ok"]


def test_sse_stream_yields_first_event_quickly(api_client, ops_headers):
    started_at = time.perf_counter()

    with api_client.stream("GET", "/v1/stream/events", headers=ops_headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        payload = None
        for line in response.iter_lines():
            if not line or line.startswith(":") or not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            break

    elapsed = time.perf_counter() - started_at
    assert payload is not None
    assert payload["event_id"].startswith("evt-")
    assert elapsed < 5


def test_webhook_test_endpoint_delivers_callback(api_client, ops_headers, webhook_receiver):
    created = api_client.post(
        "/v1/webhooks",
        headers=ops_headers,
        json={"url": webhook_receiver["url"], "filters": {}},
    )
    assert created.status_code == 201

    webhook_id = created.json()["id"]
    delivered = api_client.post(f"/v1/webhooks/{webhook_id}/test", headers=ops_headers)

    assert delivered.status_code == 200
    try:
        callback = webhook_receiver["events"].get(timeout=5)
    except Empty:
        pytest.fail("Webhook callback was not received within 5 seconds.")

    payload = json.loads(callback["body"].decode())
    assert payload["test"] is True
    assert callback["headers"]["X-AgentFlow-Event"] == "webhook.test"


def test_query_pagination_returns_next_cursor_and_second_page(api_client, ops_headers):
    first_page = api_client.post(
        "/v1/query",
        headers=ops_headers,
        json={"question": "Show me top 10 products", "limit": 5},
    )

    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert first_payload["next_cursor"] is not None
    assert first_payload["has_more"] is True
    assert len(first_payload["rows"]) == 5

    second_page = api_client.post(
        "/v1/query",
        headers=ops_headers,
        json={
            "question": "Show me top 10 products",
            "limit": 5,
            "cursor": first_payload["next_cursor"],
        },
    )

    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert len(second_payload["rows"]) == 5
    assert second_payload["has_more"] is False
