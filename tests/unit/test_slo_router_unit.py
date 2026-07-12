"""Unit coverage for ``src.serving.api.routers.slo`` — SLO reporting.

The live HTTP path is covered by the integration suite; these tests pin the
router's own logic at the unit layer: the SLI computation (``_sli`` — the
share of good units among valid units, audit P2-2), burn rates and the
error-budget helper, ``load_slos`` config parsing (tmp files), the
schema-adaptive journal paths (against a real in-memory DuckDB), and the
``get_slos`` healthy/at_risk/breached/unknown status assembly.

The measurements moved behind ``JournalReader`` (audit P0-3): they used to run
on the router's own DuckDB cursor, so a ClickHouse deployment computed its error
budget from an embedded store nothing was writing to. Audit P2-2 then replaced
the rescaled point aggregates (``threshold / measured`` is not a share of good
events) with real SLIs; the point aggregates survive as ``diagnostic``.
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
    _burn_rate,
    _diagnostic,
    _error_budget_remaining,
    _sli,
    _tenant_id,
    get_slo_config_path,
    get_slos,
    load_slos,
)
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.semantic_layer.journal import JournalReader


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


def test_tenant_id_from_request_state_then_key_then_none() -> None:
    assert _tenant_id(SimpleNamespace(state=SimpleNamespace(tenant_id="acme"))) == "acme"
    via_key = SimpleNamespace(
        state=SimpleNamespace(tenant_id=None, tenant_key=SimpleNamespace(tenant="beta"))
    )
    assert _tenant_id(via_key) == "beta"
    assert _tenant_id(SimpleNamespace(state=SimpleNamespace(tenant_id=None))) is None


def test_error_budget_remaining_branches() -> None:
    # unknown SLI -> unknown budget, never 0.0 (audit P2-2)
    assert _error_budget_remaining(0.99, None) is None
    # target >= 1.0 collapses to met/unmet
    assert _error_budget_remaining(1.0, 1.0) == 1.0
    assert _error_budget_remaining(1.0, 0.9) == 0.0
    # target 0.99, current 1.0 -> full budget; current 0.98 -> overspent
    assert _error_budget_remaining(0.99, 1.0) == 1.0
    assert _error_budget_remaining(0.99, 0.98) == 0.0


def test_burn_rate_is_budget_spend_speed() -> None:
    # burning exactly the budget over the window
    assert _burn_rate(0.99, 0.99) == 1.0
    # 10x the budget
    assert _burn_rate(0.99, 0.90) == pytest.approx(10.0)
    # empty window -> unknown; a 100% target leaves no budget to rate
    assert _burn_rate(0.99, None) is None
    assert _burn_rate(1.0, 0.5) is None


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


# ── journal-backed SLI paths (real in-memory DuckDB) ─────────────


def _conn(schema: str, inserts: list[str]) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(schema)
    for stmt in inserts:
        connection.execute(stmt)
    return connection


def _journal(conn: duckdb.DuckDBPyConnection) -> JournalReader:
    return JournalReader(DuckDBBackend(db_path=":memory:", connection=conn))


def _req(conn: duckdb.DuckDBPyConnection, *, tenant_id: Any = None) -> SimpleNamespace:
    engine = SimpleNamespace(journal=_journal(conn))
    app = SimpleNamespace(state=SimpleNamespace(query_engine=engine))
    return SimpleNamespace(app=app, state=SimpleNamespace(tenant_id=tenant_id, tenant_key=None))


@pytest.fixture
def full_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    # Staggered timestamps: the freshness SLI is time-weighted, so the fixture
    # must span observable time, not land three rows on the same NOW().
    connection = _conn(
        """
        CREATE TABLE pipeline_events (
            event_id VARCHAR, topic VARCHAR, tenant_id VARCHAR,
            processed_at TIMESTAMP, latency_ms DOUBLE, status_code INTEGER
        )
        """,
        [
            "INSERT INTO pipeline_events VALUES ('e1','orders.raw','acme',"
            " NOW() - INTERVAL '90 seconds', 100.0, 200)",
            "INSERT INTO pipeline_events VALUES ('e2','orders.raw','acme',"
            " NOW() - INTERVAL '60 seconds', 300.0, 500)",
            "INSERT INTO pipeline_events VALUES ('e3','orders.raw','acme',"
            " NOW() - INTERVAL '30 seconds', 200.0, 200)",
        ],
    )
    try:
        yield connection
    finally:
        connection.close()


def test_journal_time_column_prefers_processed_at_then_created_at_then_none() -> None:
    for schema, expected in (
        (
            "CREATE TABLE pipeline_events (processed_at TIMESTAMP, created_at TIMESTAMP)",
            "processed_at",
        ),
        ("CREATE TABLE pipeline_events (created_at TIMESTAMP)", "created_at"),
        ("CREATE TABLE pipeline_events (event_id VARCHAR)", None),
    ):
        conn = _conn(schema, [])
        try:
            assert _journal(conn).time_column() == expected
        finally:
            conn.close()


def test_a_tenant_gets_nothing_from_a_journal_that_cannot_scope_by_tenant() -> None:
    # No tenant_id column and a tenant that is not 'default': the read must
    # return nothing rather than every tenant's rows.
    conn = _conn(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)",
        ["INSERT INTO pipeline_events VALUES ('e1','events.deadletter', NOW())"],
    )
    try:
        journal = _journal(conn)

        foreign = journal.event_counts(window="30 days", tenant_id="acme")
        assert foreign is not None
        assert foreign.total == 0

        # 'default' is the unscoped legacy tenant and still sees the row.
        counts = journal.event_counts(window="30 days", tenant_id="default")
        assert counts is not None
        assert counts.total == 1
    finally:
        conn.close()


def test_sli_unknown_when_no_time_column() -> None:
    conn = _conn("CREATE TABLE pipeline_events (event_id VARCHAR)", [])
    try:
        assert _sli(_journal(conn), _definition(), None, "30 days") == (None, None, None)
    finally:
        conn.close()


def test_latency_sli_is_the_share_under_threshold(full_conn: duckdb.DuckDBPyConnection) -> None:
    # Latencies 100/300/200. Threshold 500: all three good. Threshold 150:
    # one good of three — the SLI moves with HOW MANY were slow, which is
    # exactly what threshold/p95 could not express (audit P2-2).
    share, good, valid = _sli(_journal(full_conn), _definition(), None, "30 days")
    assert (share, good, valid) == (1.0, 3.0, 3.0)

    share, good, valid = _sli(_journal(full_conn), _definition(threshold=150.0), None, "30 days")
    assert share == pytest.approx(1.0 / 3.0)
    assert (good, valid) == (1.0, 3.0)


def test_latency_sli_unknown_without_latency_column() -> None:
    conn = _conn(
        "CREATE TABLE pipeline_events (event_id VARCHAR, processed_at TIMESTAMP)",
        ["INSERT INTO pipeline_events VALUES ('e1', NOW())"],
    )
    try:
        assert _sli(_journal(conn), _definition(), None, "30 days") == (None, None, None)
    finally:
        conn.close()


def test_freshness_sli_is_time_weighted(full_conn: duckdb.DuckDBPyConnection) -> None:
    # Events at now-90s/-60s/-30s. The tail runs to the store's NOW() at
    # query time, so expectations are derived from the ACTUAL observed span
    # (valid = 90 + drift) — a loaded machine stalling between fixture and
    # query must not fail the test.
    definition = _definition(measurement="freshness_seconds", threshold=45.0)
    share, good, valid = _sli(_journal(full_conn), definition, None, "7 days")
    assert valid is not None
    assert valid >= 90.0 - 2.0
    # Two fully-fresh 30s gaps + a tail capped at the 45s threshold.
    expected_good = 30.0 + 30.0 + min(valid - 60.0, 45.0)
    assert good == pytest.approx(expected_good, abs=2.0)
    assert share == pytest.approx(expected_good / valid, abs=0.03)

    # Threshold 20s: each 30s gap contributes only 20 fresh seconds, and the
    # tail is capped at 20 too — 60 fresh regardless of drift.
    definition = _definition(measurement="freshness_seconds", threshold=20.0)
    share, good, valid = _sli(_journal(full_conn), definition, None, "7 days")
    assert good == pytest.approx(60.0, abs=2.0)
    assert valid is not None
    assert share == pytest.approx(60.0 / valid, abs=0.03)


def test_error_sli_with_status_code(full_conn: duckdb.DuckDBPyConnection) -> None:
    definition = _definition(measurement="error_rate_percent", threshold=1.0)
    share, good, valid = _sli(_journal(full_conn), definition, None, "30 days")
    # 1 of 3 rows has status_code >= 500
    assert share == pytest.approx(2.0 / 3.0)
    assert (good, valid) == (2.0, 3.0)


def test_error_sli_deadletter_fallback() -> None:
    conn = _conn(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)",
        [
            "INSERT INTO pipeline_events VALUES ('e1','orders.raw', NOW())",
            "INSERT INTO pipeline_events VALUES ('e2','events.deadletter', NOW())",
        ],
    )
    try:
        definition = _definition(measurement="error_rate_percent", threshold=1.0)
        share, good, valid = _sli(_journal(conn), definition, None, "30 days")
        assert share == pytest.approx(0.5)
        assert (good, valid) == (1.0, 2.0)
    finally:
        conn.close()


def test_sli_unknown_when_no_rows_in_window() -> None:
    conn = _conn(
        "CREATE TABLE pipeline_events (event_id VARCHAR, topic VARCHAR, processed_at TIMESTAMP)",
        [],
    )
    try:
        for measurement in ("freshness_seconds", "error_rate_percent"):
            definition = _definition(measurement=measurement, threshold=600.0)
            assert _sli(_journal(conn), definition, None, "30 days") == (None, None, None)
    finally:
        conn.close()


def test_sli_unsupported_measurement_raises_500(full_conn: duckdb.DuckDBPyConnection) -> None:
    definition = _definition(measurement="made_up_metric")
    with pytest.raises(HTTPException) as exc:
        _sli(_journal(full_conn), definition, None, "30 days")
    assert exc.value.status_code == 500


def test_diagnostic_keeps_the_point_aggregates(full_conn: duckdb.DuckDBPyConnection) -> None:
    journal = _journal(full_conn)
    p95 = _diagnostic(journal, _definition(), None, "30 days")
    assert p95["p95_latency_ms"] is not None
    assert p95["p95_latency_ms"] > 0

    fresh = _diagnostic(
        journal, _definition(measurement="freshness_seconds", threshold=600.0), None, "7 days"
    )
    assert fresh["age_seconds"] is not None
    assert fresh["age_seconds"] >= 0.0

    errors = _diagnostic(
        journal, _definition(measurement="error_rate_percent", threshold=1.0), None, "30 days"
    )
    assert errors["error_rate_percent"] == pytest.approx(100.0 / 3.0)


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
        assert status.current is not None
        assert 0.0 <= status.current <= 1.0
        assert status.status in {"healthy", "at_risk", "breached"}
        assert status.good is not None
        assert status.valid is not None
        assert set(status.burn_rates) == {"1h", "6h", "3d"}
    assert response.slos[0].unit == "events"
    assert response.slos[0].diagnostic["p95_latency_ms"] is not None
    assert response.slos[1].unit == "seconds"


async def test_get_slos_marks_at_risk_when_budget_exhausted(tmp_path: Path) -> None:
    # 10 events, 1 with status_code >= 500 -> SLI 0.90. With target 0.90 the
    # SLO is met (not breached) but the error budget is fully consumed ->
    # at_risk.
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


async def test_get_slos_pages_on_a_fast_burn_even_with_budget_left(tmp_path: Path) -> None:
    # The multi-window case the single number hides: a month of clean traffic
    # keeps the 30d SLI above target, but the last hour is burning budget at
    # 25x — (1h, 6h) both over 14.4 -> at_risk, not healthy (audit P2-2).
    inserts = [
        f"INSERT INTO pipeline_events VALUES ('old{i}','orders.raw','acme',"
        f" NOW() - INTERVAL '10 days', 100.0, 200)"
        for i in range(1000)
    ] + [
        f"INSERT INTO pipeline_events VALUES ('new{i}','orders.raw','acme',"
        f" NOW() - INTERVAL '10 minutes', 100.0, {500 if i < 2 else 200})"
        for i in range(8)
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
        "    description: under 1% errors\n"
        "    target: 0.99\n"
        "    measurement: error_rate_percent\n"
        "    threshold: 1\n"
        "    window_days: 30\n",
        encoding="utf-8",
    )
    try:
        req = _req(conn)
        req.app.state.slo_config_path = str(config)
        response = await get_slos(req)
        slo = response.slos[0]
        assert slo.current is not None
        assert slo.current > 0.99  # the window looks fine
        assert slo.burn_rates["1h"] == pytest.approx(25.0)
        assert slo.burn_rates["6h"] == pytest.approx(25.0)
        assert slo.status == "at_risk"  # ...and the burn pair still pages
    finally:
        conn.close()


async def test_get_slos_reports_unknown_when_measurement_missing(tmp_path: Path) -> None:
    # A schema with no time column -> no valid units -> unknown, NOT breached:
    # an empty journal is missing data, not a missed target (audit P2-2).
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
        assert response.slos[0].status == "unknown"
        assert response.slos[0].current is None
        assert response.slos[0].error_budget_remaining is None
    finally:
        conn.close()
