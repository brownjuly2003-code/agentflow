"""Integration tests for alert deduplication, escalation, and recovery."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from src.serving.api import alert_dispatcher
from src.serving.api.main import app


class _FrozenDateTime:
    current = datetime(2026, 4, 12, 10, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


class _Clock:
    def set(self, value: datetime) -> None:
        _FrozenDateTime.current = value


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


class _LoggerSpy:
    def __init__(self) -> None:
        self.warning_calls: list[tuple[str, dict]] = []

    def warning(self, event: str, **kwargs) -> None:
        self.warning_calls.append((event, kwargs))


@pytest.fixture
def freeze_time(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(alert_dispatcher, "datetime", _FrozenDateTime)
    return clock


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


def _write_alert_config(
    path: Path,
    *,
    escalation: list[dict],
    flap_detection: dict | None = None,
) -> str:
    alert_id = "alert-high-error"
    payload = {
        "alerts": [
            {
                "id": alert_id,
                "name": "High Error Rate",
                "tenant": "default",
                "metric": "error_rate",
                "window": "1h",
                "condition": "above",
                "threshold": 0.01,
                "webhook_url": escalation[0]["webhook_url"],
                "secret": "super-secret",
                "cooldown_minutes": 30,
                "active": True,
                "created_at": "2026-04-12T09:55:00Z",
                "updated_at": "2026-04-12T09:55:00Z",
                "last_triggered_at": None,
                "escalation": escalation,
                "flap_detection": flap_detection
                or {
                    "enabled": False,
                    "window_minutes": 5,
                    "max_changes": 3,
                },
            }
        ]
    }
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return alert_id


def _history(client: TestClient, alert_id: str) -> list[dict]:
    response = client.get(f"/v1/alerts/{alert_id}/history")
    assert response.status_code == 200
    return response.json()["history"]


@pytest.mark.integration
class TestAlertNoiseReduction:
    @pytest.mark.asyncio
    async def test_deduplicates_sustained_alert_before_next_escalation(
        self,
        client,
        freeze_time,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        alert_id = _write_alert_config(
            client.app.state.alert_config_path,
            escalation=[
                {"level": 1, "after_minutes": 0, "webhook_url": "http://agent.test/slack"},
                {"level": 2, "after_minutes": 15, "webhook_url": "http://agent.test/pager"},
            ],
        )
        metric = {"value": 0.021}
        monkeypatch.setattr(
            client.app.state.query_engine,
            "get_metric",
            lambda metric_name, window="1h", as_of=None, tenant_id=None: {
                "value": metric["value"],
                "unit": "ratio",
            },
        )

        freeze_time.set(datetime(2026, 4, 12, 10, 0, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        freeze_time.set(datetime(2026, 4, 12, 10, 5, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert [request["url"] for request in httpx_mock.requests] == ["http://agent.test/slack"]
        assert [item["event_type"] for item in _history(client, alert_id)] == ["alert.triggered"]

    @pytest.mark.asyncio
    async def test_escalates_to_second_level_after_threshold(
        self,
        client,
        freeze_time,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        _write_alert_config(
            client.app.state.alert_config_path,
            escalation=[
                {"level": 1, "after_minutes": 0, "webhook_url": "http://agent.test/slack"},
                {"level": 2, "after_minutes": 15, "webhook_url": "http://agent.test/pager"},
            ],
        )
        monkeypatch.setattr(
            client.app.state.query_engine,
            "get_metric",
            lambda metric_name, window="1h", as_of=None, tenant_id=None: {
                "value": 0.021,
                "unit": "ratio",
            },
        )

        freeze_time.set(datetime(2026, 4, 12, 10, 0, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        freeze_time.set(datetime(2026, 4, 12, 10, 16, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert [request["url"] for request in httpx_mock.requests] == [
            "http://agent.test/slack",
            "http://agent.test/pager",
        ]
        payload = json.loads(httpx_mock.requests[1]["content"].decode())
        assert httpx_mock.requests[1]["headers"]["X-AgentFlow-Event"] == "alert.escalated"
        assert payload["level"] == 2

    @pytest.mark.asyncio
    async def test_sends_resolved_webhook_when_metric_recovers(
        self,
        client,
        freeze_time,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        _write_alert_config(
            client.app.state.alert_config_path,
            escalation=[
                {"level": 1, "after_minutes": 0, "webhook_url": "http://agent.test/slack"},
            ],
        )
        metric = {"value": 0.021}
        monkeypatch.setattr(
            client.app.state.query_engine,
            "get_metric",
            lambda metric_name, window="1h", as_of=None, tenant_id=None: {
                "value": metric["value"],
                "unit": "ratio",
            },
        )

        freeze_time.set(datetime(2026, 4, 12, 10, 0, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.004
        freeze_time.set(datetime(2026, 4, 12, 10, 47, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert [request["headers"]["X-AgentFlow-Event"] for request in httpx_mock.requests] == [
            "alert.triggered",
            "alert.resolved",
        ]
        payload = json.loads(httpx_mock.requests[1]["content"].decode())
        assert payload["status"] == "resolved"
        assert payload["resolved_value"] == 0.004
        assert payload["duration_minutes"] == 47

    @pytest.mark.asyncio
    async def test_does_not_escalate_if_alert_resolves_before_escalation_window(
        self,
        client,
        freeze_time,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        _write_alert_config(
            client.app.state.alert_config_path,
            escalation=[
                {"level": 1, "after_minutes": 0, "webhook_url": "http://agent.test/slack"},
                {"level": 2, "after_minutes": 15, "webhook_url": "http://agent.test/pager"},
            ],
        )
        metric = {"value": 0.021}
        monkeypatch.setattr(
            client.app.state.query_engine,
            "get_metric",
            lambda metric_name, window="1h", as_of=None, tenant_id=None: {
                "value": metric["value"],
                "unit": "ratio",
            },
        )

        freeze_time.set(datetime(2026, 4, 12, 10, 0, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.004
        freeze_time.set(datetime(2026, 4, 12, 10, 10, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.021
        freeze_time.set(datetime(2026, 4, 12, 10, 16, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert [request["url"] for request in httpx_mock.requests] == [
            "http://agent.test/slack",
            "http://agent.test/slack",
            "http://agent.test/slack",
        ]
        assert [request["headers"]["X-AgentFlow-Event"] for request in httpx_mock.requests] == [
            "alert.triggered",
            "alert.resolved",
            "alert.triggered",
        ]

    @pytest.mark.asyncio
    async def test_suppresses_flapping_alerts_and_logs_warning(
        self,
        client,
        freeze_time,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        _write_alert_config(
            client.app.state.alert_config_path,
            escalation=[
                {"level": 1, "after_minutes": 0, "webhook_url": "http://agent.test/slack"},
            ],
            flap_detection={
                "enabled": True,
                "window_minutes": 5,
                "max_changes": 3,
            },
        )
        logger = _LoggerSpy()
        metric = {"value": 0.021}
        monkeypatch.setattr(alert_dispatcher, "logger", logger)
        monkeypatch.setattr(
            client.app.state.query_engine,
            "get_metric",
            lambda metric_name, window="1h", as_of=None, tenant_id=None: {
                "value": metric["value"],
                "unit": "ratio",
            },
        )

        freeze_time.set(datetime(2026, 4, 12, 10, 0, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.004
        freeze_time.set(datetime(2026, 4, 12, 10, 1, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.021
        freeze_time.set(datetime(2026, 4, 12, 10, 2, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.004
        freeze_time.set(datetime(2026, 4, 12, 10, 3, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert [request["headers"]["X-AgentFlow-Event"] for request in httpx_mock.requests] == [
            "alert.triggered",
            "alert.resolved",
            "alert.triggered",
        ]
        assert logger.warning_calls == [
            (
                "alert_flapping_suppressed",
                {
                    "alert_id": "alert-high-error",
                    "alert_name": "High Error Rate",
                    "changes": 4,
                    "window_minutes": 5,
                },
            )
        ]

    @pytest.mark.asyncio
    async def test_retrigger_after_resolved_starts_from_level_one_again(
        self,
        client,
        freeze_time,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        _write_alert_config(
            client.app.state.alert_config_path,
            escalation=[
                {"level": 1, "after_minutes": 0, "webhook_url": "http://agent.test/slack"},
                {"level": 2, "after_minutes": 15, "webhook_url": "http://agent.test/pager"},
            ],
        )
        metric = {"value": 0.021}
        monkeypatch.setattr(
            client.app.state.query_engine,
            "get_metric",
            lambda metric_name, window="1h", as_of=None, tenant_id=None: {
                "value": metric["value"],
                "unit": "ratio",
            },
        )

        freeze_time.set(datetime(2026, 4, 12, 10, 0, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        freeze_time.set(datetime(2026, 4, 12, 10, 16, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.004
        freeze_time.set(datetime(2026, 4, 12, 10, 20, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.021
        freeze_time.set(datetime(2026, 4, 12, 10, 21, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert httpx_mock.requests[-1]["url"] == "http://agent.test/slack"
        assert httpx_mock.requests[-1]["headers"]["X-AgentFlow-Event"] == "alert.triggered"

    @pytest.mark.asyncio
    async def test_records_trigger_escalation_and_resolved_events_in_history(
        self,
        client,
        freeze_time,
        httpx_mock,
        monkeypatch,
    ):
        _disable_auth(client)
        alert_id = _write_alert_config(
            client.app.state.alert_config_path,
            escalation=[
                {"level": 1, "after_minutes": 0, "webhook_url": "http://agent.test/slack"},
                {"level": 2, "after_minutes": 15, "webhook_url": "http://agent.test/pager"},
            ],
        )
        metric = {"value": 0.021}
        monkeypatch.setattr(
            client.app.state.query_engine,
            "get_metric",
            lambda metric_name, window="1h", as_of=None, tenant_id=None: {
                "value": metric["value"],
                "unit": "ratio",
            },
        )

        freeze_time.set(datetime(2026, 4, 12, 10, 0, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        freeze_time.set(datetime(2026, 4, 12, 10, 16, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()
        metric["value"] = 0.004
        freeze_time.set(datetime(2026, 4, 12, 10, 47, tzinfo=UTC))
        await client.app.state.alert_dispatcher.dispatch_alerts()

        assert len(httpx_mock.requests) == 4
        assert [item["event_type"] for item in _history(client, alert_id)] == [
            "alert.resolved",
            "alert.resolved",
            "alert.escalated",
            "alert.triggered",
        ]
