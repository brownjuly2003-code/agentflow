from __future__ import annotations

import logging
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import pandas as pd
from pydantic import BaseModel
from tqdm import tqdm

try:
    from clickhouse_driver import Client
    from clickhouse_driver.errors import Error as ClickHouseError
except ModuleNotFoundError:
    Client = None  # type: ignore[assignment]
    ClickHouseError = Exception  # type: ignore[misc, assignment]

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


class PartsThrottle:
    """Backpressure on the active-part count so merges keep up with inserts.

    The 2026-06-02 full load ran with merges OFF and accumulated tens of
    thousands of parts — more than an 8 GB host can even cold-start on
    (part-metadata load OOMs before the server serves a query). Keeping
    merges ON but pausing inserts whenever the active-part count crosses a
    bound keeps the part set small enough to survive a cold start at any
    moment during the load.
    """

    def __init__(
        self,
        client: Client | None,
        database: str,
        max_active_parts: int,
        poll_seconds: float = 15.0,
    ) -> None:
        self.client = client
        self.database = database
        self.max_active_parts = max_active_parts
        self.poll_seconds = poll_seconds

    def wait_if_needed(self) -> None:
        if self.client is None or self.max_active_parts <= 0:
            return
        while True:
            active = self._active_parts()
            if active <= self.max_active_parts:
                return
            LOGGER.info(
                "throttle: %s active parts in %s > %s budget, waiting %.0fs for merges",
                active,
                self.database,
                self.max_active_parts,
                self.poll_seconds,
            )
            time.sleep(self.poll_seconds)

    def _active_parts(self) -> int:
        result = self.client.execute(
            "SELECT count() FROM system.parts WHERE database = %(database)s AND active",
            {"database": self.database},
        )
        return int(result[0][0])


@click.command()
@click.option("--csv-dir", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--clickhouse-host", default="localhost", show_default=True)
@click.option("--clickhouse-port", default=9000, show_default=True, type=int)
@click.option("--clickhouse-database", default="rv", show_default=True)
@click.option("--clickhouse-user", default="default", show_default=True)
@click.option("--clickhouse-password", default="", show_default=True)
@click.option("--batch-size", default=100_000, show_default=True, type=int)
@click.option("--dry-run", is_flag=True)
@click.option(
    "--load-ts",
    default=None,
    help="UTC timestamp override, for example 2026-05-23T10:15:30Z.",
)
@click.option(
    "--max-active-parts",
    default=0,
    show_default=True,
    type=int,
    help=(
        "Pause inserts while the database has more active parts than this "
        "(0 disables). Keeps merges able to catch up on small hosts."
    ),
)
def cli(
    csv_dir: Path,
    clickhouse_host: str,
    clickhouse_port: int,
    clickhouse_database: str,
    clickhouse_user: str,
    clickhouse_password: str,
    batch_size: int,
    dry_run: bool,
    load_ts: str | None,
    max_active_parts: int,
) -> None:
    _configure_logging()
    csv_paths = _validate_csvs(csv_dir)
    current_load_ts = _parse_load_ts(load_ts)
    client = (
        None
        if dry_run
        else _connect(clickhouse_host, clickhouse_port, clickhouse_user, clickhouse_password)
    )
    throttle = PartsThrottle(client, clickhouse_database, max_active_parts)

    client_lookup: dict[str, dict[str, Any]] = {}

    _process_products(
        csv_paths["products.csv"],
        batch_size,
        current_load_ts,
        client,
        clickhouse_database,
        dry_run,
        throttle,
    )
    client_lookup.update(
        _process_clients(
            csv_paths["clients.csv"],
            batch_size,
            current_load_ts,
            client,
            clickhouse_database,
            dry_run,
            throttle,
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
        throttle,
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


def _connect(host: str, port: int, user: str, password: str) -> Client:
    if Client is None:
        raise click.ClickException("clickhouse-driver is required unless --dry-run is used.")

    try:
        client = Client(host=host, port=port, user=user, password=password)
        client.execute("SELECT 1")
        return client
    except ClickHouseError as exc:
        raise click.ClickException(f"ClickHouse is unreachable at {host}:{port}: {exc}") from exc
    except OSError as exc:
        raise click.ClickException(f"ClickHouse is unreachable at {host}:{port}: {exc}") from exc


def _parse_load_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC).replace(tzinfo=None)

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(UTC).replace(tzinfo=None)


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
    throttle: PartsThrottle,
) -> None:
    totals: dict[str, int] = defaultdict(int)
    try:
        reader = pd.read_csv(products_path, chunksize=batch_size, low_memory=False)
        for chunk in tqdm(reader, desc="products.csv", unit="chunk"):
            mapped = map_products_chunk(chunk, load_ts)
            _emit_mapped_rows(mapped, client, database, dry_run, totals)
            throttle.wait_if_needed()
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
    throttle: PartsThrottle,
) -> dict[str, dict[str, Any]]:
    totals: dict[str, int] = defaultdict(int)
    client_lookup: dict[str, dict[str, Any]] = {}
    try:
        reader = pd.read_csv(clients_path, chunksize=batch_size, low_memory=False)
        for chunk in tqdm(reader, desc="clients.csv", unit="chunk"):
            mapped, chunk_lookup = map_clients_chunk(chunk, load_ts)
            client_lookup.update(chunk_lookup)
            _emit_mapped_rows(mapped, client, database, dry_run, totals)
            throttle.wait_if_needed()
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
    throttle: PartsThrottle,
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
            throttle.wait_if_needed()
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
