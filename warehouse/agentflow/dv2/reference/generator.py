"""Deterministic generator for the AgentFlow supplier / product reference.

Given a seed, ``build_reference`` produces a coherent, reproducible grocery
reference (suppliers, products, GS1 marking codes, product->supplier
sourcing) for the X5 / EAEU context.

What is genuine vs. synthetic (kept explicit, see README):

* genuine: ТН ВЭД headings, GS1 GTIN-13 / GLN-13 check digits, RU INN-10
  check digit, EAEU GS1 prefix range, gross >= net packaging invariant;
* synthetic but plausible & labelled: supplier legal names, brand names,
  specific SKU<->GTIN<->supplier assignments, packaging dimensions, prices.

The output is storage-neutral (dataclasses / DataFrames). Landing it into the
DV2 raw vault is the job of :mod:`vault_mapping`; publishing it to cloud
storage is the job of :mod:`build`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import Decimal

from .gs1 import EAEU_PREFIX_RANGE, gtin13_check_digit, make_gtin13
from .tnved import TNVED_HEADINGS, TnvedHeading

# Branch geography -> ISO country, matching the AgentFlow 5-branch model
# (msk/spb/ekb = RU, ala = KZ, dxb = AE) plus BY as an EAEU sourcing origin.
COUNTRY_WEIGHTS: tuple[tuple[str, int], ...] = (("RU", 70), ("KZ", 12), ("BY", 10), ("AE", 8))

SUPPLIER_LEGAL_FORMS: tuple[str, ...] = ("ООО", "АО", "ПАО", "ТД")
SUPPLIER_NAME_STEMS: tuple[str, ...] = (
    "Молочный Стандарт",
    "Мясной Дом",
    "Северная Пекарня",
    "ЮгАгро",
    "ПродИмпорт",
    "Сибирская Нива",
    "Балтийский Улов",
    "ВолгаПродукт",
    "Уральские Фермы",
    "ГринФрут",
    "ЧайКофеТрейд",
    "Кондитер Плюс",
    "МаслоПром",
    "АкваИсток",
    "БакалеяОпт",
    "Фуд Альянс",
    "Агрохолдинг Восток",
    "ПремиумФрукт",
    "Рыбный Причал",
    "Хлебный Край",
    "СладкоТорг",
    "НатурПродукт",
    "Эко Ферма",
    "ГастрономЪ",
    "ПродСоюз",
    "ТоргСервис",
    "Деликатес",
    "ВкусМаркет",
    "Регион Продукт",
    "Снаб Логистик",
)
BRANDS: tuple[str, ...] = (
    "Любимый Край",
    "Домик в Деревне",
    "Каждый День",
    "Красная Цена",
    "Простоквашино",
    "Чёрный Жемчуг",
    "Зелёная Линия",
    "Особый Рецепт",
    "Первым Делом",
    "Сытый Кот",
    "Фермерское",
    "Золотая Нива",
    "Свежесть",
    "Традиция",
    "Эконом",
)
PACK_TYPES: tuple[str, ...] = ("Пакет", "Коробка", "Бутылка", "Банка", "Лоток", "Туба", "Дой-пак")
SUPPLIER_STATUSES: tuple[tuple[str, int], ...] = (("active", 88), ("inactive", 8), ("suspended", 4))
MARKING_STATUSES: tuple[tuple[str, int], ...] = (
    ("issued", 82),
    ("in_circulation", 14),
    ("withdrawn", 4),
)

_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)


def ru_inn10_check_digit(first9: str) -> int:
    """Real control digit for a 10-digit RU INN (legal entity)."""
    if len(first9) != 9 or not first9.isdigit():
        raise ValueError("RU INN-10 payload must be 9 digits")
    total = sum(w * int(d) for w, d in zip(_INN10_WEIGHTS, first9, strict=True))
    return total % 11 % 10


def make_ru_inn10(rng: random.Random) -> str:
    first9 = "".join(str(rng.randint(0, 9)) for _ in range(9))
    return first9 + str(ru_inn10_check_digit(first9))


def make_gln13(rng: random.Random, prefix: int) -> str:
    """A GS1 GLN-13 (same mod-10 check as GTIN) for a supplier location."""
    payload = f"{prefix:03d}{rng.randint(0, 10**9 - 1):09d}"
    return payload + str(gtin13_check_digit(payload))


def _weighted_choice(rng: random.Random, options: tuple[tuple[str, int], ...]) -> str:
    population = [value for value, _ in options]
    weights = [weight for _, weight in options]
    return rng.choices(population, weights=weights, k=1)[0]


@dataclass(frozen=True, slots=True)
class SupplierRef:
    supplier_bk: str  # tax id (INN / BIN / UNP / TRN) — the hub business key
    supplier_name: str
    tax_country_code: str
    supplier_status: str
    gln: str


@dataclass(frozen=True, slots=True)
class ProductRef:
    product_bk: str  # reference SKU — the hub business key
    product_name: str
    brand: str
    category: str
    tnved_code: str
    gpc_brick_code: str
    gtin: str  # GS1 marking-code business key
    marking_status: str
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
    purchase_price: Decimal
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
    stems = list(SUPPLIER_NAME_STEMS)
    rng.shuffle(stems)
    suppliers: list[SupplierRef] = []
    seen_bk: set[str] = set()
    for i in range(n):
        country = _weighted_choice(rng, COUNTRY_WEIGHTS)
        # Country-appropriate tax id; only RU INN carries a real check digit.
        if country == "RU":
            bk = make_ru_inn10(rng)
        elif country == "KZ":
            bk = "".join(str(rng.randint(0, 9)) for _ in range(12))  # БИН
        elif country == "BY":
            bk = "".join(str(rng.randint(0, 9)) for _ in range(9))  # УНП
        else:
            bk = "1000" + "".join(str(rng.randint(0, 9)) for _ in range(11))  # AE TRN
        if bk in seen_bk:
            continue
        seen_bk.add(bk)
        stem = stems[i % len(stems)]
        suffix = "" if i < len(stems) else f" №{i // len(stems) + 1}"
        name = f"{_weighted_choice_form(rng)} «{stem}{suffix}»"
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


def _make_products(rng: random.Random, n: int) -> list[ProductRef]:
    products: list[ProductRef] = []
    item_ref = rng.randint(10_000, 50_000)
    for i in range(n):
        heading: TnvedHeading = rng.choice(TNVED_HEADINGS)
        brand = rng.choice(BRANDS)
        # Clean SKU-style name "<commodity>, <brand>, <net> г" — avoids RU
        # adjective-agreement artefacts while staying catalog-realistic.
        commodity = heading.description.split(",")[0].split(" и ")[0]
        net = rng.choice((150, 180, 200, 250, 330, 400, 450, 500, 750, 900, 1000))
        gross = net + rng.choice((8, 12, 18, 25, 35, 50))
        prefix = rng.choice(list(EAEU_PREFIX_RANGE))
        item_ref = (item_ref + rng.randint(1, 37)) % 10**9
        gtin = make_gtin13(prefix, item_ref)
        sku = f"RC{i + 1:06d}"
        products.append(
            ProductRef(
                product_bk=sku,
                product_name=f"{commodity}, {brand}, {net} г",
                brand=brand,
                category=heading.category,
                tnved_code=heading.code10,
                gpc_brick_code=f"100{rng.randint(0, 99999):05d}",  # illustrative GS1 GPC brick
                gtin=gtin,
                marking_status=_weighted_choice(rng, MARKING_STATUSES),
                gross_weight_g=gross,
                net_weight_g=net,
                length_mm=rng.choice((60, 80, 100, 120, 160, 200)),
                width_mm=rng.choice((40, 50, 60, 80, 100)),
                height_mm=rng.choice((80, 120, 160, 200, 240, 300)),
                units_per_pack=rng.choice((1, 1, 1, 6, 8, 12)),
                pack_type=rng.choice(PACK_TYPES),
            )
        )
    return products


def _make_sourcing(
    rng: random.Random, products: list[ProductRef], suppliers: list[SupplierRef]
) -> list[SourcingRef]:
    active = [s for s in suppliers if s.supplier_status == "active"] or suppliers
    sourcing: list[SourcingRef] = []
    for product in products:
        n_suppliers = rng.choices((1, 2, 3), weights=(55, 33, 12), k=1)[0]
        chosen = rng.sample(active, k=min(n_suppliers, len(active)))
        for priority, supplier in enumerate(chosen, start=1):
            base_price = Decimal(rng.randint(35, 1200))
            cents = Decimal(rng.choice(("0.00", "0.50", "0.90", "0.99")))
            sourcing.append(
                SourcingRef(
                    product_bk=product.product_bk,
                    supplier_bk=supplier.supplier_bk,
                    supplier_priority=priority,
                    purchase_price=base_price + cents,
                    min_order_qty=rng.choice((1, 6, 12, 24, 48, 100)),
                    lead_time_days=rng.choice((1, 2, 3, 5, 7, 10, 14)),
                    valid_from="2026-01-01",
                    valid_to=None,
                )
            )
    return sourcing


def build_reference(
    *, n_suppliers: int = 40, n_products: int = 300, seed: int = 20260626
) -> ReferenceTables:
    """Build a deterministic supplier/product reference for the given seed."""
    if n_suppliers < 1 or n_products < 1:
        raise ValueError("n_suppliers and n_products must be positive")
    rng = random.Random(seed)
    suppliers = _make_suppliers(rng, n_suppliers)
    products = _make_products(rng, n_products)
    sourcing = _make_sourcing(rng, products, suppliers)
    return ReferenceTables(suppliers=suppliers, products=products, sourcing=sourcing, seed=seed)
