from __future__ import annotations

import json
from datetime import datetime

from src.serving.backends import BackendExecutionError, BackendMissingTableError
from src.serving.semantic_layer.stage_clock import coerce_dt, naive_store_tz

from .contracts import QueryExecutionHost


class EntityQueryMixin:
    def scan_entity_rows(
        self: QueryExecutionHost,
        table_name: str,
        *,
        limit: int,
    ) -> list[dict]:
        """Bulk-read an entity table through the active backend, ``tenant_id`` included.

        The search index used to run its own ``SELECT *`` on the raw DuckDB
        connection, so on the ClickHouse profile it indexed a store nobody was
        serving from (audit P0-3). It is bounded because the index materializes
        every row it gets, and an unbounded scan grows with the serving data —
        the next RSS-growth candidate after the webhook poller (audit P1-6).

        Deliberately *not* tenant-scoped, and the one entity read that isn't: the
        index is built once per process and serves every tenant, so it needs the
        rows of all of them, each carrying the ``tenant_id`` that says whose it
        is. ``SearchIndex`` stamps that onto the document and filters by it
        before scoring — a per-tenant index would rebuild the whole corpus once
        per tenant instead (audit P0-1). Callers other than the index want
        ``_qualify_table``, which excludes the column and filters by it.
        """
        physical = self._physical_table(table_name)
        return self._backend.execute(
            # table_name is a catalog-defined identifier, never request data.
            f"SELECT * FROM {physical} LIMIT {int(limit)}"  # nosec B608
        )

    def scan_entity_rows_by_ids(
        self: QueryExecutionHost,
        table_name: str,
        *,
        primary_key: str,
        ids: list[str],
    ) -> list[dict]:
        """Targeted companion to ``scan_entity_rows`` for the incremental
        search refresh (audit P1-6): re-read only the rows whose primary key
        appears in the journal's changed-id set, instead of full-scanning the
        table because one row moved.

        Same deliberate shape as the bulk scan: through the active backend,
        ``tenant_id`` included, NOT tenant-scoped — the caller is the
        process-global index and stamps the tenant onto each document.
        ``table_name`` and ``primary_key`` are catalog-defined identifiers;
        the id values are event-shaped data and go through ``_quote_literal``
        (single-quote escaping the backend's sqlglot round-trip re-escapes
        structurally).
        """
        if not ids:
            return []
        physical = self._physical_table(table_name)
        quoted = ", ".join(self._quote_literal(value) for value in ids)
        return self._backend.execute(
            # table/primary_key are catalog identifiers; every id is quoted.
            f"SELECT * FROM {physical} WHERE {primary_key} IN ({quoted})"  # nosec B608
        )

    def get_entity(
        self: QueryExecutionHost,
        entity_type: str,
        entity_id: str,
        tenant_id: str | None = None,
    ) -> dict | None:
        """Look up a single entity by type and ID.

        Raises ValueError if the backing table doesn't exist or query fails.
        Returns None only when the entity genuinely doesn't exist in the table.
        """
        entity_def = self.catalog.entities.get(entity_type)
        if not entity_def:
            return None

        table_name = self._qualify_table(entity_def.table, tenant_id)
        use_query_params = self._backend_name == self._duckdb_backend.name
        sql = (
            # table and primary-key identifiers come from the catalog allowlist
            f"SELECT * FROM {table_name} "  # nosec B608
            f"WHERE {self._quote_identifier(entity_def.primary_key)} = "
        )
        if use_query_params:
            sql = f"{sql}? LIMIT 1"
        else:
            sql = f"{sql}{self._quote_literal(entity_id)} LIMIT 1"
        try:
            result = (
                self._backend.execute(sql, [entity_id])
                if use_query_params
                else self._backend.execute(sql)
            )
            if not result:
                return None
        except BackendMissingTableError as e:
            msg = f"Table '{table_name}' for entity '{entity_type}' is not materialized yet"
            raise ValueError(msg) from e
        except BackendExecutionError as e:
            raise ValueError(f"Entity lookup failed: {e}") from e

        entity = dict(result[0])
        # N2: naive timestamps mean different things per backend — DuckDB local
        # wall-clock, ClickHouse UTC. coerce_dt owns that convention.
        for candidate in (
            "updated_at",
            "last_updated",
            "last_order_at",
            "ended_at",
            "started_at",
            "created_at",
        ):
            value = entity.get(candidate)
            if value is None:
                continue
            coerced = coerce_dt(value, backend_name=self._backend_name)
            if coerced is not None:
                entity["_last_updated"] = coerced.isoformat()
                break

        return entity

    def fetch_orders_by_status(
        self: QueryExecutionHost,
        statuses: list[str],
        tenant_id: str | None = None,
        *,
        limit: int,
    ) -> list[dict]:
        """Bulk read for the stuck-orders worklist (ops-surfaces-spec.md §3.2).

        Every order whose status is one of ``statuses`` — the caller-supplied
        catalog ladder (I2: never a hardcoded stage-name literal here) — in
        one query, no per-order round-trips. Journal-side composition (each
        order's latest ``orders.status`` row) happens in the caller via
        ``fetch_pipeline_events(topic="orders.status")``, the same port
        method the Order 360 timeline already uses.

        ``limit`` is required (security pre-audit S-8): without it this read
        materialises a large tenant's entire open-orders set on a worker
        thread. Truncation is deterministic (ORDER BY primary key), and the
        callers probe with ``cap + 1`` to *detect* it rather than cut
        silently.
        """
        entity_def = self.catalog.entities.get("order")
        if entity_def is None or not statuses:
            return []

        table_name = self._qualify_table(entity_def.table, tenant_id)
        use_query_params = self._backend_name == self._duckdb_backend.name
        params: list[str] = []

        def render(value: str) -> str:
            if use_query_params:
                params.append(value)
                return "?"
            return self._quote_literal(value)

        status_placeholders = ", ".join(render(status) for status in statuses)
        sql = (
            # table comes from the catalog allowlist; statuses are the
            # caller-supplied catalog ladder, never a literal here
            f"SELECT * FROM {table_name} "  # nosec B608
            f"WHERE status IN ({status_placeholders}) "
            f"ORDER BY {self._quote_identifier(entity_def.primary_key)} "
            f"LIMIT {int(limit)}"
        )
        try:
            rows = (
                self._backend.execute(sql, params)
                if use_query_params
                else self._backend.execute(sql)
            )
        except BackendMissingTableError as e:
            msg = f"Table '{table_name}' for entity 'order' is not materialized yet"
            raise ValueError(msg) from e
        except BackendExecutionError as e:
            raise ValueError(f"Open-orders lookup failed: {e}") from e

        return [dict(row) for row in rows]

    def get_entity_at(
        self: QueryExecutionHost,
        entity_type: str,
        entity_id: str,
        as_of: datetime,
        tenant_id: str | None = None,
    ) -> dict | None:
        """Look up a single entity by type and ID at a historical timestamp."""
        entity_def = self.catalog.entities.get(entity_type)
        if not entity_def:
            return None

        # Compare as_of to store timestamps in the store's own naive convention
        # (DuckDB local wall-clock, ClickHouse UTC) so historical cuts do not
        # shift by the host offset (N2).
        store_tz = naive_store_tz(self._backend_name)
        anchor = as_of.astimezone(store_tz).replace(tzinfo=None)
        pipeline_table = self._qualify_table("pipeline_events", tenant_id)
        # Probe the *physical* journal: `_qualify_table` returns a tenant-scoped
        # sub-select, which has no schema to describe (P0-1).
        event_columns = self._table_columns(self._physical_table("pipeline_events"))
        use_query_params = self._backend_name == self._duckdb_backend.name

        if {"entity_id", "entity_data"}.issubset(event_columns):
            time_column = (
                "processed_at"
                if "processed_at" in event_columns
                else "created_at"
                if "created_at" in event_columns
                else None
            )
            if time_column is not None:
                if use_query_params:
                    filters = [
                        "entity_id = ?",
                        f"{time_column} <= CAST(? AS TIMESTAMP)",
                    ]
                    params = [entity_id, anchor]
                    if "entity_type" in event_columns:
                        filters.insert(0, "entity_type = ?")
                        params.insert(0, entity_type)
                else:
                    filters = [
                        f"entity_id = {self._quote_literal(entity_id)}",
                        f"{time_column} <= CAST({self._quote_literal(anchor)} AS TIMESTAMP)",
                    ]
                    params = None
                    if "entity_type" in event_columns:
                        filters.insert(0, f"entity_type = {self._quote_literal(entity_type)}")

                try:
                    sql = (
                        # pipeline table and time column come from validated internal metadata
                        "SELECT entity_data, "  # nosec B608
                        f"{time_column} AS event_time "
                        f"FROM {pipeline_table} "
                        f"WHERE {' AND '.join(filters)} "
                        f"ORDER BY {time_column} DESC "
                        "LIMIT 1"
                    )
                    rows = (
                        self._backend.execute(sql, params)
                        if use_query_params
                        else self._backend.execute(sql)
                    )
                except BackendExecutionError as e:
                    raise ValueError(f"Historical entity lookup failed: {e}") from e

                row = rows[0] if rows else None
                if row:
                    raw_data = row["entity_data"]
                    event_time = row["event_time"]
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode()

                    try:
                        entity = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Historical entity payload is invalid JSON: {e}") from e

                    if isinstance(entity, dict):
                        coerced = coerce_dt(event_time, backend_name=self._backend_name)
                        historical = dict(entity)
                        historical["_last_updated"] = (coerced or as_of).isoformat()
                        return historical

        table_name = self._qualify_table(entity_def.table, tenant_id)
        table_columns = self._table_columns(self._physical_table(entity_def.table))
        time_column = next(
            (
                candidate
                for candidate in (
                    "updated_at",
                    "last_updated",
                    "last_order_at",
                    "ended_at",
                    "started_at",
                    "created_at",
                )
                if candidate in table_columns
            ),
            None,
        )
        if time_column is None:
            return None

        try:
            sql = (
                # table and primary-key identifiers come from the catalog allowlist
                f"SELECT * FROM {table_name} "  # nosec B608
                f"WHERE {self._quote_identifier(entity_def.primary_key)} = "
            )
            if use_query_params:
                sql = f"{sql}? AND {time_column} <= CAST(? AS TIMESTAMP)"
                rows = self._backend.execute(sql, [entity_id, anchor])
            else:
                sql = (
                    f"{sql}{self._quote_literal(entity_id)} "
                    f"AND {time_column} <= CAST({self._quote_literal(anchor)} AS TIMESTAMP)"
                )
                rows = self._backend.execute(sql)
            if not rows:
                return None
        except BackendMissingTableError as e:
            msg = f"Table '{table_name}' for entity '{entity_type}' is not materialized yet"
            raise ValueError(msg) from e
        except BackendExecutionError as e:
            raise ValueError(f"Historical entity lookup failed: {e}") from e

        entity = dict(rows[0])
        value = entity.get(time_column)
        coerced = coerce_dt(value, backend_name=self._backend_name)
        if coerced is not None:
            entity["_last_updated"] = coerced.isoformat()
        return entity
