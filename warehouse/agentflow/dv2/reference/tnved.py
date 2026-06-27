"""ТН ВЭД ЕАЭС (EAEU customs nomenclature) grocery reference subset.

The codes here are **real** Harmonized-System / ТН ВЭД ЕАЭС *headings* (the
first four digits, which are identical across the international HS and the
EAEU nomenclature) for common grocery commodities, paired with descriptions
close to the official Russian wording.

Honesty note (kept deliberately): a full ТН ВЭД ЕАЭС code is 10 digits; the
last 6 select a specific commodity sub-position. We carry the genuine 4-digit
heading and expose the 10-digit form as ``<heading>000000`` — a documented
heading-granularity placeholder, **not** a fabricated precise sub-position.
That keeps the customs classification correct at heading level without
inventing digits we cannot stand behind.

Each entry is tagged with the retail category it belongs to so product
generation stays coherent with the X5 grocery context.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TnvedHeading:
    heading: str  # real 4-digit HS / ТН ВЭД heading
    description: str  # description close to official RU wording
    category: str  # retail aisle this heading maps to

    @property
    def code10(self) -> str:
        """10-digit ТН ВЭД field, heading-granularity (last 6 digits zeroed)."""
        return f"{self.heading}000000"


# Curated grocery subset. Headings are genuine HS/ТН ВЭД headings.
TNVED_HEADINGS: tuple[TnvedHeading, ...] = (
    TnvedHeading("0201", "Мясо крупного рогатого скота, свежее или охлаждённое", "Мясо и птица"),
    TnvedHeading("0203", "Свинина свежая, охлаждённая или замороженная", "Мясо и птица"),
    TnvedHeading("0207", "Мясо и пищевые субпродукты домашней птицы", "Мясо и птица"),
    TnvedHeading("0302", "Рыба свежая или охлаждённая", "Рыба и морепродукты"),
    TnvedHeading("0303", "Рыба мороженая", "Рыба и морепродукты"),
    TnvedHeading(
        "0401", "Молоко и сливки, несгущённые, без добавления сахара", "Молочные продукты"
    ),
    TnvedHeading(
        "0403", "Йогурт, кефир и прочие ферментированные молочные продукты", "Молочные продукты"
    ),
    TnvedHeading("0405", "Сливочное масло и прочие жиры из молока", "Молочные продукты"),
    TnvedHeading("0406", "Сыры и творог", "Молочные продукты"),
    TnvedHeading("0407", "Яйца птиц в скорлупе", "Молочные продукты"),
    TnvedHeading("0701", "Картофель свежий или охлаждённый", "Овощи и фрукты"),
    TnvedHeading("0702", "Томаты свежие или охлаждённые", "Овощи и фрукты"),
    TnvedHeading("0703", "Лук репчатый, чеснок, лук-порей", "Овощи и фрукты"),
    TnvedHeading("0805", "Цитрусовые плоды, свежие или сушёные", "Овощи и фрукты"),
    TnvedHeading("0808", "Яблоки, груши и айва свежие", "Овощи и фрукты"),
    TnvedHeading("0901", "Кофе, жареный или нежареный", "Чай и кофе"),
    TnvedHeading("0902", "Чай ароматизированный или неароматизированный", "Чай и кофе"),
    TnvedHeading("1001", "Пшеница и меслин", "Бакалея"),
    TnvedHeading("1006", "Рис", "Бакалея"),
    TnvedHeading("1101", "Мука пшеничная или пшенично-ржаная", "Бакалея"),
    TnvedHeading("1509", "Масло оливковое и его фракции", "Масло и жиры"),
    TnvedHeading("1512", "Масло подсолнечное, сафлоровое или хлопковое", "Масло и жиры"),
    TnvedHeading("1601", "Колбасы и аналогичные продукты из мяса", "Мясо и птица"),
    TnvedHeading("1602", "Готовые или консервированные продукты из мяса", "Мясо и птица"),
    TnvedHeading("1701", "Сахар тростниковый или свекловичный", "Бакалея"),
    TnvedHeading(
        "1704", "Кондитерские изделия из сахара без содержания какао", "Кондитерские изделия"
    ),
    TnvedHeading(
        "1806", "Шоколад и прочие готовые продукты с содержанием какао", "Кондитерские изделия"
    ),
    TnvedHeading("1902", "Макаронные изделия", "Бакалея"),
    TnvedHeading("1905", "Хлеб, мучные кондитерские изделия, печенье", "Хлеб и выпечка"),
    TnvedHeading("2002", "Томаты, приготовленные или консервированные", "Бакалея"),
    TnvedHeading("2009", "Соки фруктовые и овощные несброженные", "Напитки"),
    TnvedHeading("2101", "Экстракты, эссенции и концентраты кофе и чая", "Чай и кофе"),
    TnvedHeading("2103", "Соусы, приправы и смешанные приправы", "Бакалея"),
    TnvedHeading("2106", "Пищевые продукты, в другом месте не поименованные", "Бакалея"),
    TnvedHeading("2201", "Воды минеральные и газированные без сахара", "Напитки"),
    TnvedHeading("2202", "Воды с добавлением сахара или ароматизаторов, прочие напитки", "Напитки"),
)

# Quick lookup: retail category -> headings (preserves declaration order).
HEADINGS_BY_CATEGORY: dict[str, list[TnvedHeading]] = {}
for _h in TNVED_HEADINGS:
    HEADINGS_BY_CATEGORY.setdefault(_h.category, []).append(_h)

CATEGORIES: tuple[str, ...] = tuple(HEADINGS_BY_CATEGORY)
