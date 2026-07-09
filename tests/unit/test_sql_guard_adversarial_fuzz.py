"""S12 — adversarial NL-SQL guard fuzz (offline, no DuckDB execution).

Hypothesis-driven mutations around the historical bypass classes:
schema-qualified tables, forbidden function names, multi-statement,
and DML nested under SELECT. Complements the fixed matrix in
``test_sql_guard.py`` and the live CH transpile matrix in
``test_clickhouse_backend.py``.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.serving.semantic_layer.sql_guard import UnsafeSQLError, validate_nl_sql

ALLOWED = {"orders_v2", "users_enriched", "products_current", "sessions_aggregated"}

FORBIDDEN_FUNCS = (
    "current_setting",
    "load_extension",
    "install_extension",
    "getenv",
    "system",
    "shell",
    "exec",
    "query_table",
    "read_csv",
    "read_parquet",
    "read_file",
)


@given(
    tenant=st.sampled_from(["acme", "victim", "other_tenant", "main"]),
    table=st.sampled_from(sorted(ALLOWED)),
)
@settings(max_examples=40, deadline=None)
def test_schema_qualified_always_rejected(tenant: str, table: str) -> None:
    sql = f'SELECT * FROM "{tenant}"."{table}"'
    with pytest.raises(UnsafeSQLError, match="Schema-qualified"):
        validate_nl_sql(sql, ALLOWED)


@given(func=st.sampled_from(FORBIDDEN_FUNCS))
@settings(max_examples=30, deadline=None)
def test_forbidden_functions_rejected_in_projection(func: str) -> None:
    sql = f"SELECT {func}('x') AS v FROM orders_v2"
    with pytest.raises(UnsafeSQLError, match="Forbidden function"):
        validate_nl_sql(sql, ALLOWED)


@given(
    func=st.sampled_from(FORBIDDEN_FUNCS),
    table=st.sampled_from(sorted(ALLOWED)),
)
@settings(max_examples=30, deadline=None)
def test_forbidden_functions_rejected_in_filter(func: str, table: str) -> None:
    sql = f"SELECT * FROM {table} WHERE {func}('x') IS NOT NULL"
    with pytest.raises(UnsafeSQLError, match="Forbidden function"):
        validate_nl_sql(sql, ALLOWED)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM orders_v2; SELECT * FROM users_enriched",
        "WITH x AS (UPDATE orders_v2 SET status='x' RETURNING id) SELECT * FROM x",
        "WITH x AS (DELETE FROM orders_v2 RETURNING id) SELECT * FROM x",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM postgres_scan('host=x')",
    ],
)
def test_fixed_smuggle_shapes_still_rejected(sql: str) -> None:
    with pytest.raises(UnsafeSQLError):
        validate_nl_sql(sql, ALLOWED)


@given(
    table=st.sampled_from(sorted(ALLOWED)),
    limit=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=20, deadline=None)
def test_simple_allowed_selects_pass(table: str, limit: int) -> None:
    validate_nl_sql(f"SELECT * FROM {table} LIMIT {limit}", ALLOWED)
