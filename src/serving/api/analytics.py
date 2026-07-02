import json
import os
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import duckdb
import structlog
from fastapi import Request
from starlette.background import BackgroundTasks
from starlette.responses import Response
from starlette.types import Message

from src.serving.control_plane import ControlPlaneStore, EmbeddedControlPlaneStore
from src.serving.duckdb_connection import connect_duckdb

logger = structlog.get_logger()


def _usage_store(source: ControlPlaneStore | Path | str) -> ControlPlaneStore:
    # ADR 0010 slice 4: the SQL for the functions below lives behind the
    # ControlPlaneStore port (control_plane/embedded.py). Slice 5 makes the
    # entry points polymorphic: callers on the scale profile hand in the
    # shared store (AuthManager.store, a PostgresControlPlaneStore there);
    # a path keeps the pre-port behavior — a fresh, cheap embedded wrapper
    # per call, nothing connected until a method on it runs.
    if isinstance(source, ControlPlaneStore):
        return source
    return EmbeddedControlPlaneStore(usage_db_path_provider=lambda: source)


AnalyticsMiddleware = Callable[
    [Request, Callable[[Request], Awaitable[Response]]],
    Awaitable[Response],
]

# Analytics runs before the route's Pydantic validation, so cap the persisted
# query text defensively at the same bound /v1/query enforces (1000 chars).
_MAX_QUERY_TEXT_CHARS = 1000

# Auth/throttle outcomes whose requests must never be recorded: the analytics
# middleware sits OUTSIDE AuthMiddleware, so recording these would let
# unauthenticated/rejected traffic drive un-throttled DB writes. (audit_30 S1)
_UNRECORDED_STATUS_CODES = frozenset({401, 403, 429, 503})


