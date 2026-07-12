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
    """One SLO, reported as a real SLI (audit P2-2): ``current`` is the share
    of good units among valid units over the SLO window — a fraction of
    events for latency/error SLIs, a fraction of observed time for the
    freshness SLI — never a rescaled point aggregate. ``None`` means the
    window holds no valid units: *unknown*, deliberately distinct from 0.0
    (an empty journal is not a breached SLO)."""

    name: str
    target: float
    current: float | None
    error_budget_remaining: float | None
    status: Literal["healthy", "at_risk", "breached", "unknown"]
    window_days: int
    # The SLI's own numerator and denominator, so the number is auditable
    # from the response instead of taken on faith.
    good: float | None
    valid: float | None
    unit: Literal["events", "seconds"]
    # Error-budget burn rates over the standard multi-window pairs
    # (Google SRE workbook): (1h, 6h) pages at >14.4, (6h, 3d) warns at >6.
    # burn = (1 - sli_window) / (1 - target); None where the window is empty.
    burn_rates: dict[str, float | None]
    # The old point aggregate, kept as what it always was: a diagnostic.
    diagnostic: dict[str, float | None]


class SLOResponse(BaseModel):
    slos: list[SLOStatus]


# Multi-window burn-rate alerting (audit P2-2): the fast pair catches a sharp
# burn quickly, the slow pair catches a slow leak; requiring BOTH windows of a
# pair over the threshold is what keeps a brief spike from paging.
_BURN_WINDOWS = {"1h": "1 hours", "6h": "6 hours", "3d": "3 days"}
_FAST_PAIR = ("1h", "6h")
_SLOW_PAIR = ("6h", "3d")
_FAST_BURN_THRESHOLD = 14.4
_SLOW_BURN_THRESHOLD = 6.0


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


def _sli(
    journal: JournalReader,
    definition: SLODefinition,
    tenant_id: str | None,
    window: str,
) -> tuple[float | None, float | None, float | None]:
    """``(share, good, valid)`` of the SLI over ``window`` — the fraction of
    good units among valid units (audit P2-2), or Nones when the window
    holds no valid units and the honest answer is *unknown*."""
    if definition.measurement == "p95_latency_ms":
        # Latency SLI: share of events at or under the threshold. The p95
        # itself is a diagnostic, not the SLI — a p95 of 2x the threshold
        # says nothing about how MANY requests were slow.
        counts = journal.latency_within(
            threshold_ms=definition.threshold, window=window, tenant_id=tenant_id
        )
        if counts is None or counts.total == 0:
            return (None, None, None)
        good = counts.total - counts.errors
        return (good / counts.total, float(good), float(counts.total))

    if definition.measurement == "freshness_seconds":
        # Freshness SLI, time-weighted: of the observed window, the share of
        # seconds during which the newest row was at most threshold old —
        # not the instantaneous age, which only describes this moment.
        pair = journal.freshness_within(
            threshold_seconds=definition.threshold, window=window, tenant_id=tenant_id
        )
        if pair is None:
            return (None, None, None)
        fresh_seconds, observed_seconds = pair
        if observed_seconds <= 0.0:
            return (None, fresh_seconds, observed_seconds)
        return (fresh_seconds / observed_seconds, fresh_seconds, observed_seconds)

    if definition.measurement == "error_rate_percent":
        counts = journal.event_counts(window=window, tenant_id=tenant_id)
        if counts is None or counts.total == 0:
            return (None, None, None)
        good = counts.total - counts.errors
        return (good / counts.total, float(good), float(counts.total))

    raise HTTPException(
        status_code=500,
        detail=f"Unsupported SLO measurement '{definition.measurement}'.",
    )


