"""Unit coverage for ``src.serving.api.routers.lineage`` — provenance-chain
reconstruction for an entity.

The live HTTP path is covered by the integration suite; these tests pin the
router's own logic at the unit layer: the pure source/topic/quality helpers,
the schema-adaptive ``_fetch_matching_events`` query (against a real in-memory
DuckDB, mirroring the webhook-dispatcher unit fixture), and ``get_lineage``'s
404/403 branches plus the five-node lineage assembly.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest
from fastapi import HTTPException

from src.serving.api.routers.lineage import (
    _coerce_datetime,
    _fetch_matching_events,
    _quality_score,
    _source_system_for_entity,
    _source_topic_for_entity,
    get_lineage,
)

# ── pure helpers ─────────────────────────────────────────────────


def test_coerce_datetime_passthrough_and_naive_and_string_and_none() -> None:
    aware = datetime(2026, 6, 13, tzinfo=UTC)
    assert _coerce_datetime(aware) == aware
    assert _coerce_datetime(datetime(2026, 6, 13)).tzinfo == UTC
    assert _coerce_datetime("2026-06-13T00:00:00").tzinfo == UTC
    assert _coerce_datetime(12345) is None


def test_source_topic_for_entity_known_and_fallback() -> None:
    assert _source_topic_for_entity("order") == "orders.raw"
    assert _source_topic_for_entity("widget") == "widget.raw"


def test_source_system_for_entity_known_and_unknown() -> None:
    assert _source_system_for_entity("session") == "web_sdk"
    assert _source_system_for_entity("widget") == "unknown"


def test_quality_score_default_when_no_latencies() -> None:
    assert _quality_score([{"latency_ms": None}], default=0.7) == 0.7
    assert _quality_score([], default=None) is None


def test_quality_score_computes_and_clamps() -> None:
    # avg 200ms -> 1 - 0.2 = 0.8
    assert _quality_score([{"latency_ms": 100}, {"latency_ms": 300}]) == 0.8
    # avg 5000ms -> clamped to 0.0
    assert _quality_score([{"latency_ms": 5000}]) == 0.0


# ── fixtures for the DuckDB-backed paths ─────────────────────────


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR,
            event_type VARCHAR, entity_id VARCHAR, entity_type VARCHAR,
            processed_at TIMESTAMP, latency_ms DOUBLE
        )
        """
    )
    try:
        yield connection
    finally:
        connection.close()


def _seed(conn: duckdb.DuckDBPyConnection, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(
        "INSERT INTO pipeline_events "
        "(event_id, topic, tenant_id, event_type, entity_id, entity_type, processed_at, latency_ms)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _req(
    conn: duckdb.DuckDBPyConnection,
    *,
    entities: dict[str, Any] | None = None,
    tenant_key: Any = None,
    tenant_id: Any = None,
) -> SimpleNamespace:
    catalog = SimpleNamespace(
        entities=entities if entities is not None else {"order": SimpleNamespace(table="orders")}
    )
    app = SimpleNamespace(
        state=SimpleNamespace(catalog=catalog, query_engine=SimpleNamespace(_conn=conn))
    )
    return SimpleNamespace(
        app=app, state=SimpleNamespace(tenant_key=tenant_key, tenant_id=tenant_id)
    )


# ── _fetch_matching_events ───────────────────────────────────────


def test_fetch_returns_empty_when_no_entity_id_column() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR)")
    try:
        assert _fetch_matching_events(_req(connection), "order", "ORD-1") == []
    finally:
        connection.close()


def test_fetch_returns_matching_rows(conn: duckdb.DuckDBPyConnection) -> None:
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    _seed(
        conn,
        [
            ("e1", "orders.raw", "acme", "order.created", "ORD-1", "order", now, 100.0),
            ("e2", "orders.raw", "acme", "order.created", "ORD-2", "order", now, 100.0),
        ],
    )
    rows = _fetch_matching_events(_req(conn), "order", "ORD-1")
    assert [r["event_id"] for r in rows] == ["e1"]


