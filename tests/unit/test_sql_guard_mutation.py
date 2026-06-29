"""Narrow, duckdb-free mutation test for the sql_guard NL->SQL denylist.

This is the test the mutation gate runs against
src/serving/semantic_layer/sql_guard.py (see scripts/mutation_report.py
MODULE_TARGETS). sql_guard imports only sqlglot, so keeping this test free of the
QueryEngine/duckdb import chain lets mutmut mutate the module without dragging
duckdb's compiled subpackage into its mutants/ workspace.

Dual-context import: under the mutation harness the module is copied to the
workspace as a top-level ``serving`` package (no ``src.`` prefix, which mutmut's
trampoline rejects -- the same reason retry.py is mutated as ``agentflow.retry``
and not ``src.…``); under ordinary pytest it lives under the ``src`` package.

Every ``pytest.raises`` pins the message so the error-text mutants die too, and
the Anonymous-vs-typed function cases both exercise the ``.lower()`` casing in
the forbidden-function check -- a surviving mutant there is a denylist bypass.
"""

try:  # mutation-harness workspace exposes it as a top-level package
    from serving.semantic_layer.sql_guard import UnsafeSQLError, validate_nl_sql
except ImportError:  # ordinary pytest sees it under the src package
    from src.serving.semantic_layer.sql_guard import UnsafeSQLError, validate_nl_sql

import pytest

ALLOWED = {"orders", "customers"}


def test_plain_select_ok():
    validate_nl_sql("SELECT id FROM orders", ALLOWED)


def test_join_and_cte_ok():
    validate_nl_sql(
        "WITH c AS (SELECT id FROM customers) SELECT o.id FROM orders o JOIN c ON o.id = c.id",
        ALLOWED,
    )


def test_known_table_case_insensitive_ok():
    validate_nl_sql("SELECT id FROM ORDERS", ALLOWED)


def test_unparseable_raises():
    with pytest.raises(UnsafeSQLError, match="Unparseable SQL"):
        validate_nl_sql("SELECT FROM", ALLOWED)


def test_multiple_statements_raise():
    with pytest.raises(UnsafeSQLError, match="Expected single statement, got 2"):
        validate_nl_sql("SELECT 1; SELECT 2", ALLOWED)


def test_non_select_drop_raises():
    with pytest.raises(UnsafeSQLError, match="Statement type Drop not allowed"):
        validate_nl_sql("DROP TABLE orders", ALLOWED)


def test_insert_rejected():
    with pytest.raises(UnsafeSQLError, match="Statement type Insert not allowed"):
        validate_nl_sql("INSERT INTO orders VALUES (1)", ALLOWED)


def test_typed_scan_function_in_subquery_raises():
    # read_csv is modelled by sqlglot as a typed Func (exp.ReadCSV).
    with pytest.raises(UnsafeSQLError, match="Forbidden function: read_csv"):
        validate_nl_sql("SELECT id FROM orders WHERE id IN (SELECT read_csv('x.csv'))", ALLOWED)


def test_anonymous_scan_function_in_projection_raises():
    # postgres_scan is modelled as exp.Anonymous, exercising the name.lower()
    # branch; pins the casing so a denylisted call cannot slip through under a
    # different case (the .lower()->.upper() mutant must die here).
    with pytest.raises(UnsafeSQLError, match="Forbidden function: postgres_scan"):
        validate_nl_sql("SELECT postgres_scan('dsn', 'tbl') FROM orders", ALLOWED)


def test_table_valued_function_raises():
    with pytest.raises(UnsafeSQLError, match=r"^Table-valued functions not allowed$"):
        validate_nl_sql("SELECT * FROM glob('*')", ALLOWED)


def test_schema_qualified_table_raises():
    with pytest.raises(UnsafeSQLError, match="Schema-qualified table names are not allowed"):
        validate_nl_sql("SELECT id FROM victim.orders", ALLOWED)


def test_unknown_table_raises():
    with pytest.raises(UnsafeSQLError, match=r"Unknown tables: \['secrets'\]"):
        validate_nl_sql("SELECT id FROM secrets", ALLOWED)