def ensure_analytics_table(db_path: Path | str) -> None:
    for attempt in range(10):
        try:
            conn = connect_duckdb(db_path)
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
            continue

        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_sessions (
                    request_id TEXT PRIMARY KEY,
                    tenant TEXT,
                    key_name TEXT,
                    endpoint TEXT,
                    method TEXT,
                    status_code INTEGER,
                    duration_ms FLOAT,
                    cache_hit BOOLEAN,
                    entity_type TEXT,
                    metric_name TEXT,
                    query_engine TEXT,
                    ts TIMESTAMP DEFAULT NOW()
                )
                """
            )
            existing_columns = {
                row[1] for row in conn.execute("PRAGMA table_info('api_sessions')").fetchall()
            }
            for column_name, column_type in (
                ("entity_id", "TEXT"),
                ("query_text", "TEXT"),
            ):
                if column_name not in existing_columns:
                    conn.execute(f"ALTER TABLE api_sessions ADD COLUMN {column_name} {column_type}")
            return
        except duckdb.Error:
            if attempt == 9:
                raise
            time.sleep(0.01 * (attempt + 1))
        finally:
            conn.close()


def build_analytics_middleware() -> AnalyticsMiddleware:
    async def analytics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith("/v1"):
            return await call_next(request)
        auth_manager = getattr(request.app.state, "auth_manager", None)
        if auth_manager is None or not auth_manager.has_configured_keys():
            return await call_next(request)

        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        started_at = time.perf_counter()
        body = b""
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if body:

                async def receive() -> Message:
                    return {"type": "http.request", "body": body, "more_body": False}

                request._receive = receive

        try:
            response = await call_next(request)
        # failure telemetry is best-effort before re-raising the original error
        except Exception:  # nosec B110
            # Record downstream failures before re-raising — but only for an
            # authenticated request, so an unauthenticated error can't drive an
            # un-throttled DB write/thread spawn. (audit_30_06_26.md S1)
            if getattr(request.state, "tenant_key", None) is not None:
                _schedule_session_write(
                    request.app.state.auth_manager.store,
                    request_id,
                    _build_session_record(
                        request=request,
                        request_id=request_id,
                        status_code=500,
                        duration_ms=(time.perf_counter() - started_at) * 1000,
                        cache_hit=False,
                        body=body,
                    ),
                )
            raise

        response.headers["X-Request-Id"] = request_id
        # Record analytics only for authenticated, non-rejected requests. This
        # middleware runs OUTSIDE AuthMiddleware, so without this gate an
        # unauthenticated/failed/throttled request would spawn a DB-writing
        # thread and persist an attacker-controlled body with neither auth nor
        # rate-limiting in front of it — a remote DoS. (audit_30_06_26.md S1)
        if (
            getattr(request.state, "tenant_key", None) is None
            or response.status_code in _UNRECORDED_STATUS_CODES
        ):
            return response
        background = response.background
        if background is None:
            background = BackgroundTasks()
        elif not isinstance(background, BackgroundTasks):
            background = BackgroundTasks([background])
        background.add_task(
            _schedule_session_write,
            request.app.state.auth_manager.store,
            request_id,
            _build_session_record(
                request=request,
                request_id=request_id,
                status_code=response.status_code,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                cache_hit=response.headers.get("X-Cache") == "HIT",
                body=body,
            ),
        )
        response.background = background
        return response

    return analytics_middleware


def get_usage_analytics(
    source: ControlPlaneStore | Path | str,
    *,
    window: str = "24h",
    tenant: str | None = None,
) -> dict:
    return _usage_store(source).get_usage_analytics(window=window, tenant=tenant)


def get_top_queries(
    source: ControlPlaneStore | Path | str,
    *,
    limit: int = 10,
    window: str = "24h",
) -> dict:
    return _usage_store(source).get_top_queries(limit=limit, window=window)


def get_top_entities(
    source: ControlPlaneStore | Path | str,
    *,
    limit: int = 10,
    window: str = "24h",
) -> dict:
    return _usage_store(source).get_top_entities(limit=limit, window=window)


def get_latency_analytics(
    source: ControlPlaneStore | Path | str,
    *,
    window: str = "24h",
) -> dict:
    return _usage_store(source).get_latency_analytics(window=window)


def get_anomalies(source: ControlPlaneStore | Path | str, *, window: str = "24h") -> dict:
    return _usage_store(source).get_anomalies(window=window)


def _schedule_session_write(
    source: ControlPlaneStore | Path | str, request_id: str, record: dict
) -> None:
    threading.Thread(
        target=_insert_session,
        args=(source, request_id, record),
        daemon=True,
    ).start()


def _insert_session(source: ControlPlaneStore | Path | str, request_id: str, record: dict) -> None:
    # Deliberately does NOT call ensure_analytics_table: the table is
    # guaranteed to exist by main.py's boot-time call (embedded profile; the
    # postgres adapter creates its schema once per process), and re-checking
    # it on every background write would be wasted work on the hot path (see
    # test_insert_session_uses_existing_schema_without_rechecking).
    _usage_store(source).record_api_session(request_id, record)


def _build_session_record(
    *,
    request: Request,
    request_id: str,
    status_code: int,
    duration_ms: float,
    cache_hit: bool,
    body: bytes,
) -> dict:
    tenant_key = getattr(request.state, "tenant_key", None)
    endpoint = request.url.path
    entity_type = None
    entity_id = None
    metric_name = None
    query_engine = None
    query_text = None
    parts = request.url.path.strip("/").split("/")

    if len(parts) >= 4 and parts[0] == "v1" and parts[1] == "entity":
        entity_type = parts[2]
        entity_id = parts[3]
        endpoint = f"/v1/entity/{entity_type}"
    elif len(parts) >= 3 and parts[0] == "v1" and parts[1] == "metrics":
        metric_name = parts[2]
        endpoint = f"/v1/metrics/{metric_name}"
    elif request.url.path == "/v1/query":
        query_engine = "llm" if os.getenv("GRACEKELLY_URL") else "rule_based"
        if body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {}
            question = payload.get("question")
            if isinstance(question, str):
                # Truncate: analytics runs before the route validates the body,
                # so an oversized question would otherwise be persisted verbatim.
                query_text = question[:_MAX_QUERY_TEXT_CHARS]

    return {
        "request_id": request_id,
        "tenant": getattr(tenant_key, "tenant", None),
        "key_name": getattr(tenant_key, "name", None),
        "endpoint": endpoint,
        "method": request.method,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 3),
        "cache_hit": cache_hit,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "metric_name": metric_name,
        "query_engine": query_engine,
        "query_text": query_text,
    }
