"""Streaming API endpoints for real-time validated events."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from starlette.concurrency import run_in_threadpool

from src.serving.seen_events import BoundedSeenSet

router = APIRouter(prefix="/v1/stream", tags=["stream"])
tracer = trace.get_tracer("agentflow.api")

# Dedup cache per open SSE connection. Bounded for the same reason as the
# webhook dispatcher's seen-set (issue #183): a connection can stay open for
# hours under sustained traffic, and an unbounded set grows one entry per
# distinct event forever. Eviction cannot re-emit an event: the scan window is
# the newest `limit` (10) rows, so an id leaves the window after 10 newer
# events but leaves the cache only after SEEN_CACHE_SIZE newer distinct ids —
# by then it can never re-enter the window.
SEEN_CACHE_SIZE = 10_000


async def fetch_recent_events(
    request: Request,
    event_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    """Fetch recent pipeline events through the serving backend.

    Offloaded to a worker thread: the SSE generator calls this once per second
    per open stream, so running the scan inline would block the event loop (and
    every other tenant on the worker) for the scan's duration — for both the
    DuckDB scan and the ClickHouse HTTP round-trip. (audit_30 A2)

    The scan goes through ``QueryEngine.fetch_pipeline_events`` (the serving
    backend), so the stream reflects the store the API serves from on either
    engine (ADR 0006).
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    return await run_in_threadpool(
        request.app.state.query_engine.fetch_pipeline_events,
        tenant_id=tenant_id,
        event_type=event_type,
        entity_id=entity_id,
        limit=limit,
        validated_only=True,
        newest_first=True,
    )


@router.get("/events", summary="Stream real-time validated events via SSE")
async def stream_events(
    request: Request,
    event_type: str | None = None,
    entity_id: str | None = None,
) -> StreamingResponse:
    """Server-Sent Events stream of validated pipeline events."""

    async def event_generator() -> AsyncIterator[str]:
        seen_event_ids = BoundedSeenSet(maxlen=SEEN_CACHE_SIZE)
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
