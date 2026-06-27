"""Load the supplier/product reference into the PostgreSQL raw vault.

This is the storage-bound counterpart to :mod:`build` (which writes the cloud
Parquet artifact for the Hub). It maps the *same* reference into raw-vault rows
and lands them in the ``rv`` schema through the shared
:class:`PostgresVaultWriter`, using idempotent ``INSERT ... ON CONFLICT DO
NOTHING``. The reference shares the vault's source-agnostic hubs/links with the
X5 / 1C feeds (byte-identical MD5 hash keys, pinned by
``tests/unit/test_dv2_supplier_reference.py``) and contributes its own
``*__ref__global`` satellites — so loading it alongside the X5 feed populates
the previously empty supplier/product-catalog slots without colliding.

Run as a module (relative imports), after ``dv2/postgres/apply.sh``::

    python -m warehouse.agentflow.dv2.reference.load_postgres \\
        --postgres-dsn postgresql://agentflow@localhost:5432/agentflow
"""

from __future__ import annotations

from datetime import UTC, datetime

import click

from ..loaders.pg_vault_writer import PostgresVaultWriter, connect
from .generator import build_reference
from .vault_mapping import VAULT_DB_COLUMNS, map_reference


@click.command()
@click.option(
    "--postgres-dsn",
    default="postgresql://agentflow@localhost:5432/agentflow",
    show_default=True,
    help="PostgreSQL DSN of the DV2 raw vault.",
)
@click.option("--seed", default=20260626, type=int)
@click.option("--n-suppliers", default=40, type=int)
@click.option("--n-products", default=300, type=int)
@click.option("--load-ts", default=None, help="Fixed UTC load timestamp (ISO-8601), else now.")
@click.option("--dry-run", is_flag=True, help="Map and summarize without connecting to PostgreSQL.")
def main(
    postgres_dsn: str,
    seed: int,
    n_suppliers: int,
    n_products: int,
    load_ts: str | None,
    dry_run: bool,
) -> None:
    ts = (
        datetime.fromisoformat(load_ts.replace("Z", "+00:00")) if load_ts else datetime.now(UTC)
    ).replace(tzinfo=None)

    tables = build_reference(n_suppliers=n_suppliers, n_products=n_products, seed=seed)
    mapped = map_reference(tables, ts)
    counts = {name: len(rows) for name, rows in mapped.items()}

    click.echo(
        f"reference seed={seed}: {sum(counts.values())} vault rows across {len(mapped)} tables"
    )
    if dry_run:
        for name in sorted(counts):
            click.echo(f"  {name}: {counts[name]}")
        click.echo("dry-run: not connecting to PostgreSQL")
        return

    writer = PostgresVaultWriter(connect(postgres_dsn))
    try:
        written = writer.write_mapped(mapped, columns_by_table=VAULT_DB_COLUMNS)
        writer.commit()
    finally:
        writer.close()

    for name in sorted(written):
        click.echo(f"  loaded {written[name]} rows into rv.{name}")
    click.echo(f"loaded {sum(written.values())} reference rows into the PostgreSQL raw vault")


if __name__ == "__main__":
    main()