def _diagnostic(
    journal: JournalReader,
    definition: SLODefinition,
    tenant_id: str | None,
    window: str,
) -> dict[str, float | None]:
    """The old point aggregate, demoted to what it always was."""
    if definition.measurement == "p95_latency_ms":
        return {
            "p95_latency_ms": journal.latency_quantile_ms(
                quantile=0.95, window=window, tenant_id=tenant_id
            )
        }
    if definition.measurement == "freshness_seconds":
        return {"age_seconds": journal.freshness(window=window, tenant_id=tenant_id).age_seconds}
    counts = journal.event_counts(window=window, tenant_id=tenant_id)
    if counts is None or counts.total == 0:
        return {"error_rate_percent": None}
    return {"error_rate_percent": (counts.errors / counts.total) * 100.0}


def _error_budget_remaining(target: float, current: float | None) -> float | None:
    if current is None:
        return None
    if target >= 1.0:
        return 1.0 if current >= 1.0 else 0.0
    budget = 1.0 - target
    consumed = (1.0 - current) / budget
    return max(0.0, min(1.0, 1.0 - consumed))


def _burn_rate(target: float, share: float | None) -> float | None:
    """How many times faster than sustainable the error budget burns:
    ``(1 - sli) / (1 - target)``. 1.0 spends exactly the budget over the SLO
    window; ``None`` when the window is empty or the target leaves no budget.
    """
    if share is None or target >= 1.0:
        return None
    return round((1.0 - share) / (1.0 - target), 2)


def _pair_burns(burn_rates: dict[str, float | None], pair: tuple[str, str], limit: float) -> bool:
    first, second = (burn_rates.get(name) for name in pair)
    return first is not None and second is not None and first > limit and second > limit


def _compute_slo_statuses(request: Request, definitions: list[SLODefinition]) -> list[SLOStatus]:
    # Runs on a worker thread (get_slos offloads it) so the per-SLO aggregate
    # scans can't block the event loop for every tenant on the worker.
    # (audit_30_06_26.md A2)
    #
    # Every aggregate goes through the active backend. These ran on a private
    # DuckDB cursor, so a ClickHouse deployment computed its SLOs — and its
    # error budget — from an embedded store nothing was writing to (audit P0-3).
    #
    # Cost shape: per SLO, one SLI aggregate over the SLO window, one per burn
    # window, and one diagnostic — bounded, indexed journal aggregates on an
    # admin surface that already runs off the event loop.
    journal = request.app.state.query_engine.journal
    tenant_id = _tenant_id(request)
    statuses = []

    for definition in definitions:
        window = f"{definition.window_days} days"
        share, good, valid = _sli(journal, definition, tenant_id, window)
        current = round(share, 4) if share is not None else None
        error_budget_remaining = _error_budget_remaining(definition.target, current)
        if error_budget_remaining is not None:
            error_budget_remaining = round(error_budget_remaining, 4)

        burn_rates = {
            label: _burn_rate(
                definition.target,
                _sli(journal, definition, tenant_id, burn_window)[0],
            )
            for label, burn_window in _BURN_WINDOWS.items()
        }

        status: Literal["healthy", "at_risk", "breached", "unknown"]
        if current is None:
            status = "unknown"
        elif current < definition.target:
            status = "breached"
        elif (
            _pair_burns(burn_rates, _FAST_PAIR, _FAST_BURN_THRESHOLD)
            or _pair_burns(burn_rates, _SLOW_PAIR, _SLOW_BURN_THRESHOLD)
            or (error_budget_remaining is not None and error_budget_remaining < 0.2)
        ):
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
                good=round(good, 2) if good is not None else None,
                valid=round(valid, 2) if valid is not None else None,
                unit="seconds" if definition.measurement == "freshness_seconds" else "events",
                burn_rates=burn_rates,
                diagnostic=_diagnostic(journal, definition, tenant_id, window),
            )
        )

    return statuses


@router.get("", response_model=SLOResponse)
async def get_slos(request: Request) -> SLOResponse:
    definitions = load_slos(get_slo_config_path(request.app))
    statuses = await run_in_threadpool(_compute_slo_statuses, request, definitions)
    return SLOResponse(slos=statuses)
