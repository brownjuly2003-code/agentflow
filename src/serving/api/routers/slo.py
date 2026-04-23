from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None

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


def get_slo_config_path(app) -> Path:
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


def _pipeline_event_columns(request: Request) -> set[str]:
    conn = request.app.state.query_engine._conn
    return {row[1] for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()}


def _time_column(columns: set[str]) -> str | None:
    if "processed_at" in columns:
        return "processed_at"
    if "created_at" in columns:
        return "created_at"
    return None


def _measurement_value(
    request: Request,
    definition: SLODefinition,
    columns: set[str],
    time_column: str | None,
) -> float | None:
    if time_column is None:
        return None

    conn = request.app.state.query_engine._conn
    window = f"{definition.window_days} days"

    if definition.measurement == "p95_latency_ms":
        if "latency_ms" not in columns:
            return None
        row = conn.execute(
            (
                "SELECT quantile_cont(latency_ms, 0.95) "  # nosec B608 - time_column is chosen from the fixed pipeline_events allowlist
                "FROM pipeline_events "
                f"WHERE {time_column} >= NOW() - CAST(? AS INTERVAL) "
                "AND latency_ms IS NOT NULL"
            ),
            [window],
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    if definition.measurement == "freshness_seconds":
        row = conn.execute(
            (
                f"SELECT MAX({time_column}) "  # nosec B608 - time_column is chosen from the fixed pipeline_events allowlist
                "FROM pipeline_events "
                f"WHERE {time_column} >= NOW() - CAST(? AS INTERVAL)"
            ),
            [window],
        ).fetchone()
        if not row or row[0] is None:
            return None
        age = conn.execute(
            "SELECT EXTRACT(EPOCH FROM (NOW() - CAST(? AS TIMESTAMP)))",
            [row[0]],
        ).fetchone()
        return float(age[0]) if age and age[0] is not None else None

    if definition.measurement == "error_rate_percent":
        if "status_code" in columns:
            row = conn.execute(
                (
                    "SELECT "  # nosec B608 - time_column is chosen from the fixed pipeline_events allowlist
                    "COUNT(*) FILTER (WHERE status_code IS NOT NULL), "
                    "COUNT(*) FILTER (WHERE status_code >= 500) "
                    "FROM pipeline_events "
                    f"WHERE {time_column} >= NOW() - CAST(? AS INTERVAL)"
                ),
                [window],
            ).fetchone()
            total = int(row[0]) if row and row[0] is not None else 0
            errors = int(row[1]) if row and row[1] is not None else 0
            if total > 0:
                return (errors / total) * 100.0

        row = conn.execute(
            (
                "SELECT COUNT(*), "  # nosec B608 - time_column is chosen from the fixed pipeline_events allowlist
                "COUNT(*) FILTER (WHERE topic = 'events.deadletter') "
                "FROM pipeline_events "
                f"WHERE {time_column} >= NOW() - CAST(? AS INTERVAL)"
            ),
            [window],
        ).fetchone()
        total = int(row[0]) if row and row[0] is not None else 0
        errors = int(row[1]) if row and row[1] is not None else 0
        if total == 0:
            return None
        return (errors / total) * 100.0

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


@router.get("", response_model=SLOResponse)
async def get_slos(request: Request):
    definitions = load_slos(get_slo_config_path(request.app))
    columns = _pipeline_event_columns(request)
    time_column = _time_column(columns)
    statuses = []

    for definition in definitions:
        current = round(
            _current_compliance(
                definition,
                _measurement_value(request, definition, columns, time_column),
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

    return SLOResponse(slos=statuses)
