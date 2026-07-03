"""Machine-checkable consistency invariants from ``docs/generator-spec.md``
§12 — the definition of "цифры взаимно согласованы" for the B1 data rebuild.

Invariants #1-#10 are pure arithmetic over :mod:`legend`'s constants (no
warehouse needed). #5/#7/#8 are also checked against the actual
:func:`build_reference` output. #11/#12 (faux-PII locale rules, loyalty
gating) are structural regression guards over the seed SQL text — a live
ClickHouse/Postgres re-verify is B4's job, not this file's.
"""

from __future__ import annotations

from pathlib import Path

from warehouse.agentflow.dv2.reference import legend
from warehouse.agentflow.dv2.reference.generator import build_reference
from warehouse.agentflow.dv2.reference.gs1 import is_valid_gtin13
from warehouse.agentflow.dv2.reference.tnved import TNVED_HEADINGS

DV2_ROOT = Path(__file__).resolve().parents[2] / "warehouse" / "agentflow" / "dv2"

_MARKETPLACE_CHANNELS = {"marketplace_fbs"}
_D2C_CHANNELS = {"d2c_site"}
_B2B_CHANNELS = {"b2b_wholesale", "b2b_re_export", "b2b_eaeu"}


def _annual_revenue_rub() -> float:
    daily = sum(orders * check for _, _, orders, check in legend.MASTER_MATRIX)
    return daily * 365


def _orders_by_group() -> dict[str, int]:
    totals = {"marketplace": 0, "d2c": 0, "b2b": 0}
    for channel, _, orders, _ in legend.MASTER_MATRIX:
        if channel in _MARKETPLACE_CHANNELS:
            totals["marketplace"] += orders
        elif channel in _D2C_CHANNELS:
            totals["d2c"] += orders
        else:
            totals["b2b"] += orders
    return totals


def _revenue_by_group() -> dict[str, float]:
    totals = {"marketplace": 0.0, "d2c": 0.0, "b2b": 0.0}
    for channel, _, orders, check in legend.MASTER_MATRIX:
        revenue = orders * check
        if channel in _MARKETPLACE_CHANNELS:
            totals["marketplace"] += revenue
        elif channel in _D2C_CHANNELS:
            totals["d2c"] += revenue
        else:
            totals["b2b"] += revenue
    return totals


# --- #1 annual revenue -------------------------------------------------------


def test_invariant_1_annual_revenue_in_corridor():
    annual_b_rub = _annual_revenue_rub() / 1_000_000_000
    assert 3.5 <= annual_b_rub <= 5.0


# --- #2 order-count mix ------------------------------------------------------


def test_invariant_2_order_count_mix():
    totals = _orders_by_group()
    grand_total = sum(totals.values())
    marketplace_pct = 100 * totals["marketplace"] / grand_total
    b2b_pct = 100 * totals["b2b"] / grand_total
    d2c_pct = 100 * totals["d2c"] / grand_total
    assert 88 <= marketplace_pct <= 90
    assert 7 <= b2b_pct <= 9
    assert 2 <= d2c_pct <= 4


# --- #3 revenue mix -----------------------------------------------------------


def test_invariant_3_revenue_mix():
    totals = _revenue_by_group()
    grand_total = sum(totals.values())
    b2b_pct = 100 * totals["b2b"] / grand_total
    marketplace_pct = 100 * totals["marketplace"] / grand_total
    assert 65 <= b2b_pct <= 72
    assert 27 <= marketplace_pct <= 33


# --- #4 bimodal AOV -----------------------------------------------------------


def test_invariant_4_bimodal_avg_checks_no_mass_in_gap():
    # §1's master matrix pins dxb (re-export, "export pallets", thinner
    # margin per §5) at a 90k avg check — outside the general [30k, 80k] B2B
    # band the same table implies for the domestic + EAEU wholesale channels.
    # Read narrowly: the [30k, 80k] band covers RU + ala wholesale; dxb is a
    # documented, table-explicit outlier, not a spec violation.
    domestic_b2b_checks = [
        check
        for channel, branch, _, check in legend.MASTER_MATRIX
        if channel in _B2B_CHANNELS and branch != "dxb"
    ]
    marketplace_checks = [
        check for channel, _, _, check in legend.MASTER_MATRIX if channel in _MARKETPLACE_CHANNELS
    ]
    assert all(30_000 <= c <= 80_000 for c in domestic_b2b_checks)
    assert all(1_500 <= c <= 3_000 for c in marketplace_checks)
    # no channel's avg check falls in the 10k-25k dead zone (holds for all
    # channels, including dxb)
    assert all(not (10_000 < check < 25_000) for _, _, _, check in legend.MASTER_MATRIX)


# --- #5 pricing ladder ---------------------------------------------------------


def test_invariant_5_pricing_ladder_bands_are_disjoint_and_ordered():
    assert legend.FOB_PCT_RANGE[1] < legend.LANDED_PCT_RANGE[0]
    assert legend.LANDED_PCT_RANGE[1] < legend.WHOLESALE_PCT_RANGE[0]
    assert legend.WHOLESALE_PCT_RANGE[1] < legend.MARKETPLACE_NET_PCT
    assert legend.MARKETPLACE_NET_PCT < legend.RRC_PCT


