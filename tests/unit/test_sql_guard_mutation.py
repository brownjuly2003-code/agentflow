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
    from serving.semantic_layer.sql_guard import (
        UnsafeSQLError,
        assert_no_pii_access,
        validate_nl_sql,
    )
except ImportError:  # ordinary pytest sees it under the src package
    from src.serving.semantic_layer.sql_guard import (
        UnsafeSQLError,
        assert_no_pii_access,
        validate_nl_sql,
    )

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


# ── assert_no_pii_access deny-gate ───────────────────────────────
# The bounded PII deny-gate lives in this module, so its mutants are scored here.
# table_to_entity maps physical tables -> catalog entity; pii_fields_by_entity maps
# entity -> declared PII columns. products has no PII entry (no PII reachable).
PII_MAP = {"users_enriched": "user", "orders_v2": "order", "products": "product"}
PII_FIELDS = {"user": frozenset({"email", "phone"}), "order": frozenset({"shipping_address"})}


def _deny(sql: str) -> None:
    assert_no_pii_access(sql, PII_MAP, PII_FIELDS)


def test_pii_allows_query_with_no_pii_bearing_table():
    # products maps to an entity with no declared PII -> nothing reachable, even *.
    _deny("SELECT * FROM products")
    _deny("SELECT name FROM products")


def test_pii_allows_count_star_over_pii_table():
    # COUNT(*) is exp.Count, not a star projection -> aggregate stays allowed.
    _deny("SELECT COUNT(*) FROM users_enriched")


def test_pii_allows_explicit_non_pii_columns_over_pii_table():
    _deny("SELECT user_id, status FROM users_enriched")


def test_pii_denies_named_pii_column():
    with pytest.raises(UnsafeSQLError, match=r"Query reads PII column\(s\): \['email'\]"):
        _deny("SELECT email FROM users_enriched")


def test_pii_denies_pii_column_case_insensitively():
    # Pins the .lower() on referenced columns: UPPER must still match the rule.
    with pytest.raises(UnsafeSQLError, match=r"PII column\(s\): \['email'\]"):
        _deny("SELECT EMAIL FROM users_enriched")


def test_pii_denies_pii_table_case_insensitively():
    # Pins the table_to_entity lowercasing: a mixed-case table still resolves PII.
    with pytest.raises(UnsafeSQLError, match="PII column"):
        _deny("SELECT email FROM USERS_ENRICHED")


def test_pii_denies_aliased_pii_column():
    # The raw column name survives the rename in the AST -> no lineage needed.
    with pytest.raises(UnsafeSQLError, match="email"):
        _deny("SELECT email AS contact FROM users_enriched")


def test_pii_denies_pii_column_in_where_clause():
    with pytest.raises(UnsafeSQLError, match=r"PII column\(s\): \['phone'\]"):
        _deny("SELECT user_id FROM users_enriched WHERE phone = '555'")


def test_pii_denies_select_star_over_pii_table():
    with pytest.raises(UnsafeSQLError, match=r"^SELECT \* / table\.\*"):
        _deny("SELECT * FROM users_enriched")


def test_pii_denies_qualified_star_over_pii_table():
    with pytest.raises(UnsafeSQLError, match=r"SELECT \* / table\.\*"):
        _deny("SELECT users_enriched.* FROM users_enriched")


def test_pii_denies_star_in_a_union_branch():
    # The star is in the second SELECT; the gate iterates every select, not just
    # the outermost. A surviving mutant here is a union-branch SELECT * leak.
    with pytest.raises(UnsafeSQLError, match=r"SELECT \* / table\.\*"):
        _deny("SELECT id FROM products UNION SELECT * FROM users_enriched")


def test_pii_denies_columns_expansion_over_pii_table():
    # DuckDB COLUMNS(...) expands to source columns like a star but parses as
    # exp.Columns, not exp.Star. (audit_01_07_26 deny-gate bypass)
    with pytest.raises(
        UnsafeSQLError,
        match=r"^COLUMNS\(\.\.\.\) expansion over a PII-bearing table is not "
        r"allowed; select explicit non-PII columns$",
    ):
        _deny("SELECT COLUMNS('.*') FROM users_enriched")


def test_pii_denies_columns_lambda_expansion_over_pii_table():
    with pytest.raises(UnsafeSQLError, match="COLUMNS"):
        _deny("SELECT COLUMNS(c -> c LIKE '%mail%') FROM users_enriched")


def test_pii_allows_columns_expansion_over_non_pii_table():
    # COLUMNS over a no-PII table stays allowed: the gate returns before the
    # COLUMNS check when nothing PII is reachable. Kills a mutant that drops the
    # reachable-PII guard and rejects COLUMNS unconditionally.
    _deny("SELECT COLUMNS('.*') FROM products")


def test_pii_denies_whole_row_struct_reference():
    # A bare table name in projection is a DuckDB whole-row STRUCT of every column
    # (PII included), naming no PII column. (audit_01_07_26 deny-gate bypass)
    with pytest.raises(
        UnsafeSQLError,
        match=r"^Whole-row struct reference over a PII-bearing table is not "
        r"allowed; select explicit non-PII columns$",
    ):
        _deny("SELECT users_enriched FROM users_enriched")


