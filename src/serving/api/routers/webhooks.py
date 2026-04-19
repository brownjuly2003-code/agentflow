from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import AnyHttpUrl, BaseModel, Field

from src.serving.api.webhook_dispatcher import (
    WebhookFilters,
    create_webhook,
    deactivate_webhook,
    get_delivery_logs,
    get_webhook,
    get_webhook_config_path,
    list_webhooks,
)

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


class WebhookCreateRequest(BaseModel):
    url: AnyHttpUrl
    filters: WebhookFilters = Field(default_factory=WebhookFilters)


def _tenant(request: Request) -> str:
    tenant_key = getattr(request.state, "tenant_key", None)
    return tenant_key.tenant if tenant_key is not None else "default"


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_webhook(payload: WebhookCreateRequest, request: Request):
    registration = create_webhook(
        get_webhook_config_path(request.app),
        url=str(payload.url),
        tenant=_tenant(request),
        filters=payload.filters,
    )
    return registration.model_dump(mode="json")


@router.get("")
async def list_my_webhooks(request: Request):
    webhooks = list_webhooks(get_webhook_config_path(request.app), _tenant(request))
    return {"webhooks": [webhook.model_dump(mode="json") for webhook in webhooks]}


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_webhook(webhook_id: str, request: Request):
    removed = deactivate_webhook(
        get_webhook_config_path(request.app),
        webhook_id,
        _tenant(request),
    )
    if not removed:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, request: Request):
    registration = get_webhook(
        get_webhook_config_path(request.app),
        webhook_id,
        _tenant(request),
    )
    if registration is None:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found.")

    payload = {
        "event_id": f"test-{webhook_id}",
        "event_type": "webhook.test",
        "tenant": registration.tenant,
        "test": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return await request.app.state.webhook_dispatcher.deliver(registration, payload)


@router.get("/{webhook_id}/logs")
async def webhook_logs(webhook_id: str, request: Request):
    registration = get_webhook(
        get_webhook_config_path(request.app),
        webhook_id,
        _tenant(request),
    )
    if registration is None:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found.")
    logs = get_delivery_logs(request.app.state.query_engine._conn, webhook_id)
    return {"logs": logs}
