"""Agent query endpoints — the core API surface for AI agents.

Designed for LLM tool-use: structured inputs, typed outputs, self-describing errors.
Every response includes metadata that helps agents assess data reliability.
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

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
from src.serving.cache import ENTITY_TTL_SECONDS, QueryCache, cache_entity_key
from src.serving.masking import PiiMasker

logger = structlog.get_logger()
tracer = trace.get_tracer("agentflow.api")
router = APIRouter(tags=["agent"])
_PII_MASKER: PiiMasker | None = None


def _get_pii_masker() -> PiiMasker:
    global _PII_MASKER
    config_path = os.getenv("AGENTFLOW_PII_CONFIG", "config/pii_fields.yaml")
    if _PII_MASKER is None or Path(_PII_MASKER.config_path) != Path(config_path):
        _PII_MASKER = PiiMasker(config_path)
    return _PII_MASKER


def _transform_payload_for_requested_version(req: Request, payload: dict) -> dict:
    try:
        requested_version = resolve_request_version(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    registry = get_version_registry(req)
    transformer = get_response_transformer(req)
    return transformer.transform(
        payload,
        from_version=registry.latest().date,
        to_version=requested_version,
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


def _metric_tables(catalog, metric_name: str) -> set[str]:
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


# ── Endpoints ───────────────────────────────────────────────────


@router.post("/query/explain", response_model=ExplainResponse)
async def explain_query(request: ExplainRequest, req: Request):
    """Return the SQL plan for a natural language query without executing it."""
    engine = req.app.state.query_engine
    tenant_key = getattr(req.state, "tenant_key", None)
    tenant_id = getattr(req.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    allowed_tables = _allowed_tables_for_request(req)

    try:
        try:
            result = engine.explain(
                request.question,
                tenant_id=tenant_id,
                allowed_tables=allowed_tables,
            )
        except TypeError as exc:
            if "tenant_id" not in str(exc) and "allowed_tables" not in str(exc):
                raise
            try:
                result = engine.explain(request.question, tenant_id=tenant_id)
            except TypeError as fallback_exc:
                if "tenant_id" not in str(fallback_exc):
                    raise
                result = engine.explain(request.question)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    return ExplainResponse(**result)


@router.post("/query", response_model=QueryResponse)
async def natural_language_query(request: NLQueryRequest, req: Request, response: Response):
    """Execute a natural language query against the data platform.

    The query engine translates natural language to SQL, executes it,
    and returns structured results. Designed for LLM tool-use.

    Example:
        POST /v1/query {"question": "Top 5 products by revenue today"}
    """
    engine = req.app.state.query_engine
    tenant_key = getattr(req.state, "tenant_key", None)
    tenant_id = getattr(req.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    allowed_tables = _allowed_tables_for_request(req)

    with tracer.start_as_current_span("query_engine.translate") as span:
        span.set_attribute("query.text", request.question)
        span.set_attribute(
            "query.engine",
            "claude" if os.getenv("ANTHROPIC_API_KEY") else "rule_based",
        )
        try:
            if hasattr(engine, "paginated_query"):
                try:
                    result = await run_in_threadpool(
                        engine.paginated_query,
                        request.question,
                        limit=request.limit,
                        cursor=request.cursor,
                        context=request.context,
                        tenant_id=tenant_id,
                        allowed_tables=allowed_tables,
                    )
                except TypeError as exc:
                    if "tenant_id" not in str(exc) and "allowed_tables" not in str(exc):
                        raise
                    try:
                        result = await run_in_threadpool(
                            engine.paginated_query,
                            request.question,
                            limit=request.limit,
                            cursor=request.cursor,
                            context=request.context,
                            tenant_id=tenant_id,
                        )
                    except TypeError as fallback_exc:
                        if "tenant_id" not in str(fallback_exc):
                            raise
                        result = await run_in_threadpool(
                            engine.paginated_query,
                            request.question,
                            limit=request.limit,
                            cursor=request.cursor,
                            context=request.context,
                        )
            else:
                try:
                    result = await run_in_threadpool(
                        engine.execute_nl_query,
                        request.question,
                        context=request.context,
                        tenant_id=tenant_id,
                        allowed_tables=allowed_tables,
                    )
                except TypeError as exc:
                    if "tenant_id" not in str(exc) and "allowed_tables" not in str(exc):
                        raise
                    try:
                        result = await run_in_threadpool(
                            engine.execute_nl_query,
                            request.question,
                            context=request.context,
                            tenant_id=tenant_id,
                        )
                    except TypeError as fallback_exc:
                        if "tenant_id" not in str(fallback_exc):
                            raise
                        result = await run_in_threadpool(
                            engine.execute_nl_query,
                            request.question,
                            context=request.context,
                        )
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        if result.get("sql") is not None:
            span.set_attribute("query.sql", result["sql"])
        span.set_attribute("query.rows", int(result.get("row_count", 0)))

    logger.info("nl_query_executed", question=request.question[:100])
    tenant = tenant_id or "default"
    catalog = getattr(req.app.state, "catalog", None)
    table_to_entity = (
        {entity.table: name for name, entity in catalog.entities.items()}
        if catalog is not None
        else {}
    )
    answer, pii_masked = _get_pii_masker().mask_query_results(
        result.get("sql", ""),
        result["data"],
        tenant,
        table_to_entity,
    )
    if pii_masked:
        response.headers["X-PII-Masked"] = "true"

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
):
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

    if as_of is not None:
        as_of = (as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)).astimezone(UTC)
        if as_of > datetime.now(UTC):
            raise HTTPException(
                status_code=422,
                detail="as_of cannot be in the future",
            )

    tenant_key = getattr(req.state, "tenant_key", None)
    tenant_id = getattr(req.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    tenant_context_required = (
        tenant_id is None
        and getattr(getattr(engine, "_tenant_router", None), "has_config", lambda: False)()
    )
    query_cache = getattr(req.app.state, "query_cache", None)
    cache_key = (
        cache_entity_key(tenant_id, entity_type, entity_id)
        if as_of is None and query_cache is not None
        else None
    )
    try:
        if (
            as_of is None
            and not tenant_context_required
            and query_cache is not None
            and cache_key is not None
        ):
            cached = await query_cache.get(cache_key)
            if cached is not None:
                logger.debug("entity_cache_hit", key=cache_key)
                cached_payload = cached.get("payload", cached)
                if cached.get("pii_masked"):
                    response.headers["X-PII-Masked"] = "true"
                response.headers["X-Cache"] = "HIT"
                transformed_payload = _transform_payload_for_requested_version(
                    req,
                    cached_payload,
                )
                return EntityResponse.model_validate(transformed_payload)
        if as_of is not None:
            try:
                result = await run_in_threadpool(
                    engine.get_entity_at,
                    entity_type,
                    entity_id,
                    as_of,
                    tenant_id=tenant_id,
                )
            except TypeError as exc:
                if "tenant_id" not in str(exc):
                    raise
                result = await run_in_threadpool(
                    engine.get_entity_at,
                    entity_type,
                    entity_id,
                    as_of,
                )
        else:
            try:
                result = await run_in_threadpool(
                    engine.get_entity,
                    entity_type,
                    entity_id,
                    tenant_id=tenant_id,
                )
            except TypeError as exc:
                if "tenant_id" not in str(exc):
                    raise
                result = await run_in_threadpool(
                    engine.get_entity,
                    entity_type,
                    entity_id,
                )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None

    if result is None:
        raise HTTPException(status_code=404, detail=f"{entity_type}/{entity_id} not found")

    now = datetime.now(UTC)
    payload = dict(result)
    last_updated = payload.pop("_last_updated", None)
    freshness = None
    if last_updated and as_of is None:
        freshness = (now - datetime.fromisoformat(last_updated)).total_seconds()
    tenant = tenant_id or "default"
    masked_payload = _get_pii_masker().mask(entity_type, payload, tenant)
    pii_masked = masked_payload != payload
    if pii_masked:
        response.headers["X-PII-Masked"] = "true"
    as_of_text = (
        as_of.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if as_of is not None
        else None
    )

    response_payload = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "data": masked_payload,
        "last_updated": last_updated,
        "freshness_seconds": freshness,
        "meta": {
            "as_of": as_of_text,
            "is_historical": as_of is not None,
            "freshness_seconds": None if as_of is not None else freshness,
        },
    }
    if (
        as_of is None
        and not tenant_context_required
        and query_cache is not None
        and cache_key is not None
    ):
        await query_cache.set(
            cache_key,
            {
                "payload": response_payload,
                "pii_masked": pii_masked,
            },
            ttl=ENTITY_TTL_SECONDS,
        )
        response.headers["X-Cache"] = "MISS"
    transformed_payload = _transform_payload_for_requested_version(req, response_payload)
    return EntityResponse.model_validate(transformed_payload)


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
):
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

    if as_of is not None:
        as_of = (as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)).astimezone(UTC)
        if as_of > datetime.now(UTC):
            raise HTTPException(
                status_code=422,
                detail="as_of cannot be in the future",
            )

    as_of_text = (
        as_of.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if as_of is not None
        else None
    )
    try:
        requested_version = resolve_request_version(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    latest_version = get_version_registry(req).latest().date
    tenant_key = getattr(req.state, "tenant_key", None)
    tenant_id = getattr(req.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    tenant_context_required = (
        tenant_id is None
        and getattr(getattr(engine, "_tenant_router", None), "has_config", lambda: False)()
    )
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
        try:
            result = await run_in_threadpool(
                engine.get_metric,
                metric_name,
                window=window,
                as_of=as_of,
                tenant_id=tenant_id,
            )
        except TypeError as exc:
            if "tenant_id" not in str(exc):
                raise
            result = await run_in_threadpool(
                engine.get_metric,
                metric_name,
                window=window,
                as_of=as_of,
            )
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None

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


@router.get("/catalog")
async def get_catalog(req: Request):
    """List all available data assets — entities, metrics, and their schemas.

    Agents should call this to discover what data is available
    before constructing queries.
    """
    catalog = req.app.state.catalog
    return {
        "entities": {
            name: {
                "description": entity.description,
                "fields": entity.fields,
                "primary_key": entity.primary_key,
            }
            for name, entity in catalog.entities.items()
        },
        "metrics": {
            name: {
                "description": metric.description,
                "unit": metric.unit,
                "available_windows": metric.available_windows,
            }
            for name, metric in catalog.metrics.items()
        },
    }