def test_pii_denies_whole_row_struct_reference_via_alias():
    # The bare reference can be a table alias, not just the table name; pins the
    # table.alias branch of the ref set.
    with pytest.raises(UnsafeSQLError, match="struct reference"):
        _deny("SELECT t FROM users_enriched AS t")


def test_pii_denies_struct_reference_case_insensitively():
    # Pins the .lower() on both the table-ref set and the projected column name.
    with pytest.raises(UnsafeSQLError, match="struct reference"):
        _deny("SELECT USERS_ENRICHED FROM USERS_ENRICHED")


def test_pii_allows_struct_reference_over_non_pii_table():
    # A whole-row reference to a non-PII table is allowed (nothing PII reachable).
    _deny("SELECT products FROM products")


def test_pii_denies_column_rename_list_projection():
    # FROM users_enriched AS t(a,b,c) renames PII cols to positional aliases;
    # SELECT b reads a PII column by ordinal. (audit_01_07_26 deny-gate bypass #3)
    with pytest.raises(
        UnsafeSQLError,
        match=r"^column-rename list over a PII-bearing table is not allowed; "
        r"reference columns by their real names$",
    ):
        _deny("SELECT b FROM users_enriched AS t(a,b,c,d,e)")


def test_pii_denies_column_rename_list_in_where():
    # The rename list also defeats a WHERE oracle; rejecting the whole table
    # reference closes both. Pins the reject-the-table (not just projection) design.
    with pytest.raises(UnsafeSQLError, match="rename list"):
        _deny("SELECT COUNT(*) FROM users_enriched AS t(a,b,c,d,e) WHERE t.b='x'")


def test_pii_allows_rename_list_over_non_pii_table():
    # A rename list on a no-PII table is allowed. Kills a mutant that drops the
    # PII guard and rejects every rename list.
    _deny("SELECT a FROM products AS p(a,b,c)")


def test_pii_allows_plain_alias_without_rename_over_pii_table():
    # A plain alias with no column list must NOT trigger the rename-list reject.
    # Kills a mutant that drops the `alias.columns` check.
    _deny("SELECT user_id FROM users_enriched AS t")


def test_pii_denies_second_entity_pii_column():
    # reachable_pii is the union over all referenced PII tables.
    with pytest.raises(UnsafeSQLError, match=r"PII column\(s\): \['shipping_address'\]"):
        _deny("SELECT shipping_address FROM orders_v2")


def test_pii_unparseable_fails_closed():
    with pytest.raises(UnsafeSQLError, match="Unparseable SQL"):
        _deny("SELECT FROM")


# ── validate_nl_sql recursive-CTE shadow guard (audit_30 D1 follow-up) ─────────
def test_recursive_cte_shadowing_allowed_table_rejected():
    # WITH RECURSIVE <name> where <name> is a real allowed table is a cross-tenant
    # read vector: the physical anchor reference cannot be re-scoped. Rejecting it
    # exercises the whole recursive_shadows comprehension — pins args.get("recursive"),
    # the .lower() membership against normalized_allowed_tables, and the `and`.
    with pytest.raises(
        UnsafeSQLError, match=r"^Recursive CTE shadows physical table\(s\): \['orders'\]$"
    ):
        validate_nl_sql(
            "WITH RECURSIVE orders AS (SELECT id FROM orders UNION "
            "SELECT id FROM orders) SELECT id FROM orders",
            ALLOWED,
        )


def test_recursive_cte_not_shadowing_is_allowed():
    # A recursive CTE whose name is NOT an allowed table is fine (it is re-scoped
    # like any CTE). Kills the `and`->`or` mutant, which would flag every recursive
    # CTE name regardless of whether it shadows a physical table.
    validate_nl_sql(
        "WITH RECURSIVE seq AS (SELECT 1 AS n UNION SELECT n + 1 FROM seq WHERE n < 3) "
        "SELECT n FROM seq",
        ALLOWED,
    )


# ── assert_no_pii_access reachable-PII union + per-table guard ─────────────────
def test_pii_reachable_union_across_two_pii_tables():
    # reachable_pii must be the UNION over every referenced PII table. A JOIN of two
    # PII entities where the projected column belongs to the first-visited table
    # kills the `|=`->`=` mutant (which would keep only the last table's fields and
    # miss `email`).
    with pytest.raises(UnsafeSQLError, match=r"Query reads PII column\(s\): \['email'\]"):
        _deny(
            "SELECT email FROM users_enriched "
            "JOIN orders_v2 ON users_enriched.user_id = orders_v2.user_id"
        )


def test_pii_rename_list_guard_requires_pii_fields_for_that_table():
    # The rename-list reject must fire only for a table whose entity actually
    # declares PII. With a PII table present (so PII is reachable and the gate does
    # not return early), a rename list on a NON-PII table (products) must stay
    # allowed — killing the `and`->`or` mutant that would reject it.
    _deny("SELECT u.user_id FROM users_enriched u JOIN products AS p(a, b) ON u.user_id = p.a")
