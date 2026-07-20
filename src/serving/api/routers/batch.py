import asyncio
import time
from copy import copy
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.serving.api.routers.agent_query import (
    _allowed_tables_for_request,
    _call_in_threadpool_with_kwarg_fallback,
    _ensure_metric_allowed,
)
from src.serving.backends import BackendExecutionError, BackendMissingTableError

logger = structlog.get_logger()
router = APIRouter(tags=["agent"])


def _safe_item_error(exc: Exception, req: Request) -> str:
    """Return a client-safe per-item error string.

    A batch item runs the same entity/metric/NL path as the single-item routes,
    so its failures carry the same raw engine text — directly as a
    ``BackendExecutionError`` or wrapped as ``ValueError(f"... failed: {e}")``.
    Genericise those (log the real text server-side under the correlation id) and
    keep plain validation messages verbatim (pre-pen-test audit, S-2).
    """
    if isinstance(exc, BackendMissingTableError) or isinstance(
        exc.__cause__, BackendMissingTableError
    ):
        # Actionable provisioning signal, kept clean of the scoped-SQL reference
        # (mirrors _client_safe_error).
        return "serving table is not materialized yet — run provisioning"
    if isinstance(exc, BackendExecutionError) or isinstance(exc.__cause__, BackendExecutionError):
        correlation_id = getattr(req.state, "correlation_id", None)
        logger.error("batch_backend_error", detail=str(exc), correlation_id=correlation_id)
        ref = f" (ref {correlation_id})" if correlation_id else ""
        return f"backend query failed{ref}"
    return str(exc)


def _unexpected_outcome_error(outcome: object, req: Request) -> str:
    """Client-safe text for a gather outcome that is not a ``BatchResult``.

    ``_execute_item`` converts every ``Exception`` into a ``BatchResult``
    itself, so anything landing here escaped that controlled path (an
    unexpected ``BaseException`` or a bug). Its text has not been through
    ``_safe_item_error`` and may carry raw engine detail — never echo it to
    the client (S-2 class, audit G-5); log it under the correlation id.
    """
    correlation_id = getattr(req.state, "correlation_id", None)
    logger.error("batch_unexpected_outcome", detail=repr(outcome), correlation_id=correlation_id)
    ref = f" (ref {correlation_id})" if correlation_id else ""
    return f"batch item failed{ref}"


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


def _run_engine_call(engine: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
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
        return BatchResult(id=item.id, status="error", error=_safe_item_error(exc, req))


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

    result = await _call_in_threadpool_with_kwarg_fallback(
        _run_engine_call,
        req.app.state.query_engine,
        "get_entity",
        entity_type,
        entity_id,
        optional_kwargs={"tenant_id": tenant_id},
    )
    if result is None:
        raise LookupError(f"{entity_type}/{entity_id} not found")

    payload = dict(result)
    payload.pop("_last_updated", None)
    return payload


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
    _ensure_metric_allowed(req, metric_name)

    result = await _call_in_threadpool_with_kwarg_fallback(
        _run_engine_call,
        req.app.state.query_engine,
        "get_metric",
        metric_name,
        window,
        optional_kwargs={"tenant_id": tenant_id},
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
    allowed_tables = _allowed_tables_for_request(req)
    result = await _call_in_threadpool_with_kwarg_fallback(
        _run_engine_call,
        req.app.state.query_engine,
        "execute_nl_query",
        question,
        optional_kwargs={"tenant_id": tenant_id, "allowed_tables": allowed_tables},
        context=context,
    )
    # PII deny-gate ran in the engine before execution, so the rows are PII-free
    # for a non-exempt tenant (or this tenant is entitled to them) — return as-is.
    return {
        "answer": result["data"],
        "sql": result.get("sql"),
        "metadata": {
            "rows_returned": result.get("row_count", 0),
            "execution_time_ms": result.get("execution_time_ms", 0),
            "data_freshness_seconds": result.get("freshness_seconds"),
        },
    }


@router.post("/batch", response_model=BatchResponse)
async def batch_query(request: BatchRequest, req: Request) -> BatchResponse:
    # A batch runs one engine op per item but the auth middleware only metered the
    # single HTTP request, so a tenant could drive up to 20x its per-minute budget
    # (concentrated on the expensive NL path) for one token. Charge the remaining
    # items against the same rate-limit bucket and reject the whole batch if the
    # budget cannot absorb them. Skipped when auth is disabled (no tenant_key).
    # (audit S-4)
    tenant_key = getattr(req.state, "tenant_key", None)
    auth_manager = getattr(req.app.state, "auth_manager", None)
    extra_units = len(request.requests) - 1
    if tenant_key is not None and auth_manager is not None and extra_units > 0:
        within_budget = await auth_manager.charge_rate_limit(tenant_key, extra_units)
        if not within_budget:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: a {len(request.requests)}-item batch costs "
                    f"{len(request.requests)} of {tenant_key.rate_limit_rpm} requests/minute."
                ),
            )

    started_at = time.monotonic()
    outcomes = await asyncio.gather(
        *[_execute_item(item, req) for item in request.requests],
        return_exceptions=True,
    )
    results = [
        outcome
        if isinstance(outcome, BatchResult)
        else BatchResult(id=item.id, status="error", error=_unexpected_outcome_error(outcome, req))
        for item, outcome in zip(request.requests, outcomes, strict=False)
    ]
    return BatchResponse(
        results=results,
        duration_ms=(time.monotonic() - started_at) * 1000,
    )
