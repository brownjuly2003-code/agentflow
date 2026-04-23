"""Integration tests for the Agent Query API.

Tests the full API stack: FastAPI + QueryEngine + DuckDB with seeded demo data.
Run with: pytest tests/integration/ -v
"""

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.nl_engine import translate_nl_to_sql
from src.serving.semantic_layer.query_engine import QueryEngine


@pytest.fixture
def client():
    """FastAPI test client with in-memory DuckDB and demo data."""
    with TestClient(app) as c:
        yield c


@pytest.mark.integration
class TestAgentAPI:
    """Test the Agent Query API endpoints."""

    def test_health_endpoint(self, client):
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "components" in data
        for component in data["components"]:
            assert "source" in component
            assert component["source"] in ("live", "placeholder")

    def test_catalog_endpoint(self, client):
        response = client.get("/v1/catalog")
        assert response.status_code == 200
        data = response.json()
        assert "entities" in data
        assert "metrics" in data
        assert "order" in data["entities"]
        assert "revenue" in data["metrics"]
        # Catalog fields must match actual table columns
        order_fields = data["entities"]["order"]["fields"]
        assert "total_amount" in order_fields
        assert "items" not in order_fields  # removed: not in runtime table

    def test_unknown_entity_type(self, client):
        response = client.get("/v1/entity/spaceship/USS-Enterprise")
        assert response.status_code == 404

    def test_unknown_metric(self, client):
        response = client.get("/v1/metrics/nonexistent")
        assert response.status_code == 404

    def test_metric_revenue_returns_real_data(self, client):
        response = client.get("/v1/metrics/revenue?window=24h")
        assert response.status_code == 200
        data = response.json()
        assert data["metric_name"] == "revenue"
        assert data["unit"] == "USD"
        assert data["value"] > 0  # demo data seeded

    def test_metric_error_rate(self, client):
        response = client.get("/v1/metrics/error_rate?window=1h")
        assert response.status_code == 200
        data = response.json()
        assert data["value"] >= 0
        assert data["unit"] == "ratio"

    def test_entity_order_lookup(self, client):
        response = client.get("/v1/entity/order/ORD-20260404-1001")
        assert response.status_code == 200
        data = response.json()
        assert data["entity_type"] == "order"
        assert data["data"]["user_id"] == "USR-10001"

    def test_entity_user_lookup(self, client):
        response = client.get("/v1/entity/user/USR-10001")
        assert response.status_code == 200
        data = response.json()
        assert data["entity_type"] == "user"
        assert data["data"]["total_orders"] == 15

    def test_entity_not_found(self, client):
        response = client.get("/v1/entity/order/ORD-99999999-0000")
        assert response.status_code == 404

    def test_nl_query_returns_results(self, client):
        response = client.post(
            "/v1/query",
            json={
                "question": "What is the average order value in the last 24 hours?",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "sql" in data
        assert data["metadata"]["rows_returned"] >= 1

    def test_nl_query_unrecognized(self, client):
        response = client.post(
            "/v1/query",
            json={
                "question": "What is the meaning of life?",
            },
        )
        assert response.status_code == 400

    def test_nl_query_top_products(self, client):
        response = client.post(
            "/v1/query",
            json={
                "question": "Show me top 3 products",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["answer"]) == 3


@pytest.mark.integration
class TestAuthAndRateLimit:
    """Test authentication and rate limiting middleware."""

    def test_health_exempt_from_auth(self, client):
        """Health endpoint works without API key even when auth is enabled."""
        response = client.get("/v1/health")
        assert response.status_code == 200

    def test_docs_exempt_from_auth(self, client):
        response = client.get("/docs")
        assert response.status_code == 200


@pytest.mark.integration
class TestQueryEngine:
    """Test the query engine directly."""

    def test_nl_to_sql_revenue(self):
        catalog = DataCatalog()
        sql = translate_nl_to_sql("what is the revenue today", catalog)
        assert sql is not None
        assert "SUM(total_amount)" in sql
        assert "24 hours" in sql

    def test_nl_to_sql_top_products(self):
        catalog = DataCatalog()
        sql = translate_nl_to_sql("show me top 3 products", catalog)
        assert sql is not None
        assert "LIMIT 3" in sql

    def test_get_metric_with_data(self):
        catalog = DataCatalog()
        engine = QueryEngine(catalog=catalog)
        result = engine.get_metric("revenue", window="24h")
        assert "value" in result
        assert result["unit"] == "USD"
        assert result["value"] > 0  # demo data

    def test_get_metric_error_rate(self):
        catalog = DataCatalog()
        engine = QueryEngine(catalog=catalog)
        result = engine.get_metric("error_rate", window="1h")
        assert result["value"] > 0  # 2 deadletter out of 10

    def test_get_entity_existing(self):
        catalog = DataCatalog()
        engine = QueryEngine(catalog=catalog)
        result = engine.get_entity("product", "PROD-001")
        assert result is not None
        assert result["name"] == "Wireless Headphones"

    def test_get_entity_missing(self):
        catalog = DataCatalog()
        engine = QueryEngine(catalog=catalog)
        result = engine.get_entity("product", "PROD-999")
        assert result is None
