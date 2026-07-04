"""Reconciliation checks — R1 ``journal_vs_store``, R2 ``stuck_replay``
(ops-surfaces-spec.md §4.3), the exception inbox's third source (D4).

Pure, read-only cross-store consistency probes: both functions read via the
QueryEngine/ControlPlaneStore ports only and never write serving state (I10)
— the caller (``routers/ops.py``) turns findings into overlay upserts and
owns the dedupe-key -> ``item_id`` mapping (``rc:<dedupe_key>``, §4.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.serving.semantic_layer.stage_clock import coerce_dt, ladder_stage_names

if TYPE_CHECKING:
    from src.serving.control_plane import ControlPlaneStore
    from src.serving.semantic_layer.query.engine import QueryEngine

_STATUS_EVENT_PREFIX = "order.status."


@dataclass(frozen=True)
class ReconciliationFinding:
    """One live detection from an R1/R2 check — not yet an overlay row."""

    dedupe_key: str
    severity: str
    title: str
    detail: str
    entity_kind: str
    entity_id: str
    occurred_at: datetime


def check_journal_vs_store(
    engine: QueryEngine,
    tenant_id: str | None,
    stage_budgets: list[dict[str, Any]] | None,
) -> list[ReconciliationFinding]:
    """R1: for every ``entity_id`` seen in ``orders.status`` journal rows, the
    serving store's order status must not be *behind* the latest journal
    stage (§4.3). Scoped to the non-terminal ladder — comparing against a
    terminal store/journal status is out of scope for v1 (an order already
    ``delivered``/``cancelled`` is never "behind" anything); a status outside
    the ladder is tolerated and skipped, never a crash (I4's spirit extended
    here).
    """
    ladder = ladder_stage_names(stage_budgets)
    if not ladder:
        return []
    rank = {name: index for index, name in enumerate(ladder)}
    terminal_names = [
        entry["name"]
        for entry in stage_budgets or []
        if isinstance(entry, dict) and entry.get("name") and entry.get("terminal")
    ]

    stage_rows = engine.fetch_pipeline_events(
        tenant_id=tenant_id, topic="orders.status", newest_first=False
    )
    latest_by_entity: dict[str, tuple[str, datetime | None]] = {}
    for row in stage_rows:
        entity_id = row.get("entity_id")
        event_type = row.get("event_type") or ""
        if not entity_id or not event_type.startswith(_STATUS_EVENT_PREFIX):
            continue
        status = event_type[len(_STATUS_EVENT_PREFIX) :]
        # Ascending iteration (`newest_first=False`): the last write per
        # entity_id wins, matching the stuck-orders worklist's own scan.
        latest_by_entity[str(entity_id)] = (status, coerce_dt(row.get("processed_at")))
    if not latest_by_entity:
        return []

    order_rows = engine.fetch_orders_by_status([*ladder, *terminal_names], tenant_id=tenant_id)
    store_status_by_id = {str(row.get("order_id")): row.get("status") for row in order_rows}

    findings: list[ReconciliationFinding] = []
    for entity_id, (journal_status, processed_at) in latest_by_entity.items():
        if journal_status not in rank:
            continue
        store_status = store_status_by_id.get(entity_id)
        if store_status is None or store_status not in rank:
            # Missing from the store, or already at/behind a terminal status
            # (never "behind" by definition) — tolerated, not flagged.
            continue
        if rank[store_status] < rank[journal_status]:
            findings.append(
                ReconciliationFinding(
                    dedupe_key=f"r1:{entity_id}:{journal_status}",
                    severity="high",
                    title=f"Order {entity_id} behind its journal stage",
                    detail=(
                        f"Journal's latest stage is '{journal_status}' but the serving "
                        f"store still shows '{store_status}' — an event landed but the "
                        "serving projection didn't (or forked)."
                    ),
                    entity_kind="order",
                    entity_id=entity_id,
                    occurred_at=processed_at or datetime.now(UTC),
                )
            )
    return findings


def check_stuck_replay(
    store: ControlPlaneStore, tenant_id: str, *, older_than_seconds: float
) -> list[ReconciliationFinding]:
    """R2: dead-letter rows sitting in ``replay_pending`` longer than
    ``older_than_seconds`` — a replay was requested but its outbox entry
    never completed the invariant-8 flip (§4.3)."""
    rows = store.list_stuck_replay_dead_letter_events(
        tenant_id, older_than_seconds=older_than_seconds
    )
    findings: list[ReconciliationFinding] = []
    for row in rows:
        event_id = row["event_id"]
        last_retried_at = coerce_dt(row.get("last_retried_at")) or datetime.now(UTC)
        findings.append(
            ReconciliationFinding(
                dedupe_key=f"r2:{event_id}",
                severity="medium",
                title=f"Replay stuck for {event_id}",
                detail=(
                    f"Dead-letter event '{event_id}' has been 'replay_pending' since "
                    f"{last_retried_at.isoformat()} — a replay was requested but its "
                    "outbox entry never completed."
                ),
                entity_kind="event",
                entity_id=event_id,
                occurred_at=last_retried_at,
            )
        )
    return findings
