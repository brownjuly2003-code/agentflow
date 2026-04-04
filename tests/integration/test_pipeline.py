"""Integration tests for the full pipeline.

These tests require Docker services (Kafka, etc.) to be running.
Run with: pytest tests/integration/ -m integration
"""

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine


@pytest.fixture
def client():
    """FastAPI test client with in-memory DuckDB."""
    with TestClient(app) as c:
        yield c


class TestAgentAPI:
    """Test the Agent Query API endpoints."""

    def test_health_endpoint(self, client):
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "components" in data

    def test_catalog_endpoint(self, client):
        response = client.get("/v1/catalog")
        assert response.status_code == 200
        data = response.json()
        assert "entities" in data
        assert "metrics" in data
        assert "order" in data["entities"]
        assert "revenue" in data["metrics"]

    def test_unknown_entity_type(self, client):
        response = client.get("/v1/entity/spaceship/USS-Enterprise")
        assert response.status_code == 404

    def test_unknown_metric(self, client):
        response = client.get("/v1/metrics/nonexistent")
        assert response.status_code == 404

    def test_metric_revenue(self, client):
        response = client.get("/v1/metrics/revenue?window=1h")
        assert response.status_code == 200
        data = response.json()
        assert data["metric_name"] == "revenue"
        assert data["unit"] == "USD"

    def test_nl_query(self, client):
        response = client.post("/v1/query", json={
            "question": "What is the average order value in the last hour?",
        })
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "sql" in data

    def test_nl_query_unrecognized(self, client):
        response = client.post("/v1/query", json={
            "question": "What is the meaning of life?",
        })
        assert response.status_code == 400


class TestQueryEngine:
    """Test the query engine directly."""

    def test_nl_to_sql_revenue(self):
        catalog = DataCatalog()
        engine = QueryEngine(catalog=catalog)
        sql = engine._nl_to_sql("what is the revenue today")
        assert sql is not None
        assert "SUM(total_amount)" in sql
        assert "24 hours" in sql

    def test_nl_to_sql_top_products(self):
        catalog = DataCatalog()
        engine = QueryEngine(catalog=catalog)
        sql = engine._nl_to_sql("show me top 3 products")
        assert sql is not None
        assert "LIMIT 3" in sql

    def test_get_metric(self):
        catalog = DataCatalog()
        engine = QueryEngine(catalog=catalog)
        result = engine.get_metric("revenue", window="1h")
        assert "value" in result
        assert result["unit"] == "USD"
