"""Unit tests for the daily batch DAG assets (src/orchestration/dags/daily_batch).

These exercise the DuckDB-backed aggregation/quality assets in local mode and
pin the None-safety of the `fetchone()` row lookups that strict mypy surfaced.
"""

import duckdb
import pytest
from dagster import build_asset_context

from src.orchestration.dags import daily_batch


@pytest.fixture
def file_db(tmp_path, monkeypatch):
    """Point the DAG at a file-backed DuckDB so assets share table state.

    The assets open their own connection per call via `_get_conn()`, so an
    in-memory DB would not retain seeded tables across calls.
    """
    db_path = tmp_path / "daily_batch.duckdb"
    monkeypatch.setattr(daily_batch, "DB_PATH", str(db_path))
    return db_path


def test_daily_product_metrics_counts_rows(file_db):
    conn = duckdb.connect(str(file_db))
    conn.execute("CREATE TABLE products_current (product_id VARCHAR)")
    conn.execute("INSERT INTO products_current VALUES ('a'), ('b'), ('c')")
    conn.close()

    result = daily_batch.daily_product_metrics(build_asset_context())

    assert result == {"products_updated": 3}


def test_daily_quality_report_aggregates_checks(file_db):
    conn = duckdb.connect(str(file_db))
    conn.execute("CREATE TABLE products_current (product_id VARCHAR)")
    conn.execute("INSERT INTO products_current VALUES ('a'), ('b')")
    conn.execute("CREATE TABLE pipeline_events (topic VARCHAR)")
    conn.execute(
        "INSERT INTO pipeline_events VALUES "
        "('events.orders'), ('events.orders'), ('events.deadletter')"
    )
    conn.close()

    result = daily_batch.daily_quality_report(build_asset_context())

    checks = result["checks"]
    assert checks["products_current"] == {"rows": 2, "status": "ok"}
    # Tables that do not exist are reported as errors, not crashes.
    assert checks["orders_v2"]["status"].startswith("error")
    assert checks["dead_letter_ratio"] == {"value": pytest.approx(1 / 3, abs=1e-4)}
    assert result["checks_failed"] == 3


def test_daily_quality_report_handles_missing_pipeline_events(file_db):
    conn = duckdb.connect(str(file_db))
    conn.execute("CREATE TABLE products_current (product_id VARCHAR)")
    conn.close()

    result = daily_batch.daily_quality_report(build_asset_context())

    # No pipeline_events table -> dead-letter ratio is unavailable, not a crash.
    assert result["checks"]["dead_letter_ratio"] == {"value": None}


def test_iceberg_assets_are_noops_in_local_mode(monkeypatch):
    monkeypatch.setattr(daily_batch, "DB_PATH", ":memory:")

    expiry = daily_batch.iceberg_snapshot_expiry(build_asset_context())
    compaction = daily_batch.iceberg_compaction(build_asset_context())

    assert expiry == {"mode": "local", "tables_processed": 0}
    assert compaction == {"mode": "local", "tables_compacted": 0}
