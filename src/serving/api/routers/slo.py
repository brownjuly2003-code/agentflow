from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src.serving.semantic_layer.journal import JournalReader

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

router = APIRouter(prefix="/v1/slo", tags=["slo"])

DEFAULT_SLO_CONFIG_PATH = Path(os.getenv("AGENTFLOW_SLO_FILE", "config/slo.yaml"))


class SLODefinition(BaseModel):
    name: str
    description: str
    target: float
    measurement: str
    threshold: float
    window_days: int


class SLOConfig(BaseModel):
    slos: list[SLODefinition] = Field(default_factory=list)


class SLOStatus(BaseModel):
    name: str
    target: float
    current: float
    error_budget_remaining: float
    status: Literal["healthy", "at_risk", "breached"]
    window_days: int


class SLOResponse(BaseModel):
    slos: list[SLOStatus]


def get_slo_config_path(app: FastAPI) -> Path:
    configured = getattr(app.state, "slo_config_path", None)
    return Path(configured) if configured else DEFAULT_SLO_CONFIG_PATH


def load_slos(path: Path) -> list[SLODefinition]:
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"SLO config '{path}' was not found.")
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return []
    data = yaml.safe_load(raw) if yaml is not None else json.loads(raw)
    return SLOConfig.model_validate(data or {}).slos


def _tenant_id(request: Request) -> str | None:
    tenant_key = getattr(request.state, "tenant_key", None)
    return getattr(request.state, "tenant_id", None) or getattr(tenant_key, "tenant", None)


def _measurement_value(
    journal: JournalReader,
    definition: SLODefinition,
    tenant_id: str | None,
) -> float | None:
    window = f"{definition.window_days} days"

    if definition.measurement == "p95_latency_ms":
        return journal.latency_quantile_ms(quantile=0.95, window=window, tenant_id=tenant_id)

    if definition.measurement == "freshness_seconds":
        # Against the store's own clock: the two stores keep journal timestamps
        # in different zones, so only the store can say how old its newest row
        # is (see semantic_layer/journal.py).
        return journal.freshness(window=window, tenant_id=tenant_id).age_seconds

    if definition.measurement == "error_rate_percent":
        counts = journal.event_counts(window=window, tenant_id=tenant_id)
        if counts is None or counts.total == 0:
            return None
        return (counts.errors / counts.total) * 100.0

    raise HTTPException(
        status_code=500,
        detail=f"Unsupported SLO measurement '{definition.measurement}'.",
    )


def _current_compliance(definition: SLODefinition, measured: float | None) -> float:
    if measured is None:
        return 0.0
    if definition.measurement == "error_rate_percent":
        return max(0.0, min(1.0, 1.0 - (measured / 100.0)))
    if measured <= definition.threshold:
        return 1.0
    return max(0.0, min(1.0, definition.threshold / measured))


def _error_budget_remaining(target: float, current: float) -> float:
    if target >= 1.0:
        return 1.0 if current >= 1.0 else 0.0
    budget = 1.0 - target
    consumed = (1.0 - current) / budget
    return max(0.0, min(1.0, 1.0 - consumed))


def _compute_slo_statuses(request: Request, definitions: list[SLODefinition]) -> list[SLOStatus]:
    # Runs on a worker thread (get_slos offloads it) so the per-SLO aggregate
    # scans can't block the event loop for every tenant on the worker.
    # (audit_30_06_26.md A2)
    #
    # Every aggregate goes through the active backend. These ran on a private
    # DuckDB cursor, so a ClickHouse deployment computed its SLOs — and its
    # error budget — from an embedded store nothing was writing to (audit P0-3).
    journal = request.app.state.query_engine.journal
    tenant_id = _tenant_id(request)
    statuses = []

    for definition in definitions:
        current = round(
            _current_compliance(
                definition,
                _measurement_value(journal, definition, tenant_id),
            ),
            4,
        )
        error_budget_remaining = round(
            _error_budget_remaining(definition.target, current),
            4,
        )
        status: Literal["healthy", "at_risk", "breached"]
        if current < definition.target:
            status = "breached"
        elif error_budget_remaining < 0.2:
            status = "at_risk"
        else:
            status = "healthy"
        statuses.append(
            SLOStatus(
                name=definition.name,
                target=definition.target,
                current=current,
                error_budget_remaining=error_budget_remaining,
                status=status,
                window_days=definition.window_days,
            )
        )

    return statuses


@router.get("", response_model=SLOResponse)
async def get_slos(request: Request) -> SLOResponse:
    definitions = load_slos(get_slo_config_path(request.app))
    statuses = await run_in_threadpool(_compute_slo_statuses, request, definitions)
    return SLOResponse(slos=statuses)
