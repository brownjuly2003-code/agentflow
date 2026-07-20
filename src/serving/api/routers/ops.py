"""Ops surfaces — GET /v1/ops/stuck-orders, the stuck-orders worklist
(ops-surfaces-spec.md §3, D3); GET/POST /v1/ops/exceptions*, the exception
inbox (ops-surfaces-spec.md §4, D4).

Composes exactly the QueryEngine port (the open-orders read
``fetch_orders_by_status`` and the stage-clock journal read
``fetch_pipeline_events``, the same two reads the Order 360 timeline uses)
and the ControlPlaneStore port (dead-letter reads, the triage overlay,
webhook dead-delivery reads). No raw engine connection reach, no vault DSN
(invariant I1).
"""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.serving.control_plane import (
    TriageState,
    get_control_plane_store,
    stuck_replay_threshold_seconds,
)
from src.serving.semantic_layer.reconciliation import (
    ReconciliationFinding,
    check_journal_vs_store,
    check_stuck_replay,
    journal_scan_limit,
    orders_scan_limit,
)
from src.serving.semantic_layer.stage_clock import (
    coerce_dt,
    ladder_stage_names,
    resolve_breach,
    stage_budget,
)

router = APIRouter(prefix="/v1/ops", tags=["ops"])

_DEADLETTER_STATUS_MAP = {
    "failed": "open",
    "replay_pending": "in_progress",
    "replayed": "resolved",
    "dismissed": "resolved",
}
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

_DEFAULT_INBOX_SCAN_LIMIT = 20_000


def inbox_scan_limit() -> int:
    """Per-source row cap for the exception-inbox store reads (security
    pre-audit S-8): the inbox materialises every dead-letter row and dead
    webhook delivery for the tenant in memory on a worker thread. Same "size
    safety net" contract as ``journal_scan_limit``/``orders_scan_limit`` —
    the gather probes with ``cap + 1``, so hitting the cap is reported
    (``scan_truncated``), never a silent cut. Env-tunable via
    ``AGENTFLOW_OPS_INBOX_SCAN_LIMIT``.
    """
    raw = (os.getenv("AGENTFLOW_OPS_INBOX_SCAN_LIMIT") or "").strip()
    if not raw:
        return _DEFAULT_INBOX_SCAN_LIMIT
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_INBOX_SCAN_LIMIT
    return value if value > 0 else _DEFAULT_INBOX_SCAN_LIMIT


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
    # True when the open-orders read hit its scan cap (S-8): the worklist,
    # summary counts, and total then cover the scanned window only.
    scan_truncated: bool = False


