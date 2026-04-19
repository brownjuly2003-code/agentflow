"""Streaming API endpoints for real-time validated events."""

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from opentelemetry import trace

router = APIRouter(prefix="/v1/stream", tags=["stream"])
tracer = trace.get_tracer("agentflow.api")


async def fetch_recent_events(
    request: Request,
    event_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Fetch recent pipeline events from DuckDB with optional filters."""
    conn = request.app.state.query_engine._conn
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info('pipeline_events')").fetchall()
    }
    time_column = "processed_at" if "processed_at" in columns else "created_at"

    select_columns = [
        "event_id",
        "topic",
        f"{time_column} AS processed_at",
        "event_type" if "event_type" in columns else "NULL AS event_type",
        "entity_id" if "entity_id" in columns else "NULL AS entity_id",
        "latency_ms" if "latency_ms" in columns else "NULL AS latency_ms",
    ]

    sql = f"SELECT {', '.join(select_columns)} FROM pipeline_events"  # nosec B608 - selected columns come from the schema allowlist
    where_clauses: list[str] = []
    params: list[str | int] = []

    if event_type:
        if "event_type" not in columns:
            return []
        if event_type == "order":
            where_clauses.append("event_type LIKE 'order.%'")
        elif event_type == "payment":
            where_clauses.append("event_type LIKE 'payment.%'")
        elif event_type == "clickstream":
            where_clauses.append("event_type IN ('click', 'page_view', 'add_to_cart')")
        elif event_type == "inventory":
            where_clauses.append("event_type LIKE 'product.%'")
        else:
            where_clauses.append("event_type = ?")
            params.append(event_type)

    if entity_id:
        if "entity_id" not in columns:
            return []
        where_clauses.append("entity_id = ?")
        params.append(entity_id)

    if where_clauses:
        sql = f"{sql} WHERE {' AND '.join(where_clauses)}"

    sql = f"{sql} ORDER BY {time_column} DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    result_columns = [description[0] for description in conn.description]
    return [dict(zip(result_columns, row, strict=False)) for row in rows]


@router.get("/events", summary="Stream real-time validated events via SSE")
async def stream_events(
    request: Request,
    event_type: str | None = None,
    entity_id: str | None = None,
):
    """Server-Sent Events stream of validated pipeline events."""

    async def event_generator():
        seen_event_ids: set[str] = set()
        events_sent = 0

        with tracer.start_as_current_span("sse_stream") as span:
            span.set_attribute("stream.event_type", event_type or "all")
            if entity_id is not None:
                span.set_attribute("stream.entity_id", entity_id)

            while True:
                if await request.is_disconnected():
                    break

                events = await fetch_recent_events(
                    request=request,
                    event_type=event_type,
                    entity_id=entity_id,
                    limit=10,
                )

                emitted = False
                for event in reversed(events):
                    if await request.is_disconnected():
                        span.set_attribute("stream.events_sent", events_sent)
                        return

                    event_id = str(event.get("event_id", ""))
                    if event_id in seen_event_ids:
                        continue

                    seen_event_ids.add(event_id)
                    payload = {
                        key: value.isoformat() if isinstance(value, datetime) else value
                        for key, value in event.items()
                    }
                    emitted = True
                    events_sent += 1
                    yield f"data: {json.dumps(payload)}\n\n"

                if not emitted:
                    yield ": keepalive\n\n"

                await asyncio.sleep(1.0)

            span.set_attribute("stream.events_sent", events_sent)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
