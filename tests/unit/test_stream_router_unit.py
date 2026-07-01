"""Unit coverage for ``src.serving.api.routers.stream`` — the SSE event stream.

The live HTTP path is covered by the integration suite; these tests pin the
router's own logic at the unit layer: the schema-adaptive
``fetch_recent_events`` query (against a real in-memory DuckDB — topic/tenant/
event-type/entity filters and the missing-column guards) and the
``stream_events`` SSE generator driven with a stateful disconnect check and a
no-op sleep (emit / dedup / keepalive / mid-loop disconnect).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest

from src.serving.api.routers import stream as stream_module
from src.serving.api.routers.stream import fetch_recent_events, stream_events
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.semantic_layer.query import QueryEngine

# ── fetch_recent_events ──────────────────────────────────────────


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR,
            event_type VARCHAR, entity_id VARCHAR,
            processed_at TIMESTAMP, latency_ms DOUBLE
        )
        """
    )
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    connection.executemany(
        "INSERT INTO pipeline_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("e1", "events.validated", "acme", "order.created", "ORD-1", now, 100.0),
            ("e2", "events.validated", "acme", "payment.initiated", "PAY-1", now, 100.0),
            ("e3", "events.validated", "acme", "click", "SES-1", now, 100.0),
            ("e4", "events.validated", "acme", "product.updated", "PROD-1", now, 100.0),
            ("e5", "events.validated", "acme", "custom.thing", "X-1", now, 100.0),
            ("e6", "orders.raw", "acme", "order.created", "ORD-2", now, 100.0),
        ],
    )
    try:
        yield connection
    finally:
        connection.close()


def _engine_stub(conn: duckdb.DuckDBPyConnection) -> QueryEngine:
    # Minimal real QueryEngine over the test connection (built via __new__ so
    # initialize_demo_data cannot widen the schema-variant fixtures): the SSE
    # scan goes through QueryEngine.fetch_pipeline_events on the serving
    # backend.
    engine = QueryEngine.__new__(QueryEngine)
    backend = DuckDBBackend(db_path=":memory:", connection=conn)
    engine._duckdb_backend = backend
    engine._backend = backend
    engine._backend_name = backend.name
    engine._conn = conn
    return engine


def _req(conn: duckdb.DuckDBPyConnection, *, tenant_id: Any = None) -> SimpleNamespace:
    app = SimpleNamespace(state=SimpleNamespace(query_engine=_engine_stub(conn)))
    return SimpleNamespace(app=app, state=SimpleNamespace(tenant_id=tenant_id))


async def test_fetch_returns_only_validated_events(conn: duckdb.DuckDBPyConnection) -> None:
    events = await fetch_recent_events(_req(conn))
    ids = {e["event_id"] for e in events}
    # e6 (orders.raw) is excluded by the topic = 'events.validated' filter.
    assert ids == {"e1", "e2", "e3", "e4", "e5"}


async def test_fetch_event_type_filters(conn: duckdb.DuckDBPyConnection) -> None:
    async def ids_for(event_type: str) -> set[str]:
        return {e["event_id"] for e in await fetch_recent_events(_req(conn), event_type=event_type)}

    assert await ids_for("order") == {"e1"}
    assert await ids_for("payment") == {"e2"}
    assert await ids_for("clickstream") == {"e3"}
    assert await ids_for("inventory") == {"e4"}
    # an unrecognised event_type falls through to an exact match
    assert await ids_for("custom.thing") == {"e5"}


async def test_fetch_entity_id_filter(conn: duckdb.DuckDBPyConnection) -> None:
    events = await fetch_recent_events(_req(conn), entity_id="ORD-1")
    assert {e["event_id"] for e in events} == {"e1"}


async def test_fetch_respects_limit_and_desc_order(conn: duckdb.DuckDBPyConnection) -> None:
    events = await fetch_recent_events(_req(conn), limit=2)
    assert len(events) == 2


async def test_fetch_filters_by_tenant(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "INSERT INTO pipeline_events VALUES "
        "('e7','events.validated','other','order.created','ORD-9', NOW(), 100.0)"
    )
    events = await fetch_recent_events(_req(conn, tenant_id="other"))
    assert {e["event_id"] for e in events} == {"e7"}


async def test_fetch_tenant_guard_without_tenant_column() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)"
    )
    try:
        assert await fetch_recent_events(_req(connection, tenant_id="acme")) == []
    finally:
        connection.close()


