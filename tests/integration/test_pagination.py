import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from agentflow import AsyncAgentFlowClient
from agentflow.client import AgentFlowClient


pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_query_first_page_returns_rows_and_cursor(client: TestClient):
    response = client.post(
        "/v1/query",
        json={"question": "Show me top 10 products", "limit": 4},
    )

    assert response.status_code == 200
    data = response.json()

    assert [row["name"] for row in data["rows"]] == [
        "Mechanical Keyboard",
        "Running Shoes",
        "Sunglasses",
        "Backpack",
    ]
    assert data["answer"] == data["rows"]
    assert data["page_size"] == 4
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["total_count"] == 10
    assert data["metadata"]["rows_returned"] == 4


def test_query_next_page_returns_following_rows(client: TestClient):
    first_page = client.post(
        "/v1/query",
        json={"question": "Show me top 10 products", "limit": 4},
    )

    response = client.post(
        "/v1/query",
        json={
            "question": "Show me top 10 products",
            "limit": 4,
            "cursor": first_page.json()["next_cursor"],
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert [row["name"] for row in data["rows"]] == [
        "Wireless Headphones",
        "Bluetooth Speaker",
        "Coffee Maker",
        "Desk Lamp",
    ]
    assert data["page_size"] == 4
    assert data["has_more"] is True
    assert data["next_cursor"] is not None
    assert data["metadata"]["rows_returned"] == 4


def test_query_last_page_clears_cursor(client: TestClient):
    first_page = client.post(
        "/v1/query",
        json={"question": "Show me top 10 products", "limit": 4},
    ).json()
    second_page = client.post(
        "/v1/query",
        json={
            "question": "Show me top 10 products",
            "limit": 4,
            "cursor": first_page["next_cursor"],
        },
    ).json()

    response = client.post(
        "/v1/query",
        json={
            "question": "Show me top 10 products",
            "limit": 4,
            "cursor": second_page["next_cursor"],
        },
    )

    assert response.status_code == 200
    data = response.json()

    assert [row["name"] for row in data["rows"]] == [
        "Yoga Mat",
        "Water Bottle",
    ]
    assert data["page_size"] == 4
    assert data["has_more"] is False
    assert data["next_cursor"] is None
    assert data["metadata"]["rows_returned"] == 2


def test_query_rejects_invalid_cursor(client: TestClient):
    response = client.post(
        "/v1/query",
        json={
            "question": "Show me top 10 products",
            "limit": 4,
            "cursor": "not-a-valid-cursor",
        },
    )

    assert response.status_code == 400
    assert "cursor" in response.json()["detail"].lower()


def test_client_paginate_iterates_over_pages(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []
    payloads = [
        {
            "rows": [{"order_id": "ORD-1"}, {"order_id": "ORD-2"}],
            "sql": "SELECT * FROM orders_v2",
            "total_count": 3,
            "next_cursor": "cursor-1",
            "has_more": True,
            "page_size": 2,
        },
        {
            "rows": [{"order_id": "ORD-3"}],
            "sql": "SELECT * FROM orders_v2",
            "total_count": 3,
            "next_cursor": None,
            "has_more": False,
            "page_size": 2,
        },
    ]

    def handler(self, method, url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(status_code=200, json=payloads[len(calls) - 1])

    monkeypatch.setattr(httpx.Client, "request", handler)

    client = AgentFlowClient("http://example.com", api_key="test-key")
    pages = list(client.paginate("all orders", page_size=2))

    assert pages == [
        [{"order_id": "ORD-1"}, {"order_id": "ORD-2"}],
        [{"order_id": "ORD-3"}],
    ]
    assert calls == [
        {"question": "all orders", "limit": 2},
        {"question": "all orders", "limit": 2, "cursor": "cursor-1"},
    ]


@pytest.mark.asyncio
async def test_async_client_paginate_iterates_over_pages(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []
    payloads = [
        {
            "rows": [{"order_id": "ORD-1"}, {"order_id": "ORD-2"}],
            "sql": "SELECT * FROM orders_v2",
            "total_count": 3,
            "next_cursor": "cursor-1",
            "has_more": True,
            "page_size": 2,
        },
        {
            "rows": [{"order_id": "ORD-3"}],
            "sql": "SELECT * FROM orders_v2",
            "total_count": 3,
            "next_cursor": None,
            "has_more": False,
            "page_size": 2,
        },
    ]

    async def handler(self, method, url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(status_code=200, json=payloads[len(calls) - 1])

    monkeypatch.setattr(httpx.AsyncClient, "request", handler)

    client = AsyncAgentFlowClient("http://example.com", api_key="test-key")
    pages = []
    async for page in client.paginate("all orders", page_size=2):
        pages.append(page)

    assert pages == [
        [{"order_id": "ORD-1"}, {"order_id": "ORD-2"}],
        [{"order_id": "ORD-3"}],
    ]
    assert calls == [
        {"question": "all orders", "limit": 2},
        {"question": "all orders", "limit": 2, "cursor": "cursor-1"},
    ]

    await client._http.aclose()
