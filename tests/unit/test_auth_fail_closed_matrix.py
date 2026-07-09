"""S12 — auth fail-closed and path-class matrix (no full app lifespan).

Pins the three path classes AuthMiddleware implements:
1. exempt — always open (health, metrics, node ingest)
2. admin — middleware skip; route Depends(require_admin_key)
3. tenant — requires keys or explicit AGENTFLOW_AUTH_DISABLED
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager, build_auth_middleware, require_admin_key
from src.serving.api.auth.middleware import _is_admin_path, _is_exempt_path


def _app(tmp_path: Path, *, auth_disabled: bool = False, with_keys: bool = False) -> FastAPI:
    keys = tmp_path / "keys.yaml"
    if with_keys:
        keys.write_text(
            "keys:\n"
            "  - key: tenant-key\n"
            "    name: Tenant\n"
            "    tenant: acme\n"
            "    rate_limit_rpm: 60\n"
            "    created_at: '2026-07-09'\n",
            encoding="utf-8",
        )
    else:
        keys.write_text("keys: []\n", encoding="utf-8")

    app = FastAPI()
    app.state.auth_manager = AuthManager(
        api_keys_path=keys,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
    )
    app.state.auth_manager.load()
    if auth_disabled:
        app.state.auth_disabled = True
    app.middleware("http")(build_auth_middleware())

    @app.get("/v1/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics/")
    async def metrics() -> dict:
        return {"ok": True}

    @app.get("/v1/entity/order/1")
    async def entity() -> dict:
        return {"id": "1"}

    @app.get("/v1/admin/ping", dependencies=[Depends(require_admin_key)])
    async def admin_ping() -> dict:
        return {"admin": True}

    @app.post("/v1/node/events")
    async def node_events() -> dict:
        # Middleware-exempt; endpoint would check bearer in production.
        return {"accepted": True}

    return app


@pytest.mark.parametrize(
    "path",
    ["/v1/health", "/metrics", "/metrics/", "/docs", "/openapi.json", "/v1/node/events"],
)
def test_exempt_path_classifier(path: str) -> None:
    assert _is_exempt_path(path)


@pytest.mark.parametrize("path", ["/v1/admin/keys", "/admin/", "/admin/partials/summary"])
def test_admin_path_classifier(path: str) -> None:
    assert _is_admin_path(path)


def test_empty_keys_fail_closed_on_tenant_route(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, with_keys=False))
    response = client.get("/v1/entity/order/1")
    assert response.status_code == 503
    assert "API key configuration is missing" in response.json()["detail"]


def test_empty_keys_open_when_auth_disabled(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, with_keys=False, auth_disabled=True))
    assert client.get("/v1/entity/order/1").status_code == 200


def test_empty_keys_still_allows_exempt_health(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, with_keys=False))
    assert client.get("/v1/health").status_code == 200


def test_configured_keys_reject_missing_and_invalid(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, with_keys=True))
    assert client.get("/v1/entity/order/1").status_code == 401
    assert client.get("/v1/entity/order/1", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/v1/entity/order/1", headers={"X-API-Key": "tenant-key"}).status_code == 200


def test_admin_route_requires_admin_key_not_tenant_key(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, with_keys=True))
    # Middleware skips admin paths; require_admin_key is the real gate.
    assert client.get("/v1/admin/ping").status_code == 401
    assert client.get("/v1/admin/ping", headers={"X-API-Key": "tenant-key"}).status_code == 401
    assert client.get("/v1/admin/ping", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert client.get("/v1/admin/ping", headers={"X-Admin-Key": "admin-secret"}).status_code == 200


def test_node_events_path_is_middleware_exempt(tmp_path: Path) -> None:
    """Bearer check lives in the endpoint; middleware must not demand X-API-Key."""
    client = TestClient(_app(tmp_path, with_keys=True))
    assert client.post("/v1/node/events").status_code == 200
