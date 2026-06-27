"""Map the supplier/product reference into DV2 raw-vault rows.

Hash keys are computed with the *same* MD5 canonicalisation as the X5 loader
(:mod:`warehouse.agentflow.dv2.loaders.x5_retail_hero.mappers`) so reference
hubs/links join byte-for-byte with vault data already loaded from other
sources. ``tests/unit/test_dv2_supplier_reference.py`` pins that equality.

Provenance is honest: every row carries ``record_source = 'ref__global'`` and
lands in source-segregated ``*__ref__global`` satellites, distinct from the
``__1c__*`` / ``__wms__*`` feeds. The shared hubs and links are, by Data Vault
design, source-agnostic anchors.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from .generator import ReferenceTables

RECORD_SOURCE = "ref__global"

TABLE_HUB_SUPPLIER = "hub_supplier"
TABLE_HUB_PRODUCT = "hub_product"
TABLE_HUB_MARKING_CODE = "hub_marking_code"
TABLE_LNK_PRODUCT_SUPPLIER = "lnk_product_supplier"
TABLE_LNK_PRODUCT_MARKING = "lnk_product_marking"
TABLE_SAT_SUPPLIER_PROFILE = "sat_supplier_profile__ref__global"
TABLE_SAT_PRODUCT_REFERENCE = "sat_product_reference__ref__global"
TABLE_SAT_MARKING_GS1 = "sat_marking_code_gs1__ref__global"
TABLE_SAT_SOURCING = "sat_lnk_product_supplier__ref__global"

Hash16 = Annotated[bytes, Field(min_length=16, max_length=16)]


# --- hashing (canonicalisation mirrors the X5 loader exactly) ----------------


def _canonical(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value).strip()


def md5_digest(value: Any) -> bytes:
    return hashlib.md5(_canonical(value).encode("utf-8"), usedforsecurity=False).digest()


def composite_md5_digest(*parts: Any) -> bytes:
    payload = "||".join(_canonical(part) for part in parts).encode("utf-8")
    return hashlib.md5(payload, usedforsecurity=False).digest()


def hash_diff(attributes: Mapping[str, Any]) -> bytes:
    payload = "||".join(f"{key}={_canonical(attributes[key])}" for key in sorted(attributes))
    return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).digest()


# --- row models --------------------------------------------------------------


class VaultRow(BaseModel):
    model_config = ConfigDict(frozen=True)


class HubRow(VaultRow):
    hk: Hash16
    bk: str
    load_ts: datetime
    record_source: str


class LinkRow(VaultRow):
    link_hk: Hash16
    left_hk: Hash16
    right_hk: Hash16
    load_ts: datetime
    record_source: str


class SatSupplierProfile(VaultRow):
    supplier_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    supplier_name: str
    tax_country_code: str
    supplier_status: str
    gln: str


class SatProductReference(VaultRow):
    product_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    product_name: str
    brand: str
    category: str
    tnved_code: str | None
    gpc_brick_code: str | None
    gross_weight_g: int
    net_weight_g: int
    length_mm: int
    width_mm: int
    height_mm: int
    units_per_pack: int
    pack_type: str


class SatMarkingGs1(VaultRow):
    marking_code_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    gs1_gtin: str
    marking_status: str


class SatSourcing(VaultRow):
    link_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    valid_from: datetime
    valid_to: datetime | None
    supplier_priority: int
    purchase_price: Decimal
    min_order_qty: int
    lead_time_days: int


MappedRows = dict[str, list[VaultRow]]


def _to_datetime(iso_date: str | None) -> datetime | None:
    if iso_date is None:
        return None
    return datetime.fromisoformat(iso_date)


def map_reference(tables: ReferenceTables, load_ts: datetime) -> MappedRows:
    """Map reference tables into raw-vault rows keyed by target table name."""
    mapped: MappedRows = {name: [] for name in _ALL_TABLES}

    supplier_hk_by_bk: dict[str, bytes] = {}
    for supplier in tables.suppliers:
        supplier_hk = md5_digest(supplier.supplier_bk)
        supplier_hk_by_bk[supplier.supplier_bk] = supplier_hk
        mapped[TABLE_HUB_SUPPLIER].append(
            HubRow(
                hk=supplier_hk,
                bk=supplier.supplier_bk,
                load_ts=load_ts,
                record_source=RECORD_SOURCE,
            )
        )
        attrs = {
            "supplier_name": supplier.supplier_name,
            "tax_country_code": supplier.tax_country_code,
            "supplier_status": supplier.supplier_status,
            "gln": supplier.gln,
        }
        mapped[TABLE_SAT_SUPPLIER_PROFILE].append(
            SatSupplierProfile(
                supplier_hk=supplier_hk,
                load_ts=load_ts,
                hash_diff=hash_diff(attrs),
                record_source=RECORD_SOURCE,
                **attrs,
            )
        )

    product_hk_by_bk: dict[str, bytes] = {}
    for product in tables.products:
        product_hk = md5_digest(product.product_bk)
        product_hk_by_bk[product.product_bk] = product_hk
        mapped[TABLE_HUB_PRODUCT].append(
            HubRow(
                hk=product_hk, bk=product.product_bk, load_ts=load_ts, record_source=RECORD_SOURCE
            )
        )
        ref_attrs: dict[str, Any] = {
            "product_name": product.product_name,
            "brand": product.brand,
            "category": product.category,
            "tnved_code": product.tnved_code,
            "gpc_brick_code": product.gpc_brick_code,
            "gross_weight_g": product.gross_weight_g,
            "net_weight_g": product.net_weight_g,
            "length_mm": product.length_mm,
            "width_mm": product.width_mm,
            "height_mm": product.height_mm,
            "units_per_pack": product.units_per_pack,
            "pack_type": product.pack_type,
        }
        mapped[TABLE_SAT_PRODUCT_REFERENCE].append(
            SatProductReference(
                product_hk=product_hk,
                load_ts=load_ts,
                hash_diff=hash_diff(ref_attrs),
                record_source=RECORD_SOURCE,
                **ref_attrs,
            )
        )

        marking_hk = md5_digest(product.gtin)
        mapped[TABLE_HUB_MARKING_CODE].append(
            HubRow(hk=marking_hk, bk=product.gtin, load_ts=load_ts, record_source=RECORD_SOURCE)
        )
        gs1_attrs = {"gs1_gtin": product.gtin, "marking_status": product.marking_status}
        mapped[TABLE_SAT_MARKING_GS1].append(
            SatMarkingGs1(
                marking_code_hk=marking_hk,
                load_ts=load_ts,
                hash_diff=hash_diff(gs1_attrs),
                record_source=RECORD_SOURCE,
                **gs1_attrs,
            )
        )
        mapped[TABLE_LNK_PRODUCT_MARKING].append(
            LinkRow(
                link_hk=composite_md5_digest(product_hk, marking_hk),
                left_hk=product_hk,
                right_hk=marking_hk,
                load_ts=load_ts,
                record_source=RECORD_SOURCE,
            )
        )

    for sourcing in tables.sourcing:
        product_hk = product_hk_by_bk[sourcing.product_bk]
        supplier_hk = supplier_hk_by_bk[sourcing.supplier_bk]
        link_hk = composite_md5_digest(product_hk, supplier_hk)
        mapped[TABLE_LNK_PRODUCT_SUPPLIER].append(
            LinkRow(
                link_hk=link_hk,
                left_hk=product_hk,
                right_hk=supplier_hk,
                load_ts=load_ts,
                record_source=RECORD_SOURCE,
            )
        )
        sourcing_attrs: dict[str, Any] = {
            "valid_from": _to_datetime(sourcing.valid_from),
            "valid_to": _to_datetime(sourcing.valid_to),
            "supplier_priority": sourcing.supplier_priority,
            "purchase_price": sourcing.purchase_price,
            "min_order_qty": sourcing.min_order_qty,
            "lead_time_days": sourcing.lead_time_days,
        }
        mapped[TABLE_SAT_SOURCING].append(
            SatSourcing(
                link_hk=link_hk,
                load_ts=load_ts,
                hash_diff=hash_diff(sourcing_attrs),
                record_source=RECORD_SOURCE,
                **sourcing_attrs,
            )
        )

    return mapped


_ALL_TABLES: tuple[str, ...] = (
    TABLE_HUB_SUPPLIER,
    TABLE_HUB_PRODUCT,
    TABLE_HUB_MARKING_CODE,
    TABLE_LNK_PRODUCT_SUPPLIER,
    TABLE_LNK_PRODUCT_MARKING,
    TABLE_SAT_SUPPLIER_PROFILE,
    TABLE_SAT_PRODUCT_REFERENCE,
    TABLE_SAT_MARKING_GS1,
    TABLE_SAT_SOURCING,
)


# The shared :class:`HubRow` / :class:`LinkRow` carry generic ``hk``/``bk`` /
# ``link_hk``/``left_hk``/``right_hk`` fields, but the raw-vault DDL names hub
# and link columns per entity (``hub_supplier.supplier_hk``,
# ``lnk_product_supplier.product_hk``/``supplier_hk``, ...). This maps each such
# table's row fields, *in field order*, to its destination column names so the
# PostgreSQL loader inserts into the right columns. Satellites already use the
# real column names (their models are entity-specific), so they are identity and
# omitted. Used by ``reference.load_postgres`` via ``write_mapped``.
VAULT_DB_COLUMNS: dict[str, list[str]] = {
    TABLE_HUB_SUPPLIER: ["supplier_hk", "supplier_bk", "load_ts", "record_source"],
    TABLE_HUB_PRODUCT: ["product_hk", "product_bk", "load_ts", "record_source"],
    TABLE_HUB_MARKING_CODE: ["marking_code_hk", "marking_code_bk", "load_ts", "record_source"],
    TABLE_LNK_PRODUCT_SUPPLIER: [
        "link_hk",
        "product_hk",
        "supplier_hk",
        "load_ts",
        "record_source",
    ],
    TABLE_LNK_PRODUCT_MARKING: [
        "link_hk",
        "product_hk",
        "marking_code_hk",
        "load_ts",
        "record_source",
    ],
}
