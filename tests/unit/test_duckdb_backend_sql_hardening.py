"""Regression tests for H-C1 (audit_kimi_25_05_26): f-string SQL paths in
``DuckDBBackend.table_columns`` and ``DuckDBBackend.explain`` must reject
non-identifier table names and non-SELECT explain inputs respectively, so a
caller cannot smuggle ``"; DROP TABLE ..."`` style payloads through the
catalog/query surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.serving.backends import BackendExecutionError, BackendMissingTableError
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.duckdb_connection import connect_duckdb


@pytest.fixture
def backend(tmp_path: Path) -> DuckDBBackend:
    db_path = tmp_path / "hardening.duckdb"
    conn = connect_duckdb(str(db_path))
    conn.execute("CREATE TABLE orders (order_id VARCHAR PRIMARY KEY, status VARCHAR)")
    return DuckDBBackend(db_path=str(db_path), connection=conn)


class TestTableColumns:
    def test_accepts_bare_identifier(self, backend: DuckDBBackend) -> None:
        assert backend.table_columns("orders") == {"order_id", "status"}

    def test_accepts_schema_qualified_identifier(self, backend: DuckDBBackend) -> None:
        # 'main.orders' is the default DuckDB schema; should match the same columns.
        assert backend.table_columns("main.orders") == {"order_id", "status"}

    def test_accepts_double_quoted_identifier(self, backend: DuckDBBackend) -> None:
        # Tenant-scoped tables flow through `SQLBuilderMixin._quote_identifier`
        # and arrive here as `"schema"."table"` — see CX P1 finding from
        # session 23 audit. Regression: the validator must not reject this
        # form or tenant fail-closed in `_qualify_table` silently breaks.
        backend.connection.execute('CREATE SCHEMA IF NOT EXISTS "acme"')
        backend.connection.execute(
            'CREATE TABLE "acme"."orders_v2" (order_id VARCHAR PRIMARY KEY, status VARCHAR)'
        )
        assert backend.table_columns('"acme"."orders_v2"') == {"order_id", "status"}
        assert backend.table_columns('"acme"') == set()  # schema-only path, not a table

    @pytest.mark.parametrize(
        "name",
        [
            "orders; DROP TABLE orders",
            "orders WHERE 1=1",
            "orders --",
            "(SELECT 1)",
            "orders' UNION SELECT 1",
            "1orders",
            "schema.with.too.many.dots",
            "schema..table",
            "",
            " orders ",
        ],
    )
    def test_rejects_injection_payloads_silently(self, backend: DuckDBBackend, name: str) -> None:
        # Reject path mirrors CatalogException — return an empty column set
        # rather than 500ing — so callers see a missing-table signal and the
        # f-string never sees the malformed input.
        assert backend.table_columns(name) == set()

    def test_returns_empty_for_unknown_but_valid_identifier(self, backend: DuckDBBackend) -> None:
        assert backend.table_columns("does_not_exist") == set()


class TestExplain:
    def test_accepts_single_select(self, backend: DuckDBBackend) -> None:
        rows = backend.explain("SELECT order_id FROM orders")
        assert rows  # EXPLAIN returns at least one plan row

    def test_rejects_multi_statement(self, backend: DuckDBBackend) -> None:
        with pytest.raises(BackendExecutionError):
            backend.explain("SELECT 1; DROP TABLE orders")

    @pytest.mark.parametrize(
        "sql",
        [
            "DELETE FROM orders",
            "INSERT INTO orders VALUES ('x', 'y')",
            "UPDATE orders SET status = 'cancelled'",
            "DROP TABLE orders",
            "CREATE TABLE evil (x VARCHAR)",
        ],
    )
    def test_rejects_non_select(self, backend: DuckDBBackend, sql: str) -> None:
        with pytest.raises(BackendExecutionError):
            backend.explain(sql)

    def test_rejects_unparseable(self, backend: DuckDBBackend) -> None:
        with pytest.raises(BackendExecutionError):
            backend.explain("THIS IS NOT SQL")

    def test_raises_missing_table_for_unknown_relation(self, backend: DuckDBBackend) -> None:
        with pytest.raises(BackendMissingTableError):
            backend.explain("SELECT * FROM nonexistent_table")
