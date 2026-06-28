"""Live ClickHouse coverage for the sqlglot transpile path (H-C2).

These tests run against a REAL ClickHouse server and close the gap the unit
suite cannot: unit tests assert what the transpiled SQL *looks like*, these
assert ClickHouse actually *executes* it — every semantic-layer metric
template, the demo DDL bypass, EXPLAIN wrapping, and the literal-preservation
property that motivated H-C2.

Gated on ``CLICKHOUSE_LIVE_HOST``: CI provides a `clickhouse` service
container on the test-integration job; locally, point it at any disposable
server (e.g. an ssh tunnel to a scratch container). The suite is read/write
but only inside the configured database, using the same
``initialize_demo_data()`` seed the product demo uses.
"""

from __future__ import annotations

import os

import pytest

from src.serving.backends.clickhouse_backend import ClickHouseBackend
from src.serving.semantic_layer.catalog import DataCatalog

LIVE_HOST = os.getenv("CLICKHOUSE_LIVE_HOST")

pytestmark = pytest.mark.skipif(
    not LIVE_HOST,
    reason="CLICKHOUSE_LIVE_HOST not configured (live ClickHouse required)",
)


@pytest.fixture(scope="module")
def backend() -> ClickHouseBackend:
    instance = ClickHouseBackend(
        host=LIVE_HOST or "localhost",
        port=int(os.getenv("CLICKHOUSE_LIVE_PORT", "8123")),
        user=os.getenv("CLICKHOUSE_LIVE_USER", "agentflow"),
        password=os.getenv("CLICKHOUSE_LIVE_PASSWORD", "agentflow"),
        database=os.getenv("CLICKHOUSE_LIVE_DATABASE", "agentflow"),
    )
    instance.initialize_demo_data()
    return instance


def test_health_reports_ok_against_live_server(backend):
    report = backend.health()

    assert report["status"] == "ok", report


def test_demo_ddl_bypass_creates_tables(backend):
    # initialize_demo_data sends native ClickHouse DDL with translate=False —
    # DESCRIBE (also untranslated) must see the schema it created.
    assert {"order_id", "user_id", "status", "total_amount"} <= backend.table_columns("orders_v2")
    assert {"event_id", "topic", "tenant_id"} <= backend.table_columns("pipeline_events")


def _metric_templates() -> list[tuple[str, str]]:
    catalog = DataCatalog()
    rendered = []
    for name, metric in sorted(catalog.metrics.items()):
        template = metric.sql_template
        sql = template.format(window="1 hour") if "{window}" in template else template
        rendered.append((name, sql))
    return rendered


@pytest.mark.parametrize(("metric_name", "sql"), _metric_templates())
def test_every_catalog_metric_template_executes_live(backend, metric_name, sql):
    """The exact DuckDB-flavored SQL the semantic layer emits must transpile
    into something ClickHouse executes: NOW()/INTERVAL arithmetic, the
    FILTER→countIf rewrite, CAST→Float64, NULLIF and CASE WHEN forms."""
    rows = backend.execute(sql)

    assert len(rows) == 1, f"{metric_name}: expected a single aggregate row, got {rows!r}"
    assert "value" in rows[0], f"{metric_name}: missing value column in {rows[0]!r}"


def test_seeded_metrics_return_plausible_values(backend):
    # The demo seed has 8 orders in the last ~2h (1 cancelled) and 2 of 10
    # pipeline events on the deadletter topic.
    catalog = DataCatalog()

    revenue = backend.scalar(catalog.metrics["revenue"].sql_template.format(window="24 hours"))
    assert revenue is not None
    assert float(revenue) > 0

    order_count = backend.scalar(
        catalog.metrics["order_count"].sql_template.format(window="24 hours")
    )
    # order_count now excludes cancelled orders (aligned with revenue/avg;
    # audit_28_06_26.md #M4): 8 seeded - 1 cancelled = 7.
    assert int(order_count) == 7

    error_rate = backend.scalar(
        catalog.metrics["error_rate"].sql_template.format(window="24 hours")
    )
    assert error_rate is not None
    assert 0.0 < float(error_rate) < 1.0


def test_as_of_anchor_literal_form_executes_live(backend):
    # metric_queries substitutes NOW() with CAST('<ts>' AS TIMESTAMP) on
    # non-DuckDB backends — that literal-anchor form must execute.
    value = backend.scalar(
        "SELECT COUNT(*) AS value FROM orders_v2 "
        "WHERE created_at >= CAST('2020-01-01 00:00:00' AS TIMESTAMP)"
    )

    assert int(value) == 8


def test_string_literal_with_dialect_tokens_round_trips(backend):
    # The H-C2 regression class: dialect tokens inside a string literal must
    # reach the server byte-identical, not half-rewritten.
    sentinel = "price ::FLOAT NOW() COUNT(*) FILTER tag"

    rows = backend.execute(f"SELECT '{sentinel}' AS s")

    assert rows == [{"s": sentinel}]


def test_explain_wraps_transpiled_query_live(backend):
    plan = backend.explain(
        "SELECT COUNT(*) FILTER (WHERE status = 'pending') AS pending FROM orders_v2"
    )

    assert plan, "EXPLAIN must return at least one plan line"
    assert any("Expression" in line or "Read" in line for (line,) in plan)


def test_entity_lookup_form_executes_live(backend):
    rows = backend.execute("SELECT * FROM orders_v2 WHERE order_id = 'ORD-20260404-1001' LIMIT 1")

    assert len(rows) == 1
    assert rows[0]["user_id"] == "USR-10001"
