"""Unit coverage for ``src.serving.api.routers.slo`` — SLO compliance reporting.

The live HTTP path is covered by the integration suite; these tests pin the
router's own logic at the unit layer: the pure compliance/error-budget/tenant
helpers, ``load_slos`` config parsing (tmp files), the schema-adaptive
``_measurement_value`` queries (p95 latency / freshness / error rate, against a
real in-memory DuckDB), and the ``get_slos`` healthy/at_risk/breached status
assembly.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest
from fastapi import HTTPException

from src.serving.api.routers.slo import (
    SLODefinition,
    _current_compliance,
    _error_budget_remaining,
    _measurement_value,
    _tenant_filter,
    _tenant_id,
    _time_column,
    get_slo_config_path,
    get_slos,
    load_slos,
)


def _definition(**overrides: Any) -> SLODefinition:
    base: dict[str, Any] = {
        "name": "latency",
        "description": "p95 latency",
        "target": 0.99,
        "measurement": "p95_latency_ms",
        "threshold": 500.0,
        "window_days": 30,
    }
    base.update(overrides)
    return SLODefinition(**base)


# ── pure helpers ─────────────────────────────────────────────────


def test_time_column_prefers_processed_at_then_created_at_then_none() -> None:
    assert _time_column({"processed_at", "created_at"}) == "processed_at"
    assert _time_column({"created_at"}) == "created_at"
    assert _time_column({"event_id"}) is None


def test_tenant_id_from_request_state_then_key_then_none() -> None:
    assert _tenant_id(SimpleNamespace(state=SimpleNamespace(tenant_id="acme"))) == "acme"
    via_key = SimpleNamespace(
        state=SimpleNamespace(tenant_id=None, tenant_key=SimpleNamespace(tenant="beta"))
    )
    assert _tenant_id(via_key) == "beta"
    assert _tenant_id(SimpleNamespace(state=SimpleNamespace(tenant_id=None))) is None


def test_tenant_filter_branches() -> None:
    assert _tenant_filter({"tenant_id"}, None) == ("", [])
    assert _tenant_filter({"tenant_id"}, "acme") == (
        " AND COALESCE(tenant_id, 'default') = ?",
        ["acme"],
    )
    assert _tenant_filter(set(), "acme") == (" AND 1 = 0", [])
    assert _tenant_filter(set(), "default") == ("", [])


def test_current_compliance_branches() -> None:
    assert _current_compliance(_definition(), None) == 0.0
    # error_rate: 1 - measured/100
    assert _current_compliance(_definition(measurement="error_rate_percent"), 5.0) == 0.95
    # threshold-based: measured under threshold -> full compliance
    assert _current_compliance(_definition(threshold=500.0), 200.0) == 1.0
    # over threshold -> ratio
    assert _current_compliance(_definition(threshold=500.0), 1000.0) == 0.5


def test_error_budget_remaining_branches() -> None:
    # target >= 1.0 collapses to met/unmet
    assert _error_budget_remaining(1.0, 1.0) == 1.0
    assert _error_budget_remaining(1.0, 0.9) == 0.0
    # target 0.99, current 1.0 -> full budget; current 0.99 -> none consumed boundary
    assert _error_budget_remaining(0.99, 1.0) == 1.0
    assert _error_budget_remaining(0.99, 0.98) == 0.0


# ── load_slos / get_slo_config_path ──────────────────────────────


def test_load_slos_missing_file_raises_503(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        load_slos(tmp_path / "nope.yaml")
    assert exc.value.status_code == 503


def test_load_slos_empty_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "slo.yaml"
    path.write_text("   \n", encoding="utf-8")
    assert load_slos(path) == []


def test_load_slos_parses_definitions(tmp_path: Path) -> None:
    path = tmp_path / "slo.yaml"
    path.write_text(
        "slos:\n"
        "  - name: latency\n"
        "    description: p95\n"
        "    target: 0.99\n"
        "    measurement: p95_latency_ms\n"
        "    threshold: 500\n"
        "    window_days: 30\n",
        encoding="utf-8",
    )
    slos = load_slos(path)
    assert [s.name for s in slos] == ["latency"]


def test_get_slo_config_path_uses_state_override_then_default() -> None:
    app = SimpleNamespace(state=SimpleNamespace(slo_config_path="configured-slo.yaml"))
    assert get_slo_config_path(app) == Path("configured-slo.yaml")
    bare = SimpleNamespace(state=SimpleNamespace())
    assert isinstance(get_slo_config_path(bare), Path)


# ── DuckDB-backed measurement paths ──────────────────────────────


def _conn(schema: str, inserts: list[str]) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(schema)
    for stmt in inserts:
        connection.execute(stmt)
    return connection


def _req(conn: duckdb.DuckDBPyConnection, *, tenant_id: Any = None) -> SimpleNamespace:
    app = SimpleNamespace(state=SimpleNamespace(query_engine=SimpleNamespace(_conn=conn)))
    return SimpleNamespace(app=app, state=SimpleNamespace(tenant_id=tenant_id, tenant_key=None))


@pytest.fixture
def full_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = _conn(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR,
            processed_at TIMESTAMP, latency_ms DOUBLE, status_code INTEGER
        )
        """,
        [
            "INSERT INTO pipeline_events VALUES ('e1','orders.raw','acme', NOW(), 100.0, 200)",
            "INSERT INTO pipeline_events VALUES ('e2','orders.raw','acme', NOW(), 300.0, 500)",
            "INSERT INTO pipeline_events VALUES ('e3','orders.raw','acme', NOW(), 200.0, 200)",
        ],
    )
    try:
        yield connection
    finally:
        connection.close()


