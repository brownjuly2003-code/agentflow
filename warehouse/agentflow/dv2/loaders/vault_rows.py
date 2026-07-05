"""Vault-generic raw-vault row models shared by DV2 PostgreSQL ingestion.

These pydantic models describe the hub / link / order-satellite shape used by
every per-branch order feed (``sat_order_header__1c__*`` /
``sat_order_pricing__1c__*``) and by ``PostgresVaultWriter``'s column-order /
DDL-coverage tests. They are entity-generic (not tied to any one source
system or dataset) — see ``reference/vault_mapping.py`` for the analogous
models used by the supplier/product reference feed.
"""

from __future__ import annotations

from datetime import datetime
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


class SatOrderHeader(VaultRow):
    # Aligned to the deployed rv.sat_order_header__* DDL (order_date / channel /
    # order_status / total_amount).
    order_hk: Hash16
    load_ts: datetime
    hash_diff: Hash16
    record_source: str
    order_date: datetime | None
    channel: str | None
    order_status: str | None
    total_amount: Decimal | None


class SatOrderPricing(VaultRow):
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
