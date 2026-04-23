from __future__ import annotations

import re
from datetime import datetime

import sqlglot
from sqlglot import exp

from src.serving.api.auth import get_current_tenant_id


class SQLBuilderMixin:
    def _resolve_tenant_id(self, tenant_id: str | None) -> str | None:
        if tenant_id is not None:
            return tenant_id
        default_tenant = "demo" if not self._tenant_router.has_config() else None
        return get_current_tenant_id(default=default_tenant)

    def _get_tenant_schema(self, tenant_id: str | None) -> str | None:
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

    def _qualify_table(self, table_name: str, tenant_id: str | None) -> str:
        if self._resolve_tenant_id(tenant_id) is None and self._tenant_router.has_config():
            for tenant in self._tenant_router.load().tenants:
                qualified = (
                    f"{self._quote_identifier(tenant.duckdb_schema)}."
                    f"{self._quote_identifier(table_name)}"
                )
                if self._table_columns(qualified):
                    raise ValueError(
                        f"Tenant context is required for tenant-scoped table '{table_name}'."
                    )
        schema = self._get_tenant_schema(tenant_id)
        if schema is None:
            return table_name
        return f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"

    def _scope_sql(self, sql: str, tenant_id: str | None) -> str:
        known_tables = {entity.table.lower() for entity in self.catalog.entities.values()}
        known_tables.add("pipeline_events")

        parsed = sqlglot.parse_one(sql, dialect="duckdb")
        cte_names = {
            cte.alias_or_name.lower() for cte in parsed.find_all(exp.CTE) if cte.alias_or_name
        }
        schema = self._get_tenant_schema(tenant_id)
        if schema is None:
            for table in parsed.find_all(exp.Table):
                table_name = table.name
                if (
                    not table_name
                    or table.db
                    or table.catalog
                    or table_name.lower() not in known_tables
                    or table_name.lower() in cte_names
                ):
                    continue
                self._qualify_table(table_name, tenant_id)
            return sql

        for table in parsed.find_all(exp.Table):
            table_name = table.name
            if (
                not table_name
                or table.db
                or table.catalog
                or table_name.lower() not in known_tables
                or table_name.lower() in cte_names
            ):
                continue
            table.set("db", exp.to_identifier(schema, quoted=True))
            table.set("this", exp.to_identifier(table_name, quoted=True))

        return parsed.sql(dialect="duckdb")
