"""SQL literal escaping for the non-binding backend path.

A leaf module on purpose. Both the semantic layer's SQL builder and the journal
reader need this, and importing it out of ``query/`` would close a cycle
(``query/__init__`` imports the engine, which imports the journal).
"""

from __future__ import annotations

from datetime import datetime


def quote_sql_literal(value: object) -> str:
    """Escape a value as a SQL literal.

    One implementation, shared by every caller that cannot bind: ClickHouse's
    ``execute(params=...)`` is a documented no-op, so anything that must run on
    both stores inlines its values here. Single quotes are doubled; the
    ClickHouse backend then re-escapes the literal structurally on the way out
    (sqlglot parses and regenerates it), which is what makes the escape hold on
    a store that honours backslash escapes where DuckDB does not.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    return "'" + str(value).replace("'", "''") + "'"
