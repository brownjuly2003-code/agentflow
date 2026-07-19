"""Agent query endpoints — the core API surface for AI agents.

Designed for LLM tool-use: structured inputs, typed outputs, self-describing errors.
Every response includes metadata that helps agents assess data reliability.
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

import sqlglot
import structlog
from fastapi import APIRouter, HTTPException, Query, Request, Response
from opentelemetry import trace
from pydantic import BaseModel, Field
from sqlglot import exp
from starlette.concurrency import run_in_threadpool

from src.serving.api.auth.manager import tenant_key_allowed_tables
from src.serving.api.versioning import (
    get_response_transformer,
    get_version_registry,
    resolve_request_version,
)
from src.serving.backends import BackendExecutionError, BackendMissingTableError
from src.serving.cache import ENTITY_TTL_SECONDS, QueryCache, cache_entity_key
from src.serving.control_plane import get_control_plane_store
from src.serving.semantic_layer.stage_clock import coerce_dt, resolve_breach, stage_budget

logger = structlog.get_logger()
tracer = trace.get_tracer("agentflow.api")
router = APIRouter(tags=["agent"])


def _client_safe_error(exc: ValueError, req: Request, status_code: int) -> HTTPException:
    """Map a query-layer ``ValueError`` to an ``HTTPException`` that never leaks
    engine internals.

    The query helpers catch a ``BackendExecutionError`` (raw ClickHouse/DuckDB
    text — engine type, SQL fragments, table/column names) and re-raise it as
    ``ValueError(f"... failed: {backend_error}")`` with ``from e``. Returning that
    detail verbatim fingerprints the backend to any authenticated caller
    (pre-pen-test audit, S-2). When the cause is a ``BackendExecutionError``, log
    the real text server-side under the correlation id and return a generic
    detail carrying only that id; a plain ``ValueError`` is request-level
    validation (safe and useful to the caller) and is returned verbatim. The
    caller's ``status_code`` is preserved in both branches.
    """
    cause = exc.__cause__
    if isinstance(cause, BackendMissingTableError):
        # A missing serving table is an actionable operator signal (run
        # provisioning), not engine internals — but the upstream message embeds
        # the scoped-SQL table reference, so return a clean fixed detail that
        # keeps the "not materialized" signal without the SQL. `/health/ready`
        # carries the full provisioning hint for operators.
        return HTTPException(
            status_code=status_code,
            detail="serving table is not materialized yet — run provisioning",
        )
    if isinstance(cause, BackendExecutionError):
        correlation_id = getattr(req.state, "correlation_id", None)
        logger.error("backend_execution_error", detail=str(exc), correlation_id=correlation_id)
        ref = f" (ref {correlation_id})" if correlation_id else ""
        return HTTPException(status_code=status_code, detail=f"backend query failed{ref}")
    return HTTPException(status_code=status_code, detail=str(exc))


# Engine call-signature compatibility (F-4): older engine implementations and
# many test fakes predate the ``tenant_id`` / ``allowed_tables`` kwargs. The
# helpers below replace three hand-rolled nested try/except TypeError cascades
# that lived inside the route handlers: kwargs are dropped progressively, and
# a TypeError only triggers the next attempt when its message mentions a kwarg
# of the CURRENT attempt — anything else re-raises immediately so genuine
# engine TypeErrors are never swallowed.
_KWARG_DROP_ORDER = ("allowed_tables", "tenant_id")


def _kwarg_fallback_attempts(optional_kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = [dict(optional_kwargs)]
    remaining = dict(optional_kwargs)
    for name in _KWARG_DROP_ORDER:
        if name in remaining:
            remaining = {key: value for key, value in remaining.items() if key != name}
            attempts.append(dict(remaining))
    return attempts


def _typeerror_mentions_attempt_kwarg(exc: TypeError, attempt_kwargs: dict[str, Any]) -> bool:
    message = str(exc)
    return any(name in message for name in attempt_kwargs)


def _call_with_kwarg_fallback(
    func: Callable[..., Any],
    *args: Any,
    optional_kwargs: dict[str, Any],
    **fixed_kwargs: Any,
) -> Any:
    for attempt in _kwarg_fallback_attempts(optional_kwargs):
        try:
            return func(*args, **fixed_kwargs, **attempt)
        except TypeError as exc:
            if not _typeerror_mentions_attempt_kwarg(exc, attempt):
                raise
    raise RuntimeError("unreachable: the bare attempt either returns or re-raises")


async def _call_in_threadpool_with_kwarg_fallback(
    func: Callable[..., Any],
    *args: Any,
    optional_kwargs: dict[str, Any],
    **fixed_kwargs: Any,
) -> Any:
    for attempt in _kwarg_fallback_attempts(optional_kwargs):
        try:
            return await run_in_threadpool(func, *args, **fixed_kwargs, **attempt)
        except TypeError as exc:
            if not _typeerror_mentions_attempt_kwarg(exc, attempt):
                raise
    raise RuntimeError("unreachable: the bare attempt either returns or re-raises")


def _resolve_tenant_id(req: Request) -> str | None:
    tenant_key = getattr(req.state, "tenant_key", None)
    tenant_id = getattr(req.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    return cast(str | None, tenant_id)


def _tenant_context_required(engine: Any, tenant_id: str | None) -> bool:
    return tenant_id is None and bool(
        getattr(getattr(engine, "_tenant_router", None), "has_config", lambda: False)()
    )


def _normalize_as_of(as_of: datetime | None) -> datetime | None:
    """Coerce a user-supplied as_of to aware-UTC and reject future anchors."""
    if as_of is None:
        return None
    as_of = (as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)).astimezone(UTC)
    if as_of > datetime.now(UTC):
        raise HTTPException(status_code=422, detail="as_of cannot be in the future")
    return as_of


def _as_of_iso_text(as_of: datetime | None) -> str | None:
    if as_of is None:
        return None
    return as_of.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _transform_payload_for_requested_version(
    req: Request, payload: dict[str, Any]
) -> dict[str, Any]:
    try:
        requested_version = resolve_request_version(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    registry = get_version_registry(req)
    transformer = get_response_transformer(req)
    return cast(
        dict[str, Any],
        transformer.transform(
            payload,
            from_version=registry.latest().date,
            to_version=requested_version,
        ),
    )


def _catalog_entity_tables(req: Request) -> dict[str, str]:
    catalog = getattr(req.app.state, "catalog", None)
    if catalog is None:
        catalog = getattr(getattr(req.app.state, "query_engine", None), "catalog", None)
    if catalog is None:
        return {}
    return {name: entity.table for name, entity in catalog.entities.items()}


def _allowed_tables_for_request(req: Request) -> list[str]:
    tenant_key = getattr(req.state, "tenant_key", None)
    tables = tenant_key_allowed_tables(tenant_key, _catalog_entity_tables(req))
    if tenant_key is None or getattr(tenant_key, "allowed_entity_types", None) is None:
        return [*tables, "pipeline_events"]
    return tables


def _metric_tables(catalog: Any, metric_name: str) -> set[str]:
    metric = catalog.metrics.get(metric_name)
    if metric is None:
        return set()
    try:
        parsed = sqlglot.parse_one(
            metric.sql_template.format(window="1 hour"),
            read="duckdb",
        )
    except sqlglot.errors.ParseError:
        return set()
    return {table.name for table in parsed.find_all(exp.Table) if table.name}


def _ensure_metric_allowed(req: Request, metric_name: str) -> None:
    tenant_key = getattr(req.state, "tenant_key", None)
    if tenant_key is None or getattr(tenant_key, "allowed_entity_types", None) is None:
        return
    allowed_tables = set(tenant_key_allowed_tables(tenant_key, _catalog_entity_tables(req)))
    metric_tables = _metric_tables(req.app.state.catalog, metric_name)
    if metric_tables and not metric_tables.issubset(allowed_tables):
        raise HTTPException(
            status_code=403,
            detail=f"API key '{tenant_key.name}' cannot access metric '{metric_name}'.",
        )


# ── Request/Response models ─────────────────────────────────────


class NLQueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        examples=[
            "What is the average order value in the last hour?",
        ],
    )
    context: dict | None = Field(
        default=None, description="Additional context for query generation"
    )
    limit: int = Field(default=100, ge=1, le=1000)
    cursor: str | None = None


class QueryResponse(BaseModel):
    answer: dict | list
    rows: list[dict] = Field(default_factory=list)
    sql: str | None = None
    total_count: int | None = None
    next_cursor: str | None = None
    has_more: bool = False
    page_size: int
    metadata: dict = Field(default_factory=dict)


class ExplainRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        examples=[
            "Top 5 products by revenue today",
        ],
    )


class ExplainResponse(BaseModel):
    question: str
    sql: str
    tables_accessed: list[str]
    estimated_rows: int | None = None
    engine: Literal["llm", "rule_based"]
    warning: str | None = None


class EntityResponse(BaseModel):
    entity_type: str
    entity_id: str
    data: dict
    last_updated: datetime | None = None
    freshness_seconds: float | None = None
    meta: dict = Field(default_factory=dict)


class MetricResponse(BaseModel):
    metric_name: str
    value: float
    unit: str
    window: str
    computed_at: datetime
    components: dict | None = None
    meta: dict = Field(default_factory=dict)


# ── Order 360 timeline models (ops-surfaces-spec.md §2.2) ────────
# The customer block is a fixed field allow-list — the users_enriched
# columns, PII-free by construction (spec invariant I3). No literal stage
# name or SLA budget appears below (invariant I2): sla_minutes/breached
# come only from the catalog's optional `stages` field, null until that
# field exists (D3, ops-surfaces-spec.md §1.5).


class OrderTimelineOrder(BaseModel):
    order_id: str
    user_id: str | None = None
    status: str | None = None
    total_amount: float | None = None
    currency: str | None = None
    created_at: datetime | None = None


class OrderTimelineStage(BaseModel):
    current: str | None = None
    entered_at: datetime | None = None
    in_stage_seconds: float | None = None
    sla_minutes: int | None = None
    breached: bool | None = None
    clock: Literal["journal", "fallback"]


class OrderTimelineStageHistoryItem(BaseModel):
    status: str
    at: datetime | None = None


class OrderTimelinePipelineTrailItem(BaseModel):
    event_id: str | None = None
    topic: str | None = None
    event_type: str | None = None
    latency_ms: float | None = None
    processed_at: datetime | None = None


class OrderTimelineCustomer(BaseModel):
    user_id: str
    total_orders: int | None = None
    total_spent: float | None = None
    first_order_at: datetime | None = None
    last_order_at: datetime | None = None
    preferred_category: str | None = None


class OrderTimelineExceptionActions(BaseModel):
    replay: str
    dismiss: str


class OrderTimelineException(BaseModel):
    event_id: str
    failure_reason: str | None = None
    status: str
    occurred_at: datetime | None = None
    actions: OrderTimelineExceptionActions


class OrderTimelineResponse(BaseModel):
    order: OrderTimelineOrder
    stage: OrderTimelineStage
    stage_history: list[OrderTimelineStageHistoryItem] = Field(default_factory=list)
    pipeline_trail: list[OrderTimelinePipelineTrailItem] = Field(default_factory=list)
    customer: OrderTimelineCustomer | None = None
    exceptions: list[OrderTimelineException] = Field(default_factory=list)


_ORDER_TIMELINE_ORDER_FIELDS = (
    "order_id",
    "user_id",
    "status",
    "total_amount",
    "currency",
    "created_at",
)
_ORDER_TIMELINE_CUSTOMER_FIELDS = (
    "user_id",
    "total_orders",
    "total_spent",
    "first_order_at",
    "last_order_at",
    "preferred_category",
)


def _build_order_timeline(request: Request, order_id: str) -> dict[str, Any] | None:
    """Sync composition for GET /entity/order/{order_id}/timeline.

    Runs on a worker thread (the route offloads it, matching lineage.py /
    deadletter.py). Composes exactly the two ops-layer ports per ADR 0011:
    QueryEngine for the order row, the journal, and the customer projection;
    ControlPlaneStore for dead-letter exception detail. No raw connection, no
    vault DSN (invariant I1).
    """
    engine = request.app.state.query_engine
    tenant_id = _resolve_tenant_id(request)
    store_tenant_id = tenant_id or "default"

    order_row = engine.get_entity("order", order_id, tenant_id=tenant_id)
    if order_row is None:
        return None
    order_row = dict(order_row)

    journal_rows = engine.fetch_pipeline_events(
        tenant_id=tenant_id, entity_id=order_id, newest_first=False
    )
    stage_rows = [row for row in journal_rows if row.get("topic") == "orders.status"]
    trail_rows = [row for row in journal_rows if row.get("topic") != "orders.status"]

    stage_history = [
        {
            "status": str(row["event_type"]).removeprefix("order.status."),
            "at": row.get("processed_at"),
        }
        for row in stage_rows
        if row.get("event_type")
    ]

    current_status = order_row.get("status")
    catalog = request.app.state.catalog
    order_def = catalog.entities.get("order")
    stage_budgets = (getattr(order_def, "stages", None) or []) if order_def else []
    budget = stage_budget(stage_budgets, current_status)

    entered_at = None
    clock = "fallback"
    target_event_type = f"order.status.{current_status}"
    store_backend = getattr(engine, "_backend_name", None)
    for row in reversed(stage_rows):
        if row.get("event_type") == target_event_type:
            entered_at = coerce_dt(row.get("processed_at"), backend_name=store_backend)
            clock = "journal"
            break
    if entered_at is None:
        entered_at = coerce_dt(order_row.get("created_at"), backend_name=store_backend)

    in_stage_seconds, sla_minutes, breached = resolve_breach(entered_at=entered_at, budget=budget)

    customer = None
    user_id = order_row.get("user_id")
    if user_id:
        try:
            user_row = engine.get_entity("user", str(user_id), tenant_id=tenant_id)
        except ValueError:
            # users_enriched not materialized for this tenant/profile — the
            # customer block is "null when absent" (spec §2.1), not a 503 for
            # the whole timeline; the order/stage/trail data is still good.
            user_row = None
        if user_row is not None:
            customer = {field: user_row.get(field) for field in _ORDER_TIMELINE_CUSTOMER_FIELDS}

    store = get_control_plane_store(request.app)
    exceptions = []
    for row in trail_rows:
        if row.get("topic") != "events.deadletter":
            continue
        event_id = row.get("event_id")
        if not event_id:
            continue
        detail = store.get_dead_letter_event(str(event_id), store_tenant_id)
        if detail is None:
            continue
        exceptions.append(
            {
                "event_id": detail["event_id"],
                "failure_reason": detail.get("failure_reason"),
                "status": detail["status"],
                "occurred_at": detail.get("received_at"),
                "actions": {
                    "replay": f"/v1/deadletter/{detail['event_id']}/replay",
                    "dismiss": f"/v1/deadletter/{detail['event_id']}/dismiss",
                },
            }
        )

    return {
        "order": {field: order_row.get(field) for field in _ORDER_TIMELINE_ORDER_FIELDS},
        "stage": {
            "current": current_status,
            "entered_at": entered_at,
            "in_stage_seconds": in_stage_seconds,
            "sla_minutes": sla_minutes,
            "breached": breached,
            "clock": clock,
        },
        "stage_history": stage_history,
        "pipeline_trail": [
            {
                "event_id": row.get("event_id"),
                "topic": row.get("topic"),
                "event_type": row.get("event_type"),
                "latency_ms": row.get("latency_ms"),
                "processed_at": row.get("processed_at"),
            }
            for row in trail_rows
        ],
        "customer": customer,
        "exceptions": exceptions,
    }


# ── Endpoints ───────────────────────────────────────────────────


@router.post("/query/explain", response_model=ExplainResponse)
async def explain_query(request: ExplainRequest, req: Request) -> ExplainResponse:
    """Return the SQL plan for a natural language query without executing it."""
    engine = req.app.state.query_engine
    tenant_id = _resolve_tenant_id(req)
    allowed_tables = _allowed_tables_for_request(req)

    try:
        result = _call_with_kwarg_fallback(
            engine.explain,
            request.question,
            optional_kwargs={"tenant_id": tenant_id, "allowed_tables": allowed_tables},
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return ExplainResponse(**result)


@router.post("/query", response_model=QueryResponse)
async def natural_language_query(request: NLQueryRequest, req: Request) -> QueryResponse:
    """Execute a natural language query against the data platform.

    The query engine translates natural language to SQL, executes it,
    and returns structured results. Designed for LLM tool-use.

    Example:
        POST /v1/query {"question": "Top 5 products by revenue today"}
    """
    engine = req.app.state.query_engine
    tenant_id = _resolve_tenant_id(req)
    allowed_tables = _allowed_tables_for_request(req)

    with tracer.start_as_current_span("query_engine.translate") as span:
        span.set_attribute("query.text", request.question)
        span.set_attribute(
            "query.engine",
            "gracekelly" if os.getenv("GRACEKELLY_URL") else "rule_based",
        )
        optional_kwargs = {"tenant_id": tenant_id, "allowed_tables": allowed_tables}
        try:
            if hasattr(engine, "paginated_query"):
                result = await _call_in_threadpool_with_kwarg_fallback(
                    engine.paginated_query,
                    request.question,
                    optional_kwargs=optional_kwargs,
                    limit=request.limit,
                    cursor=request.cursor,
                    context=request.context,
                )
            else:
                result = await _call_in_threadpool_with_kwarg_fallback(
                    engine.execute_nl_query,
                    request.question,
                    optional_kwargs=optional_kwargs,
                    context=request.context,
                )
        except HTTPException:
            raise
        except ValueError as e:
            raise _client_safe_error(e, req, status_code=400) from None
        if result.get("sql") is not None:
            span.set_attribute("query.sql", result["sql"])
        span.set_attribute("query.rows", int(result.get("row_count", 0)))

    logger.info("nl_query_executed", question=request.question[:100])
    # The serving warehouse holds no PII: users_enriched/orders_v2 carry only
    # analytics columns (aggregates, ids), so query rows are returned as-is.
    # Raw contact PII lives in the DV2 vault and is governed engine-side there
    # (ClickHouse row/column policies) — not in this serving path. See ADR 0006.
    answer = result["data"]
    rows = answer if isinstance(answer, list) else [answer]

    return QueryResponse(
        answer=answer,
        rows=rows,
        sql=result.get("sql"),
        total_count=result.get("total_count"),
        next_cursor=result.get("next_cursor"),
        has_more=bool(result.get("has_more")),
        page_size=int(result.get("page_size", request.limit)),
        metadata={
            "rows_returned": result.get("row_count", 0),
            "execution_time_ms": result.get("execution_time_ms", 0),
            "data_freshness_seconds": result.get("freshness_seconds"),
            "total_count": result.get("total_count"),
            "next_cursor": result.get("next_cursor"),
            "has_more": bool(result.get("has_more")),
            "page_size": int(result.get("page_size", request.limit)),
        },
    )


@router.get("/entity/{entity_type}/{entity_id}", response_model=EntityResponse)
async def get_entity(
    entity_type: str,
    entity_id: str,
    req: Request,
    response: Response,
    as_of: Annotated[
        datetime | None,
        Query(
            description="Return state as of this UTC timestamp (ISO 8601)",
        ),
    ] = None,
) -> EntityResponse:
    """Look up a specific entity by type and ID.

    Supported entity types: order, user, product, session.
    Returns the latest known state of the entity.

    Example:
        GET /v1/entity/order/ORD-20260401-7829
    """
    engine = req.app.state.query_engine
    catalog = req.app.state.catalog

    if entity_type not in catalog.entities:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown entity type: {entity_type}. "
            f"Available: {list(catalog.entities.keys())}",
        )

    as_of = _normalize_as_of(as_of)
    tenant_id = _resolve_tenant_id(req)
    tenant_context_required = _tenant_context_required(engine, tenant_id)
    query_cache = getattr(req.app.state, "query_cache", None)
    # (cache, key) pair, present only when the entity cache is usable for
    # this request: latest-state lookup, cache configured, tenant resolved.
    entity_cache: tuple[Any, str] | None = None
    if as_of is None and query_cache is not None and not tenant_context_required:
        entity_cache = (query_cache, cache_entity_key(tenant_id, entity_type, entity_id))
    try:
        if entity_cache is not None:
            cache, cache_key = entity_cache
            cached = await cache.get(cache_key)
            if cached is not None:
                logger.debug("entity_cache_hit", key=cache_key)
                cached_payload = cached.get("payload", cached)
                response.headers["X-Cache"] = "HIT"
                transformed_payload = _transform_payload_for_requested_version(
                    req,
                    cached_payload,
                )
                return EntityResponse.model_validate(transformed_payload)
        if as_of is not None:
            result = await _call_in_threadpool_with_kwarg_fallback(
                engine.get_entity_at,
                entity_type,
                entity_id,
                as_of,
                optional_kwargs={"tenant_id": tenant_id},
            )
        else:
            result = await _call_in_threadpool_with_kwarg_fallback(
                engine.get_entity,
                entity_type,
                entity_id,
                optional_kwargs={"tenant_id": tenant_id},
            )
    except ValueError as e:
        raise _client_safe_error(e, req, status_code=503) from None

    if result is None:
        raise HTTPException(status_code=404, detail=f"{entity_type}/{entity_id} not found")

    now = datetime.now(UTC)
    payload = dict(result)
    last_updated = payload.pop("_last_updated", None)
    freshness = None
    if last_updated and as_of is None:
        freshness = (now - datetime.fromisoformat(last_updated)).total_seconds()
    as_of_text = _as_of_iso_text(as_of)

    response_payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "data": payload,
        "last_updated": last_updated,
        "freshness_seconds": freshness,
        "meta": {
            "as_of": as_of_text,
            "is_historical": as_of is not None,
            "freshness_seconds": None if as_of is not None else freshness,
        },
    }
    if entity_cache is not None:
        cache, cache_key = entity_cache
        await cache.set(
            cache_key,
            {"payload": response_payload},
            ttl=ENTITY_TTL_SECONDS,
        )
        response.headers["X-Cache"] = "MISS"
    transformed_payload = _transform_payload_for_requested_version(req, response_payload)
    return EntityResponse.model_validate(transformed_payload)


@router.get("/entity/order/{order_id}/timeline", response_model=OrderTimelineResponse)
async def get_order_timeline(order_id: str, req: Request) -> OrderTimelineResponse:
    """Order 360: order state, stage history, pipeline trail, customer block,
    and linked exceptions — one composed read (ops-surfaces-spec.md §2).

    Same tenant scoping and 404 semantics as GET /entity/order/{order_id}.
    Not cached: this is the "now" surface (ADR 0011 constraint 3, spec §1.8).

    Example:
        GET /v1/entity/order/ORD-20260404-1001/timeline
    """
    catalog = req.app.state.catalog
    if "order" not in catalog.entities:
        raise HTTPException(status_code=404, detail="Unknown entity type: order")

    try:
        payload = await run_in_threadpool(_build_order_timeline, req, order_id)
    except ValueError as e:
        raise _client_safe_error(e, req, status_code=503) from None

    if payload is None:
        raise HTTPException(status_code=404, detail=f"order/{order_id} not found")

    return OrderTimelineResponse.model_validate(payload)


@router.get("/metrics/{metric_name}", response_model=MetricResponse)
async def get_metric(
    metric_name: str,
    req: Request,
    response: Response,
    window: str = "1h",
    as_of: Annotated[
        datetime | None,
        Query(
            description="Compute the metric at this UTC timestamp (ISO 8601)",
        ),
    ] = None,
) -> MetricResponse:
    """Get a real-time metric value.

    Supported metrics: revenue, order_count, avg_order_value, conversion_rate,
    active_sessions, error_rate.

    Window options: 5m, 15m, 1h, 6h, 24h.

    Example:
        GET /v1/metrics/revenue?window=1h
    """
    engine = req.app.state.query_engine
    catalog = req.app.state.catalog

    if metric_name not in catalog.metrics:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown metric: {metric_name}. Available: {list(catalog.metrics.keys())}",
        )
    _ensure_metric_allowed(req, metric_name)

    # Reject windows the metric doesn't declare. The engine silently maps an
    # unknown window to "1 hour" (and active_sessions ignores it entirely), so
    # without this the response would echo the *requested* window while
    # returning a *different* window's value, and each bogus window string would
    # pollute the metric cache. Mirrors the alerts router. (audit_30_06_26.md A1)
    available_windows = catalog.metrics[metric_name].available_windows
    if window not in available_windows:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported window '{window}' for metric '{metric_name}'. "
                f"Available: {available_windows}"
            ),
        )

    as_of = _normalize_as_of(as_of)
    as_of_text = _as_of_iso_text(as_of)
    try:
        requested_version = resolve_request_version(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    latest_version = get_version_registry(req).latest().date
    tenant_id = _resolve_tenant_id(req)
    tenant_context_required = _tenant_context_required(engine, tenant_id)
    query_cache = getattr(req.app.state, "query_cache", None)
    cache_key = (
        QueryCache.metric_key(
            metric_name,
            window,
            as_of_text,
            tenant=tenant_id,
            version=requested_version if requested_version != latest_version else None,
        )
        if query_cache is not None
        else None
    )
    if not tenant_context_required and query_cache is not None and cache_key is not None:
        cached = await query_cache.get(cache_key)
        if cached is not None:
            logger.debug("metric_cache_hit", key=cache_key)
            response.headers["X-Cache"] = "HIT"
            return MetricResponse.model_validate(cached)

    try:
        result = await _call_in_threadpool_with_kwarg_fallback(
            engine.get_metric,
            metric_name,
            optional_kwargs={"tenant_id": tenant_id},
            window=window,
            as_of=as_of,
        )
    except ValueError as e:
        raise _client_safe_error(e, req, status_code=503) from None

    metric_payload = {
        "metric_name": metric_name,
        "value": result["value"],
        "unit": result["unit"],
        "window": window,
        "computed_at": datetime.now(UTC),
        "components": result.get("components"),
        "meta": {
            "as_of": as_of_text,
            "is_historical": as_of is not None,
            "freshness_seconds": None,
        },
    }
    transformed_payload = _transform_payload_for_requested_version(req, metric_payload)
    metric_response = MetricResponse.model_validate(transformed_payload)
    if not tenant_context_required and query_cache is not None and cache_key is not None:
        await query_cache.set(
            cache_key,
            metric_response.model_dump(mode="json"),
            ttl=getattr(req.app.state, "cache_ttl_seconds", 30),
        )
    response.headers["X-Cache"] = "MISS"
    return metric_response


# NOTE: /catalog deliberately does NOT live on this router. The production
# handler is main.py's richer /v1/catalog (contract_version + streaming/audit
# sources); an earlier duplicate here forced main.py to strip it from the
# shared router at import time, which made router state order-dependent
# (BACKLOG #26). tests/unit/test_catalog_lineage.py pins the route's absence.
