"""Edge emitter — pushes an edge branch's live events to the center (ADR 0012 §6).

In edge role a slow background generator produces the same canonical events the
in-process pipeline already makes; each is applied to the edge's own read
surface (so the branch Space stays live) and forwarded, unchanged, to the
center's ``POST /v1/node/events``. This is push-on-activity, which is what makes
the sleep choreography self-healing: a cold/asleep center is tolerated (bounded
retries, drop on give-up), never raised into the loop, so the edge page stays up
even when the hub is down.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable

import duckdb
import httpx
import structlog

from src.processing.local_pipeline import _generate_random_event, _process_event
from src.serving.node.config import NodeConfig

logger = structlog.get_logger()


class NodeEmitter:
    """Edge-role background task. Constructed with injectable dependencies so the
    forward path and the produce/apply seam are unit-testable without a network
    or a live loop."""

    def __init__(
        self,
        *,
        config: NodeConfig,
        conn: duckdb.DuckDBPyConnection,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        interval_seconds: float = 3.0,
        batch_size: int = 5,
        timeout_seconds: float = 5.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.5,
    ) -> None:
        self._config = config
        self._conn = conn
        self._interval = interval_seconds
        self._batch_size = max(1, batch_size)
        self._timeout = timeout_seconds
        self._max_retries = max(1, max_retries)
        self._backoff_base = backoff_base_seconds
        self._client_factory = client_factory or self._default_client_factory
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    def _default_client_factory(self) -> httpx.AsyncClient:
        # The center URL is operator-configured (trusted), not a user-supplied
        # webhook target, so it deliberately does not go through the SSRF egress
        # guard the webhook dispatcher uses.
        return httpx.AsyncClient(timeout=self._timeout)

    @property
    def endpoint(self) -> str:
        base = (self._config.center_url or "").rstrip("/")
        return f"{base}/v1/node/events"

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    def _produce_local(self) -> dict:
        """Generate one event, stamp it with this edge's branch, apply it to the
        edge's own read surface, and return the **same** dict that will be
        forwarded (N7). Blocking DuckDB work — call via a worker thread."""
        _topic, event = _generate_random_event()
        metadata = event.setdefault("source_metadata", {})
        if isinstance(metadata, dict):
            metadata["branch"] = self._config.branch
        _process_event(self._conn, event, clickhouse_sink=None)
        return event

    async def _forward(self, client: httpx.AsyncClient, events: list[dict]) -> bool:
        """POST a batch to the center. Tolerant of a cold/asleep center (N9):
        bounded retries with backoff, drop + log on give-up, **never** raise into
        the loop."""
        if not events:
            return True
        payload = {"origin_branch": self._config.branch, "events": events}
        headers = {"Authorization": f"Bearer {self._config.token or ''}"}
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await client.post(self.endpoint, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logger.info("node_emit_retry", attempt=attempt, error=str(exc))
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff_base * attempt)
                continue
            if response.status_code == 200:
                return True
            # A rejected batch (auth/shape) will not succeed on retry — drop it.
            logger.info("node_emit_rejected", status=response.status_code)
            return False
        logger.info("node_emit_dropped", branch=self._config.branch, count=len(events))
        return False

    async def _run(self) -> None:
        buffer: list[dict] = []
        async with self._client_factory() as client:
            while not self._stopping.is_set():
                try:
                    event = await asyncio.to_thread(self._produce_local)
                    buffer.append(event)
                    if len(buffer) >= self._batch_size:
                        await self._forward(client, buffer)
                        buffer = []
                except Exception:  # noqa: BLE001 — the loop must never die
                    logger.warning("node_emit_loop_error", exc_info=True)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._interval)

    def start(self) -> None:
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self._run())
            logger.info(
                "node_emitter_started",
                branch=self._config.branch,
                center=self.endpoint,
                interval_seconds=self._interval,
            )

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
