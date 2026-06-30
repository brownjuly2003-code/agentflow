from __future__ import annotations

import re
from datetime import datetime
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from src.serving.api.auth import get_current_tenant_id

from .contracts import SQLBuilderHost


class SQLBuilderMixin:
    def _resolve_tenant_id(self: SQLBuilderHost, tenant_id: str | None) -> str | None:
        if tenant_id is not None:
            return tenant_id
        default_tenant = "demo" if not self._tenant_router.has_config() else None
        return get_current_tenant_id(default=default_tenant)

    def _get_tenant_schema(self: SQLBuilderHost, tenant_id: str | None) -> str | None:
        resolved_tenant_id = self._resolve_tenant_id(tenant_id)
        schema: str | None = self._tenant_router.get_duckdb_schema(resolved_tenant_id)
        if schema is None:
            return None
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema) is None:
            raise ValueError(f"Invalid DuckDB schema '{schema}' for tenant '{resolved_tenant_id}'.")
        return schema

    def _quote_identifier(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def _quote_literal(self, value: object) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int | float):
            return str(value)
        if isinstance(value, datetime):
            return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
        return "'" + str(value).replace("'", "''") + "'"

    def _qualify_table(self: SQLBuilderHost, table_name: str, tenant_id: str | None) -> str:
        resolved_tenant_id = self._resolve_tenant_id(tenant_id)
        cache = cast(
            "dict[tuple[str, str | None], str] | None",
            getattr(self, "_qualified_table_cache", None),
        )
        cache_key = (table_name, resolved_tenant_id)
        if cache is not None and cache_key in cache:
            return cache[cache_key]

        if resolved_tenant_id is None and self._tenant_router.has_config():
            for tenant in self._tenant_router.load().tenants:
                qualified = (
                    f"{self._quote_identifier(tenant.duckdb_schema)}."
                    f"{self._quote_identifier(table_name)}"
                )
                if self._table_columns(qualified):
                    raise ValueError(
                        f"Tenant context is required for tenant-scoped table '{table_name}'."
                    )
        schema: str | None = self._tenant_router.get_duckdb_schema(resolved_tenant_id)
        if schema is None:
            if cache is not None:
                cache[cache_key] = table_name
            return table_name
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema) is None:
            raise ValueError(f"Invalid DuckDB schema '{schema}' for tenant '{resolved_tenant_id}'.")
        qualified_table = f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"
        if cache is not None:
            cache[cache_key] = qualified_table
        return qualified_table

    def _scope_sql(self: SQLBuilderHost, sql: str, tenant_id: str | None) -> str:
        known_tables = {entity.table.lower() for entity in self.catalog.entities.values()}
        known_tables.add("pipeline_events")

        parsed = sqlglot.parse_one(sql, dialect="duckdb")
        # A recursive CTE *can* self-reference, so sqlglot keeps its name in its
        # own body scope and the cte_sources skip below mis-classifies the
        # physical *anchor* reference (the first UNION branch, which cannot
        # self-reference) as a CTE reference — it is never re-scoped, stays bound
        # to the shared `main` schema and leaks every tenant's rows. There is no
        # safe re-scoping of a recursive anchor (genuinely ambiguous with the
        # recursion) and no legitimate query names a recursive CTE after a
        # physical table, so fail closed. validate_nl_sql rejects this on the NL
        # path; this guards any other caller. (audit_30 D1 follow-up: WITH
        # RECURSIVE bypass of f153b23)
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
        # from tenant rescoping. The old global cte_names skip dropped any table
        # whose name matched any CTE in the statement, so the inner physical
        # `orders_v2` stayed unqualified, bound to the shared `main` schema, and
        # leaked every tenant's rows (this is the *sole* isolation mechanism:
        # one DuckDB DB, a schema per tenant, no per-connection search_path).
        # Scope resolution rescopes the physical ref while leaving the genuine
        # CTE reference alone. (audit_30_06_26.md D1; builds on audit_28 #5)
        physical_tables = [
            table
            for scope in traverse_scope(parsed)
            for table in scope.tables
            if table.name
            and table.name.lower() in known_tables
            and table.name.lower() not in {name.lower() for name in scope.cte_sources}
        ]

        schema = self._get_tenant_schema(tenant_id)
        if schema is None:
            for table in physical_tables:
                if not table.db and not table.catalog:
                    # No tenant schema resolved: keep the "tenant context is
                    # required" guard firing for a physical tenant-scoped table
                    # even when its name collides with a CTE (the old skip let
                    # such a query silently read `main`).
                    self._qualify_table(table.name, tenant_id)
            return sql

        for table in physical_tables:
            # Force the known table into the caller's tenant schema even if it
            # arrived already schema-qualified — defense-in-depth so a qualified
            # name can never read another tenant. validate_nl_sql already rejects
            # qualified NL SQL; this re-scopes (instead of skipping) any that
            # reaches here through another caller. (audit_28_06_26.md #5)
            table.set("catalog", None)
            table.set("db", exp.to_identifier(schema, quoted=True))
            table.set("this", exp.to_identifier(table.name, quoted=True))

        return parsed.sql(dialect="duckdb")
