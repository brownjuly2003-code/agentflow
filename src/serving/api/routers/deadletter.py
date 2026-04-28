from __future__ import annotations

import json
import math
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.processing.event_replayer import (
    DeadLetterEventNotFoundError,
    EventReplayer,
    ReplayValidationError,
    ensure_dead_letter_table,
)

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


def _conn(request: Request):
    conn = request.app.state.query_engine._conn
    ensure_dead_letter_table(conn)
    return conn


def _tenant_id(request: Request) -> str:
    tenant_key = getattr(request.state, "tenant_key", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    return str(tenant_id or getattr(tenant_key, "tenant", "default"))


def _decode_payload(payload) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        decoded = json.loads(payload)
        if isinstance(decoded, dict):
            return decoded
    raise HTTPException(status_code=500, detail="Dead-letter payload is not a JSON object.")


def _replayer(request: Request) -> EventReplayer:
    producer = getattr(request.app.state, "deadletter_producer", None)
    return EventReplayer(_conn(request), producer=producer if callable(producer) else None)


def _require_deadletter_write_access(request: Request, event_id: str) -> None:
    tenant_key = getattr(request.state, "tenant_key", None)
    if tenant_key is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    if tenant_key.allowed_entity_types is not None:
        raise HTTPException(
            status_code=403,
            detail="This API key has read-only access to dead-letter operations.",
        )
    row = (
        _conn(request)
        .execute(
            """
        SELECT event_id
        FROM dead_letter_events
        WHERE event_id = ? AND COALESCE(tenant_id, 'default') = ?
        """,
            [event_id, _tenant_id(request)],
        )
        .fetchone()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Dead-letter event '{event_id}' not found.")


@router.get("/stats", response_model=DeadLetterStatsResponse)
async def deadletter_stats(request: Request):
    conn = _conn(request)
    tenant_id = _tenant_id(request)
    rows = conn.execute(
        """
        SELECT failure_reason, COUNT(*)
        FROM dead_letter_events
        WHERE status = 'failed'
          AND COALESCE(tenant_id, 'default') = ?
        GROUP BY failure_reason
        ORDER BY failure_reason
        """,
        [tenant_id],
    ).fetchall()
    last_24h_row = conn.execute(
        """
        SELECT COUNT(*)
        FROM dead_letter_events
        WHERE status = 'failed'
          AND COALESCE(tenant_id, 'default') = ?
          AND received_at >= NOW() - INTERVAL '24 hours'
        """,
        [tenant_id],
    ).fetchone()
    trend_rows = conn.execute(
        """
        SELECT DATE_TRUNC('hour', received_at) AS hour_bucket, COUNT(*)
        FROM dead_letter_events
        WHERE status = 'failed'
          AND COALESCE(tenant_id, 'default') = ?
          AND received_at >= NOW() - INTERVAL '24 hours'
        GROUP BY hour_bucket
        ORDER BY hour_bucket
        """,
        [tenant_id],
    ).fetchall()
    return DeadLetterStatsResponse(
        counts={str(reason): int(count) for reason, count in rows if reason is not None},
        last_24h=int(last_24h_row[0]) if last_24h_row and last_24h_row[0] is not None else 0,
        trend=[
            {
                "hour": hour.isoformat() if hasattr(hour, "isoformat") else str(hour),
                "count": int(count),
            }
            for hour, count in trend_rows
        ],
    )


@router.get("", response_model=DeadLetterListResponse)
async def list_deadletter_events(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    reason: str | None = Query(default=None),
):
    conn = _conn(request)
    tenant_id = _tenant_id(request)
    params: list[object]
    if reason is not None:
        params = [tenant_id, reason]
        total_row = conn.execute(
            """
            SELECT COUNT(*)
            FROM dead_letter_events
            WHERE status = 'failed'
              AND COALESCE(tenant_id, 'default') = ?
              AND failure_reason = ?
            """,
            params,
        ).fetchone()
    else:
        params = [tenant_id]
        total_row = conn.execute(
            """
            SELECT COUNT(*)
            FROM dead_letter_events
            WHERE status = 'failed'
              AND COALESCE(tenant_id, 'default') = ?
            """,
            params,
        ).fetchone()
    total = int(total_row[0]) if total_row and total_row[0] is not None else 0
    offset = (page - 1) * page_size
    if reason is not None:
        rows = conn.execute(
            """
            SELECT
                event_id,
                event_type,
                failure_reason,
                failure_detail,
                received_at,
                retry_count,
                last_retried_at,
                status
            FROM dead_letter_events
            WHERE status = 'failed'
              AND COALESCE(tenant_id, 'default') = ?
              AND failure_reason = ?
            ORDER BY received_at DESC, event_id ASC
            LIMIT ? OFFSET ?
            """,
            [tenant_id, reason, page_size, offset],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
                event_id,
                event_type,
                failure_reason,
                failure_detail,
                received_at,
                retry_count,
                last_retried_at,
                status
            FROM dead_letter_events
            WHERE status = 'failed'
              AND COALESCE(tenant_id, 'default') = ?
            ORDER BY received_at DESC, event_id ASC
            LIMIT ? OFFSET ?
            """,
            [tenant_id, page_size, offset],
        ).fetchall()

    return DeadLetterListResponse(
        items=[
            DeadLetterSummary(
                event_id=row[0],
                event_type=row[1],
                failure_reason=row[2],
                failure_detail=row[3],
                received_at=row[4],
                retry_count=int(row[5] or 0),
                last_retried_at=row[6],
                status=row[7],
            )
            for row in rows
        ],
        pagination={
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": math.ceil(total / page_size) if total else 0,
        },
    )


@router.get("/{event_id}", response_model=DeadLetterDetail)
async def get_deadletter_event(event_id: str, request: Request):
    conn = _conn(request)
    row = conn.execute(
        """
        SELECT
            event_id,
            event_type,
            payload,
            failure_reason,
            failure_detail,
            received_at,
            retry_count,
            last_retried_at,
            status
        FROM dead_letter_events
        WHERE event_id = ?
          AND COALESCE(tenant_id, 'default') = ?
        """,
        [event_id, _tenant_id(request)],
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Dead-letter event '{event_id}' not found.")
    return DeadLetterDetail(
        event_id=row[0],
        event_type=row[1],
        payload=_decode_payload(row[2]),
        failure_reason=row[3],
        failure_detail=row[4],
        received_at=row[5],
        retry_count=int(row[6] or 0),
        last_retried_at=row[7],
        status=row[8],
    )


@router.post("/{event_id}/replay", response_model=ReplayResponse)
async def replay_deadletter_event(
    event_id: str,
    request: Request,
    payload: ReplayRequest | None = None,
):
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
async def dismiss_deadletter_event(event_id: str, request: Request):
    _require_deadletter_write_access(request, event_id)
    try:
        _replayer(request).dismiss(event_id)
    except DeadLetterEventNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Dead-letter event '{event_id}' not found.",
        ) from None
    return DismissResponse(event_id=event_id, status="dismissed")
