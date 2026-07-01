from __future__ import annotations

import sqlglot
from sqlglot import exp


class UnsafeSQLError(ValueError):
    pass


_FORBIDDEN_NODE_TYPES = (
    exp.Alter,
    exp.Attach,
    exp.Command,
    exp.Commit,
    exp.Copy,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Merge,
    exp.Rollback,
    exp.Transaction,
    exp.Update,
    exp.Use,
)

_FORBIDDEN_FUNCTION_NAMES = {
    "delta_scan",
    "glob",
    "iceberg_scan",
    "mysql_scan",
    "parquet_scan",
    "postgres_scan",
    "read_blob",
    "read_csv",
    "read_csv_auto",
    "read_file",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_ndjson_auto",
    "read_parquet",
    "read_text",
    "sqlite_scan",
    "st_read",
}


def validate_nl_sql(sql: str, allowed_tables: set[str]) -> None:
    try:
        statements = sqlglot.parse(sql, dialect="duckdb")
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSQLError(f"Unparseable SQL: {exc}") from exc

    if len(statements) != 1:
        raise UnsafeSQLError(f"Expected single statement, got {len(statements)}")

    statement = statements[0]
    if not isinstance(statement, exp.Select):
        raise UnsafeSQLError(f"Statement type {type(statement).__name__} not allowed")

    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_NODE_TYPES):
            raise UnsafeSQLError(f"Forbidden node: {type(node).__name__}")
        if isinstance(node, exp.Table) and not node.name:
            raise UnsafeSQLError("Table-valued functions not allowed")
        if isinstance(node, exp.Table) and (node.db or node.catalog):
            # NL SQL must use bare table names so _scope_sql can re-prefix them
            # with the caller's tenant schema. A schema/catalog qualifier
            # (e.g. victim_schema.orders_v2) would otherwise slip past the
            # leaf-name allow-list below AND past _scope_sql's skip-if-qualified
            # branch, reading another tenant's data. (audit_28_06_26.md #5)
            raise UnsafeSQLError(f"Schema-qualified table names are not allowed: {node.sql()}")
        if isinstance(node, exp.Func):
            # sqlglot models some DuckDB scan functions as typed Func nodes
            # (read_csv -> exp.ReadCSV, read_parquet -> exp.ReadParquet) rather
            # than exp.Anonymous, so an Anonymous-only check missed them in
            # projection position. Anonymous carries the call name on `.name`
            # (its `.sql_name()` is just "ANONYMOUS"); typed funcs expose it via
            # `.sql_name()`. Check both so the denylist is parser-shape-agnostic.
            func_name = (
                node.name.lower() if isinstance(node, exp.Anonymous) else node.sql_name().lower()
            )
            if func_name in _FORBIDDEN_FUNCTION_NAMES:
                raise UnsafeSQLError(f"Forbidden function: {func_name}")

    cte_names = {
        cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
    }
    normalized_allowed_tables = {table.lower() for table in allowed_tables}
    # A recursive CTE whose name shadows a real (allowed) table is a cross-tenant
    # read vector. A recursive CTE *can* self-reference, so its name lives in its
    # own body scope; the leaf-name allow-list excludes the CTE name, AND
    # _scope_sql's cte_sources skip mis-classifies the physical *anchor*
    # reference (the first UNION branch, which cannot self-reference) as a CTE
    # reference — so it stays bare, binds to the shared `main` schema, and leaks
    # every tenant's rows. Non-recursive shadows are safely re-scoped, but the
    # recursive anchor cannot be, so reject the shape outright. (audit_30 D1
    # follow-up: WITH RECURSIVE bypass of f153b23)
    recursive_shadows = {
        cte.alias_or_name.lower()
        for with_node in statement.find_all(exp.With)
        if with_node.args.get("recursive")
        for cte in with_node.expressions
        if cte.alias_or_name and cte.alias_or_name.lower() in normalized_allowed_tables
    }
    if recursive_shadows:
        raise UnsafeSQLError(
            f"Recursive CTE shadows physical table(s): {sorted(recursive_shadows)}"
        )
    unknown_tables = {
        table.name.lower()
        for table in statement.find_all(exp.Table)
        if table.name and table.name.lower() not in cte_names
    } - normalized_allowed_tables
    if unknown_tables:
        raise UnsafeSQLError(f"Unknown tables: {sorted(unknown_tables)}")
