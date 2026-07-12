"""Data lineage API endpoints."""

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/v1/lineage", tags=["lineage"])


class LineageNode(BaseModel):
    layer: str
    system: str
    table_or_topic: str
    processed_at: datetime | None
    quality_score: float | None


class LineageResponse(BaseModel):
    entity_type: str
    entity_id: str
    lineage: list[LineageNode]
    freshness_seconds: float
    validated: bool
    enriched: bool


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _source_topic_for_entity(entity_type: str) -> str:
    return {
        "order": "orders.raw",
        "user": "orders.raw",
        "product": "products.cdc",
        "session": "clicks.raw",
    }.get(entity_type, f"{entity_type}.raw")


def _source_system_for_entity(entity_type: str) -> str:
    return {
        "order": "postgres_cdc",
        "user": "postgres_cdc",
        "product": "postgres_cdc",
        "session": "web_sdk",
    }.get(entity_type, "unknown")


def _quality_score(rows: list[dict], *, default: float | None = None) -> float | None:
    latencies = [
        float(value)
        for value in (row.get("latency_ms") for row in rows)
        if isinstance(value, int | float)
    ]
    if not latencies:
        return default
    average_latency = sum(latencies) / len(latencies)
    score = max(0.0, min(1.0, 1.0 - (average_latency / 1000.0)))
    return round(score, 3)


def _fetch_matching_events(request: Request, entity_type: str, entity_id: str) -> list[dict]:
    # Runs on a worker thread (get_lineage offloads it) so a journal scan cannot
    # block the event loop and starve every other tenant on the worker.
    # (audit_30_06_26.md A2)
    #
    # Reads the journal through the *active* backend. This endpoint used to open
    # its own DuckDB cursor, so on the ClickHouse profile it reconstructed
    # lineage from a store nobody was serving from — demo rows, confidently
    # presented as provenance (audit P0-3).
    journal = request.app.state.query_engine.journal
    return cast(
        "list[dict]",
        journal.lineage_events(
            entity_type=entity_type,
            entity_id=entity_id,
            tenant_id=getattr(request.state, "tenant_id", None),
        ),
    )


@router.get(
    "/{entity_type}/{entity_id}",
    response_model=LineageResponse,
    summary="Get provenance chain for an entity",
)
async def get_lineage(entity_type: str, entity_id: str, request: Request) -> LineageResponse:
    """Return the reconstructed lineage for an entity from source to serving."""
    catalog = request.app.state.catalog
    entity = catalog.entities.get(entity_type)
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown entity type: {entity_type}. Available: {list(catalog.entities.keys())}"
            ),
        )
    tenant_key = getattr(request.state, "tenant_key", None)
    if (
        tenant_key is not None
        and tenant_key.allowed_entity_types is not None
        and entity_type not in tenant_key.allowed_entity_types
    ):
        raise HTTPException(
            status_code=403,
            detail=f"API key '{tenant_key.name}' cannot access entity type '{entity_type}'.",
        )

    rows = await run_in_threadpool(_fetch_matching_events, request, entity_type, entity_id)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No lineage found for {entity_type}/{entity_id}",
        )

    dated_rows = [row | {"processed_at": _coerce_datetime(row.get("processed_at"))} for row in rows]
    timestamps = [row["processed_at"] for row in dated_rows if row["processed_at"] is not None]
    if not timestamps:
        raise HTTPException(
            status_code=404,
            detail=f"No lineage found for {entity_type}/{entity_id}",
        )

    earliest_at = min(timestamps)
    latest_at = max(timestamps)
    source_topic = next(
        (
            topic
            for row in dated_rows
            for topic in [row.get("topic")]
            if isinstance(topic, str) and topic not in {"events.validated", "events.deadletter"}
        ),
        _source_topic_for_entity(entity_type),
    )
    validated_rows = [row for row in dated_rows if row.get("topic") == "events.validated"]
    validated = bool(validated_rows)
    enriched = validated
    validation_at = (
        max(
            (row["processed_at"] for row in validated_rows if row["processed_at"] is not None),
            default=latest_at,
        )
        if validated_rows
        else latest_at
    )

    lineage = [
        LineageNode(
            layer="source",
            system=_source_system_for_entity(entity_type),
            table_or_topic=source_topic,
            processed_at=earliest_at,
            quality_score=None,
        ),
        LineageNode(
            layer="ingestion",
            system="kafka",
            table_or_topic=source_topic,
            processed_at=earliest_at,
            quality_score=_quality_score(dated_rows, default=1.0),
        ),
        LineageNode(
            layer="validation",
            system="flink",
            table_or_topic="events.validated",
            processed_at=validation_at,
            quality_score=1.0 if validated else 0.0,
        ),
        LineageNode(
            layer="enrichment",
            # The store that actually served this, not a hardcoded "duckdb" —
            # which is what a ClickHouse deployment used to be told (audit P0-3).
            system=request.app.state.query_engine.backend.name,
            table_or_topic=entity.table,
            processed_at=latest_at,
            quality_score=_quality_score(validated_rows, default=1.0 if validated else None),
        ),
        LineageNode(
            layer="serving",
            system="fastapi",
            table_or_topic=entity.table,
            processed_at=latest_at,
            quality_score=1.0 if validated else None,
        ),
    ]

    freshness_seconds = max(0.0, (datetime.now(UTC) - latest_at).total_seconds())

    return LineageResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        lineage=lineage,
        freshness_seconds=round(freshness_seconds, 3),
        validated=validated,
        enriched=enriched,
    )
