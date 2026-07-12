from __future__ import annotations

import re
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from src.serving.api.auth import get_current_tenant_id
from src.serving.backends import BackendExecutionError
from src.serving.semantic_layer.sql_literals import quote_sql_literal
from src.tenancy import DEFAULT_TENANT

from .contracts import SQLBuilderHost

# Physical name of the tenant column on every serving table (audit P0-1). It is
# part of each table's write key — ClickHouse sorting key, DuckDB PRIMARY KEY —
# so two tenants that share an entity id are two rows, not two versions of one.
TENANT_COLUMN = "tenant_id"

# Tenant identifiers reach SQL as inlined literals on the ClickHouse path (its
# `execute(params=...)` is a documented no-op), so they are constrained to the
# shape a tenant id may actually have. Config-sourced, never request data — but
# the table-scoping predicate is the isolation boundary itself, so it validates
# rather than trusts.
#
# Matched with `fullmatch`, not `match`: Python's `$` also matches *before* a
# trailing newline, so an anchored `match()` accepted `"acme\n"` — a string that
# is a different tenant than `"acme"` and would have quietly become its own
# partition. Caught by tests/property/test_tenant_isolation_properties.py.
_TENANT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class SQLBuilderMixin:
    def _resolve_tenant_id(self: SQLBuilderHost, tenant_id: str | None) -> str | None:
        if tenant_id is not None:
            return tenant_id
        # No tenants config means a single-tenant deployment, and its rows are the
        # ones the pipeline writes with no tenant on them — `event_tenant()` falls
        # back to DEFAULT_TENANT, and so does the demo seed. The old fallback here
        # was "demo", which was a *schema* name that never existed anywhere: it
        # resolved to no schema, so the read fell through to the unqualified table
        # and the value never mattered. It matters now — it is the filter — so it
        # has to name the tenant the data is actually under (ADR-004).
        default_tenant = DEFAULT_TENANT if not self._tenant_router.has_config() else None
        return get_current_tenant_id(default=default_tenant)

    def _quote_identifier(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def _quote_literal(self, value: object) -> str:
        return quote_sql_literal(value)

    def _physical_table(self, table_name: str) -> str:
        """The table as it exists in the store — what you can DESCRIBE.

        Separate from :meth:`_qualify_table`, which returns a *scoped relation*
        (a sub-select) rather than a name. Schema probes (``_table_columns``)
        need the physical name; query bodies need the scoped relation. Conflating
        the two is what would break the moment tenant scoping stopped being
        expressible as a name.
        """
        return table_name

    def _tenant_predicate(self: SQLBuilderHost, tenant_id: str | None) -> str | None:
        """``tenant_id = '<tenant>'``, or ``None`` for an unscoped read.

        ``None`` means "no tenant filter" — a cross-tenant read. That is not a
        hole: it is reachable only when auth is disabled (dev/demo), because
        ``AuthMiddleware`` always puts a concrete tenant on an authenticated
        request. The same invariant already governs
        ``QueryEngine.fetch_pipeline_events`` and ``JournalReader``.
        """
        resolved = self._resolve_tenant_id(tenant_id)
        if resolved is None:
            return None
        if _TENANT_ID_RE.fullmatch(resolved) is None:
            raise ValueError(f"Invalid tenant id {resolved!r}.")
        return f"{TENANT_COLUMN} = {quote_sql_literal(resolved)}"

    def _holds_foreign_tenant_rows(self: SQLBuilderHost, physical: str) -> bool:
        """Does ``physical`` hold rows of a tenant other than the default one?

        This is the fail-closed check (audit p2_1 #5), carried over to the column
        model. A store whose rows are spread across tenants must not be read
        without a tenant context: answering such a request unscoped would hand
        the caller every tenant's data. A single-tenant store — everything under
        ``DEFAULT_TENANT``, which is what a deployment that never sets a tenant
        produces — has nothing to leak, so it stays readable.

        The old check asked the same question of the schema model ("does a
        tenant's copy of this table physically exist?"). It could not simply be
        kept: in the column model *every* table is tenant-scoped, so a check on
        the config alone would fail-closed on the single-tenant demo too.

        One probe per table per process (cached), like the ``_table_columns``
        probe the old guard used.
        """
        cache = cast("dict[str, bool] | None", getattr(self, "_foreign_tenant_cache", None))
        if cache is not None and physical in cache:
            return cache[physical]

        backend = getattr(self, "_backend", None)
        if backend is None:  # pragma: no cover - host doubles without a store
            return False
        try:
            rows = backend.execute(
                # physical is a catalog identifier; the literal is a module constant
                f"SELECT 1 FROM {physical} "  # nosec B608  # noqa: S608
                f"WHERE {TENANT_COLUMN} <> {quote_sql_literal(DEFAULT_TENANT)} LIMIT 1"
            )
        except BackendExecutionError:
            # Not materialized yet, or no tenant column: nothing to leak.
            rows = []
        found = bool(rows)
        if cache is not None:
            cache[physical] = found
        return found

    def _qualify_table(self: SQLBuilderHost, table_name: str, tenant_id: str | None) -> str:
        """The tenant-scoped relation to read ``table_name`` through.

        Returns a sub-select, not a name::

            (SELECT * EXCLUDE (tenant_id) FROM orders_v2 WHERE tenant_id = 'demo')
                AS orders_v2

        Tenant isolation used to be a *schema qualification* (``"demo"."orders_v2"``),
        which only ever worked on DuckDB — and not even there, since nothing in
        `src/` creates a tenant schema, so an authenticated request died on a
        relation that did not exist. On ClickHouse the same name meant a database
        nobody creates. The boundary is now the ``tenant_id`` column, on both
        stores, and this is the one place it is applied to entity reads (audit
        P0-1).

        Aliasing the sub-select back to the bare table name keeps every caller's
        SQL — WHERE, ORDER BY, JOIN, the ``pipeline_events`` scans — working
        unchanged. ``EXCLUDE`` keeps ``tenant_id`` out of ``SELECT *``, so the
        row an API caller sees has exactly the columns the entity contract
        promises and the two stores stay column-identical.
        """
        predicate = self._tenant_predicate(tenant_id)
        cache = cast(
            "dict[tuple[str, str | None], str] | None",
            getattr(self, "_qualified_table_cache", None),
        )
        cache_key = (table_name, predicate)
        if cache is not None and cache_key in cache:
            return cache[cache_key]

        physical = self._physical_table(table_name)
        if predicate is None and self._holds_foreign_tenant_rows(physical):
            # No tenant context, but this table holds more than one tenant's rows:
            # an unscoped read would answer with all of them. Fail closed — the
            # caller gets a 503, not somebody else's data (audit p2_1 #5).
            raise ValueError(f"Tenant context is required for tenant-scoped table '{table_name}'.")
        where = f" WHERE {predicate}" if predicate is not None else ""
        # The table is a catalog identifier and the predicate is built from a
        # tenant id validated by `_tenant_predicate` — neither is request data.
        select = f"SELECT * EXCLUDE ({TENANT_COLUMN}) FROM {physical}{where}"  # nosec B608  # noqa: S608
        scoped = f"({select}) AS {self._quote_identifier(table_name)}"
        if cache is not None:
            cache[cache_key] = scoped
        return scoped

    def _scope_sql(self: SQLBuilderHost, sql: str, tenant_id: str | None) -> str:
        """Rewrite every physical reference to a serving table into a scoped read.

        This is the free-SQL counterpart of :meth:`_qualify_table` — it carries
        metric templates and NL-generated SQL, which name tables directly. Each
        physical reference becomes the same tenant-filtered sub-select, aliased
        back to the table's own name so the surrounding query is untouched.
        """
        known_tables = {entity.table.lower() for entity in self.catalog.entities.values()}
        known_tables.add("pipeline_events")

        parsed = sqlglot.parse_one(sql, dialect="duckdb")
        # A recursive CTE *can* self-reference, so sqlglot keeps its name in its
        # own body scope and the cte_sources skip below mis-classifies the
        # physical *anchor* reference (the first UNION branch, which cannot
        # self-reference) as a CTE reference — it is never re-scoped and reads
        # every tenant's rows. There is no safe re-scoping of a recursive anchor
        # (genuinely ambiguous with the recursion) and no legitimate query names
        # a recursive CTE after a physical table, so fail closed. validate_nl_sql
        # rejects this on the NL path; this guards any other caller. (audit_30 D1
        # follow-up: WITH RECURSIVE bypass of f153b23)
        recursive_shadow = sorted(
            {
                cte.alias_or_name.lower()
                for with_node in parsed.find_all(exp.With)
                if with_node.args.get("recursive")
                for cte in with_node.expressions
                if cte.alias_or_name and cte.alias_or_name.lower() in known_tables
            }
        )
        if recursive_shadow:
            raise ValueError(f"Recursive CTE shadows tenant-scoped table(s): {recursive_shadow}")
        # Classify every table reference by scope so a CTE whose name collides
        # with a real table — e.g. `WITH orders_v2 AS (SELECT * FROM orders_v2)
        # SELECT * FROM orders_v2` — cannot hide the *physical* inner reference
        # from tenant scoping. The old global cte_names skip dropped any table
        # whose name matched any CTE in the statement, so the inner physical
        # `orders_v2` stayed unscoped and read every tenant's rows. Scope
        # resolution scopes the physical ref while leaving the genuine CTE
        # reference alone. (audit_30_06_26.md D1; builds on audit_28 #5)
        physical_tables = [
            table
            for scope in traverse_scope(parsed)
            for table in scope.tables
            if table.name
            and table.name.lower() in known_tables
            and table.name.lower() not in {name.lower() for name in scope.cte_sources}
        ]
        if not physical_tables:
            return sql

        for table in physical_tables:
            # Replace the reference wholesale — catalog and db included — so a
            # name that arrived already qualified cannot escape the scoping.
            # (validate_nl_sql rejects qualified NL SQL; this re-scopes anything
            # that reaches here through another caller. audit_28_06_26.md #5)
            scoped = self._qualify_table(table.name, tenant_id)
            table.replace(sqlglot.parse_one(scoped, dialect="duckdb"))

        return parsed.sql(dialect="duckdb")
