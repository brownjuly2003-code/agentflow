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


def _is_star_projection(projection: exp.Expression) -> bool:
    """Whether a select item expands to every column of its source.

    ``SELECT *`` parses to an :class:`exp.Star`; a qualified ``t.*`` parses to an
    :class:`exp.Column` wrapping a star. A star nested as a *function argument*
    (``COUNT(*)``) is deliberately **not** a star projection — it exposes no
    columns, so an aggregate over a PII-bearing table stays allowed.
    """
    if isinstance(projection, exp.Star):
        return True
    return isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)


def assert_no_pii_access(
    sql: str,
    table_to_entity: dict[str, str],
    pii_fields_by_entity: dict[str, frozenset[str]],
) -> None:
    """Reject queries that read a PII column — best-effort, NOT a bounded guarantee.

    .. warning::
       This is a **defense-in-depth denylist of SQL projection shapes**, not a bounded
       proof of PII-safety. It reasons about AST *shape*, but a leak is defined by the
       *column ordinal* the query actually reads, which no amount of shape-denial
       bounds — DuckDB's ``FROM t AS a(c1, c2, …)`` rename list, and any future
       expanding form, can read a PII column under a harmless name. Three distinct
       bypasses were found and closed in one audit (``audit_01_07_26.md``); treat that
       as evidence the approach is whack-a-mole, exactly like the lineage masker it
       replaced. In the **shipped rule-based** translator PII-safety actually rests on
       the translator's fixed template repertoire (it cannot emit these forms); the
       **LLM translator** (opt-in ``ANTHROPIC_API_KEY``) emits arbitrary SELECTs and is
       therefore NOT bounded here. A truly bounded guarantee needs column-level
       resolution against the real schema (execution / DESCRIBE / column security) —
       tracked as a follow-up. Do not enable the LLM translator against real PII until
       then.

    Given that caveat, the gate rejects the shapes known to reach PII without naming a
    PII column outright:

    * a ``SELECT *`` / ``table.*`` at **any** nesting level over a PII-bearing query
      is rejected — a star can expand to any column, and proving a nested star never
      reaches the output is exactly the lineage analysis we removed, so we fail
      closed rather than reason about it;
    * a DuckDB ``COLUMNS(...)`` projection (regex or lambda) is rejected — it
      expands to one-or-more source columns just like a star (incl. PII) but parses
      as ``exp.Columns``, not ``exp.Star``;
    * a DuckDB whole-row struct reference — a bare table name or table alias in
      projection position (``SELECT users_enriched FROM users_enriched``) returns a
      STRUCT of every column, PII included, without naming a column or using a star;
    * a DuckDB column-rename list on a PII table (``FROM users_enriched AS t(a, b,
      …)``) is rejected wholesale — it renames PII columns to harmless positional
      aliases that the shape check cannot otherwise catch (in projection or WHERE);
    * a reference to a PII column by name anywhere — projection, filter, join, a
      subquery, an alias source (``email AS contact``), an expression
      (``upper(email)``) — is rejected, because the raw column name still appears in
      the AST however it is renamed downstream.

    Over-rejection (a non-PII column that merely shares a name with a PII column) is
    the safe direction and is accepted. Callers skip this for PII-exempt tenants.

    ``table_to_entity`` maps a physical table name to its catalog entity;
    ``pii_fields_by_entity`` maps an entity to its declared PII field names. PII is
    "reachable" only when the query references a table whose entity declares PII.
    """
    try:
        statement = sqlglot.parse_one(sql, read="duckdb")
    except sqlglot.errors.ParseError as exc:
        # Unparseable means we cannot prove the query is PII-free → fail closed.
        # (validate_nl_sql already rejects this upstream; the re-parse is defensive.
        # parse_one returns an Expression or raises — it never yields None.)
        raise UnsafeSQLError(f"Unparseable SQL: {exc}") from exc

    normalized_map = {table.lower(): entity for table, entity in table_to_entity.items()}
    reachable_pii: set[str] = set()
    for table in statement.find_all(exp.Table):
        entity = normalized_map.get(table.name.lower()) if table.name else None
        if entity:
            reachable_pii |= {
                field.lower() for field in pii_fields_by_entity.get(entity, frozenset())
            }
    if not reachable_pii:
        return

    for select in statement.find_all(exp.Select):
        if any(_is_star_projection(projection) for projection in select.expressions):
            raise UnsafeSQLError(
                "SELECT * / table.* over a PII-bearing table is not allowed; "
                "select explicit non-PII columns"
            )

    # DuckDB COLUMNS(...) expands to one-or-more source columns (PII included),
    # exactly like a star, but parses as exp.Columns rather than exp.Star — so the
    # star check above misses it. Fail closed over a PII-bearing table.
    # (audit_01_07_26.md deny-gate bypass: SELECT COLUMNS('.*') FROM users_enriched)
    if statement.find(exp.Columns) is not None:
        raise UnsafeSQLError(
            "COLUMNS(...) expansion over a PII-bearing table is not allowed; "
            "select explicit non-PII columns"
        )

    # A bare table name (or table alias) in projection position is a DuckDB
    # whole-row struct reference: `SELECT users_enriched FROM users_enriched` (or
    # `SELECT t FROM users_enriched AS t`) returns a STRUCT of every column, PII
    # included, without ever naming a PII column or using a star. It parses as an
    # unqualified exp.Column whose name is a referenced table/alias.
    # (audit_01_07_26.md deny-gate bypass)
    table_refs: set[str] = set()
    for table in statement.find_all(exp.Table):
        if table.name:
            table_refs.add(table.name.lower())
        if table.alias:
            table_refs.add(table.alias.lower())
    for column in statement.find_all(exp.Column):
        if not column.table and column.name and column.name.lower() in table_refs:
            raise UnsafeSQLError(
                "Whole-row struct reference over a PII-bearing table is not "
                "allowed; select explicit non-PII columns"
            )

    # A DuckDB column-rename list on a PII table — FROM users_enriched AS t(a, b, …)
    # — renames columns positionally, so projecting a harmless alias (SELECT b)
    # reads a PII column BY ORDINAL, with no PII name, star or struct-ref anywhere in
    # the AST (and it defeats a WHERE-clause too: WHERE t.b = '…'). We cannot resolve
    # an ordinal to a name without the physical schema, so fail closed: reject any
    # PII-bearing table that carries a rename list. (audit_01_07_26.md deny-gate
    # bypass #3 — and see the module note: shape-based denial is not bounded.)
    for table in statement.find_all(exp.Table):
        entity = normalized_map.get(table.name.lower()) if table.name else None
        if entity and pii_fields_by_entity.get(entity):
            alias = table.args.get("alias")
            if alias is not None and alias.columns:
                raise UnsafeSQLError(
                    "column-rename list over a PII-bearing table is not allowed; "
                    "reference columns by their real names"
                )

    referenced_columns = {
        column.name.lower() for column in statement.find_all(exp.Column) if column.name
    }
    forbidden = sorted(referenced_columns & reachable_pii)
    if forbidden:
        raise UnsafeSQLError(f"Query reads PII column(s): {forbidden}")
