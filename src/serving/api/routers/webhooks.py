import asyncio
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import AnyHttpUrl, BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.serving.api.egress_guard import UnsafeEgressURLError, validate_public_url
from src.serving.api.webhook_dispatcher import (
    WebhookDispatcher,
    WebhookFilters,
    create_webhook,
    deactivate_webhook,
    get_webhook,
    list_webhooks,
)
from src.serving.control_plane import get_control_plane_store

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


class WebhookCreateRequest(BaseModel):
    url: AnyHttpUrl
    filters: WebhookFilters = Field(default_factory=WebhookFilters)


def _tenant(request: Request) -> str:
    tenant_key = getattr(request.state, "tenant_key", None)
    if tenant_key is None:
        return "default"
    return str(tenant_key.tenant)


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_webhook(payload: WebhookCreateRequest, request: Request) -> dict[str, object]:
    try:
        await asyncio.to_thread(validate_public_url, str(payload.url))
    except UnsafeEgressURLError as exc:
        raise HTTPException(status_code=400, detail=f"Unsafe webhook URL: {exc}") from exc
    registration = create_webhook(
        request.app,
        url=str(payload.url),
        tenant=_tenant(request),
        filters=payload.filters,
    )
    return registration.model_dump(mode="json")


@router.get("")
async def list_my_webhooks(request: Request) -> dict[str, object]:
    webhooks = list_webhooks(request.app, _tenant(request))
    # Exclude `secret` from list/read responses. Plaintext signing material
    # is returned only once on POST. Listing it again would let any tenant
    # API key recover signing secrets after creation (audit p2_2 #7).
    return {
        "webhooks": [webhook.model_dump(mode="json", exclude={"secret"}) for webhook in webhooks]
    }


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_webhook(webhook_id: str, request: Request) -> Response:
    removed = deactivate_webhook(
        request.app,
        webhook_id,
        _tenant(request),
    )
    if not removed:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, request: Request) -> dict[str, object]:
    registration = get_webhook(
        request.app,
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
    dispatcher = cast(WebhookDispatcher, request.app.state.webhook_dispatcher)
    return cast(dict[str, object], await dispatcher.deliver(registration, payload))


@router.get("/{webhook_id}/logs")
async def webhook_logs(webhook_id: str, request: Request) -> dict[str, object]:
    registration = get_webhook(
        request.app,
        webhook_id,
        _tenant(request),
    )
    if registration is None:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found.")
    logs = await run_in_threadpool(_read_delivery_logs, request, webhook_id)
    return {"logs": logs}


def _read_delivery_logs(request: Request, webhook_id: str) -> list[dict]:
    # Runs on a worker thread (run_in_threadpool); the control-plane store
    # isolates the read (a dedicated cursor per call in the embedded adapter)
    # so concurrent reads on different threads don't collide on the shared
    # connection. (audit_30_06_26.md A2)
    return get_control_plane_store(request.app).get_webhook_delivery_logs(webhook_id)
