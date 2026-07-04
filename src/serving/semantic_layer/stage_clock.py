"""Stage-clock resolution shared by Order 360 timeline (D2) and the
stuck-orders worklist (D3) — ops-surfaces-spec.md §1.4/§1.5.

Budgets come from exactly one place: the catalog entity's `stages` block
(the contract loaded via ``entity_type_registry.py``). This module is the
single place that reads a budget entry and turns it into breach arithmetic,
so no stage-name or budget literal needs to be duplicated between the
timeline endpoint and the worklist endpoint (invariant I2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def coerce_dt(value: object) -> datetime | None:
    """Parse a journal/order timestamp (datetime or ISO string) to aware UTC.

    Naive DuckDB timestamps are local wall-clock (DuckDB's ``NOW()``), not
    UTC — same ``local_tz`` convention as ``EntityQueryMixin.get_entity``'s
    ``_last_updated``. On non-DuckDB backends timestamps arrive as
    ISO-format strings (JSON transport), not datetimes.
    """
    local_tz = datetime.now().astimezone().tzinfo or UTC
    if isinstance(value, datetime):
        return (
            value.astimezone(UTC)
            if value.tzinfo is not None
            else value.replace(tzinfo=local_tz).astimezone(UTC)
        )
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return (
            parsed.astimezone(UTC)
            if parsed.tzinfo is not None
            else parsed.replace(tzinfo=local_tz).astimezone(UTC)
        )
    return None


def stage_budget(
    stage_budgets: list[dict[str, Any]] | None, status: str | None
) -> dict[str, Any] | None:
    """Look up the catalog stage-budget entry for `status`, or None if absent."""
    if not stage_budgets:
        return None
    return next(
        (
            entry
            for entry in stage_budgets
            if isinstance(entry, dict) and entry.get("name") == status
        ),
        None,
    )


def ladder_stage_names(stage_budgets: list[dict[str, Any]] | None) -> list[str]:
    """Non-terminal stage names, in catalog list order (§1.5: list order = ladder order)."""
    if not stage_budgets:
        return []
    return [
        entry["name"]
        for entry in stage_budgets
        if isinstance(entry, dict) and entry.get("name") and not entry.get("terminal")
    ]


def resolve_breach(
    *, entered_at: datetime | None, budget: dict[str, Any] | None
) -> tuple[float | None, int | None, bool | None]:
    """Compute (in_stage_seconds, sla_minutes, breached) for one order's stage entry.

    `breached` is None for terminal/unknown stages or when no budget/clock is
    available (I4) — never a crash, never a guess.
    """
    in_stage_seconds = (
        (datetime.now(UTC) - entered_at).total_seconds() if entered_at is not None else None
    )
    sla_minutes = budget.get("sla_minutes") if budget else None
    is_terminal = bool(budget.get("terminal")) if budget else False
    breached = (
        None
        if is_terminal or sla_minutes is None or in_stage_seconds is None
        else in_stage_seconds > sla_minutes * 60
    )
    return in_stage_seconds, sla_minutes, breached
