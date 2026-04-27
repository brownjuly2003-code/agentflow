"""Integration tests for the data lineage endpoint."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.serving.api.auth import TenantKey
from src.serving.api.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _prepare_lineage_events(client: TestClient, tenant_id: str = "default") -> None:
    conn = client.app.state.query_engine._conn
    columns = {row[1] for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()}

    if "tenant_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN tenant_id VARCHAR DEFAULT 'default'")
    if "event_type" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN event_type VARCHAR")
    if "entity_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN entity_id VARCHAR")
    if "latency_ms" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN latency_ms INTEGER")

    conn.execute("DELETE FROM pipeline_events")
    conn.execute("""
        INSERT INTO pipeline_events (
            event_id, topic, processed_at, event_type, entity_id, latency_ms, tenant_id
        )
        VALUES
            (
                'evt-order-source', 'orders.raw', NOW() - INTERVAL '30 seconds',
                'order.created', 'ORD-1', 900, ?
            ),
            (
                'evt-order-validated', 'events.validated', NOW() - INTERVAL '20 seconds',
                'order.created', 'ORD-1', 120, ?
            ),
            (
                'evt-order-enriched', 'events.validated', NOW() - INTERVAL '10 seconds',
                'order.confirmed', 'ORD-1', 40, ?
            ),
            (
                'evt-other-order', 'events.validated', NOW() - INTERVAL '5 seconds',
                'order.shipped', 'ORD-2', 35, ?
            )
    """, [tenant_id, tenant_id, tenant_id, tenant_id])


def _prepare_shared_lineage_events(client: TestClient) -> None:
    conn = client.app.state.query_engine._conn
    columns = {row[1] for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()}
    if "tenant_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN tenant_id VARCHAR DEFAULT 'default'")
    if "event_type" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN event_type VARCHAR")
    if "entity_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN entity_id VARCHAR")
    if "latency_ms" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN latency_ms INTEGER")

    conn.execute("DELETE FROM pipeline_events")
    conn.execute("""
        INSERT INTO pipeline_events (
            event_id, topic, processed_at, event_type, entity_id, latency_ms, tenant_id
        )
        VALUES
            (
                'evt-acme-source', 'acme.orders.raw', NOW() - INTERVAL '30 seconds',
                'order.created', 'ORD-SHARED', 30, 'acme'
            ),
            (
                'evt-acme-validated', 'events.validated', NOW() - INTERVAL '20 seconds',
                'order.created', 'ORD-SHARED', 20, 'acme'
            ),
            (
                'evt-beta-source', 'beta.orders.raw', NOW() - INTERVAL '10 seconds',
                'order.created', 'ORD-SHARED', 10, 'beta'
            ),
            (
                'evt-beta-validated', 'events.validated', NOW() - INTERVAL '5 seconds',
                'order.created', 'ORD-SHARED', 5, 'beta'
            )
    """)


def _disable_auth(client: TestClient, monkeypatch) -> None:
    manager = client.app.state.auth_manager
    monkeypatch.setattr(manager, "keys_by_value", {})
    manager._rate_windows.clear()
    # Auth fail-closed default in middleware needs an explicit opt-out for tests.
    monkeypatch.setattr(client.app.state, "auth_disabled", True, raising=False)


@pytest.mark.integration
class TestLineageAPI:
    def test_lineage_returns_provenance_chain(self, client, monkeypatch):
        _prepare_lineage_events(client)
        _disable_auth(client, monkeypatch)

        response = client.get("/v1/lineage/order/ORD-1")

        assert response.status_code == 200
        data = response.json()
        assert data["entity_type"] == "order"
        assert data["entity_id"] == "ORD-1"
        assert len(data["lineage"]) >= 3
        assert data["lineage"][0]["layer"] == "source"
        assert data["lineage"][-1]["layer"] == "serving"
        assert data["validated"] is True
        assert data["enriched"] is True
        assert data["freshness_seconds"] >= 0

    def test_lineage_returns_404_when_entity_has_no_events(self, client, monkeypatch):
        _prepare_lineage_events(client)
        _disable_auth(client, monkeypatch)

        response = client.get("/v1/lineage/order/ORD-404")

        assert response.status_code == 404
        assert response.json()["detail"] == "No lineage found for order/ORD-404"

    def test_lineage_requires_api_key_when_auth_enabled(self, client, monkeypatch):
        _prepare_lineage_events(client, tenant_id="acme")

        manager = client.app.state.auth_manager
        monkeypatch.setattr(
            manager,
            "keys_by_value",
            {
                "lineage-test-key": TenantKey(
                    key="lineage-test-key",
                    name="lineage-tester",
                    tenant="acme",
                    rate_limit_rpm=60,
                    allowed_entity_types=None,
                    created_at=datetime.now(UTC).date(),
                )
            },
        )
        manager._rate_windows.clear()

        unauthorized = client.get("/v1/lineage/order/ORD-1")
        assert unauthorized.status_code == 401

        authorized = client.get(
            "/v1/lineage/order/ORD-1",
            headers={"X-API-Key": "lineage-test-key"},
        )
        assert authorized.status_code == 200

    def test_lineage_does_not_return_other_tenant_events_for_shared_entity_id(
        self,
        client,
        monkeypatch,
    ):
        _prepare_shared_lineage_events(client)

        manager = client.app.state.auth_manager
        monkeypatch.setattr(
            manager,
            "keys_by_value",
            {
                "acme-lineage-key": TenantKey(
                    key="acme-lineage-key",
                    name="acme-lineage",
                    tenant="acme",
                    rate_limit_rpm=60,
                    allowed_entity_types=None,
                    created_at=datetime.now(UTC).date(),
                ),
                "beta-lineage-key": TenantKey(
                    key="beta-lineage-key",
                    name="beta-lineage",
                    tenant="beta",
                    rate_limit_rpm=60,
                    allowed_entity_types=None,
                    created_at=datetime.now(UTC).date(),
                ),
            },
        )
        manager._rate_windows.clear()

        response = client.get(
            "/v1/lineage/order/ORD-SHARED",
            headers={"X-API-Key": "acme-lineage-key"},
        )

        assert response.status_code == 200
        lineage_topics = [item["table_or_topic"] for item in response.json()["lineage"]]
        assert "acme.orders.raw" in lineage_topics
        assert "beta.orders.raw" not in lineage_topics

    def test_catalog_documents_lineage_endpoint(self, client, monkeypatch):
        _disable_auth(client, monkeypatch)

        response = client.get("/v1/catalog")

        assert response.status_code == 200
        data = response.json()
        assert "audit_sources" in data
        assert data["audit_sources"]["lineage"]["path"] == "/v1/lineage/{entity_type}/{entity_id}"
