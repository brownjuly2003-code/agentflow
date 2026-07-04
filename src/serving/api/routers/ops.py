"""Ops surfaces — GET /v1/ops/stuck-orders, the stuck-orders worklist
(ops-surfaces-spec.md §3, D3).

Composes exactly the QueryEngine port: the open-orders read
(``fetch_orders_by_status``) and the stage-clock journal read
(``fetch_pipeline_events``), the same two reads the Order 360 timeline uses.
No raw engine connection reach, no vault DSN (invariant I1).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.serving.semantic_layer.stage_clock import (
    coerce_dt,
    ladder_stage_names,
    resolve_breach,
    stage_budget,
)

router = APIRouter(prefix="/v1/ops", tags=["ops"])


class StuckOrderItem(BaseModel):
    order_id: str
    user_id: str | None = None
    status: str
    entered_at: datetime | None = None
    in_stage_seconds: float | None = None
    sla_minutes: int | None = None
    overshoot_ratio: float | None = None
    clock: Literal["journal", "fallback"]
    total_amount: float | None = None
    currency: str | None = None


class StuckOrdersSummary(BaseModel):
    open_by_stage: dict[str, int] = Field(default_factory=dict)
    breached_by_stage: dict[str, int] = Field(default_factory=dict)


class StuckOrdersResponse(BaseModel):
    items: list[StuckOrderItem]
    summary: StuckOrdersSummary
    pagination: dict[str, int]


def _resolve_tenant_id(request: Request) -> str | None:
    tenant_key = getattr(request.state, "tenant_key", None)
    tenant_id = getattr(request.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    return cast("str | None", tenant_id)


def _build_stuck_order_item(
    order_row: dict[str, Any],
    latest_stage_row: dict[str, Any] | None,
    budget: dict[str, Any] | None,
) -> dict[str, Any]:
    """One order's worklist row: stage clock per §1.4, breach per §1.5."""
    entered_at = coerce_dt(latest_stage_row.get("processed_at")) if latest_stage_row else None
    clock = "journal" if entered_at is not None else "fallback"
    if entered_at is None:
        entered_at = coerce_dt(order_row.get("created_at"))

    in_stage_seconds, sla_minutes, breached = resolve_breach(entered_at=entered_at, budget=budget)
    overshoot_ratio = (
        in_stage_seconds / (sla_minutes * 60)
        if in_stage_seconds is not None and sla_minutes
        else None
    )

    return {
        "order_id": order_row.get("order_id"),
        "user_id": order_row.get("user_id"),
        "status": order_row.get("status"),
        "entered_at": entered_at,
        "in_stage_seconds": in_stage_seconds,
        "sla_minutes": sla_minutes,
        "overshoot_ratio": overshoot_ratio,
        "clock": clock,
        "total_amount": order_row.get("total_amount"),
        "currency": order_row.get("currency"),
        "_breached": breached,
    }


def _build_stuck_orders_payload(
    request: Request,
    stage: str | None,
    include_within_sla: bool,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Sync composition for GET /v1/ops/stuck-orders.

    Runs on a worker thread (matches lineage.py/deadletter.py/the Order 360
    timeline). Ladder + budgets come from the catalog `stages:` block only
    (I2) — no stage-name or budget literal here.
    """
    engine = request.app.state.query_engine
    tenant_id = _resolve_tenant_id(request)

    catalog = request.app.state.catalog
    order_def = catalog.entities.get("order")
    stage_budgets = (getattr(order_def, "stages", None) or []) if order_def else []
    ladder = ladder_stage_names(stage_budgets)

    order_rows = engine.fetch_orders_by_status(ladder, tenant_id=tenant_id)
    stage_rows = engine.fetch_pipeline_events(
        tenant_id=tenant_id, topic="orders.status", newest_first=False
    )

    # Latest journal row per (order, event_type), matching each order's
    # *current* status — not merely the most recent row overall (§1.4).
    # Ascending iteration means the last write for a key wins.
    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in stage_rows:
        entity_id = row.get("entity_id")
        event_type = row.get("event_type")
        if not entity_id or not event_type:
            continue
        latest_by_key[(str(entity_id), str(event_type))] = row

    all_items = [
        _build_stuck_order_item(
            order_row,
            latest_by_key.get(
                (str(order_row.get("order_id")), f"order.status.{order_row.get('status')}")
            ),
            stage_budget(stage_budgets, order_row.get("status")),
        )
        for order_row in order_rows
    ]

    open_by_stage: dict[str, int] = {}
    breached_by_stage: dict[str, int] = {}
    for item in all_items:
        status = item["status"]
        open_by_stage[status] = open_by_stage.get(status, 0) + 1
        if item["_breached"]:
            breached_by_stage[status] = breached_by_stage.get(status, 0) + 1

    filtered = all_items
    if stage is not None:
        filtered = [item for item in filtered if item["status"] == stage]
    if not include_within_sla:
        filtered = [item for item in filtered if item["_breached"]]

    def _sort_key(item: dict[str, Any]) -> float:
        ratio = item["overshoot_ratio"]
        return ratio if ratio is not None else -1.0

    filtered.sort(key=_sort_key, reverse=True)

    total = len(filtered)
    start = (page - 1) * page_size
    page_items = filtered[start : start + page_size]

    return {
        "items": [
            {key: value for key, value in item.items() if key != "_breached"} for item in page_items
        ],
        "summary": {"open_by_stage": open_by_stage, "breached_by_stage": breached_by_stage},
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": math.ceil(total / page_size) if total else 0,
        },
    }


@router.get("/stuck-orders", response_model=StuckOrdersResponse)
async def get_stuck_orders(
    request: Request,
    stage: str | None = Query(default=None),
    include_within_sla: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> StuckOrdersResponse:
    payload = await run_in_threadpool(
        _build_stuck_orders_payload, request, stage, include_within_sla, page, page_size
    )
    return StuckOrdersResponse.model_validate(payload)
