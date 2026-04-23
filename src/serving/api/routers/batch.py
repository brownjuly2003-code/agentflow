import asyncio
import time
from copy import copy
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.serving.api.routers.agent_query import _get_pii_masker

router = APIRouter(tags=["agent"])


class BatchItem(BaseModel):
    id: str
    type: Literal["entity", "metric", "query"]
    params: dict[str, Any] = Field(default_factory=dict)


class BatchRequest(BaseModel):
    requests: list[BatchItem] = Field(..., max_length=20)


class BatchResult(BaseModel):
    id: str
    status: Literal["ok", "error"]
    data: dict[str, Any] | None = None
    error: str | None = None


class BatchResponse(BaseModel):
    results: list[BatchResult]
    duration_ms: float


def _run_engine_call(engine, method_name: str, *args, **kwargs):
    worker_engine = copy(engine)
    worker_engine._conn = engine._conn.cursor()
    try:
        method = getattr(worker_engine, method_name)
        return method(*args, **kwargs)
    finally:
        worker_engine._conn.close()


async def _execute_item(item: BatchItem, req: Request) -> BatchResult:
    try:
        if item.type == "entity":
            data = await _execute_entity_item(item, req)
        elif item.type == "metric":
            data = await _execute_metric_item(item, req)
        else:
            data = await _execute_query_item(item, req)
        return BatchResult(id=item.id, status="ok", data=data)
    except Exception as exc:
        return BatchResult(id=item.id, status="error", error=str(exc))


async def _execute_entity_item(item: BatchItem, req: Request) -> dict[str, Any]:
    entity_type = item.params.get("entity_type")
    entity_id = item.params.get("entity_id")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        raise ValueError("Entity batch item requires string params 'entity_type' and 'entity_id'.")

    catalog = req.app.state.catalog
    if entity_type not in catalog.entities:
        raise ValueError(
            f"Unknown entity type: {entity_type}. Available: {list(catalog.entities.keys())}"
        )

    tenant_key = getattr(req.state, "tenant_key", None)
    tenant_id = getattr(req.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    auth_manager = getattr(req.app.state, "auth_manager", None)
    if (
        tenant_key is not None
        and auth_manager is not None
        and not auth_manager.is_entity_allowed(tenant_key, entity_type)
    ):
        raise PermissionError(
            f"API key '{tenant_key.name}' cannot access entity type '{entity_type}'."
        )

    try:
        result = await run_in_threadpool(
            _run_engine_call,
            req.app.state.query_engine,
            "get_entity",
            entity_type,
            entity_id,
            tenant_id=tenant_id,
        )
    except TypeError as exc:
        if "tenant_id" not in str(exc):
            raise
        result = await run_in_threadpool(
            _run_engine_call,
            req.app.state.query_engine,
            "get_entity",
            entity_type,
            entity_id,
        )
    if result is None:
        raise LookupError(f"{entity_type}/{entity_id} not found")

    payload = dict(result)
    payload.pop("_last_updated", None)
    return _get_pii_masker().mask(entity_type, payload, tenant_id or "default")


async def _execute_metric_item(item: BatchItem, req: Request) -> dict[str, Any]:
    metric_name = item.params.get("name")
    window = item.params.get("window", "1h")
    if not isinstance(metric_name, str) or not isinstance(window, str):
        raise ValueError("Metric batch item requires string params 'name' and 'window'.")

    catalog = req.app.state.catalog
    tenant_key = getattr(req.state, "tenant_key", None)
    tenant_id = getattr(req.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    if metric_name not in catalog.metrics:
        raise ValueError(
            f"Unknown metric: {metric_name}. Available: {list(catalog.metrics.keys())}"
        )

    try:
        result = await run_in_threadpool(
            _run_engine_call,
            req.app.state.query_engine,
            "get_metric",
            metric_name,
            window,
            tenant_id=tenant_id,
        )
    except TypeError as exc:
        if "tenant_id" not in str(exc):
            raise
        result = await run_in_threadpool(
            _run_engine_call,
            req.app.state.query_engine,
            "get_metric",
            metric_name,
            window,
        )
    return dict(result)


async def _execute_query_item(item: BatchItem, req: Request) -> dict[str, Any]:
    question = item.params.get("question")
    context = item.params.get("context")
    if not isinstance(question, str):
        raise ValueError("Query batch item requires string param 'question'.")
    if context is not None and not isinstance(context, dict):
        raise ValueError("Query batch item param 'context' must be an object.")

    tenant_key = getattr(req.state, "tenant_key", None)
    tenant_id = getattr(req.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)
    try:
        result = await run_in_threadpool(
            _run_engine_call,
            req.app.state.query_engine,
            "execute_nl_query",
            question,
            context=context,
            tenant_id=tenant_id,
        )
    except TypeError as exc:
        if "tenant_id" not in str(exc):
            raise
        result = await run_in_threadpool(
            _run_engine_call,
            req.app.state.query_engine,
            "execute_nl_query",
            question,
            context=context,
        )
    table_to_entity = {
        entity.table: name for name, entity in req.app.state.catalog.entities.items()
    }
    answer, _ = _get_pii_masker().mask_query_results(
        result.get("sql", ""),
        result["data"],
        tenant_id or "default",
        table_to_entity,
    )
    return {
        "answer": answer,
        "sql": result.get("sql"),
        "metadata": {
            "rows_returned": result.get("row_count", 0),
            "execution_time_ms": result.get("execution_time_ms", 0),
            "data_freshness_seconds": result.get("freshness_seconds"),
        },
    }


@router.post("/batch", response_model=BatchResponse)
async def batch_query(request: BatchRequest, req: Request):
    started_at = time.monotonic()
    outcomes = await asyncio.gather(
        *[_execute_item(item, req) for item in request.requests],
        return_exceptions=True,
    )
    results = [
        outcome
        if isinstance(outcome, BatchResult)
        else BatchResult(id=item.id, status="error", error=str(outcome))
        for item, outcome in zip(request.requests, outcomes, strict=False)
    ]
    return BatchResponse(
        results=results,
        duration_ms=(time.monotonic() - started_at) * 1000,
    )
