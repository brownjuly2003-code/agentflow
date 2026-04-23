from __future__ import annotations

import json
from datetime import UTC, datetime

from src.serving.backends import BackendExecutionError, BackendMissingTableError


class EntityQueryMixin:
    def get_entity(
        self,
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
            f"SELECT * FROM {table_name} "  # nosec B608 - table and primary-key identifiers come from the catalog allowlist
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
        local_tz = datetime.now().astimezone().tzinfo or UTC

        for candidate in (
            "updated_at",
            "last_updated",
            "last_order_at",
            "ended_at",
            "started_at",
            "created_at",
        ):
            value = entity.get(candidate)
            if isinstance(value, datetime):
                entity["_last_updated"] = (
                    value.astimezone(UTC)
                    if value.tzinfo is not None
                    else value.replace(tzinfo=local_tz).astimezone(UTC)
                ).isoformat()
                break
            if isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(value)
                except ValueError:
                    continue
                entity["_last_updated"] = (
                    parsed.astimezone(UTC)
                    if parsed.tzinfo is not None
                    else parsed.replace(tzinfo=local_tz).astimezone(UTC)
                ).isoformat()
                break

        return entity

    def get_entity_at(
        self,
        entity_type: str,
        entity_id: str,
        as_of: datetime,
        tenant_id: str | None = None,
    ) -> dict | None:
        """Look up a single entity by type and ID at a historical timestamp."""
        entity_def = self.catalog.entities.get(entity_type)
        if not entity_def:
            return None

        local_tz = datetime.now().astimezone().tzinfo or UTC
        anchor = as_of.astimezone(local_tz).replace(tzinfo=None)
        pipeline_table = self._qualify_table("pipeline_events", tenant_id)
        event_columns = self._table_columns(pipeline_table)
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
                        "SELECT entity_data, "  # nosec B608 - pipeline table and time column come from validated internal metadata
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
                        if isinstance(event_time, datetime):
                            normalized_time = (
                                event_time.astimezone(UTC)
                                if event_time.tzinfo is not None
                                else event_time.replace(tzinfo=local_tz).astimezone(UTC)
                            )
                        else:
                            normalized_time = as_of
                        historical = dict(entity)
                        historical["_last_updated"] = normalized_time.isoformat()
                        return historical

        table_name = self._qualify_table(entity_def.table, tenant_id)
        table_columns = self._table_columns(table_name)
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
                f"SELECT * FROM {table_name} "  # nosec B608 - table and primary-key identifiers come from the catalog allowlist
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
        if isinstance(value, datetime):
            entity["_last_updated"] = (
                value.astimezone(UTC)
                if value.tzinfo is not None
                else value.replace(tzinfo=local_tz).astimezone(UTC)
            ).isoformat()
        return entity
