"""Data lineage API endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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


def _fetch_matching_events(request: Request, entity_id: str) -> list[dict]:
    conn = request.app.state.query_engine._conn
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()
    }
    if "entity_id" not in columns:
        return []

    time_column = "processed_at" if "processed_at" in columns else "created_at"
    select_columns = [
        "event_id",
        "topic",
        f"{time_column} AS processed_at",
        "event_type" if "event_type" in columns else "NULL AS event_type",
        "entity_id",
        "latency_ms" if "latency_ms" in columns else "NULL AS latency_ms",
    ]

    cursor = conn.execute(
        (
            f"SELECT {', '.join(select_columns)} "  # nosec B608 - selected columns come from the schema allowlist
            "FROM pipeline_events "
            f"WHERE entity_id = ? ORDER BY {time_column} ASC"
        ),
        [entity_id],
    )
    result_columns = [description[0] for description in cursor.description]
    return [dict(zip(result_columns, row, strict=False)) for row in cursor.fetchall()]


@router.get(
    "/{entity_type}/{entity_id}",
    response_model=LineageResponse,
    summary="Get provenance chain for an entity",
)
async def get_lineage(entity_type: str, entity_id: str, request: Request):
    """Return the reconstructed lineage for an entity from source to serving."""
    catalog = request.app.state.catalog
    entity = catalog.entities.get(entity_type)
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown entity type: {entity_type}. "
                f"Available: {list(catalog.entities.keys())}"
            ),
        )

    rows = _fetch_matching_events(request, entity_id)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No lineage found for {entity_type}/{entity_id}",
        )

    dated_rows = [
        row | {"processed_at": _coerce_datetime(row.get("processed_at"))}
        for row in rows
    ]
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
            if isinstance(topic, str)
            and topic not in {"events.validated", "events.deadletter"}
        ),
        _source_topic_for_entity(entity_type),
    )
    validated_rows = [row for row in dated_rows if row.get("topic") == "events.validated"]
    validated = bool(validated_rows)
    enriched = validated
    validation_at = (
        max(row["processed_at"] for row in validated_rows if row["processed_at"] is not None)
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
            system="duckdb",
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
