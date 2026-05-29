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
    sku: str
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
    order_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    transaction_datetime: datetime | None
    purchase_sum: Decimal | None
    regular_points_received: Decimal | None
    express_points_received: Decimal | None
    regular_points_spent: Decimal | None
    express_points_spent: Decimal | None


class SatLinkOrderProduct(VaultRow):
    link_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    product_quantity: Decimal | None
    trn_sum_from_iss: Decimal | None
