"""Integration tests for webhook subscriptions."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.serving.api import webhook_dispatcher
from src.serving.api.auth import TenantKey
from src.serving.api.main import app


class _HTTPXMock:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[httpx.Response] = []

    def add_response(self, status_code: int = 200, json_data: dict | None = None) -> None:
        self.responses.append(
            httpx.Response(
                status_code,
                json=json_data or {"ok": True},
                request=httpx.Request("POST", "http://agent.test/webhook"),
            )
        )

    async def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> httpx.Response:
        self.requests.append({"url": url, "content": content, "headers": headers})
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(
            200,
            json={"ok": True},
            request=httpx.Request("POST", url),
        )


@pytest.fixture
def httpx_mock(monkeypatch) -> _HTTPXMock:
    mock = _HTTPXMock()

    class _AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> _HTTPXMock:
            return mock

        async def __aexit__(self, *args) -> None:
            pass

    monkeypatch.setattr(webhook_dispatcher.httpx, "AsyncClient", _AsyncClient)
    return mock


@pytest.fixture
def client(tmp_path: Path):
    previous_path = getattr(app.state, "webhook_config_path", None)
    previous_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
    app.state.webhook_config_path = tmp_path / "webhooks.yaml"
    app.state.webhook_dispatcher_autostart = False

    with TestClient(app) as c:
        c.app.state.webhook_dispatcher.backoff_seconds = [0, 0]
        yield c

    app.state.webhook_config_path = previous_path
    app.state.webhook_dispatcher_autostart = previous_autostart


def _disable_auth(client: TestClient) -> None:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {}
    manager._rate_windows.clear()


def _set_auth(client: TestClient, tenants: dict[str, str]) -> None:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {
        key: TenantKey(
            key=key,
            name=f"{tenant}-agent",
            tenant=tenant,
            rate_limit_rpm=100,
            allowed_entity_types=None,
            created_at=datetime.now(UTC).date(),
        )
        for key, tenant in tenants.items()
    }
    manager._rate_windows.clear()


def _register(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
    filters: dict | None = None,
    url: str = "http://agent.test/webhook",
) -> dict:
    response = client.post(
        "/v1/webhooks",
        headers=headers or {},
        json={"url": url, "filters": filters or {}},
    )
    assert response.status_code == 201
    return response.json()


def _prepare_pipeline_events(client: TestClient) -> None:
    conn = client.app.state.query_engine._conn
    columns = {row[1] for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()}
    if "event_type" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN event_type VARCHAR")
    if "entity_id" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN entity_id VARCHAR")
    if "latency_ms" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN latency_ms INTEGER")
    if "total_amount" not in columns:
        conn.execute("ALTER TABLE pipeline_events ADD COLUMN total_amount DOUBLE")

    conn.execute("DELETE FROM pipeline_events")
    conn.executemany(
        """
        INSERT INTO pipeline_events (
            event_id, topic, processed_at, event_type, entity_id, latency_ms,
            total_amount
        )
        VALUES (?, ?, NOW() - CAST(? AS INTERVAL), ?, ?, ?, ?)
        """,
        [
            (
                "evt-order-1",
                "events.validated",
                "3 seconds",
                "order.created",
                "ORD-1",
                15,
                209.97,
            ),
            (
                "evt-payment-1",
                "events.validated",
                "2 seconds",
                "payment.initiated",
                "ORD-1",
                20,
                209.97,
            ),
            (
                "evt-order-2",
                "events.validated",
                "1 seconds",
                "order.created",
                "ORD-2",
                12,
                50.00,
            ),
        ],
    )


@pytest.mark.integration
class TestWebhooksAPI:
    def test_register_webhook_returns_id_secret_and_persists(self, client):
        _disable_auth(client)

        data = _register(client, filters={"event_types": ["order"]})

        assert data["id"]
        assert data["secret"]
        assert data["active"] is True
        assert data["filters"]["event_types"] == ["order"]
        assert client.app.state.webhook_config_path.read_text(encoding="utf-8")

    def test_list_webhooks_filters_by_tenant(self, client):
        _set_auth(client, {"acme-key": "acme", "beta-key": "beta"})

        acme = _register(client, headers={"X-API-Key": "acme-key"})
        _register(client, headers={"X-API-Key": "beta-key"})

        response = client.get("/v1/webhooks", headers={"X-API-Key": "acme-key"})

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["webhooks"]] == [acme["id"]]

    def test_delete_webhook_unregisters_it(self, client):
        _disable_auth(client)
        created = _register(client)

        deleted = client.delete(f"/v1/webhooks/{created['id']}")
        listed = client.get("/v1/webhooks")

        assert deleted.status_code == 204
        assert listed.json()["webhooks"] == []

    def test_test_endpoint_delivers_payload_with_hmac_headers(self, client, httpx_mock):
        _disable_auth(client)
        created = _register(client)

        response = client.post(f"/v1/webhooks/{created['id']}/test")

        assert response.status_code == 200
        assert len(httpx_mock.requests) == 1
        request = httpx_mock.requests[0]
        payload = json.loads(request["content"].decode())
        signature = request["headers"]["X-AgentFlow-Signature"]
        expected = (
            "sha256="
            + hmac.new(
                created["secret"].encode(),
                request["content"],
                hashlib.sha256,
            ).hexdigest()
        )
        assert payload["test"] is True
        assert request["headers"]["X-AgentFlow-Event"] == "webhook.test"
        assert request["headers"]["X-AgentFlow-Delivery"]
        assert signature == expected

    def test_test_endpoint_retries_5xx_three_attempts(self, client, httpx_mock):
        _disable_auth(client)
        created = _register(client)
        httpx_mock.add_response(status_code=500)
        httpx_mock.add_response(status_code=502)
        httpx_mock.add_response(status_code=200)

        response = client.post(f"/v1/webhooks/{created['id']}/test")

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["attempts"] == 3
        assert len(httpx_mock.requests) == 3

    def test_logs_endpoint_returns_delivery_history(self, client, httpx_mock):
        _disable_auth(client)
        created = _register(client)

        client.post(f"/v1/webhooks/{created['id']}/test")
        response = client.get(f"/v1/webhooks/{created['id']}/logs")

        assert response.status_code == 200
        assert response.json()["logs"][0]["webhook_id"] == created["id"]
        assert response.json()["logs"][0]["status_code"] == 200
        assert response.json()["logs"][0]["success"] is True

    @pytest.mark.asyncio
    async def test_dispatcher_delivers_matching_pipeline_events(self, client, httpx_mock):
        _disable_auth(client)
        _register(
            client,
            filters={
                "event_types": ["order"],
                "entity_ids": ["ORD-1"],
                "min_amount": 100,
            },
        )
        _prepare_pipeline_events(client)
        client.app.state.webhook_dispatcher.seen_event_ids.clear()

        await client.app.state.webhook_dispatcher.dispatch_new_events()

        assert len(httpx_mock.requests) == 1
        payload = json.loads(httpx_mock.requests[0]["content"].decode())
        assert payload["event_id"] == "evt-order-1"

    def test_webhook_registrations_survive_api_restart(self, tmp_path: Path):
        config_path = tmp_path / "webhooks.yaml"
        previous_path = getattr(app.state, "webhook_config_path", None)
        previous_autostart = getattr(app.state, "webhook_dispatcher_autostart", True)
        app.state.webhook_config_path = config_path
        app.state.webhook_dispatcher_autostart = False

        try:
            with TestClient(app) as first_client:
                _disable_auth(first_client)
                created = _register(first_client)

            with TestClient(app) as second_client:
                _disable_auth(second_client)
                response = second_client.get("/v1/webhooks")

            assert response.status_code == 200
            assert [item["id"] for item in response.json()["webhooks"]] == [created["id"]]
        finally:
            app.state.webhook_config_path = previous_path
            app.state.webhook_dispatcher_autostart = previous_autostart
