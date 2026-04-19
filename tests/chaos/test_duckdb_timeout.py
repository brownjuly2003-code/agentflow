from __future__ import annotations

from datetime import datetime


def test_metric_endpoint_returns_503_on_duckdb_timeout(
    chaos_client,
    chaos_headers,
):
    def raise_timeout(
        metric_name: str,
        window: str = "1h",
        as_of: datetime | None = None,
        tenant_id: str | None = None,
    ):
        del metric_name, window, as_of, tenant_id
        raise ValueError("Metric query failed: timeout waiting for DuckDB")

    chaos_client.app.state.query_engine.get_metric = raise_timeout

    response = chaos_client.get(
        "/v1/metrics/revenue?window=1h",
        headers=chaos_headers,
    )
    health = chaos_client.get("/v1/health")

    assert response.status_code == 503
    assert "DuckDB" in response.json()["detail"]
    assert health.status_code == 200


def test_entity_endpoint_returns_503_on_duckdb_timeout(
    chaos_client,
    chaos_headers,
):
    def raise_timeout(entity_type: str, entity_id: str, tenant_id: str | None = None):
        del entity_type, entity_id, tenant_id
        raise ValueError("Entity lookup failed: timeout waiting for DuckDB")

    chaos_client.app.state.query_engine.get_entity = raise_timeout

    response = chaos_client.get(
        "/v1/entity/order/ORD-20260404-1001",
        headers=chaos_headers,
    )

    assert response.status_code == 503
    assert "DuckDB" in response.json()["detail"]