def test_fetch_returns_empty_when_tenant_set_but_no_tenant_column() -> None:
    # A non-default tenant cannot be isolated on a schema without a tenant_id
    # column, so the fetch refuses to leak cross-tenant rows.
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR,"
        " entity_id VARCHAR, processed_at TIMESTAMP)"
    )
    connection.execute("INSERT INTO pipeline_events VALUES ('e1', 'orders.raw', 'ORD-1', NOW())")
    try:
        assert _fetch_matching_events(_req(connection, tenant_id="acme"), "order", "ORD-1") == []
    finally:
        connection.close()


def test_fetch_filters_by_tenant(conn: duckdb.DuckDBPyConnection) -> None:
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    _seed(
        conn,
        [
            ("e1", "orders.raw", "acme", "order.created", "ORD-1", "order", now, 100.0),
            ("e2", "orders.raw", "other", "order.created", "ORD-1", "order", now, 100.0),
        ],
    )
    rows = _fetch_matching_events(_req(conn, tenant_id="acme"), "order", "ORD-1")
    assert [r["event_id"] for r in rows] == ["e1"]


# ── get_lineage ──────────────────────────────────────────────────


async def test_get_lineage_unknown_entity_type_404(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(HTTPException) as exc:
        await get_lineage("ghost", "X", _req(conn))
    assert exc.value.status_code == 404
    assert "Unknown entity type" in exc.value.detail


async def test_get_lineage_forbidden_entity_type_403(conn: duckdb.DuckDBPyConnection) -> None:
    tenant_key = SimpleNamespace(name="agent", allowed_entity_types=["user"])
    with pytest.raises(HTTPException) as exc:
        await get_lineage("order", "ORD-1", _req(conn, tenant_key=tenant_key))
    assert exc.value.status_code == 403


async def test_get_lineage_no_events_404(conn: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(HTTPException) as exc:
        await get_lineage("order", "ORD-1", _req(conn))
    assert exc.value.status_code == 404
    assert "No lineage found" in exc.value.detail


async def test_get_lineage_rows_without_timestamps_404(conn: duckdb.DuckDBPyConnection) -> None:
    _seed(conn, [("e1", "orders.raw", "acme", "order.created", "ORD-1", "order", None, 100.0)])
    with pytest.raises(HTTPException) as exc:
        await get_lineage("order", "ORD-1", _req(conn))
    assert exc.value.status_code == 404


async def test_get_lineage_validated_assembles_five_nodes(conn: duckdb.DuckDBPyConnection) -> None:
    base = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    _seed(
        conn,
        [
            ("e1", "orders.raw", "acme", "order.created", "ORD-1", "order", base, 120.0),
            (
                "e2",
                "events.validated",
                "acme",
                "order.created",
                "ORD-1",
                "order",
                base + timedelta(seconds=1),
                None,
            ),
        ],
    )
    response = await get_lineage("order", "ORD-1", _req(conn))

    assert response.entity_type == "order"
    assert response.validated is True
    assert response.enriched is True
    assert [node.layer for node in response.lineage] == [
        "source",
        "ingestion",
        "validation",
        "enrichment",
        "serving",
    ]
    # source topic is the non-internal topic seen on the chain
    assert response.lineage[0].table_or_topic == "orders.raw"
    # serving node points at the entity's serving table
    assert response.lineage[-1].table_or_topic == "orders"
    assert response.freshness_seconds >= 0.0


async def test_get_lineage_unvalidated_marks_validation_zero(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    base = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    _seed(conn, [("e1", "orders.raw", "acme", "order.created", "ORD-1", "order", base, 50.0)])
    response = await get_lineage("order", "ORD-1", _req(conn))

    assert response.validated is False
    validation_node = next(n for n in response.lineage if n.layer == "validation")
    assert validation_node.quality_score == 0.0
