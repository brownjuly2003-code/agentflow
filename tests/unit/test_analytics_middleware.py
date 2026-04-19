from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from src.serving.api import analytics as analytics_module
from src.serving.api.analytics import build_analytics_middleware, ensure_analytics_table


@pytest.mark.anyio
async def test_analytics_middleware_does_not_read_body_for_get_requests(tmp_path: Path):
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(
        db_path=tmp_path / "usage.duckdb",
        has_configured_keys=lambda: True,
    )
    middleware = build_analytics_middleware()

    async def receive():
        raise AssertionError("GET request body should not be consumed")

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/v1/health",
            "raw_path": b"/v1/health",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "app": app,
        },
        receive=receive,
    )

    async def call_next(_: Request) -> Response:
        return Response(status_code=204)

    response = await middleware(request, call_next)

    assert response.status_code == 204


@pytest.mark.anyio
async def test_analytics_middleware_skips_logging_when_auth_is_open(tmp_path: Path, monkeypatch):
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(
        db_path=tmp_path / "usage.duckdb",
        has_configured_keys=lambda: False,
    )
    middleware = build_analytics_middleware()

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/v1/entity/order/ORD-20260404-1001",
            "raw_path": b"/v1/entity/order/ORD-20260404-1001",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "app": app,
        }
    )

    async def call_next(_: Request) -> Response:
        return Response(status_code=204)

    response = await middleware(request, call_next)

    assert response.status_code == 204
    assert getattr(response.background, "tasks", []) == []


def test_insert_session_uses_existing_schema_without_rechecking(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "usage.duckdb"
    ensure_analytics_table(db_path)

    def fail_ensure(*args, **kwargs):
        raise AssertionError("schema bootstrap should not run during every background insert")

    monkeypatch.setattr(analytics_module, "ensure_analytics_table", fail_ensure)

    analytics_module._insert_session(
        db_path,
        "req-1",
        {
            "tenant": "acme",
            "key_name": "Acme Agent",
            "endpoint": "/v1/metrics/revenue",
            "method": "GET",
            "status_code": 200,
            "duration_ms": 12.3,
            "cache_hit": False,
            "entity_type": None,
            "entity_id": None,
            "metric_name": "revenue",
            "query_engine": None,
            "query_text": None,
        },
    )

    count = duckdb.connect(str(db_path)).execute("SELECT COUNT(*) FROM api_sessions").fetchone()[0]
    assert count == 1
