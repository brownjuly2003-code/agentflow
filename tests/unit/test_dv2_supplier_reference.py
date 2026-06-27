"""Unit tests for the DV2 supplier/product reference (no Docker).

Pins the genuine standards (GS1 GTIN/GLN, RU INN, ТН ВЭД), generator
determinism, hash-key join-compatibility with the X5/1C vault feeds, and
raw-vault referential integrity.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from click.testing import CliRunner

from warehouse.agentflow.dv2.loaders.x5_retail_hero.mappers import (
    composite_md5_digest as x5_composite_md5_digest,
)
from warehouse.agentflow.dv2.loaders.x5_retail_hero.mappers import (
    md5_digest as x5_md5_digest,
)
from warehouse.agentflow.dv2.reference.build import (
    _manifest,
    _reference_frames,
    _vault_frames,
)
from warehouse.agentflow.dv2.reference.build import main as build_main
from warehouse.agentflow.dv2.reference.generator import (
    build_reference,
    make_gtin13,
    ru_inn10_check_digit,
)
from warehouse.agentflow.dv2.reference.gs1 import (
    EAEU_PREFIX_RANGE,
    gtin13_check_digit,
    is_valid_gtin13,
)
from warehouse.agentflow.dv2.reference.tnved import TNVED_HEADINGS
from warehouse.agentflow.dv2.reference.vault_mapping import (
    RECORD_SOURCE,
    composite_md5_digest,
    map_reference,
    md5_digest,
)

LOAD_TS = datetime(2026, 6, 26, 12, 0, 0)


# --- genuine standards -------------------------------------------------------


def test_gtin13_check_digit_known_vector():
    # Classic EAN-13 test value 4006381333931 -> check digit 1.
    assert gtin13_check_digit("400638133393") == 1


def test_make_gtin13_is_valid_with_eaeu_prefix():
    gtin = make_gtin13(460, 123456)
    assert is_valid_gtin13(gtin)
    assert int(gtin[:3]) in EAEU_PREFIX_RANGE


def test_make_gtin13_rejects_non_eaeu_prefix():
    with pytest.raises(ValueError):
        make_gtin13(500, 1)


def test_is_valid_gtin13_rejects_bad_check_and_length():
    assert not is_valid_gtin13("4006381333930")  # wrong check digit
    assert not is_valid_gtin13("123")  # wrong length
    assert not is_valid_gtin13("abcdefghijklm")  # non-numeric


def test_ru_inn10_check_digit_known_vector():
    # Yandex LLC INN 7736207543 -> control digit 3.
    assert ru_inn10_check_digit("773620754") == 3


def test_tnved_headings_are_real_format():
    assert len(TNVED_HEADINGS) >= 30
    for h in TNVED_HEADINGS:
        assert len(h.heading) == 4
        assert h.heading.isdigit()
        assert h.code10 == f"{h.heading}000000"
        assert len(h.code10) == 10
        assert h.description.strip()
        assert h.category.strip()


# --- generator ---------------------------------------------------------------


def test_build_reference_is_deterministic():
    a = build_reference(n_suppliers=25, n_products=120, seed=7)
    b = build_reference(n_suppliers=25, n_products=120, seed=7)
    assert [s.supplier_bk for s in a.suppliers] == [s.supplier_bk for s in b.suppliers]
    assert [p.gtin for p in a.products] == [p.gtin for p in b.products]
    assert [s.purchase_price for s in a.sourcing] == [s.purchase_price for s in b.sourcing]


def test_different_seed_changes_output():
    a = build_reference(n_suppliers=25, n_products=120, seed=1)
    b = build_reference(n_suppliers=25, n_products=120, seed=2)
    assert [p.gtin for p in a.products] != [p.gtin for p in b.products]


def test_generated_products_obey_invariants():
    tables = build_reference(n_suppliers=40, n_products=300, seed=20260626)
    assert all(is_valid_gtin13(p.gtin) for p in tables.products)
    assert all(p.gross_weight_g >= p.net_weight_g for p in tables.products)
    assert all(p.tnved_code.endswith("000000") for p in tables.products)
    # unique business keys
    assert len({p.product_bk for p in tables.products}) == len(tables.products)
    assert len({s.supplier_bk for s in tables.suppliers}) == len(tables.suppliers)


def test_each_product_has_a_primary_supplier():
    tables = build_reference(n_suppliers=40, n_products=120, seed=3)
    by_product: dict[str, list[int]] = {}
    for s in tables.sourcing:
        by_product.setdefault(s.product_bk, []).append(s.supplier_priority)
    assert by_product, "expected sourcing rows"
    for priorities in by_product.values():
        assert 1 in priorities  # a primary source always exists
        assert sorted(priorities) == list(range(1, len(priorities) + 1))


# --- hash-key join-compatibility (the critical pin) --------------------------


def test_hash_keys_match_x5_loader_byte_for_byte():
    for value in ["7736207543", "RC000001", "4660000254375", "ООО «ГринФрут»", "123"]:
        assert md5_digest(value) == x5_md5_digest(value)
    left, right = md5_digest("a"), md5_digest("b")
    assert composite_md5_digest(left, right) == x5_composite_md5_digest(left, right)


# --- vault mapping -----------------------------------------------------------


def test_map_reference_counts_and_record_source():
    tables = build_reference(n_suppliers=40, n_products=300, seed=20260626)
    mapped = map_reference(tables, LOAD_TS)
    assert len(mapped["hub_supplier"]) == len(tables.suppliers)
    assert len(mapped["hub_product"]) == len(tables.products)
    assert len(mapped["hub_marking_code"]) == len(tables.products)
    assert len(mapped["lnk_product_supplier"]) == len(tables.sourcing)
    assert len(mapped["sat_product_reference__ref__global"]) == len(tables.products)
    assert all(r.record_source == RECORD_SOURCE for rows in mapped.values() for r in rows)


def test_map_reference_referential_integrity():
    tables = build_reference(n_suppliers=40, n_products=200, seed=11)
    mapped = map_reference(tables, LOAD_TS)
    hub_product = {r.hk for r in mapped["hub_product"]}
    hub_supplier = {r.hk for r in mapped["hub_supplier"]}
    hub_marking = {r.hk for r in mapped["hub_marking_code"]}

    for link in mapped["lnk_product_supplier"]:
        assert link.left_hk in hub_product
        assert link.right_hk in hub_supplier
    for link in mapped["lnk_product_marking"]:
        assert link.left_hk in hub_product
        assert link.right_hk in hub_marking

    link_supplier = {r.link_hk for r in mapped["lnk_product_supplier"]}
    for sat in mapped["sat_lnk_product_supplier__ref__global"]:
        assert sat.link_hk in link_supplier
    for sat in mapped["sat_supplier_profile__ref__global"]:
        assert sat.supplier_hk in hub_supplier
    for sat in mapped["sat_product_reference__ref__global"]:
        assert sat.product_hk in hub_product


def test_map_reference_is_load_ts_stable():
    tables = build_reference(n_suppliers=10, n_products=30, seed=5)
    a = map_reference(tables, LOAD_TS)
    b = map_reference(tables, LOAD_TS)
    assert [r.hk for r in a["hub_product"]] == [r.hk for r in b["hub_product"]]
    assert [r.hash_diff for r in a["sat_product_reference__ref__global"]] == [
        r.hash_diff for r in b["sat_product_reference__ref__global"]
    ]


# --- build artifact ----------------------------------------------------------


def test_build_frames_and_manifest_agree():
    tables = build_reference(n_suppliers=15, n_products=60, seed=9)
    dataset = _reference_frames(tables)
    vault = _vault_frames(tables, LOAD_TS)
    manifest = _manifest(tables, LOAD_TS, vault)
    assert manifest["record_source"] == RECORD_SOURCE
    assert manifest["counts"]["products"] == len(dataset["products"]) == 60
    assert manifest["vault_row_counts"]["hub_marking_code"] == 60
    assert set(dataset) == {"suppliers", "products", "sourcing"}
    assert manifest["genuine"]
    assert manifest["synthetic_but_labelled"]


def test_build_cli_dry_run_writes_nothing(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        build_main,
        ["--dry-run", "--n-suppliers", "5", "--n-products", "20", "--out-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output
    assert not any(tmp_path.iterdir())


def test_build_cli_writes_artifact(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        build_main,
        [
            "--n-suppliers",
            "8",
            "--n-products",
            "25",
            "--seed",
            "42",
            "--out-dir",
            str(tmp_path),
            "--load-ts",
            "2026-06-26T12:00:00Z",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "manifest.json").exists()
    for name in ("suppliers", "products", "sourcing"):
        assert (tmp_path / "dataset" / f"{name}.parquet").exists()
    assert (tmp_path / "vault" / "hub_product.parquet").exists()
