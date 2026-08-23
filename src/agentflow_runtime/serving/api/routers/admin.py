from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from starlette.concurrency import run_in_threadpool

from agentflow_runtime.serving.api.analytics import (
    get_anomalies,
    get_latency_analytics,
    get_top_entities,
    get_top_queries,
    get_usage_analytics,
)
from agentflow_runtime.serving.api.auth import KeyCreateRequest, get_auth_manager, require_admin_key
from agentflow_runtime.serving.api.auth.manager import (
    KEY_STORE_READONLY_DETAIL,
    AuthManager,
    KeyStoreReadOnlyError,
    is_permission_denied,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_key)],
)

_T = TypeVar("_T")


def _key_store_conflict() -> HTTPException:
    # 409 not 501: the server implements the operation; the current store state conflicts.
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=KEY_STORE_READONLY_DETAIL,
    )


def _run_key_mutation(manager: AuthManager, op: Callable[[], _T]) -> _T:
    if not manager.key_store_writable:
        raise _key_store_conflict()
    try:
        return op()
    except KeyStoreReadOnlyError as exc:
        raise _key_store_conflict() from exc
    except OSError as exc:
        if is_permission_denied(exc):
            raise _key_store_conflict() from exc
        raise


@router.post("/keys", status_code=status.HTTP_201_CREATED, response_model=None)
async def create_api_key(payload: KeyCreateRequest, request: Request) -> dict[str, object]:
    manager = get_auth_manager(request)
    item = _run_key_mutation(manager, lambda: manager.create_key(payload))
    return {
        "key_id": item.key_id,
        "key": item.key,
        "name": item.name,
        "tenant": item.tenant,
        "rate_limit_rpm": item.rate_limit_rpm,
        "allowed_entity_types": item.allowed_entity_types,
        "created_at": item.created_at.isoformat(),
    }


@router.get("/keys", response_model=None)
async def list_api_keys(request: Request) -> dict[str, object]:
    manager = get_auth_manager(request)
    # Blocking: flushes the usage writer, then reads DuckDB. Off the loop.
    return {"keys": await run_in_threadpool(manager.list_keys_with_usage)}


@router.post("/keys/{key_id}/rotate", response_model=None)
async def rotate_api_key(key_id: str, request: Request) -> dict[str, object]:
    manager = get_auth_manager(request)
    try:
        item, expires_at = _run_key_mutation(manager, lambda: manager.rotate_key(key_id))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "new_key": item.key,
        "expires_at": expires_at.isoformat(),
    }


@router.get("/keys/{key_id}/rotation-status", response_model=None)
async def get_rotation_status(key_id: str, request: Request) -> dict[str, object]:
    manager = get_auth_manager(request)
    try:
        return manager.get_rotation_status(key_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found.") from None


@router.post("/keys/{key_id}/revoke-old", response_model=None)
async def revoke_old_api_key(key_id: str, request: Request) -> dict[str, object]:
    manager = get_auth_manager(request)
    try:
        revoked = _run_key_mutation(manager, lambda: manager.revoke_old_key(key_id))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found.") from None
    if not revoked:
        raise HTTPException(status_code=409, detail="No old key is pending revocation.")
    return {"revoked": True}


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def revoke_api_key(key_id: str, request: Request) -> Response:
    manager = get_auth_manager(request)
    if not _run_key_mutation(manager, lambda: manager.revoke_key_by_id(key_id)):
        raise HTTPException(status_code=404, detail="API key not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/usage", response_model=None)
async def get_usage(request: Request) -> dict[str, object]:
    manager = get_auth_manager(request)
    # Blocking: flushes the usage writer, then reads DuckDB. Off the loop.
    return {"usage": await run_in_threadpool(manager.usage_by_tenant)}


@router.get("/analytics/usage", response_model=None)
async def get_analytics_usage(
    request: Request,
    window: str = Query("24h"),
    tenant: str | None = Query(default=None),
) -> dict[str, object]:
    manager = get_auth_manager(request)
    try:
        return get_usage_analytics(manager.store, window=window, tenant=tenant)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/top-queries", response_model=None)
async def get_analytics_top_queries(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
    window: str = Query("24h"),
) -> dict[str, object]:
    manager = get_auth_manager(request)
    try:
        return get_top_queries(manager.store, limit=limit, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/top-entities", response_model=None)
async def get_analytics_top_entities(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
    window: str = Query("24h"),
) -> dict[str, object]:
    manager = get_auth_manager(request)
    try:
        return get_top_entities(manager.store, limit=limit, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/latency", response_model=None)
async def get_analytics_latency(
    request: Request,
    window: str = Query("24h"),
) -> dict[str, object]:
    manager = get_auth_manager(request)
    try:
        return get_latency_analytics(manager.store, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/anomalies", response_model=None)
async def get_analytics_anomalies(
    request: Request,
    window: str = Query("24h"),
) -> dict[str, object]:
    manager = get_auth_manager(request)
    try:
        return get_anomalies(manager.store, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
