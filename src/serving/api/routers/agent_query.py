"""Agent query endpoints — the core API surface for AI agents.

Designed for LLM tool-use: structured inputs, typed outputs, self-describing errors.
Every response includes metadata that helps agents assess data reliability.
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = structlog.get_logger()
router = APIRouter(tags=["agent"])


# ── Request/Response models ─────────────────────────────────────


class NLQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000, examples=[
        "What is the average order value in the last hour?",
    ])
    context: dict | None = Field(
        default=None, description="Additional context for query generation"
    )


class QueryResponse(BaseModel):
    answer: dict | list
    sql: str | None = None
    metadata: dict = Field(default_factory=dict)


class EntityResponse(BaseModel):
    entity_type: str
    entity_id: str
    data: dict
    last_updated: datetime | None = None
    freshness_seconds: float | None = None


class MetricResponse(BaseModel):
    metric_name: str
    value: float
    unit: str
    window: str
    computed_at: datetime
    components: dict | None = None


# ── Endpoints ───────────────────────────────────────────────────


@router.post("/query", response_model=QueryResponse)
async def natural_language_query(request: NLQueryRequest, req: Request):
    """Execute a natural language query against the data platform.

    The query engine translates natural language to SQL, executes it,
    and returns structured results. Designed for LLM tool-use.

    Example:
        POST /v1/query {"question": "Top 5 products by revenue today"}
    """
    engine = req.app.state.query_engine

    try:
        result = engine.execute_nl_query(request.question, context=request.context)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    logger.info("nl_query_executed", question=request.question[:100])

    return QueryResponse(
        answer=result["data"],
        sql=result.get("sql"),
        metadata={
            "rows_returned": result.get("row_count", 0),
            "execution_time_ms": result.get("execution_time_ms", 0),
            "data_freshness_seconds": result.get("freshness_seconds"),
        },
    )


@router.get("/entity/{entity_type}/{entity_id}", response_model=EntityResponse)
async def get_entity(entity_type: str, entity_id: str, req: Request):
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

    try:
        result = engine.get_entity(entity_type, entity_id)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None

    if result is None:
        raise HTTPException(
            status_code=404, detail=f"{entity_type}/{entity_id} not found"
        )

    now = datetime.now(UTC)
    last_updated = result.get("_last_updated")
    freshness = None
    if last_updated:
        freshness = (now - datetime.fromisoformat(last_updated)).total_seconds()

    return EntityResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        data=result,
        last_updated=last_updated,
        freshness_seconds=freshness,
    )


@router.get("/metrics/{metric_name}", response_model=MetricResponse)
async def get_metric(metric_name: str, req: Request, window: str = "1h"):
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

    try:
        result = engine.get_metric(metric_name, window=window)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from None

    return MetricResponse(
        metric_name=metric_name,
        value=result["value"],
        unit=result["unit"],
        window=window,
        computed_at=datetime.now(UTC),
        components=result.get("components"),
    )


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
