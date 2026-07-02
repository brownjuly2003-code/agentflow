import json
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
        store=analytics_module._usage_store(tmp_path / "usage.duckdb"),
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
        store=analytics_module._usage_store(tmp_path / "usage.duckdb"),
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


def _v1_request(app: FastAPI, *, method: str, path: str, body: bytes = b"") -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "state": {},
            "app": app,
        },
        receive=receive,
    )


@pytest.mark.anyio
async def test_analytics_middleware_skips_unauthenticated_request(tmp_path: Path):
    # Analytics runs OUTSIDE AuthMiddleware. An unauthenticated /v1 request
    # (no tenant_key on request.state, rejected downstream with 401) must NOT
    # schedule a session write — otherwise unauthenticated, un-throttled traffic
    # drives a DB-writing thread spawn per request. (audit_30_06_26.md S1)
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(
        db_path=tmp_path / "usage.duckdb",
        store=analytics_module._usage_store(tmp_path / "usage.duckdb"),
        has_configured_keys=lambda: True,
    )
    middleware = build_analytics_middleware()
    request = _v1_request(app, method="POST", path="/v1/query", body=b'{"question": "x"}')

    async def call_next(_: Request) -> Response:
        return Response(status_code=401)

    response = await middleware(request, call_next)

    assert response.status_code == 401
    assert getattr(response.background, "tasks", []) == []


@pytest.mark.anyio
async def test_analytics_middleware_records_authenticated_request(tmp_path: Path):
    # The happy path still records: an authenticated request schedules exactly
    # one session-write background task.
    app = FastAPI()
    app.state.auth_manager = SimpleNamespace(
        db_path=tmp_path / "usage.duckdb",
        store=analytics_module._usage_store(tmp_path / "usage.duckdb"),
        has_configured_keys=lambda: True,
    )
    middleware = build_analytics_middleware()
    request = _v1_request(app, method="GET", path="/v1/entity/order/ORD-1")
    request.state.tenant_key = SimpleNamespace(tenant="acme", name="Agent")

    async def call_next(_: Request) -> Response:
        return Response(status_code=200)

    response = await middleware(request, call_next)

    assert response.status_code == 200
    assert len(getattr(response.background, "tasks", [])) == 1


def test_build_session_record_caps_query_text(tmp_path: Path):
    # An oversized /v1/query body is truncated before it is persisted, so it
    # can't be used to amplify storage. (audit_30_06_26.md S1)
    app = FastAPI()
    body = json.dumps({"question": "x" * 5000}).encode()
    request = _v1_request(app, method="POST", path="/v1/query", body=body)

    record = analytics_module._build_session_record(
        request=request,
        request_id="req-1",
        status_code=200,
        duration_ms=1.0,
        cache_hit=False,
        body=body,
    )

    assert len(record["query_text"]) == 1000
