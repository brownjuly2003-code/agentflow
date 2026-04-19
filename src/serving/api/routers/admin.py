from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from src.serving.api.analytics import (
    get_anomalies,
    get_latency_analytics,
    get_top_entities,
    get_top_queries,
    get_usage_analytics,
)
from src.serving.api.auth import KeyCreateRequest, get_auth_manager, require_admin_key

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_key)],
)


@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: KeyCreateRequest, request: Request):
    manager = get_auth_manager(request)
    item = manager.create_key(payload)
    return {
        "key_id": item.key_id,
        "key": item.key,
        "name": item.name,
        "tenant": item.tenant,
        "rate_limit_rpm": item.rate_limit_rpm,
        "allowed_entity_types": item.allowed_entity_types,
        "created_at": item.created_at.isoformat(),
    }


@router.get("/keys")
async def list_api_keys(request: Request):
    manager = get_auth_manager(request)
    return {"keys": manager.list_keys_with_usage()}


@router.post("/keys/{key_id}/rotate")
async def rotate_api_key(key_id: str, request: Request):
    manager = get_auth_manager(request)
    try:
        item, expires_at = manager.rotate_key(key_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "new_key": item.key,
        "expires_at": expires_at.isoformat(),
    }


@router.get("/keys/{key_id}/rotation-status")
async def get_rotation_status(key_id: str, request: Request):
    manager = get_auth_manager(request)
    try:
        return manager.get_rotation_status(key_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found.")


@router.post("/keys/{key_id}/revoke-old")
async def revoke_old_api_key(key_id: str, request: Request):
    manager = get_auth_manager(request)
    try:
        revoked = manager.revoke_old_key(key_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found.")
    if not revoked:
        raise HTTPException(status_code=409, detail="No old key is pending revocation.")
    return {"revoked": True}


@router.delete("/keys/{api_key}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(api_key: str, request: Request):
    manager = get_auth_manager(request)
    if not manager.revoke_key(api_key):
        raise HTTPException(status_code=404, detail=f"API key '{api_key}' not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/usage")
async def get_usage(request: Request):
    manager = get_auth_manager(request)
    return {"usage": manager.usage_by_tenant()}


@router.get("/analytics/usage")
async def get_analytics_usage(
    request: Request,
    window: str = Query("24h"),
    tenant: str | None = Query(default=None),
):
    manager = get_auth_manager(request)
    try:
        return get_usage_analytics(manager.db_path, window=window, tenant=tenant)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/top-queries")
async def get_analytics_top_queries(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
    window: str = Query("24h"),
):
    manager = get_auth_manager(request)
    try:
        return get_top_queries(manager.db_path, limit=limit, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/top-entities")
async def get_analytics_top_entities(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
    window: str = Query("24h"),
):
    manager = get_auth_manager(request)
    try:
        return get_top_entities(manager.db_path, limit=limit, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/latency")
async def get_analytics_latency(
    request: Request,
    window: str = Query("24h"),
):
    manager = get_auth_manager(request)
    try:
        return get_latency_analytics(manager.db_path, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analytics/anomalies")
async def get_analytics_anomalies(
    request: Request,
    window: str = Query("24h"),
):
    manager = get_auth_manager(request)
    try:
        return get_anomalies(manager.db_path, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
