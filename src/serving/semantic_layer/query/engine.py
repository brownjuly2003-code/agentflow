from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb

from src.serving.backends import ServingBackend, create_backend
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.db_pool import DuckDBPool
from src.serving.duckdb_connection import connect_duckdb
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.journal import JournalReader
from src.tenancy import TenantRouter

from .entity_queries import EntityQueryMixin
from .metric_queries import MetricQueryMixin
from .nl_queries import NLQueryMixin
from .sql_builder import SQLBuilderMixin


def _coerce_journal_timestamp(value: datetime | str, *, floor_seconds: bool = True) -> datetime:
    """Parse a journal-scan cursor into a naive datetime.

    Accepts what the journal itself hands back: ``datetime`` objects (DuckDB
    rows) or ``YYYY-MM-DD HH:MM:SS[.ffffff]`` strings, ``T``-separated or not
    (ClickHouse JSON transport). Anything else raises ``ValueError`` — the
    cursor is interpolated into SQL, so it must never pass through as free
    text.

    ``floor_seconds`` (default) truncates to whole seconds: the inclusive
    ``>=`` re-fetch of the cursor second is what that path's seen-set is for,
    and ClickHouse journal timestamps are second-granular anyway. The
    **composite keyset** path passes ``floor_seconds=False`` and keeps
    sub-second precision on purpose: with a second floored away, every row of a
    saturated second collapses to one comparison key and the ``(processed_at,
    event_id)`` keyset can no longer advance *within* that second — which is the
    exact cohort-wedge this cursor exists to prevent (audit 2026-07-17 #1). The
    value is still strict-parsed, so it can never reach SQL as free text.

    Timezone-aware input is rejected rather than converted: journal
    timestamps are stored naive (N2 — UTC on ClickHouse, local on DuckDB),
    and a cursor must round-trip within the one store it came from, not go
    through timezone arithmetic here.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            raise ValueError("journal-scan cursor must be naive (store-local) time")
        return value.replace(microsecond=0) if floor_seconds else value
    text = str(value).strip().replace("T", " ")
    if floor_seconds:
        base = text.split(".", 1)[0]
        return datetime.strptime(base, "%Y-%m-%d %H:%M:%S")
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


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
        *,
        seed_demo_data: bool | None = None,
    ):
        self.catalog = catalog
        self._db_path: str = db_path or os.getenv("DUCKDB_PATH", ":memory:") or ":memory:"
        self._tenant_router = TenantRouter(tenants_config_path)
        self._table_columns_cache: dict[str, set[str]] = {}
        self._qualified_table_cache: dict[tuple[str, str | None], str] = {}
        # One probe per table: does it hold rows of more than the default tenant?
        # Drives the fail-closed guard on an unscoped read (SQLBuilderMixin).
        self._foreign_tenant_cache: dict[str, bool] = {}
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
        # The embedded store belongs to this process — no other provisioner,
        # nothing to migrate from — so its schema is laid down here and the
        # control-plane/lake reads have tables to hit.
        self._duckdb_backend.ensure_schema()
        if seed_demo_data is None:
            # Off unless asked. Demo rows used to land in the store on every
            # boot, before anything read a flag, so a fresh store got them for
            # no better reason than being empty (audit P0-2).
            seed_demo_data = os.getenv("AGENTFLOW_SEED_ON_BOOT", "").lower() == "true"
        if seed_demo_data:
            self._duckdb_backend.seed_demo_data()

        # The external serving backend is deliberately not provisioned here.
        # This constructor used to run its DDL and seed it with demo rows on
        # every boot, whatever the demo flags said: that forced the serving
        # identity to hold CREATE/ALTER/INSERT, let several booting replicas
        # race on the same seed, and dropped demo orders into whichever
        # production store was configured, just because it was empty (audit
        # P0-2). External stores are provisioned out of band — `python -m
        # src.serving.provision`, or the bridge writer — and /health/ready says
        # so loudly when that has not happened.
        self._backend = create_backend(duckdb_backend=self._duckdb_backend)
        self._backend_name = self._backend.name
        self._journal = JournalReader(self._backend)

    @property
    def backend(self) -> ServingBackend:
        """The store the API actually serves from.

        Public on purpose: read surfaces used to reach into ``_conn`` and read
        the embedded DuckDB whatever the configured backend was (audit P0-3).
        A ratchet test now fails on any private reach outside the composition
        root, so there has to be a front door.
        """
        return self._backend

    @property
    def journal(self) -> JournalReader:
        """Reads of ``pipeline_events`` through the active backend."""
        return self._journal

    def provision_external_demo_store(self) -> None:
        """Provision and seed the *external* serving backend — demo profile only.

        The rule is that the API issues no DDL and no demo DML against a store
        it does not own (audit P0-2). This is the one documented exception, and
        the caller must have decided that an explicit demo profile is active —
        nothing here checks. A no-op on the embedded profile, whose schema the
        constructor already laid down.
        """
        if self._backend_name == self._duckdb_backend.name:
            return
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
        min_event_id: str | None = None,
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

        ``min_processed_at`` is the incremental-scan cursor (issue #183),
        accepting the ``datetime``/string forms the journal itself returns
        (strictly parsed — see ``_coerce_journal_timestamp``). Pair it with
        ``limit`` so a poller re-reads only the frontier of a large journal
        instead of materializing all of it on every pass. Ignored when the
        journal has no time column (the scan then stays bounded by ``limit``
        alone). It has two modes:

        * alone, it is an **inclusive** lower bound (``processed_at >= cursor``,
          second-floored) — the caller's seen-set dedups the re-fetched second.
        * paired with ``min_event_id``, it becomes a **composite keyset**:
          ``processed_at > ts OR (processed_at = ts AND event_id > id)`` —
          strictly after the ``(processed_at, event_id)`` of the last row the
          caller consumed, keeping the same ``ORDER BY processed_at, event_id``.
          This is what lets the scan advance *within* a single second that holds
          more than ``limit`` rows; the inclusive bound alone pins there forever
          and silently drops every later event (audit 2026-07-17 #1). The
          predicate is written as the OR-decomposition rather than a row-value
          tuple ``(a, b) > (x, y)`` because the tuple form does not transpile to
          ClickHouse, while the decomposition round-trips through sqlglot on
          both backends. ``min_event_id`` alone (no ``min_processed_at``) is
          ignored — a keyset needs both halves.

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
            # CAST keeps the comparison typed on both engines (DuckDB binds a
            # VARCHAR param; the ClickHouse transpile maps TIMESTAMP to
            # DateTime).
            if min_event_id is not None:
                # Composite keyset (audit 2026-07-17 #1): strictly past
                # (processed_at, event_id) so a second holding >= `limit` rows
                # cannot pin the window. Sub-second precision is preserved
                # (floor_seconds=False) so a saturated DuckDB second stays
                # discriminable; on ClickHouse processed_at is second-granular
                # so the literal is a whole second either way. The row-value
                # tuple form does not transpile — this OR-decomposition does
                # (verified duckdb + clickhouse). `render` is called once per
                # placeholder so the DuckDB param list matches the SQL.
                cursor = _coerce_journal_timestamp(min_processed_at, floor_seconds=False)
                if cursor.microsecond:
                    cursor_text = cursor.strftime("%Y-%m-%d %H:%M:%S.%f")
                else:
                    cursor_text = cursor.strftime("%Y-%m-%d %H:%M:%S")
                gt_ts = render(cursor_text)
                eq_ts = render(cursor_text)
                cursor_id = render(str(min_event_id))
                where_clauses.append(
                    f"({time_column} > CAST({gt_ts} AS TIMESTAMP) "
                    f"OR ({time_column} = CAST({eq_ts} AS TIMESTAMP) "
                    f"AND event_id > {cursor_id}))"
                )
            else:
                cursor = _coerce_journal_timestamp(min_processed_at)
                rendered = render(cursor.strftime("%Y-%m-%d %H:%M:%S"))
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
