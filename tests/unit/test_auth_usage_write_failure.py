"""A failed usage write must not fail the request it was counting.

``ControlPlaneStore.record_api_usage`` raises on exhausted retries so that
``record_usage`` skips its post-insert audit publish. That exception used to
propagate out of ``AuthMiddleware`` through the ASGI stack, so a request that
had already authenticated and would have served a 200 came back as a 500 —
observed on all six endpoints of the 2026-07-09 Load Test when concurrent
DuckDB opens collided on the usage database.

The middleware now counts the dropped row and serves the request.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.serving.api.auth import AuthManager, build_auth_middleware
from src.serving.api.metrics import USAGE_RECORD_FAILURES

API_KEY = "tenant-order-key"


def _build_app(tmp_path: Path) -> FastAPI:
    api_keys_path = tmp_path / "config" / "api_keys.yaml"
    api_keys_path.parent.mkdir(parents=True, exist_ok=True)
    api_keys_path.write_text(
        f"""
keys:
  - key: "{API_KEY}"
    name: "Order Agent"
    tenant: "acme"
    rate_limit_rpm: 100
    created_at: "2026-04-10"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    app = FastAPI()
    app.state.auth_manager = AuthManager(
        api_keys_path=api_keys_path,
        db_path=tmp_path / "usage.duckdb",
        admin_key="admin-secret",
    )
    app.state.auth_manager.load()
    app.state.auth_manager.ensure_usage_table()
    app.middleware("http")(build_auth_middleware())

    @app.get("/v1/metrics/revenue")
    async def revenue():
        return {"metric_name": "revenue", "value": 100.0}

    return app


def _failures_count() -> float:
    return USAGE_RECORD_FAILURES._value.get()


def test_request_succeeds_when_the_usage_write_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _build_app(tmp_path)

    def exploding_record_usage(*_args, **_kwargs):
        raise duckdb.BinderException(
            'Unique file handle conflict: Cannot attach "agentflow-api-usage"'
        )

    monkeypatch.setattr(
        app.state.auth_manager, "record_usage", exploding_record_usage, raising=True
    )

    before = _failures_count()
    with TestClient(app) as client:
        response = client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert response.json() == {"metric_name": "revenue", "value": 100.0}
    assert _failures_count() == before + 1


def test_healthy_request_does_not_touch_the_failure_counter(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    before = _failures_count()
    with TestClient(app) as client:
        response = client.get("/v1/metrics/revenue", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert _failures_count() == before
