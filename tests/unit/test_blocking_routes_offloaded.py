"""Cold read endpoints must offload their synchronous DuckDB scans to a worker
thread (audit_30_06_26.md A2). The hot paths (entity/metric/query) are pinned by
test_agent_query_async; lineage was left running its scan inline on the event
loop, so concurrent requests serialized and blocked every other tenant on the
worker. This drives the lineage route through ASGI with a connection whose scan
sleeps, and asserts four concurrent requests overlap instead of serializing.

The same applies to the deadletter stats/list/detail reads and the alert-history
and webhook-log reads (the A2 follow-up): each ran its scan inline, so they are
pinned the same way below.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.serving.api.routers import alerts as alerts_module
from src.serving.api.routers import webhooks as webhooks_module
from src.serving.api.routers.deadletter import router as deadletter_router
from src.serving.api.routers.lineage import router as lineage_router
from src.serving.semantic_layer.catalog import DataCatalog

_PRAGMA_ROWS = [
    (0, "event_id"),
    (1, "topic"),
    (2, "processed_at"),
    (3, "tenant_id"),
    (4, "event_type"),
    (5, "entity_id"),
    (6, "latency_ms"),
]


class _SlowExecutor:
    """Mimics a DuckDB connection/cursor: ``execute`` returns self and the
    provenance SELECT sleeps. Supporting ``execute`` directly (the pre-fix path)
    *and* ``cursor()`` (the fixed path) lets the same test serialize on the old
    code and overlap on the new."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self._mode = "pragma"
        self.description: list[tuple[str]] = []

    def execute(self, sql: str, params: object = None) -> _SlowExecutor:
        if "PRAGMA" in sql:
            self._mode = "pragma"
        else:
            # The provenance scan — this is what blocked the event loop inline.
            time.sleep(self.delay_seconds)
            self._mode = "select"
            self.description = [
                ("event_id",),
                ("topic",),
                ("processed_at",),
                ("tenant_id",),
                ("event_type",),
                ("entity_id",),
                ("latency_ms",),
            ]
        return self

    def fetchall(self) -> list[tuple]:
        if self._mode == "pragma":
            return _PRAGMA_ROWS
        return [
            (
                "E1",
                "orders.raw",
                datetime(2026, 6, 30, tzinfo=UTC),
                "default",
                "order.created",
                "ORD-1",
                5.0,
            )
        ]

    def close(self) -> None:
        pass


class _SlowConn(_SlowExecutor):
    def cursor(self) -> _SlowExecutor:
        return _SlowExecutor(self.delay_seconds)


@pytest.mark.asyncio
async def test_lineage_does_not_block_event_loop() -> None:
    app = FastAPI()
    app.state.catalog = DataCatalog()
    app.state.query_engine = SimpleNamespace(_conn=_SlowConn(delay_seconds=0.3))
    app.include_router(lineage_router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        started_at = time.perf_counter()
        responses = await asyncio.gather(*[client.get("/v1/lineage/order/ORD-1") for _ in range(4)])
        elapsed = time.perf_counter() - started_at

    assert all(response.status_code == 200 for response in responses)
    # 4 × 0.3s serialized ≈ 1.2s; offloaded to the threadpool they overlap (~0.3s).
    assert elapsed < 0.9, f"Event loop blocked: {elapsed:.2f}s (expected < 0.9s)"


class _SleepyHistoryConn:
    """A fake DuckDB connection whose *data* scans sleep. DDL (CREATE/ALTER) and
    PRAGMA statements return immediately; a SELECT sleeps, mimicking the blocking
    scan these read handlers ran inline on the event loop. Supports ``execute``
    directly (the pre-fix path) and ``cursor()`` (the offloaded path), so the same
    test serializes on the old code and overlaps on the new. ``fetchall`` /
    ``fetchone`` return empty results — the test asserts timing, not content.
    """

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.description: list[tuple[str]] = [("c",)]

    def cursor(self) -> _SleepyHistoryConn:
        return _SleepyHistoryConn(self.delay_seconds)

    def execute(self, sql: str, params: object = None) -> _SleepyHistoryConn:
        if sql.lstrip().upper().startswith("SELECT"):
            time.sleep(self.delay_seconds)
        return self

    def fetchall(self) -> list[tuple]:
        return []

    def fetchone(self) -> tuple | None:
        return None

    def close(self) -> None:
        pass


async def _assert_concurrent_requests_overlap(app: FastAPI, url: str, *, budget: float) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        started_at = time.perf_counter()
        responses = await asyncio.gather(*[client.get(url) for _ in range(4)])
        elapsed = time.perf_counter() - started_at
    assert all(response.status_code == 200 for response in responses)
    assert elapsed < budget, f"Event loop blocked: {elapsed:.2f}s (expected < {budget}s)"


@pytest.mark.asyncio
async def test_deadletter_stats_does_not_block_event_loop() -> None:
    app = FastAPI()
    app.state.query_engine = SimpleNamespace(_conn=_SleepyHistoryConn(delay_seconds=0.1))
    app.include_router(deadletter_router)
    # /stats runs three scans per request: 4 × serialized ≈ 1.2s, offloaded ≈ 0.3s.
    await _assert_concurrent_requests_overlap(app, "/v1/deadletter/stats", budget=0.9)


@pytest.mark.asyncio
async def test_alert_history_does_not_block_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    # The rule lookup is a YAML read, not the DuckDB scan under test — stub it so
    # the handler reaches the history scan with a non-None rule.
    monkeypatch.setattr(alerts_module, "get_alert_config_path", lambda app: Path("unused"))
    monkeypatch.setattr(alerts_module, "get_alert", lambda *a, **k: SimpleNamespace(id="A1"))
    app = FastAPI()
    app.state.query_engine = SimpleNamespace(_conn=_SleepyHistoryConn(delay_seconds=0.3))
    app.include_router(alerts_module.router)
    # One scan per request: 4 × serialized ≈ 1.2s, offloaded ≈ 0.3s.
    await _assert_concurrent_requests_overlap(app, "/v1/alerts/A1/history", budget=0.9)


@pytest.mark.asyncio
async def test_webhook_logs_does_not_block_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    # The registration lookup is a YAML read, not the DuckDB scan under test.
    monkeypatch.setattr(webhooks_module, "get_webhook_config_path", lambda app: Path("unused"))
    monkeypatch.setattr(webhooks_module, "get_webhook", lambda *a, **k: SimpleNamespace(id="W1"))
    app = FastAPI()
    app.state.query_engine = SimpleNamespace(_conn=_SleepyHistoryConn(delay_seconds=0.3))
    app.include_router(webhooks_module.router)
    # One scan per request: 4 × serialized ≈ 1.2s, offloaded ≈ 0.3s.
    await _assert_concurrent_requests_overlap(app, "/v1/webhooks/W1/logs", budget=0.9)
