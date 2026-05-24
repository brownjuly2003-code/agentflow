from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import make_asgi_app

from src.serving.api.auth import AuthManager, build_auth_middleware
from src.serving.api.metrics import AUTH_FAILURES, HTTP_REQUESTS
from src.serving.api.middleware.metrics import (
    UNMATCHED_ROUTE_LABEL,
    build_metrics_middleware,
)
from src.serving.api.routers.admin import router as admin_router


def _write_api_keys(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


@pytest.fixture
def api_keys_path(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "api_keys.yaml"
    _write_api_keys(
        path,
        """
        keys:
          - key: "tenant-key"
            name: "Tenant Agent"
            tenant: "acme"
            rate_limit_rpm: 60
            created_at: "2026-04-10"
        """,
    )
    return path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "usage.duckdb"


def _build_app_with_metrics(api_keys_path: Path, db_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.auth_manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=db_path,
        admin_key="admin-secret",
    )
    app.state.auth_manager.load()
    app.state.auth_manager.ensure_usage_table()
    app.middleware("http")(build_auth_middleware())
    app.middleware("http")(build_metrics_middleware())
    app.include_router(admin_router, prefix="/v1")
    app.mount("/metrics", make_asgi_app())

    @app.get("/v1/entity/{entity_type}/{entity_id}")
    async def get_entity(entity_type: str, entity_id: str):
        return {"entity_type": entity_type, "entity_id": entity_id}

    @app.get("/v1/boom")
    async def boom():
        raise RuntimeError("kapow")

    return app


def _build_app_without_keys(db_path: Path, tmp_path: Path) -> FastAPI:
    keys_path = tmp_path / "config" / "missing_keys.yaml"
    keys_path.parent.mkdir(parents=True, exist_ok=True)
    keys_path.write_text("keys: []\n", encoding="utf-8")
    app = FastAPI()
    app.state.auth_manager = AuthManager(
        api_keys_path=keys_path,
        db_path=db_path,
        admin_key=None,
    )
    app.state.auth_manager.load()
    app.state.auth_manager.ensure_usage_table()
    app.middleware("http")(build_auth_middleware())
    app.include_router(admin_router, prefix="/v1")

    @app.get("/v1/entity/{entity_type}/{entity_id}")
    async def get_entity(entity_type: str, entity_id: str):
        return {"entity_type": entity_type, "entity_id": entity_id}

    return app


def _counter_value(counter, **labels) -> float:
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == labels:
                return sample.value
    return 0.0


def test_auth_failures_records_missing_key(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app_with_metrics(api_keys_path, db_path))
    before = _counter_value(AUTH_FAILURES, reason="missing_key")

    response = client.get("/v1/entity/order/ORD-1")

    assert response.status_code == 401
    assert _counter_value(AUTH_FAILURES, reason="missing_key") == before + 1


def test_auth_failures_records_invalid_key(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app_with_metrics(api_keys_path, db_path))
    before = _counter_value(AUTH_FAILURES, reason="invalid_key")

    response = client.get(
        "/v1/entity/order/ORD-1",
        headers={"X-API-Key": "totally-wrong"},
    )

    assert response.status_code == 401
    assert _counter_value(AUTH_FAILURES, reason="invalid_key") == before + 1


def test_auth_failures_records_key_file_empty(tmp_path: Path, db_path: Path):
    client = TestClient(_build_app_without_keys(db_path, tmp_path))
    before = _counter_value(AUTH_FAILURES, reason="key_file_empty")

    response = client.get("/v1/entity/order/ORD-1")

    assert response.status_code == 503
    assert _counter_value(AUTH_FAILURES, reason="key_file_empty") == before + 1


def test_auth_failures_records_admin_invalid(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app_with_metrics(api_keys_path, db_path))
    before = _counter_value(AUTH_FAILURES, reason="admin_invalid")

    response = client.get("/v1/admin/keys", headers={"X-Admin-Key": "nope"})

    assert response.status_code == 401
    assert _counter_value(AUTH_FAILURES, reason="admin_invalid") == before + 1


def test_http_requests_counts_success_by_route_template(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app_with_metrics(api_keys_path, db_path))
    labels = {
        "method": "GET",
        "route": "/v1/entity/{entity_type}/{entity_id}",
        "status": "200",
    }
    before = _counter_value(HTTP_REQUESTS, **labels)

    response = client.get(
        "/v1/entity/order/ORD-1",
        headers={"X-API-Key": "tenant-key"},
    )

    assert response.status_code == 200
    assert _counter_value(HTTP_REQUESTS, **labels) == before + 1


def test_http_requests_counts_unauthenticated_401_as_unmatched(api_keys_path: Path, db_path: Path):
    # Auth middleware short-circuits BEFORE the router matches a route, so
    # rejected requests land in the <unmatched> bucket. The route-level
    # detail for auth failures is exposed by agentflow_auth_failures_total
    # instead — see docs/runbooks/auth-401-spike.md.
    client = TestClient(_build_app_with_metrics(api_keys_path, db_path))
    labels = {"method": "GET", "route": UNMATCHED_ROUTE_LABEL, "status": "401"}
    before = _counter_value(HTTP_REQUESTS, **labels)

    response = client.get("/v1/entity/order/ORD-1")

    assert response.status_code == 401
    assert _counter_value(HTTP_REQUESTS, **labels) == before + 1


def test_http_requests_counts_5xx_on_exception(api_keys_path: Path, db_path: Path):
    client = TestClient(
        _build_app_with_metrics(api_keys_path, db_path), raise_server_exceptions=False
    )
    labels = {"method": "GET", "route": "/v1/boom", "status": "500"}
    before = _counter_value(HTTP_REQUESTS, **labels)

    response = client.get("/v1/boom", headers={"X-API-Key": "tenant-key"})

    assert response.status_code == 500
    assert _counter_value(HTTP_REQUESTS, **labels) == before + 1


def test_http_requests_falls_back_to_unmatched_label(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app_with_metrics(api_keys_path, db_path))
    labels = {"method": "GET", "route": UNMATCHED_ROUTE_LABEL, "status": "404"}
    before = _counter_value(HTTP_REQUESTS, **labels)

    response = client.get("/v1/does-not-exist", headers={"X-API-Key": "tenant-key"})

    assert response.status_code == 404
    assert _counter_value(HTTP_REQUESTS, **labels) == before + 1


def test_metrics_endpoint_exposes_both_counters(api_keys_path: Path, db_path: Path):
    client = TestClient(_build_app_with_metrics(api_keys_path, db_path))
    client.get("/v1/entity/order/ORD-1", headers={"X-API-Key": "tenant-key"})
    client.get("/v1/entity/order/ORD-1", headers={"X-API-Key": "bad"})

    metrics_body = client.get("/metrics").text

    assert "agentflow_http_requests_total" in metrics_body
    assert "agentflow_auth_failures_total" in metrics_body
