"""Deterministic generator for the AgentFlow supplier / product reference.

Given a seed, ``build_reference`` produces a coherent, reproducible small
kitchen-appliance reference (suppliers, products, GS1 marking codes,
product->supplier sourcing) for the own-brand importer legend
(``docs/domain.md``, ``docs/generator-spec.md``).

What is genuine vs. synthetic (kept explicit, see README):

* genuine: ТН ВЭД headings, GS1 GTIN-13 / GLN-13 check digits, RU INN-10
  check digit, EAEU GS1 prefix range, gross >= net packaging invariant;
* synthetic but plausible & labelled: supplier legal names, the specific
  SKU<->GTIN<->supplier assignments, packaging dimensions, prices, and the
  CN USCC-18 check character (structurally shaped, **not** a verified
  GB 32100-2015 check digit — see :func:`make_cn_uscc18`).

The output is storage-neutral (dataclasses / DataFrames). Landing it into the
DV2 raw vault is the job of :mod:`vault_mapping`; publishing it to cloud
storage is the job of :mod:`build`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .gs1 import EAEU_PREFIX_RANGE, gtin13_check_digit, make_gtin13
from .legend import (
    BASE_CATEGORY_QUOTAS,
    COUNTRY_WEIGHTS,
    FOB_PCT_RANGE,
    GENERATOR_SEED,
    TOTAL_PRODUCTS,
    TOTAL_SUPPLIERS,
)
from .tnved import TNVED_HEADINGS, TnvedHeading

# --- supplier naming pools ----------------------------------------------------

CN_CITY_STEMS: tuple[str, ...] = (
    "Foshan",
    "Ningbo",
    "Shenzhen",
    "Cixi",
    "Yongkang",
    "Zhongshan",
    "Dongguan",
    "Taizhou",
    "Hangzhou",
    "Guangzhou",
    "Shunde",
    "Ciqing",
    "Jieyang",
    "Chaozhou",
    "Yuyao",
)
CN_SUFFIXES: tuple[str, ...] = (
    "Electric Appliance Co., Ltd.",
    "Household Appliance Co., Ltd.",
    "Kitchenware Manufacturing Co., Ltd.",
    "Electronics Co., Ltd.",
    "Housewares Co., Ltd.",
    "Smart Home Appliance Co., Ltd.",
)
RU_SUPPLIER_STEMS: tuple[str, ...] = (
    "УпакТорг",
    "БумПак Сервис",
    "КабельКомплект",
    "ПечатьЛайн",
    "КомплектСнаб",
    "ТараПром",
    "ИнструкцияПринт",
    "МаркПак",
)
AE_SUPPLIER_NAMES: tuple[str, ...] = (
    "Jebel Ali Trading FZE",
    "Gulf Gate General Trading LLC",
    "Al Falah Consolidators FZCO",
    "Dubai Bridge Trading FZE",
    "Emirates Cargo Hub General Trading LLC",
    "Jafza Link Trading FZCO",
)
KZ_SUPPLIER_NAMES: tuple[str, ...] = (
    "Алатау Дистрибьюшн",
    "ЕвразияСервис Логистик",
    "Алматы Снаб Транзит",
    "Достык Трейд Сервис",
)

SUPPLIER_LEGAL_FORMS: tuple[str, ...] = ("ООО", "АО", "ПАО", "ТД")
SUPPLIER_STATUSES: tuple[tuple[str, int], ...] = (("active", 88), ("inactive", 8), ("suspended", 4))
MARKING_STATUSES: tuple[tuple[str, int], ...] = (
    ("issued", 82),
    ("in_circulation", 14),
    ("withdrawn", 4),
)
PACK_TYPES: tuple[str, ...] = (
    "Коробка",
    "Коробка с ручкой",
    "Групповая упаковка",
    "Индивидуальная упаковка",
)

_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)

# GB 32100-2015 (统一社会信用代码) 31-char alphabet: digits + letters, excluding
# I/O/S/V/Z (visually ambiguous with 1/0/5/... in Chinese official use).
_USCC_ALPHABET = "0123456789ABCDEFGHJKLMNPQRTUWXY"


def ru_inn10_check_digit(first9: str) -> int:
    """Real control digit for a 10-digit RU INN (legal entity)."""
    if len(first9) != 9 or not first9.isdigit():
        raise ValueError("RU INN-10 payload must be 9 digits")
    total = sum(w * int(d) for w, d in zip(_INN10_WEIGHTS, first9, strict=True))
    return total % 11 % 10


def make_ru_inn10(rng: random.Random) -> str:
    first9 = "".join(str(rng.randint(0, 9)) for _ in range(9))
    return first9 + str(ru_inn10_check_digit(first9))


def make_cn_uscc18(rng: random.Random) -> str:
    """Mint an 18-char CN USCC (统一社会信用代码), structurally shaped.

    The first two positions (registration-department / organization-category
    code) and the 6-digit administrative-division code follow the real
    GB 32100-2015 layout. The 18th (check) character is a **labelled
    placeholder**, not a verified GB 32100-2015 mod-31 check digit — cheaper
    and, unverified, safer than shipping a check-digit algorithm we cannot
    confirm against a known-good vector. See README "synthetic but labelled".
    """
    reg_dept = "9"  # enterprise
    org_category = rng.choice("1239")
    division = "".join(rng.choice("0123456789") for _ in range(6))
    body = "".join(rng.choice(_USCC_ALPHABET) for _ in range(9))
    check = rng.choice(_USCC_ALPHABET)
    return reg_dept + org_category + division + body + check


def make_gln13(rng: random.Random, prefix: int) -> str:
    """A GS1 GLN-13 (same mod-10 check as GTIN) for a supplier location."""
    payload = f"{prefix:03d}{rng.randint(0, 10**9 - 1):09d}"
    return payload + str(gtin13_check_digit(payload))


def _weighted_choice(rng: random.Random, options: tuple[tuple[str, int], ...]) -> str:
    population = [value for value, _ in options]
    weights = [weight for _, weight in options]
    return rng.choices(population, weights=weights, k=1)[0]


def _largest_remainder_allocation(
    total: int, weights: tuple[tuple[str, int], ...]
) -> dict[str, int]:
    """Allocate ``total`` items across ``weights`` (label, weight) pairs so the
    counts sum to exactly ``total`` while tracking the weights proportionally
    (largest-remainder / Hamilton apportionment). Deterministic, no RNG.
    """
    weight_sum = sum(w for _, w in weights)
    shares = {label: total * w / weight_sum for label, w in weights}
    counts = {label: int(share) for label, share in shares.items()}
    remainder = total - sum(counts.values())
    order = sorted(shares, key=lambda label: shares[label] - counts[label], reverse=True)
    for label in order[:remainder]:
        counts[label] += 1
    return counts


@dataclass(frozen=True, slots=True)
class SupplierRef:
    supplier_bk: str  # tax id (INN / USCC / TRN / BIN) — the hub business key
    supplier_name: str
    tax_country_code: str
    supplier_status: str
    gln: str


@dataclass(frozen=True, slots=True)
class ProductRef:
    product_bk: str  # reference SKU — the hub business key
    product_name: str
    brand: str  # empty string: no-brand-token decision (generator-spec.md §3)
    category: str
    tnved_code: str
    gpc_brick_code: str
    gtin: str  # GS1 marking-code business key
    marking_status: str
    rrc_price: Decimal  # recommended retail price, ₽, x,x90-style (§3/§5 rung 5)
    gross_weight_g: int
    net_weight_g: int
    length_mm: int
    width_mm: int
    height_mm: int
    units_per_pack: int
    pack_type: str


@dataclass(frozen=True, slots=True)
class SourcingRef:
    product_bk: str
    supplier_bk: str
    supplier_priority: int  # 1 = primary
    purchase_price: Decimal  # FOB price, ₽ (§5 rung 1: 24-30% of RRC)
    min_order_qty: int
    lead_time_days: int
    valid_from: str  # ISO date
    valid_to: str | None


@dataclass(frozen=True, slots=True)
class ReferenceTables:
    suppliers: list[SupplierRef] = field(default_factory=list)
    products: list[ProductRef] = field(default_factory=list)
    sourcing: list[SourcingRef] = field(default_factory=list)
    seed: int = 0


def _make_suppliers(rng: random.Random, n: int) -> list[SupplierRef]:
    country_counts = _largest_remainder_allocation(n, COUNTRY_WEIGHTS)
    countries: list[str] = []
    for country, count in country_counts.items():
        countries.extend([country] * count)
    rng.shuffle(countries)

    ru_stems = list(RU_SUPPLIER_STEMS)
    rng.shuffle(ru_stems)
    ae_names = list(AE_SUPPLIER_NAMES)
    rng.shuffle(ae_names)
    kz_names = list(KZ_SUPPLIER_NAMES)
    rng.shuffle(kz_names)

    suppliers: list[SupplierRef] = []
    seen_bk: set[str] = set()
    ru_i = ae_i = kz_i = 0
    for i, country in enumerate(countries):
        if country == "CN":
            bk = make_cn_uscc18(rng)
            city = CN_CITY_STEMS[i % len(CN_CITY_STEMS)]
            suffix = rng.choice(CN_SUFFIXES)
            district = CN_CITY_STEMS[(i * 7) % len(CN_CITY_STEMS)]
            name = f"{city} {district} {suffix}" if district != city else f"{city} {suffix}"
        elif country == "RU":
            bk = make_ru_inn10(rng)
            stem = ru_stems[ru_i % len(ru_stems)]
            ru_i += 1
            suffix = "" if ru_i <= len(ru_stems) else f" №{ru_i // len(ru_stems) + 1}"
            name = f"{_weighted_choice_form(rng)} «{stem}{suffix}»"
        elif country == "AE":
            bk = "1000" + "".join(str(rng.randint(0, 9)) for _ in range(11))  # AE TRN, 15 digits
            name = ae_names[ae_i % len(ae_names)]
            ae_i += 1
        else:  # KZ
            bk = "".join(str(rng.randint(0, 9)) for _ in range(12))  # KZ BIN
            name = f"{kz_names[kz_i % len(kz_names)]} ТОО"
            kz_i += 1
        if bk in seen_bk:
            continue
        seen_bk.add(bk)
        prefix = rng.choice(list(EAEU_PREFIX_RANGE))
        suppliers.append(
            SupplierRef(
                supplier_bk=bk,
                supplier_name=name,
                tax_country_code=country,
                supplier_status=_weighted_choice(rng, SUPPLIER_STATUSES),
                gln=make_gln13(rng, prefix),
            )
        )
    return suppliers


def _weighted_choice_form(rng: random.Random) -> str:
    return rng.choices(list(SUPPLIER_LEGAL_FORMS), weights=[60, 20, 8, 12], k=1)[0]


# Catalog quotas and pricing-ladder bands live in :mod:`legend` (single
# source of truth, also asserted against by the §12 invariant tests). Bands
# are disjoint by construction (FOB max 0.30 < landed min 0.32 < wholesale
# min 0.60 < mp-net 0.78 < RRC 1.00), so any sample within each band preserves
# the FOB < landed < wholesale < marketplace-net < RRC chain per SKU.


def _scale_category_quotas(n_products: int) -> dict[str, int]:
    weights = tuple((category, count) for category, count, _, _ in BASE_CATEGORY_QUOTAS)
    return _largest_remainder_allocation(n_products, weights)


def _pick_rrc(rng: random.Random, low: int, high: int) -> Decimal:
    """Recommended retail price, ₽, snapped to the x,x90 ending (§3)."""
    lo_hundreds, hi_hundreds = low // 100, high // 100
    candidates = [
        h * 100 + 90 for h in range(lo_hundreds, hi_hundreds + 1) if low <= h * 100 + 90 <= high
    ]
    return Decimal(rng.choice(candidates or [low]))


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# category -> attribute-based RU naming templates (no brand token). Each
# template is (base_name, attr_pools) where attr_pools are joined as
# comma-separated clauses to avoid RU adjective-agreement artefacts.
_NAME_SPECS: dict[str, tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]] = {
    "Электрочайники": (
        (
            "Чайник электрический",
            (
                ("1 л", "1.2 л", "1.5 л", "1.7 л", "2 л"),
                ("1800 Вт", "2000 Вт", "2200 Вт", "2400 Вт"),
            ),
        ),
    ),
    "Аэрогрили и грили": (
        ("Аэрогриль", (("3 л", "4 л", "5 л", "6 л"), ("1200 Вт", "1500 Вт", "1800 Вт"))),
        (
            "Гриль электрический",
            (("открытого типа", "закрытого типа"), ("1500 Вт", "1800 Вт", "2000 Вт")),
        ),
    ),
    "Блендеры": (
        ("Блендер погружной", (("600 Вт", "700 Вт", "800 Вт", "1000 Вт"),)),
        ("Блендер стационарный", (("1.5 л", "2 л"), ("500 Вт", "600 Вт", "700 Вт"))),
    ),
    "Миксеры": (
        ("Миксер ручной", (("300 Вт", "400 Вт", "500 Вт"),)),
        ("Миксер планетарный", (("4 л", "5 л"), ("1000 Вт", "1200 Вт"))),
    ),
    "Кофеварки и кофемолки": (
        ("Кофеварка капельная", (("0.6 л", "1 л", "1.2 л"),)),
        ("Кофеварка рожковая", (("15 бар", "19 бар"),)),
        ("Кофемолка электрическая", (("150 Вт", "200 Вт"),)),
    ),
    "Мультипекари, вафельницы, сэндвичницы": (
        ("Мультипекарь", (("700 Вт", "800 Вт", "1000 Вт"),)),
        ("Вафельница электрическая", (("800 Вт", "1000 Вт"),)),
        ("Сэндвичница электрическая", (("700 Вт", "900 Вт"),)),
    ),
    "Измельчители": (
        (
            "Измельчитель электрический",
            (("0.5 л", "0.8 л", "1 л", "1.5 л"), ("200 Вт", "300 Вт", "400 Вт")),
        ),
    ),
    "Соковыжималки": (
        ("Соковыжималка шнековая", (("150 Вт", "200 Вт"),)),
        ("Соковыжималка центробежная", (("400 Вт", "600 Вт", "800 Вт"),)),
    ),
    "Кухонные весы": (("Весы кухонные электронные", (("до 3 кг", "до 5 кг", "до 10 кг"),)),),
    "Вакууматоры и сушилки": (
        ("Вакууматор бытовой", (("100 Вт", "120 Вт", "135 Вт"),)),
        (
            "Сушилка для продуктов электрическая",
            (("5 лотков", "6 лотков", "8 лотков"), ("250 Вт", "350 Вт", "500 Вт")),
        ),
    ),
}


_VACUUM_DRY_CATEGORY = "Вакууматоры и сушилки"


def _tnved_for_category_slot(category: str, index_in_category: int) -> TnvedHeading:
    """Pick the ТН ВЭД heading (and, for the split category, the matching
    name template index) for the ``index_in_category``-th SKU of
    ``category``. Categories with a single heading always return it;
    "Вакууматоры и сушилки" splits 5:3 vacuum-sealer (8422) : dryer (8516)
    per 8-slot block, so both sub-types are represented across the quota.
    """
    headings = [h for h in TNVED_HEADINGS if h.category == category]
    if len(headings) == 1:
        return headings[0]
    return headings[0] if index_in_category % 8 < 5 else headings[1]


def _make_product_name(rng: random.Random, category: str, index_in_category: int) -> str:
    templates = _NAME_SPECS[category]
    if category == _VACUUM_DRY_CATEGORY:
        # template[0] = vacuum sealer (8422), template[1] = dryer (8516) —
        # same 5:3 split as _tnved_for_category_slot so name and heading agree.
        template = templates[0] if index_in_category % 8 < 5 else templates[1]
    else:
        template = rng.choice(templates)
    base, attr_pools = template
    attrs = ", ".join(rng.choice(pool) for pool in attr_pools)
    return f"{base}, {attrs}" if attrs else base


def _make_products(rng: random.Random, n: int) -> list[ProductRef]:
    quotas = _scale_category_quotas(n)
    band_by_category = {cat: (low, high) for cat, _, low, high in BASE_CATEGORY_QUOTAS}
    products: list[ProductRef] = []
    item_ref = rng.randint(10_000, 50_000)
    i = 0
    for category, _, _, _ in BASE_CATEGORY_QUOTAS:
        quota = quotas[category]
        low, high = band_by_category[category]
        for slot in range(quota):
            heading = _tnved_for_category_slot(category, slot)
            rrc = _pick_rrc(rng, low, high)
            net = rng.choice((350, 500, 700, 900, 1200, 1800, 2500, 3500))
            gross = net + rng.choice((80, 120, 180, 250, 350))
            prefix = rng.choice(list(EAEU_PREFIX_RANGE))
            item_ref = (item_ref + rng.randint(1, 37)) % 10**9
            gtin = make_gtin13(prefix, item_ref)
            sku = f"RC{i + 1:06d}"
            products.append(
                ProductRef(
                    product_bk=sku,
                    product_name=_make_product_name(rng, category, slot),
                    brand="",
                    category=category,
                    tnved_code=heading.code10,
                    gpc_brick_code=f"100{rng.randint(0, 99999):05d}",  # illustrative GS1 GPC brick
                    gtin=gtin,
                    marking_status=_weighted_choice(rng, MARKING_STATUSES),
                    rrc_price=rrc,
                    gross_weight_g=gross,
                    net_weight_g=net,
                    length_mm=rng.choice((150, 200, 250, 300, 350, 420)),
                    width_mm=rng.choice((120, 150, 200, 250, 300)),
                    height_mm=rng.choice((150, 200, 250, 320, 400)),
                    units_per_pack=rng.choices(
                        (1, 1, 1, 1, 4, 6), weights=(70, 70, 70, 70, 8, 4), k=1
                    )[0],
                    pack_type=rng.choice(PACK_TYPES),
                )
            )
            i += 1
    return products


def _make_sourcing(
    rng: random.Random, products: list[ProductRef], suppliers: list[SupplierRef]
) -> list[SourcingRef]:
    cn_active = (
        [s for s in suppliers if s.tax_country_code == "CN" and s.supplier_status == "active"]
        or [s for s in suppliers if s.tax_country_code == "CN"]
        or suppliers
    )
    quarters = ("2026-01-01", "2026-04-01", "2026-07-01", "2026-10-01")
    sourcing: list[SourcingRef] = []
    for product in products:
        n_suppliers = rng.choices((1, 2), weights=(60, 40), k=1)[0]
        chosen = rng.sample(cn_active, k=min(n_suppliers, len(cn_active)))
        fob_pct = rng.uniform(*FOB_PCT_RANGE)
        for priority, supplier in enumerate(chosen, start=1):
            purchase_price = _quantize_money(product.rrc_price * Decimal(str(round(fob_pct, 4))))
            is_air = rng.random() < 0.10
            lead_time = rng.randint(12, 18) if is_air else rng.randint(40, 60)
            sourcing.append(
                SourcingRef(
                    product_bk=product.product_bk,
                    supplier_bk=supplier.supplier_bk,
                    supplier_priority=priority,
                    purchase_price=purchase_price,
                    min_order_qty=rng.choice((300, 400, 500, 600, 800, 1000)),
                    lead_time_days=lead_time,
                    valid_from=rng.choice(quarters),
                    valid_to=None,
                )
            )
    return sourcing


def build_reference(
    *,
    n_suppliers: int = TOTAL_SUPPLIERS,
    n_products: int = TOTAL_PRODUCTS,
    seed: int = GENERATOR_SEED,
) -> ReferenceTables:
    """Build a deterministic supplier/product reference for the given seed."""
    if n_suppliers < 1 or n_products < 1:
        raise ValueError("n_suppliers and n_products must be positive")
    rng = random.Random(seed)
    suppliers = _make_suppliers(rng, n_suppliers)
    products = _make_products(rng, n_products)
    sourcing = _make_sourcing(rng, products, suppliers)
    return ReferenceTables(suppliers=suppliers, products=products, sourcing=sourcing, seed=seed)