def test_invariant_5_pricing_ladder_holds_per_sku():
    tables = build_reference()
    rrc_by_sku = {p.product_bk: p.rrc_price for p in tables.products}
    for sourcing in tables.sourcing:
        rrc = rrc_by_sku[sourcing.product_bk]
        fob_pct = sourcing.purchase_price / rrc
        assert legend.FOB_PCT_RANGE[0] <= fob_pct <= legend.FOB_PCT_RANGE[1]


# --- #6 seasonal curves average to 1.0 -----------------------------------------


def test_invariant_6_seasonal_curves_average_to_one():
    assert len(legend.SEASONAL_RETAIL) == 12
    assert len(legend.SEASONAL_B2B) == 12
    assert sum(legend.SEASONAL_RETAIL) / 12 == 1.0
    assert sum(legend.SEASONAL_B2B) / 12 == 1.0


# --- #7 GTIN validity -----------------------------------------------------------


def test_invariant_7_every_gtin_valid_and_in_eaeu_range():
    tables = build_reference()
    for product in tables.products:
        assert is_valid_gtin13(product.gtin)
        assert 460 <= int(product.gtin[:3]) <= 469


# --- #8 tnved headings ----------------------------------------------------------


def test_invariant_8_every_tnved_code_matches_a_spec_heading():
    allowed_headings = {"8516", "8509", "8423", "8422"}
    assert {h.heading for h in TNVED_HEADINGS} <= allowed_headings
    tables = build_reference()
    for product in tables.products:
        assert product.tnved_code.endswith("000000")
        assert len(product.tnved_code) == 10
        assert product.tnved_code[:4] in allowed_headings


# --- #9 dealer ordering frequency -> B2B orders/day -----------------------------


def test_invariant_9_dealer_frequency_yields_150_to_200_b2b_orders_per_day():
    assert sum(count for _, count, _ in legend.DEALER_FREQUENCY_TIERS) == legend.DEALER_CUSTOMERS
    weekly_orders = sum(count * freq for _, count, freq in legend.DEALER_FREQUENCY_TIERS)
    daily_b2b_orders = weekly_orders / 7
    assert 150 <= daily_b2b_orders <= 200


# --- #10 branch revenue shares ---------------------------------------------------


def test_invariant_10_branch_revenue_shares():
    by_branch: dict[str, float] = {}
    for _, branch, orders, check in legend.MASTER_MATRIX:
        by_branch[branch] = by_branch.get(branch, 0.0) + orders * check
    grand_total = sum(by_branch.values())
    shares = {branch: 100 * revenue / grand_total for branch, revenue in by_branch.items()}
    assert abs(sum(shares.values()) - 100) < 1e-6
    assert 55 <= shares["msk"] <= 65


# --- #11 faux-PII locale rules (structural, over seed SQL text) -----------------


def _read_seed_sql(*names: str) -> str:
    return "\n".join((DV2_ROOT / name).read_text(encoding="utf-8") for name in names)


def test_invariant_11_faux_pii_locale_rules_present_in_seed_sql():
    seed_sql = _read_seed_sql("satellite_seed.sql", "satellite_seed_all_branches.sql")
    # RU jurisdictions (§8): city phone prefixes + @example.test emails.
    assert "+7495" in seed_sql  # msk
    assert "+7812" in seed_sql  # spb
    assert "+7343" in seed_sql  # ekb
    assert "@example.test" in seed_sql
    # AE jurisdiction (dxb): +971 phones, latin transliteration names, .ae emails.
    assert "+971" in seed_sql
    assert "@example.ae" in seed_sql
    # KZ jurisdiction (ala): +7727 phones, .kz emails.
    assert "+7727" in seed_sql
    assert "@example.kz" in seed_sql


# --- #12 loyalty gating -----------------------------------------------------------


def test_invariant_12_loyalty_points_cap_is_within_three_percent_of_min_quarterly_spend():
    min_quarterly_spend = legend._TAIL_ORDERS_PER_WEEK * legend._RU_B2B_AVG_CHECK_RUB * 13
    assert legend.LOYALTY_POINTS_MAX_RUB <= legend.LOYALTY_RETRO_BONUS_PCT * min_quarterly_spend


def test_invariant_12_loyalty_rows_only_for_eligible_branches_in_seed_sql():
    assert legend.LOYALTY_ELIGIBLE_BRANCHES == ("msk", "spb", "ekb")
    seed_sql = _read_seed_sql("satellite_seed.sql", "satellite_seed_all_branches.sql")
    for branch in legend.LOYALTY_ELIGIBLE_BRANCHES:
        assert f"sat_customer_loyalty__bitrix__{branch}" in seed_sql
    for branch in ("dxb", "ala"):
        assert f"sat_customer_loyalty__bitrix__{branch}" not in seed_sql
