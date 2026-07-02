import asyncio
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import AnyHttpUrl, BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.serving.api.alert_dispatcher import (
    create_alert,
    deactivate_alert,
    ensure_alert_dispatcher,
    get_alert,
    list_alerts,
    update_alert,
)
from src.serving.api.egress_guard import UnsafeEgressURLError, validate_public_url
from src.serving.control_plane import get_control_plane_store

router = APIRouter(prefix="/v1/alerts", tags=["alerts"])


class AlertCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    metric: str
    window: str = "1h"
    condition: Literal["above", "below", "change_pct"]
    threshold: float
    webhook_url: AnyHttpUrl
    cooldown_minutes: int = Field(30, ge=0, le=1440)


class AlertUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    metric: str | None = None
    window: str | None = None
    condition: Literal["above", "below", "change_pct"] | None = None
    threshold: float | None = None
    webhook_url: AnyHttpUrl | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    active: bool | None = None


def _tenant(request: Request) -> str:
    tenant_key = getattr(request.state, "tenant_key", None)
    if tenant_key is None:
        return "default"
    return str(tenant_key.tenant)


def _validate_metric_request(request: Request, metric: str, window: str) -> None:
    catalog = request.app.state.catalog
    metric_def = catalog.metrics.get(metric)
    if metric_def is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown metric: {metric}. Available: {list(catalog.metrics.keys())}",
        )
    if window not in metric_def.available_windows:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported window '{window}' for metric '{metric}'. "
                f"Available: {metric_def.available_windows}"
            ),
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_alert(payload: AlertCreateRequest, request: Request) -> dict[str, object]:
    _validate_metric_request(request, payload.metric, payload.window)
    try:
        await asyncio.to_thread(validate_public_url, str(payload.webhook_url))
    except UnsafeEgressURLError as exc:
        raise HTTPException(status_code=400, detail=f"Unsafe webhook URL: {exc}") from exc
    rule = create_alert(
        request.app,
        name=payload.name,
        tenant=_tenant(request),
        metric=payload.metric,
        window=payload.window,
        condition=payload.condition,
        threshold=payload.threshold,
        webhook_url=str(payload.webhook_url),
        cooldown_minutes=payload.cooldown_minutes,
    )
    ensure_alert_dispatcher(request.app)
    return rule.model_dump(mode="json")


@router.get("")
async def list_my_alerts(request: Request) -> dict[str, object]:
    alerts = list_alerts(request.app, _tenant(request))
    # Exclude signing `secret` from list responses (audit p2_2 #7).
    return {"alerts": [alert.model_dump(mode="json", exclude={"secret"}) for alert in alerts]}


@router.put("/{alert_id}")
async def modify_alert(
    alert_id: str, payload: AlertUpdateRequest, request: Request
) -> dict[str, object]:
    existing = get_alert(request.app, alert_id, _tenant(request))
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")

    updates = payload.model_dump(mode="json", exclude_none=True)
    next_metric = updates.get("metric", existing.metric)
    next_window = updates.get("window", existing.window)
    _validate_metric_request(request, next_metric, next_window)
    if "webhook_url" in updates:
        try:
            await asyncio.to_thread(validate_public_url, str(updates["webhook_url"]))
        except UnsafeEgressURLError as exc:
            raise HTTPException(status_code=400, detail=f"Unsafe webhook URL: {exc}") from exc

    updated = update_alert(request.app, alert_id, _tenant(request), updates)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")
    # Exclude signing `secret` from update responses (audit p2_2 #7).
    return updated.model_dump(mode="json", exclude={"secret"})


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_alert(alert_id: str, request: Request) -> Response:
    removed = deactivate_alert(request.app, alert_id, _tenant(request))
    if not removed:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{alert_id}/test")
async def test_alert(alert_id: str, request: Request) -> dict[str, object]:
    rule = get_alert(request.app, alert_id, _tenant(request))
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")
    return cast(dict[str, object], await ensure_alert_dispatcher(request.app).send_test_alert(rule))


@router.get("/{alert_id}/history")
async def alert_history(alert_id: str, request: Request) -> dict[str, object]:
    rule = get_alert(request.app, alert_id, _tenant(request))
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found.")
    history = await run_in_threadpool(_read_alert_history, request, alert_id)
    return {"history": history}


def _read_alert_history(request: Request, alert_id: str) -> list[dict]:
    # Runs on a worker thread (run_in_threadpool); the control-plane store
    # isolates the read (a dedicated cursor per call in the embedded adapter)
    # so concurrent reads on different threads don't collide on the shared
    # connection. (audit_30_06_26.md A2)
    return get_control_plane_store(request.app).get_alert_delivery_history(alert_id)
