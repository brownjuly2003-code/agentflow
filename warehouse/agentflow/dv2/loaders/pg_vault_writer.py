"""Idempotent PostgreSQL writer for DV2 raw-vault rows.

Both ingestion feeds — the X5 retail loader and the supplier reference — map
their source data into the same pydantic raw-vault row models keyed by target
table name (``dict[str, list[BaseModel]]``). This module is the single PG sink
they share: it renders one parametrised, idempotent ``INSERT`` per table
(matching the PostgreSQL DDL in ``dv2/postgres/``) and streams rows through
``executemany`` in batches.

Idempotency follows the table kind, exactly like the in-database promotion in
``postgres_oltp/promote_to_raw_vault_pg.sql``:

* **hubs / links** collide on their BYTEA primary key — ``ON CONFLICT DO
  NOTHING`` makes a re-load a no-op.
* **satellites** are SCD2 *insert-on-change*: a new ``(hk, load_ts)`` version
  lands only when its ``hash_diff`` differs from the *current* (latest
  ``load_ts``) version for that hash key. Without this gate a re-run with a new
  ``load_ts`` but unchanged data inserts a duplicate version every time
  (storage bloat — see ``audit_28_06_26.md`` #10); the descriptive ``hash_diff``
  both loaders already compute is what makes the change-detection correct.

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


def satellite_hash_key(columns: Sequence[str]) -> str | None:
    """Return a satellite's hash-key column, or ``None`` for a hub/link.

    A satellite is identified structurally, without the loader needing a table
    registry: it is the only raw-vault shape carrying a ``hash_diff`` column, and
    it hangs off exactly one hub via a single ``*_hk`` hash key. Hubs carry a
    ``*_hk`` but no ``hash_diff``; links carry several ``*_hk`` but no
    ``hash_diff`` — both return ``None`` and keep collide-on-PK semantics.
    """
    if "hash_diff" not in columns:
        return None
    hash_keys = [name for name in columns if name.endswith("_hk")]
    if len(hash_keys) != 1:
        raise ValueError(
            f"satellite columns must carry exactly one *_hk hash key, found {hash_keys}"
        )
    return hash_keys[0]


def build_insert_sql(table: str, columns: Sequence[str], schema: str = DEFAULT_SCHEMA) -> str:
    """Render an idempotent parametrised INSERT for one raw-vault table.

    Hubs/links get ``VALUES (...) ON CONFLICT DO NOTHING`` (collide on their
    BYTEA primary key). Satellites get an SCD2 *insert-on-change* form: the row
    is materialised only when ``hash_diff`` differs from the current (latest
    ``load_ts``) version for the hash key, mirroring the in-database promotion in
    ``promote_to_raw_vault_pg.sql``; ``ON CONFLICT DO NOTHING`` still backstops
    an exact ``(hk, load_ts)`` duplicate. Satellite SQL appends two extra
    placeholders (the hash key and ``hash_diff``) for the gate — see
    :meth:`PostgresVaultWriter.write`. Columns are listed explicitly so the row
    order is pinned and a DDL default (e.g. ``is_deleted``) is left to
    PostgreSQL.
    """
    if not columns:
        raise ValueError(f"no columns to insert into {schema}.{table}")
    column_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    hash_key = satellite_hash_key(columns)
    if hash_key is None:
        return (
            f"INSERT INTO {schema}.{table} ({column_sql}) "
            f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        )
    return (
        f"INSERT INTO {schema}.{table} ({column_sql}) "
        f"SELECT {placeholders} "
        f"WHERE NOT EXISTS ("
        f"SELECT 1 FROM {schema}.{table} e "
        f"WHERE e.{hash_key} = %s AND e.hash_diff = %s "
        f"AND e.load_ts = (SELECT max(e2.load_ts) FROM {schema}.{table} e2 "
        f"WHERE e2.{hash_key} = e.{hash_key})"
        f") ON CONFLICT DO NOTHING"
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
        The return value counts rows *sent*, not rows materialised — a satellite
        row suppressed by the insert-on-change gate is still counted as sent.

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
        rows_values = [tuple(record[name] for name in field_order) for record in dumped]
        hash_key = satellite_hash_key(insert_columns)
        if hash_key is None:
            params = rows_values
        else:
            # The insert-on-change gate references the hash key and hash_diff
            # again (two trailing placeholders); destination columns are pinned
            # positionally to the row values, so reuse those positions.
            hk_idx = insert_columns.index(hash_key)
            hd_idx = insert_columns.index("hash_diff")
            params = [(*values, values[hk_idx], values[hd_idx]) for values in rows_values]

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
