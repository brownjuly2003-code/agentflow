"""Build the supplier-reference artifact for cloud publication + DV2 ingestion.

Outputs (under ``--out-dir``):

* ``dataset/{suppliers,products,sourcing}.parquet`` — the Hugging Face Dataset
  payload (the supplier reference itself);
* ``vault/<table>.parquet`` — the same reference mapped to DV2 raw-vault rows,
  ready to land in the ``rv`` database (hubs/links/``*__ref__global`` sats);
* ``manifest.json`` — counts, seed, provenance, and the genuine-vs-synthetic
  ledger, so the dataset is self-describing on the Hub.

Publishing ``dataset/`` to the Hub is a separate, gated step (see README).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import click
import pandas as pd

from .generator import ReferenceTables, build_reference
from .legend import GENERATOR_SEED, TOTAL_PRODUCTS, TOTAL_SUPPLIERS
from .vault_mapping import RECORD_SOURCE, map_reference


def _reference_frames(tables: ReferenceTables) -> dict[str, pd.DataFrame]:
    return {
        "suppliers": pd.DataFrame([asdict(r) for r in tables.suppliers]),
        "products": pd.DataFrame([asdict(r) for r in tables.products]),
        "sourcing": pd.DataFrame([asdict(r) for r in tables.sourcing]),
    }


def _vault_frames(tables: ReferenceTables, load_ts: datetime) -> dict[str, pd.DataFrame]:
    mapped = map_reference(tables, load_ts)
    return {
        name: pd.DataFrame([r.model_dump(mode="python") for r in rows])
        for name, rows in mapped.items()
    }


def _manifest(tables: ReferenceTables, load_ts: datetime, vault: dict[str, pd.DataFrame]) -> dict:
    return {
        "dataset": "agentflow-supplier-reference",
        "record_source": RECORD_SOURCE,
        "seed": tables.seed,
        "load_ts": load_ts.isoformat(),
        "counts": {
            "suppliers": len(tables.suppliers),
            "products": len(tables.products),
            "sourcing": len(tables.sourcing),
        },
        "vault_row_counts": {name: int(len(df)) for name, df in vault.items()},
        "genuine": [
            "ТН ВЭД ЕАЭС headings (4-digit, HS-aligned)",
            "GS1 GTIN-13 and GLN-13 check digits",
            "RU INN-10 control digit",
            "EAEU GS1 prefix range 460-469",
            "gross_weight_g >= net_weight_g invariant",
            "pricing ladder ordering (FOB < landed < wholesale < marketplace-net < RRC)",
            "MD5 hash keys join-compatible with the transactional vault feeds",
        ],
        "synthetic_but_labelled": [
            "supplier legal names (no brand token anywhere in the data)",
            "SKU <-> GTIN <-> supplier assignments",
            "packaging dimensions, RRC and FOB purchase prices",
            "GPC brick codes (illustrative)",
            "ТН ВЭД sub-position digits (zero-padded; heading granularity)",
            "CN USCC-18 check character (structurally shaped, not GB 32100-2015 verified)",
        ],
    }


@click.command()
@click.option(
    "--out-dir", default="reference/build", type=click.Path(file_okay=False, path_type=Path)
)
@click.option("--seed", default=GENERATOR_SEED, type=int)
@click.option("--n-suppliers", default=TOTAL_SUPPLIERS, type=int)
@click.option("--n-products", default=TOTAL_PRODUCTS, type=int)
@click.option("--load-ts", default=None, help="Fixed UTC load timestamp (ISO-8601), else now.")
@click.option("--dry-run", is_flag=True, help="Build and summarize without writing files.")
def main(
    out_dir: Path, seed: int, n_suppliers: int, n_products: int, load_ts: str | None, dry_run: bool
) -> None:
    base = out_dir if out_dir.is_absolute() else Path(__file__).resolve().parent.parent / out_dir
    ts = (
        datetime.fromisoformat(load_ts.replace("Z", "+00:00")) if load_ts else datetime.now(UTC)
    ).replace(tzinfo=None)

    tables = build_reference(n_suppliers=n_suppliers, n_products=n_products, seed=seed)
    dataset = _reference_frames(tables)
    vault = _vault_frames(tables, ts)
    manifest = _manifest(tables, ts, vault)

    counts = manifest["counts"]
    vault_rows = sum(manifest["vault_row_counts"].values())
    click.echo(
        f"reference seed={seed}: {counts['suppliers']} suppliers, {counts['products']} products, "
        f"{counts['sourcing']} sourcing links; {vault_rows} vault rows across {len(vault)} tables"
    )
    if dry_run:
        click.echo("dry-run: no files written")
        return

    (base / "dataset").mkdir(parents=True, exist_ok=True)
    (base / "vault").mkdir(parents=True, exist_ok=True)
    for name, df in dataset.items():
        df.to_parquet(base / "dataset" / f"{name}.parquet", index=False)
    for name, df in vault.items():
        df.to_parquet(base / "vault" / f"{name}.parquet", index=False)
    (base / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    click.echo(f"wrote dataset/, vault/, manifest.json into {base}")


if __name__ == "__main__":
    main()