def test_measurement_value_none_when_no_time_column(full_conn: duckdb.DuckDBPyConnection) -> None:
    assert _measurement_value(_req(full_conn), _definition(), set(), None) is None


def test_measurement_p95_latency(full_conn: duckdb.DuckDBPyConnection) -> None:
    cols = {"processed_at", "latency_ms", "tenant_id", "status_code", "topic"}
    value = _measurement_value(_req(full_conn), _definition(), cols, "processed_at")
    assert value is not None
    assert value > 0


def test_measurement_p95_latency_none_without_latency_column() -> None:
    conn = _conn(
        "CREATE TABLE pipeline_events (event_id VARCHAR, processed_at TIMESTAMP)",
        ["INSERT INTO pipeline_events VALUES ('e1', NOW())"],
    )
    try:
        assert (
            _measurement_value(_req(conn), _definition(), {"processed_at"}, "processed_at") is None
        )
    finally:
        conn.close()


def test_measurement_freshness(full_conn: duckdb.DuckDBPyConnection) -> None:
    definition = _definition(measurement="freshness_seconds", threshold=600.0)
    cols = {"processed_at", "latency_ms", "tenant_id", "status_code", "topic"}
    value = _measurement_value(_req(full_conn), definition, cols, "processed_at")
    assert value is not None
    assert value >= 0.0


def test_measurement_error_rate_with_status_code(full_conn: duckdb.DuckDBPyConnection) -> None:
    definition = _definition(measurement="error_rate_percent", threshold=1.0)
    cols = {"processed_at", "latency_ms", "tenant_id", "status_code", "topic"}
    value = _measurement_value(_req(full_conn), definition, cols, "processed_at")
    # 1 of 3 rows has status_code >= 500
    assert value == pytest.approx(100.0 / 3.0)


def test_measurement_error_rate_deadletter_fallback() -> None:
    conn = _conn(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)",
        [
            "INSERT INTO pipeline_events VALUES ('e1','orders.raw', NOW())",
            "INSERT INTO pipeline_events VALUES ('e2','events.deadletter', NOW())",
        ],
    )
    try:
        definition = _definition(measurement="error_rate_percent", threshold=1.0)
        value = _measurement_value(
            _req(conn), definition, {"processed_at", "topic"}, "processed_at"
        )
        assert value == pytest.approx(50.0)
    finally:
        conn.close()