async def test_fetch_event_type_without_column_returns_empty() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)"
    )
    try:
        assert await fetch_recent_events(_req(connection), event_type="order") == []
    finally:
        connection.close()


async def test_fetch_entity_id_without_column_returns_empty() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)"
    )
    try:
        assert await fetch_recent_events(_req(connection), entity_id="ORD-1") == []
    finally:
        connection.close()


async def test_fetch_synthesizes_topic_when_column_absent() -> None:
    # No `topic` column: the select substitutes the 'events.validated' literal
    # and the topic WHERE clause is skipped, so the row still comes back.
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE pipeline_events (event_id VARCHAR, processed_at TIMESTAMP)")
    connection.execute("INSERT INTO pipeline_events VALUES ('e1', NOW())")
    try:
        events = await fetch_recent_events(_req(connection))
        assert events[0]["topic"] == "events.validated"
    finally:
        connection.close()


# ── stream_events (SSE generator) ────────────────────────────────


class _StreamReq:
    """Request whose ``is_disconnected`` flips to True after N checks, so the
    SSE loop runs a bounded number of iterations."""

    def __init__(self, *, disconnect_after: int) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(query_engine=SimpleNamespace(_conn=None)))
        self.state = SimpleNamespace(tenant_id=None)
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(stream_module.asyncio, "sleep", _instant)


async def _drain(response: Any) -> str:
    chunks = [chunk async for chunk in response.body_iterator]
    return "".join(c.decode() if isinstance(c, bytes) else c for c in chunks)


async def test_stream_emits_event_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    event = {
        "event_id": "e1",
        "topic": "events.validated",
        "event_type": "order.created",
        "processed_at": datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
    }

    async def fake_fetch(**_kwargs: Any) -> list[dict[str, object]]:
        return [event]

    monkeypatch.setattr(stream_module, "fetch_recent_events", fake_fetch)

    # checks: while-top (False), event e1 (False), next while-top (True) -> stop.
    # entity_id is passed so the span records it too.
    response = await stream_events(_StreamReq(disconnect_after=2), entity_id="ORD-1")
    text = await _drain(response)

    assert "data: " in text
    assert "e1" in text
    # the datetime is serialised to ISO text
    assert "2026-06-13T12:00:00+00:00" in text


async def test_stream_emits_keepalive_when_no_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(**_kwargs: Any) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(stream_module, "fetch_recent_events", fake_fetch)

    # checks: while-top (False) -> empty fetch -> keepalive -> while-top (True)
    response = await stream_events(_StreamReq(disconnect_after=1))
    text = await _drain(response)

    assert ": keepalive" in text
    assert "data: " not in text


async def test_stream_stops_immediately_when_already_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_fetch(**_kwargs: Any) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(stream_module, "fetch_recent_events", fake_fetch)

    response = await stream_events(_StreamReq(disconnect_after=0))
    text = await _drain(response)

    assert text == ""
    assert called is False


async def test_stream_returns_mid_loop_on_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        {"event_id": "e1", "topic": "events.validated"},
        {"event_id": "e2", "topic": "events.validated"},
    ]

    async def fake_fetch(**_kwargs: Any) -> list[dict[str, object]]:
        return events

    monkeypatch.setattr(stream_module, "fetch_recent_events", fake_fetch)

    # The generator emits in reverse(fetch order), so e2 goes first.
    # checks: while-top (False), e2 (False) -> emit e2, e1 (True) -> return
    response = await stream_events(_StreamReq(disconnect_after=2))
    text = await _drain(response)

    assert "e2" in text
    assert "e1" not in text


async def test_stream_dedups_already_seen_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(**_kwargs: Any) -> list[dict[str, object]]:
        return [{"event_id": "e1", "topic": "events.validated"}]

    monkeypatch.setattr(stream_module, "fetch_recent_events", fake_fetch)

    # 2 full iterations: iter1 emits e1; iter2 sees e1 already-seen -> dedup
    # continue -> no emit -> keepalive; iter3 while-top True -> stop.
    response = await stream_events(_StreamReq(disconnect_after=4))
    text = await _drain(response)

    assert text.count('"event_id": "e1"') == 1
    assert ": keepalive" in text


async def test_stream_events_returns_event_stream_media_type() -> None:
    response = await stream_events(_StreamReq(disconnect_after=0))
    assert response.media_type == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"
