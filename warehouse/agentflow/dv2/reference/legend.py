"""Business-legend constants: the numeric single source of truth pinned in
``docs/generator-spec.md``.

This module holds no logic — only the master matrix, seasonal curves,
customer-population and pricing-ladder numbers a human can read straight off
generator-spec.md's tables. Two consumers:

1. :mod:`generator` imports the catalog quotas and pricing-ladder bands, so
   the reference-catalog code and this module can't drift apart.
2. ``tests/unit/test_generator_spec_invariants.py`` asserts generator-spec.md
   §12's consistency invariants directly against these constants — the
   "цифры взаимно согласованы" contract made machine-checkable without a
   live warehouse.

The DV2 seed SQL (``synthetic_seed.sql``, ``satellite_seed*.sql``,
``postgres_oltp/seed.sql``) is hand-authored (ClickHouse/Postgres SQL can't
import this module) but its literal constants are derived from these same
numbers — each seed file's header comment cites the generator-spec.md section
it mirrors.
"""

from __future__ import annotations

# --- §1 master matrix — baseline day (seasonal multiplier 1.0) --------------

# (channel, branch, orders_per_day, avg_check_rub)
MASTER_MATRIX: tuple[tuple[str, str, int, int], ...] = (
    ("b2b_wholesale", "msk", 70, 52_000),
    ("b2b_wholesale", "spb", 35, 52_000),
    ("b2b_wholesale", "ekb", 25, 52_000),
    ("b2b_re_export", "dxb", 15, 90_000),
    ("b2b_eaeu", "ala", 15, 45_000),
    ("marketplace_fbs", "msk", 1_750, 2_150),
    ("d2c_site", "msk", 55, 3_300),
)

# --- §4 seasonal calendar — 12 monthly multipliers, each curve averages 1.0 -

SEASONAL_RETAIL: tuple[float, ...] = (
    0.70,
    1.10,
    1.20,
    0.85,
    0.80,
    0.75,
    0.80,
    0.90,
    0.95,
    1.05,
    1.45,
    1.45,
)
SEASONAL_B2B: tuple[float, ...] = (
    0.60,
    1.15,
    0.95,
    0.85,
    0.80,
    0.85,
    0.95,
    1.05,
    1.20,
    1.40,
    1.30,
    0.90,
)

# --- §5 pricing ladder — share of RRC, disjoint bands by construction -------

FOB_PCT_RANGE: tuple[float, float] = (0.24, 0.30)
LANDED_PCT_RANGE: tuple[float, float] = (0.32, 0.40)
WHOLESALE_PCT_RANGE: tuple[float, float] = (0.60, 0.65)
MARKETPLACE_NET_PCT: float = 0.78
RRC_PCT: float = 1.00

# --- §3 SKU catalog — 10 categories, 160 SKUs baseline ----------------------

# (category, count-at-160-baseline, rrc_low, rrc_high)
BASE_CATEGORY_QUOTAS: tuple[tuple[str, int, int, int], ...] = (
    ("Электрочайники", 22, 1490, 3990),
    ("Аэрогрили и грили", 20, 3490, 7990),
    ("Блендеры", 20, 1690, 4490),
    ("Миксеры", 14, 1990, 7990),
    ("Кофеварки и кофемолки", 18, 1990, 6990),
    ("Мультипекари, вафельницы, сэндвичницы", 16, 1790, 3490),
    ("Измельчители", 12, 1290, 2490),
    ("Соковыжималки", 10, 2490, 5990),
    ("Кухонные весы", 12, 790, 1490),
    ("Вакууматоры и сушилки", 16, 2290, 5490),
)

# --- §6 supplier country mix -------------------------------------------------

COUNTRY_WEIGHTS: tuple[tuple[str, int], ...] = (("CN", 72), ("RU", 16), ("AE", 8), ("KZ", 4))
TOTAL_SUPPLIERS: int = 30  # 22 CN + 5 RU + 2 AE + 1 KZ

# --- §7 customer populations -------------------------------------------------

RETAIL_CUSTOMERS: int = 2_000  # all msk jurisdiction
DEALER_ACCOUNTS_BY_BRANCH: dict[str, int] = {
    "msk": 190,
    "spb": 100,
    "ekb": 70,
    "dxb": 60,
    "ala": 80,
}
DEALER_CUSTOMERS: int = sum(DEALER_ACCOUNTS_BY_BRANCH.values())  # 500
TOTAL_CUSTOMERS: int = RETAIL_CUSTOMERS + DEALER_CUSTOMERS  # 2,500

# Ordering-frequency tiers (§7): (tier, account_count, orders_per_week).
# core(200) + mid(200) + tail(100) = 500 = DEALER_CUSTOMERS.
DEALER_FREQUENCY_TIERS: tuple[tuple[str, int, float], ...] = (
    ("core", 200, 4.0),
    ("mid", 200, 1.5),
    ("tail", 100, 0.5),
)

# Branches eligible for the dealer retro-bonus loyalty program (§8/§12 #12) —
# dxb/ala dealers are on contract terms, not the bonus program.
LOYALTY_ELIGIBLE_BRANCHES: tuple[str, ...] = ("msk", "spb", "ekb")
LOYALTY_RETRO_BONUS_PCT: float = 0.03  # 3% of trailing-quarter purchases

# Safe upper bound for seeded loyalty_points: 3% of the smallest plausible
# trailing-quarter spend among loyalty-eligible (msk/spb/ekb) dealers — a
# tail-tier dealer (0.5 orders/week) at the RU B2B avg check. Any seed formula
# that caps loyalty_points at this constant satisfies §12 invariant #12 for
# every eligible dealer, not just the average one.
_TAIL_ORDERS_PER_WEEK = DEALER_FREQUENCY_TIERS[2][2]
_RU_B2B_AVG_CHECK_RUB = 52_000  # MASTER_MATRIX b2b_wholesale avg_check_rub
_MIN_QUARTERLY_SPEND_RUB = _TAIL_ORDERS_PER_WEEK * _RU_B2B_AVG_CHECK_RUB * 13
LOYALTY_POINTS_MAX_RUB: int = 9_000  # < LOYALTY_RETRO_BONUS_PCT * _MIN_QUARTERLY_SPEND_RUB

# --- §11 DV2 seed volumes — hub_order split ----------------------------------

TOTAL_PRODUCTS: int = 160
ORDERS_MARKETPLACE: int = 8_900
ORDERS_SITE: int = 280
ORDERS_B2B_BY_BRANCH: dict[str, int] = {
    "msk": 360,
    "spb": 180,
    "ekb": 130,
    "dxb": 75,
    "ala": 75,
}
TOTAL_ORDERS: int = ORDERS_MARKETPLACE + ORDERS_SITE + sum(ORDERS_B2B_BY_BRANCH.values())  # 10,000

# --- §10 currencies and determinism ------------------------------------------

FX_AED_RUB: float = 24.50
FX_KZT_RUB: float = 0.175
FX_CNY_RUB: float = 12.40
GENERATOR_SEED: int = 20260626
