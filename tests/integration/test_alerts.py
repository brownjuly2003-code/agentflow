"""Integration tests for metric alert subscriptions."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.serving.api import alert_dispatcher
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
                request=httpx.Request("POST", "http://agent.test/alerts"),
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

    monkeypatch.setattr(alert_dispatcher.httpx, "AsyncClient", _AsyncClient)
    return mock


@pytest.fixture
def client(tmp_path: Path):
    previous_path = getattr(app.state, "alert_config_path", None)
    previous_autostart = getattr(app.state, "alert_dispatcher_autostart", True)
    app.state.alert_config_path = tmp_path / "alerts.yaml"
    app.state.alert_dispatcher_autostart = False

    with TestClient(app) as c:
        dispatcher = getattr(c.app.state, "alert_dispatcher", None)
        if dispatcher is not None:
            dispatcher.backoff_seconds = [0, 0]
        yield c

    app.state.alert_config_path = previous_path
    app.state.alert_dispatcher_autostart = previous_autostart


def _disable_auth(client: TestClient) -> None:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {}
    manager._rate_windows.clear()
    # Auth fail-closed default in middleware needs an explicit opt-out for tests.
    client.app.state.auth_disabled = True


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


def _create_alert(
    client: TestClient,
    *,
    headers: dict[str, str] | None = None,
    name: str = "High Error Rate",
    metric: str = "error_rate",
    window: str = "1h",
    condition: str = "above",
    threshold: float = 0.01,
    webhook_url: str = "http://agent.test/alerts",
    cooldown_minutes: int = 30,
) -> dict:
    response = client.post(
        "/v1/alerts",
        headers=headers or {},
        json={
            "name": name,
            "metric": metric,
            "window": window,
            "condition": condition,
            "threshold": threshold,
            "webhook_url": webhook_url,
            "cooldown_minutes": cooldown_minutes,
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.integration
class TestAlertsAPI:
    def test_create_alert_persists_rule_and_returns_secret(self, client):
        _disable_auth(client)

        created = _create_alert(client)

        assert created["id"]
        assert created["secret"]
        assert created["active"] is True
        assert created["tenant"] == "default"
        assert created["last_triggered_at"] is None
        assert "High Error Rate" in client.app.state.alert_config_path.read_text(encoding="utf-8")

    def test_list_alerts_filters_by_tenant(self, client):
        _set_auth(client, {"acme-key": "acme", "beta-key": "beta"})

        acme = _create_alert(client, headers={"X-API-Key": "acme-key"})
        _create_alert(
            client,
            headers={"X-API-Key": "beta-key"},
            name="Revenue Drop",
            metric="revenue",
            condition="below",
            threshold=100.0,
        )

        response = client.get("/v1/alerts", headers={"X-API-Key": "acme-key"})

        assert response.status_code == 200
        assert [item["id"] for item in response.json()["alerts"]] == [acme["id"]]

    def test_update_alert_changes_threshold_and_active_state(self, client):
        _disable_auth(client)
        created = _create_alert(client)

        response = client.put(
            f"/v1/alerts/{created['id']}",
            json={"threshold": 0.02, "active": False},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["threshold"] == 0.02
        assert body["active"] is False

    def test_delete_alert_hides_it_from_active_list(self, client):
        _disable_auth(client)
        created = _create_alert(client)

        deleted = client.delete(f"/v1/alerts/{created['id']}")
        listed = client.get("/v1/alerts")

        assert deleted.status_code == 204
        assert listed.status_code == 200
        assert listed.json()["alerts"] == []

    def test_test_endpoint_delivers_signed_payload_and_records_history(
        self,
        client,
        httpx_mock,
    ):
        _disable_auth(client)
        created = _create_alert(client)

        response = client.post(f"/v1/alerts/{created['id']}/test")

        assert response.status_code == 200
        assert len(httpx_mock.requests) == 1
        request = httpx_mock.requests[0]
        payload = json.loads(request["content"].decode())
        expected = (
            "sha256="
            + hmac.new(
                created["secret"].encode(),
                request["content"],
                hashlib.sha256,
            ).hexdigest()
        )
        assert payload["test"] is True
        assert request["headers"]["X-AgentFlow-Event"] == "alert.test"
        assert request["headers"]["X-AgentFlow-Signature"] == expected

        history = client.get(f"/v1/alerts/{created['id']}/history")
        assert history.status_code == 200
        assert history.json()["history"][0]["alert_id"] == created["id"]
        assert history.json()["history"][0]["success"] is True

    @pytest.mark.asyncio
    async def test_dispatcher_triggers_alert_once_per_cooldown(
        self,
        client,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        created = _create_alert(
            client,
            metric="revenue",
            condition="above",
            threshold=100.0,
        )

        monkeypatch.setattr(
            client.app.state.query_engine,
            "get_metric",
            lambda metric_name, window="1h", as_of=None, tenant_id=None: {
                "value": 150.0,
                "unit": "USD",
            },
        )

        await client.app.state.alert_dispatcher.dispatch_alerts()
        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert len(httpx_mock.requests) == 1
        history = client.get(f"/v1/alerts/{created['id']}/history")
        assert history.status_code == 200
        assert len(history.json()["history"]) == 1

    @pytest.mark.asyncio
    async def test_dispatcher_supports_change_pct_condition(
        self,
        client,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        _create_alert(
            client,
            name="Revenue Drop",
            metric="revenue",
            condition="change_pct",
            threshold=-10.0,
        )
        calls = {"count": 0}

        def _fake_get_metric(metric_name, window="1h", as_of=None, tenant_id=None):
            calls["count"] += 1
            return {
                "value": 80.0 if calls["count"] == 1 else 100.0,
                "unit": "USD",
            }

        monkeypatch.setattr(client.app.state.query_engine, "get_metric", _fake_get_metric)

        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert len(httpx_mock.requests) == 1
