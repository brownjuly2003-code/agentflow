from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.serving.api.auth import TenantKey
from src.serving.api.main import app

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _disable_auth(client: TestClient) -> None:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {}
    manager._rate_windows.clear()


def _set_auth(client: TestClient, key: str = "search-test-key") -> None:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {
        key: TenantKey(
            key=key,
            name="search-agent",
            tenant="acme",
            rate_limit_rpm=100,
            allowed_entity_types=None,
            created_at=datetime.now(UTC).date(),
        )
    }
    manager._rate_windows.clear()


def _prepare_search_data(client: TestClient) -> None:
    conn = client.app.state.query_engine._conn
    now = datetime.now(UTC).replace(microsecond=0)

    conn.execute("DELETE FROM orders_v2")
    conn.execute("DELETE FROM users_enriched")
    conn.execute("DELETE FROM products_current")
    conn.execute("DELETE FROM sessions_aggregated")
    conn.execute("DELETE FROM pipeline_events")

    conn.executemany(
        """
        INSERT INTO orders_v2 (
            order_id, user_id, status, total_amount, currency, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("ORD-SRCH-1", "USR-SRCH-1", "delivered", 450.0, "USD", now - timedelta(minutes=55)),
            ("ORD-SRCH-2", "USR-SRCH-2", "pending", 35.0, "USD", now - timedelta(minutes=20)),
            ("ORD-SRCH-3", "USR-SRCH-1", "confirmed", 220.0, "USD", now - timedelta(minutes=5)),
        ],
    )
    conn.executemany(
        """
        INSERT INTO users_enriched (
            user_id, total_orders, total_spent, first_order_at, last_order_at, preferred_category
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "USR-SRCH-1",
                12,
                1840.0,
                now - timedelta(days=120),
                now - timedelta(minutes=5),
                "electronics",
            ),
            (
                "USR-SRCH-2",
                2,
                85.0,
                now - timedelta(days=15),
                now - timedelta(minutes=20),
                "home",
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO products_current (
            product_id, name, category, price, in_stock, stock_quantity
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("PROD-SRCH-1", "Wireless Headphones", "electronics", 79.99, True, 18),
            ("PROD-SRCH-2", "Desk Lamp", "home", 44.99, False, 0),
        ],
    )
    conn.executemany(
        """
        INSERT INTO sessions_aggregated (
            session_id, user_id, started_at, ended_at, duration_seconds, event_count,
            unique_pages, funnel_stage, is_conversion
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "SES-SRCH-1",
                "USR-SRCH-1",
                now - timedelta(minutes=30),
                now - timedelta(minutes=10),
                1200.0,
                9,
                4,
                "checkout",
                True,
            ),
            (
                "SES-SRCH-2",
                "USR-SRCH-2",
                now - timedelta(minutes=12),
                None,
                None,
                3,
                2,
                "browse",
                False,
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO pipeline_events (event_id, topic, processed_at)
        VALUES (?, ?, ?)
        """,
        [
            ("evt-search-1", "events.validated", now - timedelta(minutes=3)),
            ("evt-search-2", "events.validated", now - timedelta(minutes=2)),
            ("evt-search-3", "events.deadletter", now - timedelta(minutes=1)),
        ],
    )

    search_index = getattr(client.app.state, "search_index", None)
    if search_index is not None:
        search_index.rebuild()


class TestSemanticSearch:
    def test_search_large_orders_returns_ranked_order_entities(self, client):
        _disable_auth(client)
        _prepare_search_data(client)

        response = client.get("/v1/search?q=large+orders")

        assert response.status_code == 200
        results = response.json()["results"]
        assert results
        assert results[0]["type"] == "entity"
        assert results[0]["entity_type"] == "order"
        assert results[0]["id"] == "ORD-SRCH-1"
        assert results[0]["endpoint"] == "/v1/entity/order/ORD-SRCH-1"
        assert results[0]["score"] >= results[-1]["score"]

    def test_search_revenue_returns_metric_result(self, client):
        _disable_auth(client)
        _prepare_search_data(client)

        response = client.get("/v1/search?q=revenue")

        assert response.status_code == 200
        results = response.json()["results"]
        revenue = next(item for item in results if item["type"] == "metric")
        assert revenue["id"] == "revenue"
        assert revenue["endpoint"] == "/v1/metrics/revenue"
        assert "revenue" in revenue["snippet"].lower()

    def test_search_filters_results_by_entity_types(self, client):
        _disable_auth(client)
        _prepare_search_data(client)

        response = client.get("/v1/search?q=electronics&entity_types=order,user")

        assert response.status_code == 200
        results = response.json()["results"]
        assert results
        assert all(item["type"] != "metric" for item in results)
        assert all(item["entity_type"] in {"order", "user"} for item in results)
        assert any(item["entity_type"] == "user" for item in results)

    def test_search_limit_caps_number_of_results(self, client):
        _disable_auth(client)
        _prepare_search_data(client)

        response = client.get("/v1/search?q=order&limit=1")

        assert response.status_code == 200
        assert len(response.json()["results"]) == 1

    def test_search_returns_empty_results_when_nothing_matches(self, client):
        _disable_auth(client)
        _prepare_search_data(client)

        response = client.get("/v1/search?q=quantum+hedgehog")

        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_search_results_include_callable_endpoint(self, client):
        _disable_auth(client)
        _prepare_search_data(client)

        response = client.get("/v1/search?q=wireless")

        assert response.status_code == 200
        results = response.json()["results"]
        product = next(item for item in results if item["id"] == "PROD-SRCH-1")
        assert product["endpoint"] == "/v1/entity/product/PROD-SRCH-1"

    def test_search_requires_auth_when_api_keys_are_configured(self, client):
        _prepare_search_data(client)
        _set_auth(client)

        response = client.get("/v1/search?q=revenue")

        assert response.status_code == 401
        assert "API key" in response.json()["detail"]

    def test_search_accepts_valid_api_key(self, client):
        _prepare_search_data(client)
        _set_auth(client)

        response = client.get(
            "/v1/search?q=revenue",
            headers={"X-API-Key": "search-test-key"},
        )

        assert response.status_code == 200
        assert response.json()["results"]