def test_measurement_freshness_none_when_no_rows_in_window() -> None:
    conn = _conn("CREATE TABLE pipeline_events (event_id VARCHAR, processed_at TIMESTAMP)", [])
    try:
        definition = _definition(measurement="freshness_seconds", threshold=600.0)
        assert _measurement_value(_req(conn), definition, {"processed_at"}, "processed_at") is None
    finally:
        conn.close()


def test_measurement_error_rate_deadletter_none_when_no_rows() -> None:
    conn = _conn(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)", []
    )
    try:
        definition = _definition(measurement="error_rate_percent", threshold=1.0)
        assert (
            _measurement_value(_req(conn), definition, {"processed_at", "topic"}, "processed_at")
            is None
        )
    finally:
        conn.close()


def test_measurement_unsupported_raises_500(full_conn: duckdb.DuckDBPyConnection) -> None:
    definition = _definition(measurement="made_up_metric")
    cols = {"processed_at", "latency_ms"}
    with pytest.raises(HTTPException) as exc:
        _measurement_value(_req(full_conn), definition, cols, "processed_at")
    assert exc.value.status_code == 500


# ── get_slos end-to-end ──────────────────────────────────────────


async def test_get_slos_assembles_statuses(
    full_conn: duckdb.DuckDBPyConnection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "slo.yaml"
    config.write_text(
        "slos:\n"
        "  - name: latency\n"
        "    description: p95 latency under 500ms\n"
        "    target: 0.99\n"
        "    measurement: p95_latency_ms\n"
        "    threshold: 500\n"
        "    window_days: 30\n"
        "  - name: freshness\n"
        "    description: data fresh within 10m\n"
        "    target: 0.95\n"
        "    measurement: freshness_seconds\n"
        "    threshold: 600\n"
        "    window_days: 7\n",
        encoding="utf-8",
    )
    req = _req(full_conn)
    req.app.state.slo_config_path = str(config)

    response = await get_slos(req)

    assert [s.name for s in response.slos] == ["latency", "freshness"]
    for status in response.slos:
        assert 0.0 <= status.current <= 1.0
        assert status.status in {"healthy", "at_risk", "breached"}


async def test_get_slos_marks_at_risk_when_budget_exhausted(tmp_path: Path) -> None:
    # 10 events, 1 with status_code >= 500 -> 10% error rate -> current 0.90.
    # With target 0.90 the SLO is met (not breached) but the error budget is
    # fully consumed -> at_risk.
    inserts = [
        f"INSERT INTO pipeline_events VALUES ('e{i}','orders.raw','acme', NOW(), 100.0,"
        f" {500 if i == 0 else 200})"
        for i in range(10)
    ]
    conn = _conn(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR,
            processed_at TIMESTAMP, latency_ms DOUBLE, status_code INTEGER
        )
        """,
        inserts,
    )
    config = tmp_path / "slo.yaml"
    config.write_text(
        "slos:\n"
        "  - name: error_rate\n"
        "    description: under 10% errors\n"
        "    target: 0.90\n"
        "    measurement: error_rate_percent\n"
        "    threshold: 1\n"
        "    window_days: 30\n",
        encoding="utf-8",
    )
    try:
        req = _req(conn)
        req.app.state.slo_config_path = str(config)
        response = await get_slos(req)
        assert response.slos[0].current == 0.9
        assert response.slos[0].status == "at_risk"
    finally:
        conn.close()


async def test_get_slos_marks_breached_when_measurement_missing(tmp_path: Path) -> None:
    # A schema with no time column -> measurement None -> compliance 0 -> breached.
    conn = _conn("CREATE TABLE pipeline_events (event_id VARCHAR)", [])
    config = tmp_path / "slo.yaml"
    config.write_text(
        "slos:\n"
        "  - name: latency\n"
        "    description: p95\n"
        "    target: 0.99\n"
        "    measurement: p95_latency_ms\n"
        "    threshold: 500\n"
        "    window_days: 30\n",
        encoding="utf-8",
    )
    try:
        req = _req(conn)
        req.app.state.slo_config_path = str(config)
        response = await get_slos(req)
        assert response.slos[0].status == "breached"
        assert response.slos[0].current == 0.0
    finally:
        conn.close()
