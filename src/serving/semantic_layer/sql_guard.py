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

    cte_names = {
        cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
    }
    normalized_allowed_tables = {table.lower() for table in allowed_tables}
    unknown_tables = {
        table.name.lower()
        for table in statement.find_all(exp.Table)
        if table.name and table.name.lower() not in cte_names
    } - normalized_allowed_tables
    if unknown_tables:
        raise UnsafeSQLError(f"Unknown tables: {sorted(unknown_tables)}")
