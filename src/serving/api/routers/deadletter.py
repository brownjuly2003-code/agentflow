from __future__ import annotations

import json
import math
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.processing.event_replayer import (
    DeadLetterEventNotFoundError,
    EventReplayer,
    ReplayValidationError,
)
from src.serving.control_plane import get_control_plane_store

router = APIRouter(prefix="/v1/deadletter", tags=["deadletter"])


class DeadLetterSummary(BaseModel):
    event_id: str
    event_type: str | None = None
    failure_reason: str | None = None
    failure_detail: str | None = None
    received_at: datetime | None = None
    retry_count: int = 0
    last_retried_at: datetime | None = None
    status: str


class DeadLetterDetail(DeadLetterSummary):
    payload: dict


class DeadLetterListResponse(BaseModel):
    items: list[DeadLetterSummary]
    pagination: dict[str, int]


class DeadLetterStatsResponse(BaseModel):
    counts: dict[str, int]
    last_24h: int
    trend: list[dict[str, int | str]] = Field(default_factory=list)


class ReplayRequest(BaseModel):
    corrected_payload: dict | None = None


class ReplayResponse(BaseModel):
    event_id: str
    status: str
    retry_count: int
    last_retried_at: datetime


class DismissResponse(BaseModel):
    event_id: str
    status: str


def _tenant_id(request: Request) -> str:
    tenant_key = getattr(request.state, "tenant_key", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    return str(tenant_id or getattr(tenant_key, "tenant", "default"))


def _decode_payload(payload: object) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        decoded = json.loads(payload)
        if isinstance(decoded, dict):
            return decoded
    raise HTTPException(status_code=500, detail="Dead-letter payload is not a JSON object.")


def _replayer(request: Request) -> EventReplayer:
    producer = getattr(request.app.state, "deadletter_producer", None)
    return EventReplayer(
        store=get_control_plane_store(request.app),
        producer=producer if callable(producer) else None,
    )


def _require_deadletter_write_access(request: Request, event_id: str) -> None:
    tenant_key = getattr(request.state, "tenant_key", None)
    if tenant_key is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    if tenant_key.allowed_entity_types is not None:
        raise HTTPException(
            status_code=403,
            detail="This API key has read-only access to dead-letter operations.",
        )
    exists = get_control_plane_store(request.app).dead_letter_event_exists(
        event_id, _tenant_id(request)
    )
    if not exists:
        raise HTTPException(status_code=404, detail=f"Dead-letter event '{event_id}' not found.")


@router.get("/stats", response_model=DeadLetterStatsResponse)
async def deadletter_stats(request: Request) -> DeadLetterStatsResponse:
    return await run_in_threadpool(_deadletter_stats, request)


def _deadletter_stats(request: Request) -> DeadLetterStatsResponse:
    stats = get_control_plane_store(request.app).get_dead_letter_stats(_tenant_id(request))
    return DeadLetterStatsResponse(**stats)


@router.get("", response_model=DeadLetterListResponse)
async def list_deadletter_events(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    reason: str | None = Query(default=None),
) -> DeadLetterListResponse:
    return await run_in_threadpool(_list_deadletter_events, request, page, page_size, reason)


def _list_deadletter_events(
    request: Request, page: int, page_size: int, reason: str | None
) -> DeadLetterListResponse:
    items, total = get_control_plane_store(request.app).list_dead_letter_events(
        tenant_id=_tenant_id(request), reason=reason, page=page, page_size=page_size
    )
    return DeadLetterListResponse(
        items=[DeadLetterSummary(**item) for item in items],
        pagination={
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": math.ceil(total / page_size) if total else 0,
        },
    )


@router.get("/{event_id}", response_model=DeadLetterDetail)
async def get_deadletter_event(event_id: str, request: Request) -> DeadLetterDetail:
    return await run_in_threadpool(_get_deadletter_event, request, event_id)


def _get_deadletter_event(request: Request, event_id: str) -> DeadLetterDetail:
    row = get_control_plane_store(request.app).get_dead_letter_event(event_id, _tenant_id(request))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Dead-letter event '{event_id}' not found.")
    return DeadLetterDetail(**{**row, "payload": _decode_payload(row["payload"])})


@router.post("/{event_id}/replay", response_model=ReplayResponse)
async def replay_deadletter_event(
    event_id: str,
    request: Request,
    payload: ReplayRequest | None = None,
) -> ReplayResponse:
    _require_deadletter_write_access(request, event_id)
    try:
        result = _replayer(request).replay(
            event_id,
            corrected_payload=payload.corrected_payload if payload is not None else None,
        )
    except DeadLetterEventNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Dead-letter event '{event_id}' not found.",
        ) from None
    except ReplayValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ReplayResponse(
        event_id=result.event_id,
        status=result.status,
        retry_count=result.retry_count,
        last_retried_at=result.last_retried_at,
    )


@router.post("/{event_id}/dismiss", response_model=DismissResponse)
async def dismiss_deadletter_event(event_id: str, request: Request) -> DismissResponse:
    _require_deadletter_write_access(request, event_id)
    try:
        _replayer(request).dismiss(event_id)
    except DeadLetterEventNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Dead-letter event '{event_id}' not found.",
        ) from None
    return DismissResponse(event_id=event_id, status="dismissed")
