from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Hash16 = Annotated[bytes, Field(min_length=16, max_length=16)]


class VaultRow(BaseModel):
    model_config = ConfigDict(frozen=True)


class HubCustomer(VaultRow):
    customer_hk: Hash16
    customer_bk: str
    load_ts: datetime
    record_source: str


class HubProduct(VaultRow):
    product_hk: Hash16
    product_bk: str
    load_ts: datetime
    record_source: str


class HubStore(VaultRow):
    store_hk: Hash16
    store_bk: str
    load_ts: datetime
    record_source: str


class HubOrder(VaultRow):
    order_hk: Hash16
    order_bk: str
    load_ts: datetime
    record_source: str


class LinkOrderCustomer(VaultRow):
    link_hk: Hash16
    order_hk: Hash16
    customer_hk: Hash16
    load_ts: datetime
    record_source: str


class LinkOrderProduct(VaultRow):
    link_hk: Hash16
    order_hk: Hash16
    product_hk: Hash16
    load_ts: datetime
    record_source: str


class LinkOrderStore(VaultRow):
    link_hk: Hash16
    order_hk: Hash16
    store_hk: Hash16
    load_ts: datetime
    record_source: str


class SatCustomerPersonal(VaultRow):
    customer_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    age: int | None
    gender: str | None
    first_issue_date: date | None
    first_redeem_date: date | None


class SatProductCatalog(VaultRow):
    product_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    level_1: str | None
    level_2: str | None
    level_3: str | None
    level_4: str | None
    brand_id: str | None
    segment_id: str | None
    netto: Decimal | None
    is_own_trademark: bool | None


class SatOrderHeader(VaultRow):
    # Aligned to the deployed rv.sat_order_header__* DDL (order_date / channel /
    # order_status / total_amount) so X5 orders are visible to bv_order_canonical.
    order_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    order_date: datetime | None
    channel: str | None
    order_status: str | None
    total_amount: Decimal | None


class SatOrderPricing(VaultRow):
    # Synthesized from the X5 purchase_sum (gross) with per-branch tax rates so
    # bv_order_canonical / branch_pnl have a non-null subtotal_amount.
    order_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    subtotal_amount: Decimal | None
    discount_amount: Decimal | None
    tax_amount: Decimal | None
    shipping_cost: Decimal | None


class SatLinkOrderProduct(VaultRow):
    link_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    product_quantity: Decimal | None
    trn_sum_from_iss: Decimal | None
