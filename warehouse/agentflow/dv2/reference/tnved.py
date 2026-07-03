"""ТН ВЭД ЕАЭС (EAEU customs nomenclature) small-kitchen-appliance reference
subset.

The codes here are **real** Harmonized-System / ТН ВЭД ЕАЭС *headings* (the
first four digits, which are identical across the international HS and the
EAEU nomenclature) for the small-appliance headings an own-brand kitchen
importer actually classifies against, paired with descriptions close to the
official Russian wording.

Honesty note (kept deliberately): a full ТН ВЭД ЕАЭС code is 10 digits; the
last 6 select a specific commodity sub-position. We carry the genuine 4-digit
heading and expose the 10-digit form as ``<heading>000000`` — a documented
heading-granularity placeholder, **not** a fabricated precise sub-position.
That keeps the customs classification correct at heading level without
inventing digits we cannot stand behind.

Each entry is tagged with the catalog category (domain.md §1 / generator-spec
§3) it belongs to, so product generation stays coherent with the own-brand
kitchen-appliance importer legend. Categories stay RU-flavored — DV2/warehouse
content mirrors what 1С/Bitrix24 emit (generator-spec.md §3, RU vs EN split);
the EN-facing catalog is a serving-layer concern (repin step).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TnvedHeading:
    heading: str  # real 4-digit HS / ТН ВЭД heading
    description: str  # description close to official RU wording
    category: str  # catalog category this heading maps to (RU, 1С-flavored)

    @property
    def code10(self) -> str:
        """10-digit ТН ВЭД field, heading-granularity (last 6 digits zeroed)."""
        return f"{self.heading}000000"


# The 10 catalog categories (generator-spec.md §3), each pinned to its real
# HS/ТН ВЭД heading. "Вакууматоры и сушилки" genuinely splits across two
# headings (vacuum sealers are packing machinery; dryers are electrothermic
# appliances), so it carries two entries — the honest reading, not a
# simplification.
TNVED_HEADINGS: tuple[TnvedHeading, ...] = (
    TnvedHeading(
        "8516",
        "Приборы электронагревательные бытового назначения; электрочайники "
        "и аналогичные приборы для нагрева воды",
        "Электрочайники",
    ),
    TnvedHeading(
        "8516",
        "Приборы электронагревательные бытового назначения; грили и аэрогрили электрические",
        "Аэрогрили и грили",
    ),
    TnvedHeading(
        "8509",
        "Машины электромеханические бытовые с вмонтированным электродвигателем; блендеры",
        "Блендеры",
    ),
    TnvedHeading(
        "8509",
        "Машины электромеханические бытовые с вмонтированным электродвигателем; "
        "миксеры, в т.ч. планетарные",
        "Миксеры",
    ),
    TnvedHeading(
        "8516",
        "Приборы электронагревательные бытового назначения; кофеварки и кофемолки электрические",
        "Кофеварки и кофемолки",
    ),
    TnvedHeading(
        "8516",
        "Приборы электронагревательные бытового назначения; мультипекари, "
        "вафельницы и сэндвичницы электрические",
        "Мультипекари, вафельницы, сэндвичницы",
    ),
    TnvedHeading(
        "8509",
        "Машины электромеханические бытовые с вмонтированным электродвигателем; "
        "измельчители (чопперы)",
        "Измельчители",
    ),
    TnvedHeading(
        "8509",
        "Машины электромеханические бытовые с вмонтированным электродвигателем; соковыжималки",
        "Соковыжималки",
    ),
    TnvedHeading(
        "8423",
        "Оборудование для взвешивания бытового назначения; весы кухонные",
        "Кухонные весы",
    ),
    TnvedHeading(
        "8422",
        "Машины для укупорки, герметизации тары; вакууматоры бытовые",
        "Вакууматоры и сушилки",
    ),
    TnvedHeading(
        "8516",
        "Приборы электронагревательные бытового назначения; сушилки для продуктов электрические",
        "Вакууматоры и сушилки",
    ),
)

# Quick lookup: catalog category -> headings (preserves declaration order).
HEADINGS_BY_CATEGORY: dict[str, list[TnvedHeading]] = {}
for _h in TNVED_HEADINGS:
    HEADINGS_BY_CATEGORY.setdefault(_h.category, []).append(_h)

CATEGORIES: tuple[str, ...] = tuple(HEADINGS_BY_CATEGORY)
