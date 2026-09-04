"""API boundary and packaged client for scheduled analytics retention (T-27)."""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Callable
from types import ModuleType

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentflow_runtime.serving.api.routers import admin as admin_module


class _RetentionStore:
    def __init__(self, deleted_rows: int = 7) -> None:
        self.deleted_rows = deleted_rows
        self.calls: list[int] = []

    def prune_api_sessions(self, *, older_than_days: int) -> int:
        self.calls.append(older_than_days)
        return self.deleted_rows


class _AdminManager:
    def __init__(self, store: _RetentionStore) -> None:
        self.admin_key = "admin-secret"
        self.store = store

    def is_failed_auth_limited(self, _client_ip: str) -> bool:
        return False

    def record_failed_auth(self, _client_ip: str) -> None:
        return None

    def clear_failed_auth(self, _client_ip: str) -> None:
        return None


def _api_client(store: _RetentionStore) -> TestClient:
    app = FastAPI()
    app.state.auth_manager = _AdminManager(store)
    app.include_router(admin_module.router, prefix="/v1")
    return TestClient(app)


def _client_module() -> ModuleType:
    return importlib.import_module("agentflow_runtime.serving.api.analytics_retention_client")


def test_retention_endpoint_requires_the_admin_key() -> None:
    store = _RetentionStore()

    with _api_client(store) as client:
        response = client.post("/v1/admin/analytics/retention", json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing admin key."}
    assert store.calls == []


def test_retention_endpoint_defaults_through_the_policy_and_offloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _RetentionStore(deleted_rows=11)
    offloaded: list[tuple[Callable[..., object], tuple[object, ...], dict[str, object]]] = []

    async def run_in_threadpool(
        func: Callable[..., object], *args: object, **kwargs: object
    ) -> object:
        offloaded.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.delenv("AGENTFLOW_PROFILE", raising=False)
    monkeypatch.delenv("AGENTFLOW_QUERY_ANALYTICS_RETENTION_DAYS", raising=False)
    monkeypatch.setattr(admin_module, "run_in_threadpool", run_in_threadpool)

    with _api_client(store) as client:
        response = client.post(
            "/v1/admin/analytics/retention",
            headers={"X-Admin-Key": "admin-secret"},
            json={},
        )

    assert response.status_code == 200
    assert response.json() == {
        "retention_days": 30,
        "dry_run": False,
        "deleted_rows": 11,
    }
    assert store.calls == [30]
    assert len(offloaded) == 1
    assert offloaded[0][2] == {"older_than_days": 30}


def test_retention_endpoint_accepts_an_explicit_window() -> None:
    store = _RetentionStore(deleted_rows=3)

    with _api_client(store) as client:
        response = client.post(
            "/v1/admin/analytics/retention",
            headers={"X-Admin-Key": "admin-secret"},
            json={"retention_days": 14},
        )

    assert response.status_code == 200
    assert response.json() == {
        "retention_days": 14,
        "dry_run": False,
        "deleted_rows": 3,
    }
    assert store.calls == [14]


def test_retention_endpoint_dry_run_never_opens_the_store() -> None:
    store = _RetentionStore()

    with _api_client(store) as client:
        response = client.post(
            "/v1/admin/analytics/retention",
            headers={"X-Admin-Key": "admin-secret"},
            json={"retention_days": 7, "dry_run": True},
        )

    assert response.status_code == 200
    assert response.json() == {
        "retention_days": 7,
        "dry_run": True,
        "deleted_rows": None,
    }
    assert store.calls == []


def test_retention_endpoint_rejects_a_zero_day_window() -> None:
    store = _RetentionStore()

    with _api_client(store) as client:
        response = client.post(
            "/v1/admin/analytics/retention",
            headers={"X-Admin-Key": "admin-secret"},
            json={"retention_days": 0},
        )

    assert response.status_code == 422
    assert store.calls == []


def test_packaged_client_posts_the_key_from_env_and_the_requested_policy() -> None:
    module = _client_module()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"retention_days": 14, "dry_run": True, "deleted_rows": None},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = module.run_retention(
            url="http://agentflow:8000/v1/admin/analytics/retention",
            retention_days=14,
            dry_run=True,
            env={"AGENTFLOW_ADMIN_KEY": "client-secret"},
            client=client,
        )

    assert result == {"retention_days": 14, "dry_run": True, "deleted_rows": None}
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.headers["X-Admin-Key"] == "client-secret"
    assert json.loads(request.content) == {"retention_days": 14, "dry_run": True}
    assert "admin_key" not in inspect.signature(module.run_retention).parameters


def test_packaged_client_omits_the_optional_window() -> None:
    module = _client_module()
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"retention_days": 30, "dry_run": False, "deleted_rows": 4},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        module.run_retention(
            url="http://agentflow:8000/v1/admin/analytics/retention",
            env={"AGENTFLOW_ADMIN_KEY": "client-secret"},
            client=client,
        )

    assert payloads == [{"dry_run": False}]


def test_packaged_client_requires_the_admin_key_before_sending() -> None:
    module = _client_module()
    sent = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent = True
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(module.AnalyticsRetentionClientError, match="AGENTFLOW_ADMIN_KEY"):
            module.run_retention(
                url="http://agentflow:8000/v1/admin/analytics/retention",
                env={},
                client=client,
            )

    assert sent is False


def test_packaged_client_never_prints_the_key_or_server_error_body(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _client_module()
    key = "do-not-print-this-admin-key"
    server_body = "private database failure: tenant=secret-customer"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=server_body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        exit_code = module.main(
            ["--url", "http://agentflow:8000/v1/admin/analytics/retention"],
            env={"AGENTFLOW_ADMIN_KEY": key},
            client=client,
        )

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert exit_code == 1
    assert "HTTP 500" in combined
    assert key not in combined
    assert server_body not in combined
