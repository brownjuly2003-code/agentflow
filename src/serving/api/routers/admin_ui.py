from __future__ import annotations

from pathlib import Path

import duckdb
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from src.serving.api.analytics import ensure_analytics_table
from src.serving.api.auth import require_admin_key
from src.serving.cache import ENTITY_TTL_SECONDS
from src.serving.duckdb_connection import connect_duckdb

router = APIRouter(
    prefix="/admin",
    tags=["admin-ui"],
    dependencies=[Depends(require_admin_key)],
)
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard(request: Request):
    context = await _build_context(request, partial=False)
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context=context,
    )


@router.get("/partials/summary", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard_summary(request: Request):
    context = await _build_context(request, partial=True)
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context=context,
    )


async def _build_context(request: Request, *, partial: bool) -> dict[str, object]:
    state = request.app.state
    manager = state.auth_manager
    health = await _gather_health(state)
    return {
        "request": request,
        "partial": partial,
        "health": health,
        "configured_keys": manager.configured_key_count,
        "key_usage": manager.list_keys_with_usage(),
        "db_pool": state.db_pool.stats(),
        "cache_stats": _cache_stats(state),
        "qps_1m": await run_in_threadpool(_qps_last_minute, manager.db_path),
    }


async def _gather_health(state) -> dict[str, object]:
    payload = await run_in_threadpool(state.health_collector.collect)
    result: dict[str, object] = payload.to_dict()
    return result


def _cache_stats(state) -> dict[str, object]:
    query_cache = getattr(state, "query_cache", None)
    rate_limiter = getattr(getattr(state, "auth_manager", None), "rate_limiter", None)
    cache_backend = "redis" if getattr(query_cache, "_redis", None) is not None else "none"
    rate_limit_backend = "redis" if getattr(rate_limiter, "_redis", None) is not None else "memory"
    return {
        "backend": cache_backend,
        "entity_ttl_seconds": ENTITY_TTL_SECONDS,
        "rate_limit_backend": rate_limit_backend,
    }


def _qps_last_minute(db_path: Path | str) -> float:
    ensure_analytics_table(db_path)
    conn = connect_duckdb(db_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM api_sessions
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '1 minute'
            """
        ).fetchone()
        requests_last_minute = row[0] if row else 0
    except duckdb.Error:
        return 0.0
    finally:
        conn.close()
    return round(float(requests_last_minute) / 60.0, 2)
