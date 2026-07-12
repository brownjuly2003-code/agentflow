from __future__ import annotations

from typing import Protocol

from src.serving.backends import ServingBackend
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.semantic_layer.catalog import DataCatalog
from src.tenancy import TenantRouter


class SQLBuilderHost(Protocol):
    catalog: DataCatalog
    _tenant_router: TenantRouter
    # The store the fail-closed guard probes: an unscoped read is refused when
    # the table holds more than one tenant's rows (SQLBuilderMixin).
    _backend: ServingBackend

    def _resolve_tenant_id(self, tenant_id: str | None) -> str | None: ...

    def _holds_foreign_tenant_rows(self, physical: str) -> bool: ...

    def _quote_identifier(self, value: str) -> str: ...

    def _quote_literal(self, value: object) -> str: ...

    def _physical_table(self, table_name: str) -> str: ...

    def _tenant_predicate(self, tenant_id: str | None) -> str | None: ...

    def _qualify_table(self, table_name: str, tenant_id: str | None) -> str: ...

    def _scope_sql(self, sql: str, tenant_id: str | None) -> str: ...

    def _table_columns(self, table_name: str) -> set[str]: ...


class QueryExecutionHost(SQLBuilderHost, Protocol):
    _backend: ServingBackend
    _duckdb_backend: DuckDBBackend
    _backend_name: str


class NLQueryHost(QueryExecutionHost, Protocol):
    def _translate_question_to_sql(
        self,
        question: str,
        tenant_id: str | None = None,
    ) -> str: ...

    def _build_query_hash(self, sql: str, tenant_id: str | None) -> str: ...

    def _encode_cursor(self, offset: int, query_hash: str) -> str: ...

    def _decode_cursor(self, cursor: str) -> tuple[int, str]: ...
