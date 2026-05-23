from __future__ import annotations

import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import pandas as pd
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError
from pydantic import BaseModel
from tqdm import tqdm

try:
    from .branch_distributor import distribute_stores_to_branches
    from .mappers import (
        map_clients_chunk,
        map_products_chunk,
        map_purchases_chunk,
        rows_to_dicts,
    )
except ImportError:
    from branch_distributor import distribute_stores_to_branches
    from mappers import (
        map_clients_chunk,
        map_products_chunk,
        map_purchases_chunk,
        rows_to_dicts,
    )


REQUIRED_CSVS = ("clients.csv", "products.csv", "purchases.csv")
LOGGER = logging.getLogger("x5_retail_hero_loader")


@click.command()
@click.option("--csv-dir", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--clickhouse-host", default="localhost", show_default=True)
@click.option("--clickhouse-port", default=9000, show_default=True, type=int)
@click.option("--clickhouse-database", default="rv", show_default=True)
@click.option("--batch-size", default=100_000, show_default=True, type=int)
@click.option("--dry-run", is_flag=True)
@click.option("--load-ts", default=None, help="UTC timestamp override, for example 2026-05-23T10:15:30Z.")
def cli(
    csv_dir: Path,
    clickhouse_host: str,
    clickhouse_port: int,
    clickhouse_database: str,
    batch_size: int,
    dry_run: bool,
    load_ts: str | None,
) -> None:
    _configure_logging()
    csv_paths = _validate_csvs(csv_dir)
    current_load_ts = _parse_load_ts(load_ts)
    client = None if dry_run else _connect(clickhouse_host, clickhouse_port)

    client_lookup: dict[str, dict[str, Any]] = {}

    _process_products(
        csv_paths["products.csv"],
        batch_size,
        current_load_ts,
        client,
        clickhouse_database,
        dry_run,
    )
    client_lookup.update(
        _process_clients(
            csv_paths["clients.csv"],
            batch_size,
            current_load_ts,
            client,
            clickhouse_database,
            dry_run,
        )
    )

    LOGGER.info("Building stable branch map from purchases.csv store_id values")
    store_branch_map = _build_store_branch_map(csv_paths["purchases.csv"], batch_size)
    LOGGER.info("Mapped %s stores to branches", len(store_branch_map))

    seen_customer_personal: set[tuple[str, str]] = set()
    _process_purchases(
        csv_paths["purchases.csv"],
        batch_size,
        current_load_ts,
        store_branch_map,
        client_lookup,
        seen_customer_personal,
        client,
        clickhouse_database,
        dry_run,
    )


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def _validate_csvs(csv_dir: Path) -> dict[str, Path]:
    if not csv_dir.exists() or not csv_dir.is_dir():
        raise click.ClickException(f"CSV directory does not exist: {csv_dir}")

    paths = {filename: csv_dir / filename for filename in REQUIRED_CSVS}
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise click.ClickException(f"Missing required CSV file(s): {', '.join(missing)}")

    return paths


def _connect(host: str, port: int) -> Client:
    try:
        client = Client(host=host, port=port)
        client.execute("SELECT 1")
        return client
    except ClickHouseError as exc:
        raise click.ClickException(f"ClickHouse is unreachable at {host}:{port}: {exc}") from exc
    except OSError as exc:
        raise click.ClickException(f"ClickHouse is unreachable at {host}:{port}: {exc}") from exc


def _parse_load_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _build_store_branch_map(purchases_path: Path, batch_size: int) -> dict[Any, str]:
    store_ids: set[Any] = set()
    try:
        reader = pd.read_csv(
            purchases_path,
            chunksize=batch_size,
            usecols=["store_id"],
            low_memory=False,
        )
        for chunk in tqdm(reader, desc="purchases.csv stores", unit="chunk"):
            store_ids.update(chunk["store_id"].dropna().unique().tolist())
    except (KeyError, ValueError, FileNotFoundError, pd.errors.EmptyDataError) as exc:
        raise click.ClickException(f"Unable to read store_id from {purchases_path}: {exc}") from exc

    return distribute_stores_to_branches(store_ids)


def _process_products(
    products_path: Path,
    batch_size: int,
    load_ts: datetime,
    client: Client | None,
    database: str,
    dry_run: bool,
) -> None:
    totals: dict[str, int] = defaultdict(int)
    try:
        reader = pd.read_csv(products_path, chunksize=batch_size, low_memory=False)
        for chunk in tqdm(reader, desc="products.csv", unit="chunk"):
            mapped = map_products_chunk(chunk, load_ts)
            _emit_mapped_rows(mapped, client, database, dry_run, totals)
    except (KeyError, ValueError, FileNotFoundError, pd.errors.EmptyDataError) as exc:
        raise click.ClickException(f"Unable to process {products_path}: {exc}") from exc

    _log_totals("products.csv", totals, dry_run)


def _process_clients(
    clients_path: Path,
    batch_size: int,
    load_ts: datetime,
    client: Client | None,
    database: str,
    dry_run: bool,
) -> dict[str, dict[str, Any]]:
    totals: dict[str, int] = defaultdict(int)
    client_lookup: dict[str, dict[str, Any]] = {}
    try:
        reader = pd.read_csv(clients_path, chunksize=batch_size, low_memory=False)
        for chunk in tqdm(reader, desc="clients.csv", unit="chunk"):
            mapped, chunk_lookup = map_clients_chunk(chunk, load_ts)
            client_lookup.update(chunk_lookup)
            _emit_mapped_rows(mapped, client, database, dry_run, totals)
    except (KeyError, ValueError, FileNotFoundError, pd.errors.EmptyDataError) as exc:
        raise click.ClickException(f"Unable to process {clients_path}: {exc}") from exc

    _log_totals("clients.csv", totals, dry_run)
    return client_lookup


def _process_purchases(
    purchases_path: Path,
    batch_size: int,
    load_ts: datetime,
    store_branch_map: dict[Any, str],
    client_lookup: dict[str, dict[str, Any]],
    seen_customer_personal: set[tuple[str, str]],
    client: Client | None,
    database: str,
    dry_run: bool,
) -> None:
    totals: dict[str, int] = defaultdict(int)
    try:
        reader = pd.read_csv(purchases_path, chunksize=batch_size, low_memory=False)
        for chunk in tqdm(reader, desc="purchases.csv", unit="chunk"):
            mapped = map_purchases_chunk(
                chunk,
                load_ts,
                store_branch_map,
                client_lookup,
                seen_customer_personal,
            )
            _emit_mapped_rows(mapped, client, database, dry_run, totals)
    except (KeyError, ValueError, FileNotFoundError, pd.errors.EmptyDataError) as exc:
        raise click.ClickException(f"Unable to process {purchases_path}: {exc}") from exc

    _log_totals("purchases.csv", totals, dry_run)


def _emit_mapped_rows(
    mapped: dict[str, list[BaseModel]],
    client: Client | None,
    database: str,
    dry_run: bool,
    totals: dict[str, int],
) -> None:
    for table, rows in mapped.items():
        if not rows:
            continue
        totals[table] += len(rows)
        if dry_run:
            continue
        _insert_rows(client, _qualified_table(database, table), rows)


def _insert_rows(client: Client | None, table: str, rows: list[BaseModel]) -> None:
    if client is None:
        return

    dict_rows = rows_to_dicts(rows)
    if not dict_rows:
        return

    columns = list(dict_rows[0].keys())
    column_sql = ", ".join(columns)
    try:
        client.execute(f"INSERT INTO {table} ({column_sql}) VALUES", dict_rows)
    except ClickHouseError as exc:
        raise click.ClickException(f"Insert failed for {table}: {exc}") from exc
    except OSError as exc:
        raise click.ClickException(f"Insert failed for {table}: {exc}") from exc


def _qualified_table(database: str, table: str) -> str:
    if "." in table:
        return table
    return f"{database}.{table}"


def _log_totals(filename: str, totals: dict[str, int], dry_run: bool) -> None:
    mode = "mapped" if dry_run else "inserted"
    for table in sorted(totals):
        LOGGER.info("%s %s %s rows into %s", filename, mode, totals[table], table)


if __name__ == "__main__":
    cli()
