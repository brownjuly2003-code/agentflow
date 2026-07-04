"""Center node-ingest endpoint — ``POST /v1/node/events`` (ADR 0012 §3 / build §4).

An edge branch pushes a batch of the **same canonical events** the in-process
pipeline already understands; the center applies each through
:func:`local_pipeline._process_event` — no new serving logic — tagging the
originating branch on the ``pipeline_events`` journal so the cross-branch view
(step 5), Order 360, and freshness move.

The endpoint is mounted on every node but is a no-op (``404``) off the center,
carries its own bearer-token auth (distinct from the public ``demo-key``), and
is hidden from the public OpenAPI catalog (``include_in_schema=False``) because
it is internal node-to-node federation, not an agent-facing surface.
"""

from __future__ import annotations

import json
import secrets
import threading
from typing import Literal

import duckdb
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from src.processing.local_pipeline import _process_event

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/node", tags=["node"])

# Bounded batch (build contract §4): a demo edge emits a handful of events per
# request, never a load-test flood.
MAX_EVENTS_PER_BATCH = 500

# Ingest writes go through the shared serving write-connection; serialize them
# so two concurrent POSTs never interleave BEGIN/COMMIT on it. One center =
# one process = one lock.
_INGEST_LOCK = threading.Lock()


class NodeEventBatch(BaseModel):
    """One edge->center push. ``origin_branch`` is constrained to the live edge
    branches, so an unknown/mismatched branch is rejected as ``422`` (N12)."""

    origin_branch: Literal["spb", "ekb"]
    events: list[dict] = Field(default_factory=list, max_length=MAX_EVENTS_PER_BATCH)


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _existing_event_ids(conn: duckdb.DuckDBPyConnection, event_ids: list[str]) -> set[str]:
    """Batch ids already present in the ingest journal — the idempotency filter
    (N5). A static query over the two ingest topics (the derived
    ``orders.status`` row uses a distinct id/topic); intersected with the batch
    in Python so the SQL carries no interpolated values."""
    if not event_ids:
        return set()
    rows = conn.execute(
        "SELECT DISTINCT event_id FROM pipeline_events "
        "WHERE topic IN ('events.validated', 'events.deadletter')"
    ).fetchall()
    return {str(row[0]) for row in rows} & set(event_ids)


@router.post("/events", include_in_schema=False, response_model=None)
async def ingest_node_events(request: Request) -> JSONResponse:
    config = request.app.state.node_config

    # N2/N12: a usable ingest exists only on the center — every other role
    # (edge, standalone) is 404, even with a valid token.
    if not config.is_center:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    # Bearer auth against the node token, constant-time, distinct from the
    # public demo-key path (N3/N10). Role gate above runs first so a non-center
    # node never even reveals the auth ladder.
    bearer = _extract_bearer(request)
    if bearer is None:
        return JSONResponse(
            status_code=401, content={"detail": "Missing or malformed bearer token."}
        )
    expected = config.token or ""
    if not expected or not secrets.compare_digest(bearer, expected):
        return JSONResponse(status_code=403, content={"detail": "Invalid node token."})

    # Body shape (422); an unknown origin_branch is rejected here by the Literal.
    try:
        raw = await request.json()
        batch = NodeEventBatch.model_validate(raw)
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        return JSONResponse(status_code=422, content={"detail": f"Invalid batch: {exc}"})

    origin = batch.origin_branch
    events = batch.events
    conn = request.app.state.query_engine._conn

    def _apply() -> tuple[int, int, int]:
        with _INGEST_LOCK:
            ids = [str(e["event_id"]) for e in events if isinstance(e, dict) and e.get("event_id")]
            seen = _existing_event_ids(conn, ids)
            applied = dead = duplicates = 0
            for event in events:
                event_id = event.get("event_id") if isinstance(event, dict) else None
                if event_id is not None and str(event_id) in seen:
                    # Idempotency (N5): re-POSTing the same batch never
                    # re-applies or re-journals; count it, do not double-count.
                    duplicates += 1
                    continue
                # Tag origin so the journal/lineage carry the branch (N4).
                metadata = event.setdefault("source_metadata", {})
                if isinstance(metadata, dict):
                    metadata["branch"] = origin
                # No new serving logic — the center reuses the exact event->metric
                # path the in-process pipeline uses. clickhouse_sink is None: the
                # HF three-node demo serves from DuckDB.
                success, _reason = _process_event(conn, event, clickhouse_sink=None)
                if success:
                    applied += 1
                    if event_id is not None:
                        seen.add(str(event_id))
                else:
                    dead += 1
            return applied, dead, duplicates

    applied, dead_lettered, duplicates = await run_in_threadpool(_apply)
    logger.info(
        "node_events_ingested",
        origin_branch=origin,
        accepted=len(events),
        applied=applied,
        dead_lettered=dead_lettered,
        duplicates=duplicates,
    )
    return JSONResponse(
        status_code=200,
        content={
            "accepted": len(events),
            "applied": applied,
            "dead_lettered": dead_lettered,
            "duplicates": duplicates,
        },
    )
