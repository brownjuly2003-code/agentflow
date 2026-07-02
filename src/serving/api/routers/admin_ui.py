from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import State
from starlette.responses import Response

from src.serving.api.auth import require_admin_key
from src.serving.cache import ENTITY_TTL_SECONDS
from src.serving.control_plane import ControlPlaneStore, EmbeddedControlPlaneStore

router = APIRouter(
    prefix="/admin",
    tags=["admin-ui"],
    dependencies=[Depends(require_admin_key)],
)
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard(request: Request) -> Response:
    context = await _build_context(request, partial=False)
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context=context,
    )


@router.get("/partials/summary", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard_summary(request: Request) -> Response:
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
        "qps_1m": await run_in_threadpool(_qps_last_minute, manager.store),
    }


async def _gather_health(state: State) -> dict[str, object]:
    payload = await run_in_threadpool(state.health_collector.collect)
    result: dict[str, object] = payload.to_dict()
    return result


def _cache_stats(state: State) -> dict[str, object]:
    query_cache = getattr(state, "query_cache", None)
    rate_limiter = getattr(getattr(state, "auth_manager", None), "rate_limiter", None)
    cache_backend = "redis" if getattr(query_cache, "_redis", None) is not None else "none"
    rate_limit_backend = "redis" if getattr(rate_limiter, "_redis", None) is not None else "memory"
    return {
        "backend": cache_backend,
        "entity_ttl_seconds": ENTITY_TTL_SECONDS,
        "rate_limit_backend": rate_limit_backend,
    }


def _qps_last_minute(source: ControlPlaneStore | Path | str) -> float:
    # ADR 0010 slice 4: routed through the ControlPlaneStore port — was a
    # direct connect_duckdb(db_path) query. Slice 5: the admin dashboard
    # hands in the manager's store (shared PostgreSQL store on the scale
    # profile); a bare path still builds the embedded per-call wrapper.
    if isinstance(source, ControlPlaneStore):
        return source.get_queries_per_second_last_minute()
    store = EmbeddedControlPlaneStore(usage_db_path_provider=lambda: source)
    return store.get_queries_per_second_last_minute()