def _resolve_tenant_id(request: Request) -> str | None:
    # n4 (G2 audit): None here means auth is disabled (dev/demo mode) — a
    # real authenticated request always carries a concrete `tenant_key.tenant`
    # (AuthMiddleware). Passed through to `fetch_pipeline_events`, where
    # tenant_id=None is the documented cross-tenant-scan invariant, not an
    # oversight — see QueryEngine.fetch_pipeline_events's docstring.
    tenant_key = getattr(request.state, "tenant_key", None)
    tenant_id = getattr(request.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    return cast("str | None", tenant_id)


def _build_stuck_order_item(
    order_row: dict[str, Any],
    latest_stage_row: dict[str, Any] | None,
    budget: dict[str, Any] | None,
    *,
    backend_name: str | None = None,
) -> dict[str, Any]:
    """One order's worklist row: stage clock per §1.4, breach per §1.5."""
    entered_at = (
        coerce_dt(latest_stage_row.get("processed_at"), backend_name=backend_name)
        if latest_stage_row
        else None
    )
    clock = "journal" if entered_at is not None else "fallback"
    if entered_at is None:
        entered_at = coerce_dt(order_row.get("created_at"), backend_name=backend_name)

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

    # cap+1 probe: hitting the cap is reported as `scan_truncated`, never a
    # silent cut of the worklist (S-8). Truncation is deterministic — the
    # engine read orders by primary key.
    scan_cap = orders_scan_limit()
    order_rows = engine.fetch_orders_by_status(ladder, tenant_id=tenant_id, limit=scan_cap + 1)
    scan_truncated = len(order_rows) > scan_cap
    if scan_truncated:
        order_rows = order_rows[:scan_cap]
    stage_rows = engine.fetch_pipeline_events(
        tenant_id=tenant_id,
        topic="orders.status",
        newest_first=True,
        limit=journal_scan_limit(),
    )

    # Latest journal row per (order, event_type), matching each order's
    # *current* status — not merely the most recent row overall (§1.4).
    # Descending iteration (`newest_first=True`, bounded per m13's
    # `journal_scan_limit()` — a size safety net against an unbounded scan of
    # the whole journal at production scale): the first row seen per key is
    # its latest — skip once a key is already recorded.
    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in stage_rows:
        entity_id = row.get("entity_id")
        event_type = row.get("event_type")
        if not entity_id or not event_type:
            continue
        key = (str(entity_id), str(event_type))
        if key in latest_by_key:
            continue
        latest_by_key[key] = row

    store_backend = getattr(engine, "_backend_name", None)
    all_items = [
        _build_stuck_order_item(
            order_row,
            latest_by_key.get(
                (str(order_row.get("order_id")), f"order.status.{order_row.get('status')}")
            ),
            stage_budget(stage_budgets, order_row.get("status")),
            backend_name=store_backend,
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
        "scan_truncated": scan_truncated,
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


# ---------------------------------------------------------------------------
# Exception inbox (D4, ops-surfaces-spec.md §4)
# ---------------------------------------------------------------------------


class EntityRef(BaseModel):
    kind: Literal["event", "order", "webhook"]
    id: str


class ExceptionAction(BaseModel):
    action: str
    href: str


class ExceptionItem(BaseModel):
    item_id: str
    source: Literal["deadletter", "webhook_delivery", "reconciliation"]
    severity: Literal["high", "medium", "low"]
    occurred_at: datetime
    last_seen_at: datetime
    entity_ref: EntityRef
    title: str
    detail: str
    status: Literal["open", "in_progress", "acknowledged", "resolved"]
    actions: list[ExceptionAction]


class ExceptionsListResponse(BaseModel):
    items: list[ExceptionItem]
    pagination: dict[str, int]
    # True when a source read hit its scan cap (S-8): the inbox and its
    # counts then cover the scanned window only.
    scan_truncated: bool = False


class ExceptionsStatsResponse(BaseModel):
    by_source: dict[str, dict[str, int]] = Field(default_factory=dict)
    last_24h: int
    manual_resolutions: int
    scan_truncated: bool = False


class TriageActionRequest(BaseModel):
    note: str | None = None


class TriageActionResponse(BaseModel):
    item_id: str
    status: str


def _tenant_id(request: Request) -> str:
    tenant_key = getattr(request.state, "tenant_key", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    return str(tenant_id or getattr(tenant_key, "tenant", "default"))


def _deadletter_row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    status = _DEADLETTER_STATUS_MAP.get(row["status"], "open")
    occurred_at = coerce_dt(row.get("received_at")) or datetime.now(UTC)
    last_seen_at = coerce_dt(row.get("last_retried_at")) or occurred_at
    event_id = row["event_id"]
    actions = (
        []
        if status == "resolved"
        else [
            {"action": "replay", "href": f"/v1/deadletter/{event_id}/replay"},
            {"action": "dismiss", "href": f"/v1/deadletter/{event_id}/dismiss"},
        ]
    )
    return {
        "item_id": f"dl:{event_id}",
        "source": "deadletter",
        "severity": "high",
        "occurred_at": occurred_at,
        "last_seen_at": last_seen_at,
        "entity_ref": {"kind": "event", "id": event_id},
        "title": f"Dead-letter: {row.get('failure_reason') or 'unknown reason'}",
        "detail": row.get("failure_detail") or "",
        "status": status,
        "actions": actions,
    }


def _webhook_delivery_row_to_item(
    row: dict[str, Any], state: TriageState | None, now: datetime
) -> dict[str, Any]:
    item_id = f"wh:{row['webhook_id']}:{row['event_id']}"
    status = state.status if state is not None else "open"
    fallback_at = coerce_dt(row.get("updated_at")) or now
    # Overlay timestamps come back naive from DuckDB, aware from PostgreSQL
    # (TIMESTAMPTZ) — coerce_dt normalizes either to aware UTC.
    occurred_at = fallback_at
    last_seen_at = fallback_at
    if state is not None:
        occurred_at = coerce_dt(state.first_seen_at) or fallback_at
        last_seen_at = coerce_dt(state.last_seen_at) or fallback_at
    actions = (
        []
        if status == "resolved"
        else [
            {"action": "acknowledge", "href": f"/v1/ops/exceptions/{item_id}/acknowledge"},
            {"action": "resolve", "href": f"/v1/ops/exceptions/{item_id}/resolve"},
        ]
    )
    return {
        "item_id": item_id,
        "source": "webhook_delivery",
        "severity": "medium",
        "occurred_at": occurred_at,
        "last_seen_at": last_seen_at,
        "entity_ref": {"kind": "webhook", "id": row["webhook_id"]},
        "title": f"Webhook delivery dead for {row['webhook_id']}",
        "detail": row.get("last_error") or "",
        "status": status,
        "actions": actions,
    }


def _reconciliation_finding_to_item(
    finding: ReconciliationFinding, state: TriageState | None
) -> dict[str, Any]:
    item_id = f"rc:{finding.dedupe_key}"
    status = state.status if state is not None else "open"
    occurred_at = finding.occurred_at
    last_seen_at = finding.occurred_at
    if state is not None:
        occurred_at = coerce_dt(state.first_seen_at) or finding.occurred_at
        last_seen_at = coerce_dt(state.last_seen_at) or finding.occurred_at
    actions = (
        []
        if status == "resolved"
        else [
            {"action": "acknowledge", "href": f"/v1/ops/exceptions/{item_id}/acknowledge"},
            {"action": "resolve", "href": f"/v1/ops/exceptions/{item_id}/resolve"},
        ]
    )
    return {
        "item_id": item_id,
        "source": "reconciliation",
        "severity": finding.severity,
        "occurred_at": occurred_at,
        "last_seen_at": last_seen_at,
        "entity_ref": {"kind": finding.entity_kind, "id": finding.entity_id},
        "title": finding.title,
        "detail": finding.detail,
        "status": status,
        "actions": actions,
    }


def _gather_exception_items(request: Request) -> tuple[list[dict[str, Any]], str, bool]:
    """Run R1/R2, upsert/auto-resolve the overlay, and assemble every current
    item across all three sources (§4.1), unfiltered — the list and stats
    endpoints both start from this same picture, so counts never drift
    between them within one request. The third element reports whether any
    source read hit its scan cap (S-8)."""
    store = get_control_plane_store(request.app)
    engine = request.app.state.query_engine
    tenant_id = _tenant_id(request)
    catalog = request.app.state.catalog
    order_def = catalog.entities.get("order")
    stage_budgets = (getattr(order_def, "stages", None) or []) if order_def else []
    now = datetime.now(UTC)
    scan_cap = inbox_scan_limit()

    # Source 2: webhook dead deliveries — overlay-backed (§4.1 #2).
    dead_deliveries = store.list_dead_webhook_deliveries(tenant_id, limit=scan_cap + 1)
    webhook_truncated = len(dead_deliveries) > scan_cap
    if webhook_truncated:
        dead_deliveries = dead_deliveries[:scan_cap]
    webhook_seen_ids = [f"wh:{row['webhook_id']}:{row['event_id']}" for row in dead_deliveries]
    for row, item_id in zip(dead_deliveries, webhook_seen_ids, strict=True):
        seen_at = coerce_dt(row.get("updated_at")) or now
        store.upsert_triage_finding(
            item_id=item_id, tenant_id=tenant_id, source="webhook_delivery", seen_at=seen_at
        )
    if not webhook_truncated:
        # A truncated scan cannot prove absence: auto-resolving against an
        # incomplete seen-set would mark still-dead deliveries resolved.
        store.auto_resolve_missing_triage_findings(
            tenant_id=tenant_id,
            source="webhook_delivery",
            seen_item_ids=webhook_seen_ids,
            resolved_at=now,
        )

    # Source 3: reconciliation findings — overlay-backed (§4.1 #3).
    findings = [
        *check_journal_vs_store(engine, tenant_id, stage_budgets),
        *check_stuck_replay(store, tenant_id, older_than_seconds=stuck_replay_threshold_seconds()),
    ]
    reconciliation_seen_ids = [f"rc:{finding.dedupe_key}" for finding in findings]
    for finding, item_id in zip(findings, reconciliation_seen_ids, strict=True):
        store.upsert_triage_finding(
            item_id=item_id,
            tenant_id=tenant_id,
            source="reconciliation",
            seen_at=finding.occurred_at,
        )
    store.auto_resolve_missing_triage_findings(
        tenant_id=tenant_id,
        source="reconciliation",
        seen_item_ids=reconciliation_seen_ids,
        resolved_at=now,
    )

    overlay_states = {
        state.item_id: state for state in store.list_triage_states(tenant_id=tenant_id)
    }

    deadletter_rows = store.list_dead_letter_events_for_inbox(tenant_id, limit=scan_cap + 1)
    deadletter_truncated = len(deadletter_rows) > scan_cap
    if deadletter_truncated:
        deadletter_rows = deadletter_rows[:scan_cap]

    items: list[dict[str, Any]] = [_deadletter_row_to_item(row) for row in deadletter_rows]
    items.extend(
        _webhook_delivery_row_to_item(row, overlay_states.get(item_id), now)
        for row, item_id in zip(dead_deliveries, webhook_seen_ids, strict=True)
    )
    items.extend(
        _reconciliation_finding_to_item(finding, overlay_states.get(item_id))
        for finding, item_id in zip(findings, reconciliation_seen_ids, strict=True)
    )
    return items, tenant_id, webhook_truncated or deadletter_truncated


def _build_exceptions_list_payload(
    request: Request,
    source: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    items, _tenant, scan_truncated = _gather_exception_items(request)

    if source is not None:
        items = [item for item in items if item["source"] == source]
    if status is not None:
        items = [item for item in items if item["status"] == status]
    else:
        # List params default: everything not `resolved` (§4.4).
        items = [item for item in items if item["status"] != "resolved"]

    items.sort(
        key=lambda item: (
            _SEVERITY_RANK.get(item["severity"], 3),
            -item["occurred_at"].timestamp(),
        )
    )

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]

    return {
        "items": page_items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": math.ceil(total / page_size) if total else 0,
        },
        "scan_truncated": scan_truncated,
    }


def _build_exceptions_stats_payload(request: Request) -> dict[str, Any]:
    items, tenant_id, scan_truncated = _gather_exception_items(request)
    store = get_control_plane_store(request.app)
    now = datetime.now(UTC)

    by_source: dict[str, dict[str, int]] = {}
    for item in items:
        source_counts = by_source.setdefault(item["source"], {})
        source_counts[item["status"]] = source_counts.get(item["status"], 0) + 1

    last_24h = sum(1 for item in items if item["occurred_at"] >= now - timedelta(hours=24))
    manual_resolutions = store.count_dead_letter_manual_actions(
        tenant_id
    ) + store.count_triage_manual_actions(tenant_id)

    return {
        "by_source": by_source,
        "last_24h": last_24h,
        "manual_resolutions": manual_resolutions,
        "scan_truncated": scan_truncated,
    }


def _require_exceptions_write_access(request: Request) -> None:
    tenant_key = getattr(request.state, "tenant_key", None)
    if tenant_key is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    if tenant_key.allowed_entity_types is not None:
        raise HTTPException(
            status_code=403,
            detail="This API key has read-only access to exception-inbox operations.",
        )


def _set_exception_state(
    request: Request, item_id: str, status: str, payload: TriageActionRequest | None
) -> TriageActionResponse:
    _require_exceptions_write_access(request)
    if item_id.startswith("dl:"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Dead-letter items are native — use /v1/deadletter/{event_id}/replay "
                "or /dismiss instead of the exception-inbox overlay."
            ),
        )
    store = get_control_plane_store(request.app)
    tenant_id = _tenant_id(request)
    note = payload.note if payload is not None else None
    updated = store.set_triage_state(item_id=item_id, tenant_id=tenant_id, status=status, note=note)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Exception item '{item_id}' not found.")
    return TriageActionResponse(item_id=item_id, status=status)


@router.get("/exceptions", response_model=ExceptionsListResponse)
async def list_exceptions(
    request: Request,
    source: Literal["deadletter", "webhook_delivery", "reconciliation"] | None = Query(
        default=None
    ),
    status: Literal["open", "in_progress", "acknowledged", "resolved"] | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> ExceptionsListResponse:
    payload = await run_in_threadpool(
        _build_exceptions_list_payload, request, source, status, page, page_size
    )
    return ExceptionsListResponse.model_validate(payload)


@router.get("/exceptions/stats", response_model=ExceptionsStatsResponse)
async def exceptions_stats(request: Request) -> ExceptionsStatsResponse:
    payload = await run_in_threadpool(_build_exceptions_stats_payload, request)
    return ExceptionsStatsResponse.model_validate(payload)


@router.post("/exceptions/{item_id}/acknowledge", response_model=TriageActionResponse)
async def acknowledge_exception(
    item_id: str, request: Request, payload: TriageActionRequest | None = None
) -> TriageActionResponse:
    return await run_in_threadpool(_set_exception_state, request, item_id, "acknowledged", payload)


@router.post("/exceptions/{item_id}/resolve", response_model=TriageActionResponse)
async def resolve_exception(
    item_id: str, request: Request, payload: TriageActionRequest | None = None
) -> TriageActionResponse:
    return await run_in_threadpool(_set_exception_state, request, item_id, "resolved", payload)
