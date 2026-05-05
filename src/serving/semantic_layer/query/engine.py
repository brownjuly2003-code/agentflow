from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from src.ingestion.tenant_router import TenantRouter
from src.serving.backends import create_backend
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.db_pool import DuckDBPool
from src.serving.duckdb_connection import connect_duckdb
from src.serving.semantic_layer.catalog import DataCatalog

from .entity_queries import EntityQueryMixin
from .metric_queries import MetricQueryMixin
from .nl_queries import NLQueryMixin
from .sql_builder import SQLBuilderMixin


class QueryEngine(
    SQLBuilderMixin,
    NLQueryMixin,
    EntityQueryMixin,
    MetricQueryMixin,
):
    """Executes queries against the data platform."""

    def __init__(
        self,
        catalog: DataCatalog,
        db_path: str | None = None,
        tenants_config_path: str | Path | None = None,
        db_pool: DuckDBPool | None = None,
    ):
        self.catalog = catalog
        self._db_path: str = db_path or os.getenv("DUCKDB_PATH", ":memory:") or ":memory:"
        self._tenant_router = TenantRouter(tenants_config_path)
        self._table_columns_cache: dict[str, set[str]] = {}
        self._qualified_table_cache: dict[tuple[str, str | None], str] = {}
        self._db_pool = db_pool
        self._owns_connection = self._db_pool is None
        self._closed = False
        self._conn = (
            self._db_pool.write_connection
            if self._db_pool is not None
            else connect_duckdb(self._db_path)
        )
        self._duckdb_backend = DuckDBBackend(
            db_path=self._db_path,
            db_pool=self._db_pool,
            connection=self._conn,
        )
        self._duckdb_backend.initialize_demo_data()
        self._backend = create_backend(duckdb_backend=self._duckdb_backend)
        self._backend_name = self._backend.name
        if self._backend_name != self._duckdb_backend.name:
            self._backend.initialize_demo_data()

    @contextmanager
    def _read_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._duckdb_backend.read_connection() as conn:
            yield conn

    def _table_columns(self, table_name: str) -> set[str]:
        columns = self._table_columns_cache.get(table_name)
        if columns is None:
            columns = self._backend.table_columns(table_name)
            self._table_columns_cache[table_name] = columns
        return columns

    def health(self) -> dict:
        return self._backend.health()

    def close(self) -> None:
        if self._closed:
            return
        if self._owns_connection:
            self._conn.close()
        self._closed = True
