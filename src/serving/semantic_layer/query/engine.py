from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb

from src.serving.backends import create_backend
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.db_pool import DuckDBPool
from src.serving.duckdb_connection import connect_duckdb
from src.serving.semantic_layer.catalog import DataCatalog
from src.tenancy import TenantRouter

from .entity_queries import EntityQueryMixin
from .metric_queries import MetricQueryMixin
from .nl_queries import NLQueryMixin
from .sql_builder import SQLBuilderMixin


def _coerce_journal_timestamp(value: datetime | str) -> datetime:
    """Parse a journal-scan cursor into a naive, second-precision datetime.

    Accepts what the journal itself hands back: ``datetime`` objects (DuckDB
    rows) or ``YYYY-MM-DD HH:MM:SS[.ffffff]`` strings, ``T``-separated or not
    (ClickHouse JSON transport). Anything else raises ``ValueError`` — the
    cursor is interpolated into SQL, so it must never pass through as free
    text. Sub-second precision is floored: journal timestamps are
    second-granular on ClickHouse, and an inclusive ``>=`` re-fetch of the
    cursor second is what the callers' seen-sets are for.

    Timezone-aware input is rejected rather than converted: journal
    timestamps are stored naive (N2 — UTC on ClickHouse, local on DuckDB),
    and a cursor must round-trip within the one store it came from, not go
    through timezone arithmetic here.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            raise ValueError("journal-scan cursor must be naive (store-local) time")
        return value.replace(microsecond=0)
    text = str(value).strip().replace("T", " ")
    base = text.split(".", 1)[0]
    return datetime.strptime(base, "%Y-%m-%d %H:%M:%S")


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

    def fetch_pipeline_events(
        self,
        *,
        tenant_id: str | None = None,
        event_type: str | None = None,
        entity_id: str | None = None,
        topic: str | None = None,
        limit: int | None = None,
        validated_only: bool = False,
        newest_first: bool = False,
        min_processed_at: datetime | str | None = None,
    ) -> list[dict]:
        """Read the ``pipeline_events`` journal through the serving backend.

        This is the freshness-critical scan: the webhook dispatcher, the S7
        MetricCacheController journal fallback, and the SSE stream watch
        the journal *of the store the API serves from*. Going through
        ``self._backend`` — instead of the embedded DuckDB connection — is what
        keeps event-driven freshness alive when the serving engine is external
        (ADR 0006): an out-of-process writer lands events in ClickHouse and
        this scan sees them.

        Rows are normalized to a canonical column set regardless of the
        physical journal schema — ``event_id, topic, tenant_id, entity_id,
        event_type, latency_ms, processed_at`` — plus a pass-through of any
        additional journal columns (webhook filters match on event payload
        fields such as ``total_amount``, so the scan must stay schema-open the
        way the former ``SELECT *`` was). On non-DuckDB backends timestamp
        values arrive as ISO-format strings (JSON transport), not datetimes.

        ``event_type`` accepts the demo event families (``order``, ``payment``,
        ``clickstream``, ``inventory``) or an exact event type; family
        semantics mirror what the pipeline produces.

        ``topic`` is an exact-match filter (e.g. ``orders.status`` for the
        stage clock, ops-surfaces-spec.md §1.2/§3.2) — orthogonal to
        ``event_type``/``validated_only``, usable without an ``entity_id``
        for a bulk scan across many entities in one query.

        ``min_processed_at`` is the incremental-scan cursor (issue #183): an
        inclusive lower bound on the journal time column, accepting the
        ``datetime``/string forms the journal itself returns (strictly parsed
        — see ``_coerce_journal_timestamp``). Pair it with ``limit`` so a
        poller re-reads only the frontier of a large journal instead of
        materializing all of it on every pass. Ignored when the journal has
        no time column (the scan then stays bounded by ``limit`` alone).

        ``tenant_id=None`` is an explicit invariant, not incidental behaviour
        (n4, G2 audit): it means "no tenant filter" — an unscoped, cross-
        tenant scan. Two call shapes reach it deliberately: the webhook
        dispatcher's background scan, which is intentionally tenant-agnostic
        (it matches events against every registered webhook regardless of
        tenant); and the ``/v1/ops/*`` and ``/v1/stream/*`` routers, whose
        per-request ``tenant_id`` is resolved from ``request.state`` and is
        ``None`` in exactly one situation — auth is disabled
        (``AGENTFLOW_AUTH_DISABLED``/``app.state.auth_disabled``, dev/demo
        mode only; ``AuthMiddleware`` always sets a concrete tenant on an
        authenticated request). A genuinely multi-tenant deployment with auth
        enabled never produces ``tenant_id=None`` from those routers.
        """
        # Deliberately uncached (unlike _table_columns): the journal is created
        # and widened by out-of-process writers, so a scan must see schema
        # changes that happen after engine startup — exactly like the PRAGMA
        # probe this replaces.
        columns = self._backend.table_columns("pipeline_events")
        if not columns:
            return []
        if tenant_id is not None and "tenant_id" not in columns and tenant_id != "default":
            return []

        use_query_params = self._backend_name == self._duckdb_backend.name
        params: list[str | int] = []

        def render(value: str) -> str:
            if use_query_params:
                params.append(value)
                return "?"
            return self._quote_literal(value)

        if "processed_at" in columns:
            time_column = "processed_at"
        elif "created_at" in columns:
            time_column = "created_at"
        else:
            time_column = None

        select_columns = [
            "event_id",
            "topic" if "topic" in columns else "'events.validated' AS topic",
            (
                "COALESCE(tenant_id, 'default') AS tenant_id"
                if "tenant_id" in columns
                else "'default' AS tenant_id"
            ),
            "entity_id" if "entity_id" in columns else "NULL AS entity_id",
            "event_type" if "event_type" in columns else "NULL AS event_type",
            "latency_ms" if "latency_ms" in columns else "NULL AS latency_ms",
            (
                f"{time_column} AS processed_at"
                if time_column is not None and time_column != "processed_at"
                else ("processed_at" if time_column is not None else "NULL AS processed_at")
            ),
        ]
        # Pass through every remaining journal column (schema-open, like the
        # former SELECT *): webhook filters match on event payload fields such
        # as total_amount. Names come from the backend schema probe; anything
        # that is not a bare identifier is skipped to keep the f-string SQL
        # allowlisted.
        canonical = {
            "event_id",
            "topic",
            "tenant_id",
            "entity_id",
            "event_type",
            "latency_ms",
            "processed_at",
        }
        select_columns.extend(
            column
            for column in sorted(columns)
            if column not in canonical and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column)
        )

        where_clauses: list[str] = []
        if tenant_id is not None and "tenant_id" in columns:
            where_clauses.append(f"COALESCE(tenant_id, 'default') = {render(str(tenant_id))}")
        if validated_only and "topic" in columns:
            where_clauses.append("topic = 'events.validated'")
        if topic is not None:
            if "topic" not in columns:
                return []
            where_clauses.append(f"topic = {render(topic)}")
        if event_type:
            if "event_type" not in columns:
                return []
            if event_type == "order":
                where_clauses.append("event_type LIKE 'order.%'")
            elif event_type == "payment":
                where_clauses.append("event_type LIKE 'payment.%'")
            elif event_type == "clickstream":
                where_clauses.append("event_type IN ('click', 'page_view', 'add_to_cart')")
            elif event_type == "inventory":
                where_clauses.append("event_type LIKE 'product.%'")
            else:
                where_clauses.append(f"event_type = {render(event_type)}")
        if entity_id:
            if "entity_id" not in columns:
                return []
            where_clauses.append(f"entity_id = {render(entity_id)}")
        if min_processed_at is not None and time_column is not None:
            cursor = _coerce_journal_timestamp(min_processed_at)
            rendered = render(cursor.strftime("%Y-%m-%d %H:%M:%S"))
            # CAST keeps the comparison typed on both engines (DuckDB binds a
            # VARCHAR param; the ClickHouse transpile maps TIMESTAMP to
            # DateTime).
            where_clauses.append(f"{time_column} >= CAST({rendered} AS TIMESTAMP)")

        # column names come from the schema allowlist above
        sql = f"SELECT {', '.join(select_columns)} FROM pipeline_events"  # nosec B608
        if where_clauses:
            sql = f"{sql} WHERE {' AND '.join(where_clauses)}"
        order_column = time_column or "event_id"
        if newest_first:
            sql = f"{sql} ORDER BY {order_column} DESC, event_id DESC"
        else:
            sql = f"{sql} ORDER BY {order_column} ASC, event_id ASC"
        if limit is not None:
            sql = f"{sql} LIMIT {int(limit)}"

        return self._backend.execute(sql, params if use_query_params else None)

    def close(self) -> None:
        if self._closed:
            return
        if self._owns_connection:
            self._conn.close()
        self._closed = True
