"""Idempotent PostgreSQL writer for DV2 raw-vault rows.

Both ingestion feeds — the X5 retail loader and the supplier reference — map
their source data into the same pydantic raw-vault row models keyed by target
table name (``dict[str, list[BaseModel]]``). This module is the single PG sink
they share: it renders one parametrised ``INSERT ... ON CONFLICT DO NOTHING``
per table (idempotent, matching the PostgreSQL DDL in ``dv2/postgres/``) and
streams rows through ``executemany`` in batches.

The driver import is guarded exactly the way the X5 loader guards
``clickhouse_driver``: psycopg is only needed for a live load (a single-node Mac
smoke), never for the no-Docker unit tests, which drive a fake connection.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from pydantic import BaseModel

try:  # psycopg 3; absent is fine until a live load is actually attempted.
    import psycopg

    _PSYCOPG_IMPORT_ERROR: ModuleNotFoundError | None = None
except ModuleNotFoundError as exc:  # pragma: no cover - hosts without psycopg
    psycopg = None  # type: ignore[assignment]
    _PSYCOPG_IMPORT_ERROR = exc


DEFAULT_SCHEMA = "rv"
DEFAULT_BATCH_SIZE = 1000


def build_insert_sql(table: str, columns: Sequence[str], schema: str = DEFAULT_SCHEMA) -> str:
    """Render an idempotent parametrised INSERT for one raw-vault table.

    ``ON CONFLICT DO NOTHING`` (no conflict target) makes the load idempotent
    for every table shape — hubs/links collide on their BYTEA primary key,
    satellites on ``(hk, load_ts)`` — without the loader needing to know each
    table's key. Columns are listed explicitly so the row order is pinned and a
    DDL default (e.g. ``is_deleted``) is left to PostgreSQL.
    """
    if not columns:
        raise ValueError(f"no columns to insert into {schema}.{table}")
    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    return (
        f"INSERT INTO {schema}.{table} ({column_sql}) "
        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    )


def _chunked(rows: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def connect(dsn: str) -> Any:
    """Open a PostgreSQL connection, or fail loudly if psycopg is unavailable.

    Returns the raw psycopg connection (typed ``Any`` because psycopg is an
    optional import). Callers wrap it in :class:`PostgresVaultWriter`.
    """
    if psycopg is None:
        raise RuntimeError(
            "psycopg is required for a PostgreSQL load. Install psycopg[binary] "
            f"(import failed: {_PSYCOPG_IMPORT_ERROR})."
        )
    return psycopg.connect(dsn)


class PostgresVaultWriter:
    """Stream pydantic raw-vault rows into the PostgreSQL ``rv`` schema.

    Construction is driver-agnostic: any object exposing the DB-API ``cursor()``
    / ``commit()`` / ``close()`` surface works, which is what lets the unit tests
    drive a fake connection without psycopg installed.
    """

    def __init__(
        self,
        connection: Any,
        schema: str = DEFAULT_SCHEMA,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._connection = connection
        self.schema = schema
        self.batch_size = batch_size

    def write(
        self,
        table: str,
        rows: Sequence[BaseModel],
        columns: Sequence[str] | None = None,
    ) -> int:
        """Insert ``rows`` into ``rv.<table>``; returns the number of rows sent.

        No-op (returns 0) for an empty batch. Hash-key columns are Python
        ``bytes`` and land in ``BYTEA`` unchanged; ``Decimal`` / ``datetime`` /
        ``date`` / ``bool`` / ``None`` adapt through psycopg's standard typing.

        ``columns`` overrides the destination column names (same length and
        order as the row's model fields). The X5 loader's models already carry
        the real column names, so it passes nothing; the supplier reference uses
        generic ``hk``/``bk``/``left_hk``/``right_hk`` hub/link fields and passes
        the entity-specific column names (see ``vault_mapping.VAULT_DB_COLUMNS``).
        """
        if not rows:
            return 0
        dumped = [row.model_dump(mode="python") for row in rows]
        field_order = list(dumped[0].keys())
        insert_columns = list(columns) if columns is not None else field_order
        if len(insert_columns) != len(field_order):
            raise ValueError(
                f"column override for {self.schema}.{table} has "
                f"{len(insert_columns)} names, expected {len(field_order)}"
            )
        sql = build_insert_sql(table, insert_columns, self.schema)
        params = [tuple(record[name] for name in field_order) for record in dumped]

        cursor = self._connection.cursor()
        try:
            for batch in _chunked(params, self.batch_size):
                cursor.executemany(sql, batch)
        finally:
            cursor.close()
        return len(rows)

    def write_mapped(
        self,
        mapped: Mapping[str, Sequence[BaseModel]],
        columns_by_table: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, int]:
        """Write every non-empty table in a ``{table: rows}`` mapping.

        ``columns_by_table`` supplies per-table column-name overrides (tables
        not listed use their model field names).
        """
        overrides = columns_by_table or {}
        return {
            table: self.write(table, rows, overrides.get(table))
            for table, rows in mapped.items()
            if rows
        }

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
