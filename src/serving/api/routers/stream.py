"""Streaming API endpoints for real-time validated events."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from src.serving.seen_events import BoundedSeenSet

if TYPE_CHECKING:
    from fastapi import FastAPI

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

DEFAULT_MAX_STREAMS_PER_TENANT = 5


def max_streams_per_tenant() -> int:
    """Per-tenant cap on concurrent SSE connections (security pre-audit S-5).

    Each open stream runs a journal scan every second for as long as it stays
    open, but the rate limiter only charges the one request that opened it —
    without a cap a tenant's scan load grows by rate_limit_rpm scanners per
    minute, unbounded. The cap is per process, like the failed-auth throttle
    (S-7 accepted risk): N replicas give an N× effective cap, which still
    bounds the growth the finding is about.
    """
    default = str(DEFAULT_MAX_STREAMS_PER_TENANT)
    return int(os.getenv("AGENTFLOW_SSE_MAX_STREAMS_PER_TENANT", default))


def _active_stream_counts(app: "FastAPI") -> dict[str, int]:
    counts = getattr(app.state, "sse_active_streams", None)
    if counts is None:
        counts = {}
        app.state.sse_active_streams = counts
    return counts


class _StreamSlot:
    """One tenant's claim on a concurrent-stream slot.

    ``release()`` is idempotent and wired to BOTH the generator's ``finally``
    and the response's background task: a started generator releases on close
    (client disconnect included, via ``aclose()``), while a generator the
    server never iterates skips its ``finally`` entirely — there the
    background task, which Starlette runs after the response finishes, is the
    release path. Check-then-claim runs with no ``await`` in between, so it is
    atomic on the event loop.
    """

    def __init__(self, counts: dict[str, int], tenant_id: str) -> None:
        self._counts = counts
        self._tenant_id = tenant_id
        self._released = False
        counts[tenant_id] = counts.get(tenant_id, 0) + 1

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        remaining = self._counts.get(self._tenant_id, 0) - 1
        if remaining > 0:
            self._counts[self._tenant_id] = remaining
        else:
            self._counts.pop(self._tenant_id, None)


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
    # tenant_id is None only with auth disabled (dev/demo mode) — then the cap
    # is skipped, same convention as the /v1/batch rate-limit charge (S-4).
    tenant_id = getattr(request.state, "tenant_id", None)
    slot: _StreamSlot | None = None
    if tenant_id is not None:
        cap = max_streams_per_tenant()
        counts = _active_stream_counts(request.app)
        if counts.get(tenant_id, 0) >= cap:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Too many concurrent event streams for this tenant "
                    f"(limit {cap}). Close an open stream and retry."
                ),
                headers={"Retry-After": "1"},
            )
        slot = _StreamSlot(counts, tenant_id)

    async def event_generator() -> AsyncIterator[str]:
        try:
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
        finally:
            if slot is not None:
                slot.release()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
        background=BackgroundTask(slot.release) if slot is not None else None,
    )
