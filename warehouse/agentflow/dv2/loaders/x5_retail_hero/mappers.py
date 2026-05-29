from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from pydantic import BaseModel

try:
    from .branch_distributor import normalize_store_id
    from .schemas import (
        HubCustomer,
        HubOrder,
        HubProduct,
        HubStore,
        LinkOrderCustomer,
        LinkOrderProduct,
        LinkOrderStore,
        SatCustomerPersonal,
        SatLinkOrderProduct,
        SatOrderHeader,
        SatProductCatalog,
    )
except ImportError:
    from branch_distributor import normalize_store_id
    from schemas import (
        HubCustomer,
        HubOrder,
        HubProduct,
        HubStore,
        LinkOrderCustomer,
        LinkOrderProduct,
        LinkOrderStore,
        SatCustomerPersonal,
        SatLinkOrderProduct,
        SatOrderHeader,
        SatProductCatalog,
    )


SOURCE_SYSTEM = "1c"
PRODUCT_BRANCH = "msk"
TABLE_HUB_CUSTOMER = "hub_customer"
TABLE_HUB_PRODUCT = "hub_product"
TABLE_HUB_STORE = "hub_store"
TABLE_HUB_ORDER = "hub_order"
TABLE_LNK_ORDER_CUSTOMER = "lnk_order_customer"
TABLE_LNK_ORDER_PRODUCT = "lnk_order_product"
TABLE_LNK_ORDER_STORE = "lnk_order_store"
TABLE_SAT_PRODUCT_CATALOG = f"sat_product_catalog__{SOURCE_SYSTEM}__{PRODUCT_BRANCH}"

MappedRows = dict[str, list[BaseModel]]
ClientLookup = dict[str, dict[str, Any]]


def md5_digest(value: Any) -> bytes:
    return hashlib.md5(_canonical(value).encode("utf-8"), usedforsecurity=False).digest()


def composite_md5_digest(*parts: Any) -> bytes:
    payload = "||".join(_canonical(part) for part in parts).encode("utf-8")
    return hashlib.md5(payload, usedforsecurity=False).digest()


def hash_diff(attributes: Mapping[str, Any]) -> bytes:
    payload = "||".join(f"{key}={_canonical(attributes[key])}" for key in sorted(attributes))
    return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).digest()


def record_source(branch_code: str) -> str:
    return f"{SOURCE_SYSTEM}__{branch_code}"


def order_business_key(branch_code: str, transaction_id: Any) -> str:
    return f"{SOURCE_SYSTEM}__{branch_code}__{_clean_string(transaction_id)}"


def store_code(branch_code: str, store_id: Any) -> str:
    return f"{branch_code}-{normalize_store_id(store_id)}"


def map_products_chunk(products: pd.DataFrame, load_ts: datetime) -> MappedRows:
    mapped: MappedRows = defaultdict(list)
    rows = products.drop_duplicates(subset=["product_id"]).to_dict("records")

    for row in rows:
        sku = _clean_string(row["product_id"])
        if not sku:
            continue

        product_hk = md5_digest(sku)
        source = record_source(PRODUCT_BRANCH)
        mapped[TABLE_HUB_PRODUCT].append(
            HubProduct(product_hk=product_hk, sku=sku, load_ts=load_ts, record_source=source)
        )

        attrs = {
            "brand_id": _nullable_string(row.get("brand_id")),
            "is_own_trademark": _nullable_bool(row.get("is_own_trademark")),
            "level_1": _nullable_string(row.get("level_1")),
            "level_2": _nullable_string(row.get("level_2")),
            "level_3": _nullable_string(row.get("level_3")),
            "level_4": _nullable_string(row.get("level_4")),
            "netto": _nullable_decimal(row.get("netto")),
            "segment_id": _nullable_string(row.get("segment_id")),
        }
        mapped[TABLE_SAT_PRODUCT_CATALOG].append(
            SatProductCatalog(
                product_hk=product_hk,
                load_ts=load_ts,
                hash_diff=hash_diff(attrs),
                record_source=source,
                **attrs,
            )
        )

    return dict(mapped)


def map_clients_chunk(
    clients: pd.DataFrame,
    load_ts: datetime,
    default_branch: str = PRODUCT_BRANCH,
) -> tuple[MappedRows, ClientLookup]:
    mapped: MappedRows = defaultdict(list)
    lookup: ClientLookup = {}
    rows = clients.drop_duplicates(subset=["client_id"]).to_dict("records")

    for row in rows:
        customer_bk = _clean_string(row["client_id"])
        if not customer_bk:
            continue

        customer_hk = md5_digest(customer_bk)
        mapped[TABLE_HUB_CUSTOMER].append(
            HubCustomer(
                customer_hk=customer_hk,
                customer_bk=customer_bk,
                load_ts=load_ts,
                record_source=record_source(default_branch),
            )
        )
        lookup[customer_bk] = {
            "age": _nullable_int(row.get("age")),
            "gender": _nullable_string(row.get("gender")),
            "first_issue_date": _nullable_date(row.get("first_issue_date")),
            "first_redeem_date": _nullable_date(row.get("first_redeem_date")),
        }

    return dict(mapped), lookup


def map_customer_personal(
    customer_bk: str,
    branch_code: str,
    attrs: Mapping[str, Any],
    load_ts: datetime,
) -> SatCustomerPersonal:
    satellite_attrs = {
        "age": attrs.get("age"),
        "gender": attrs.get("gender"),
        "first_issue_date": attrs.get("first_issue_date"),
        "first_redeem_date": attrs.get("first_redeem_date"),
    }
    return SatCustomerPersonal(
        customer_hk=md5_digest(customer_bk),
        load_ts=load_ts,
        hash_diff=hash_diff(satellite_attrs),
        record_source=record_source(branch_code),
        **satellite_attrs,
    )


def map_purchases_chunk(
    purchases: pd.DataFrame,
    load_ts: datetime,
    store_branch_map: Mapping[Any, str],
    client_lookup: Mapping[str, Mapping[str, Any]],
    seen_customer_personal: set[tuple[str, str]] | None = None,
) -> MappedRows:
    mapped: MappedRows = defaultdict(list)
    seen_stores: set[str] = set()
    seen_orders: set[str] = set()
    seen_order_customer_links: set[bytes] = set()
    seen_order_product_links: set[bytes] = set()
    seen_order_store_links: set[bytes] = set()
    seen_order_headers: set[bytes] = set()

    for row in purchases.to_dict("records"):
        branch_code = _resolve_branch(row["store_id"], store_branch_map)
        source = record_source(branch_code)
        customer_bk = _clean_string(row["client_id"])
        sku = _clean_string(row["product_id"])
        transaction_id = _clean_string(row["transaction_id"])
        order_bk = order_business_key(branch_code, transaction_id)
        current_store_code = store_code(branch_code, row["store_id"])

        if not customer_bk or not sku or not transaction_id or not current_store_code:
            continue

        customer_hk = md5_digest(customer_bk)
        product_hk = md5_digest(sku)
        store_hk = md5_digest(current_store_code)
        order_hk = md5_digest(order_bk)

        if current_store_code not in seen_stores:
            mapped[TABLE_HUB_STORE].append(
                HubStore(
                    store_hk=store_hk,
                    store_bk=current_store_code,
                    load_ts=load_ts,
                    record_source=source,
                )
            )
            seen_stores.add(current_store_code)

        if order_bk not in seen_orders:
            mapped[TABLE_HUB_ORDER].append(
                HubOrder(
                    order_hk=order_hk,
                    order_bk=order_bk,
                    load_ts=load_ts,
                    record_source=source,
                )
            )
            seen_orders.add(order_bk)

        order_customer_hk = composite_md5_digest(order_hk, customer_hk)
        if order_customer_hk not in seen_order_customer_links:
            mapped[TABLE_LNK_ORDER_CUSTOMER].append(
                LinkOrderCustomer(
                    link_hk=order_customer_hk,
                    order_hk=order_hk,
                    customer_hk=customer_hk,
                    load_ts=load_ts,
                    record_source=source,
                )
            )
            seen_order_customer_links.add(order_customer_hk)

        order_product_hk = composite_md5_digest(order_hk, product_hk)
        if order_product_hk not in seen_order_product_links:
            mapped[TABLE_LNK_ORDER_PRODUCT].append(
                LinkOrderProduct(
                    link_hk=order_product_hk,
                    order_hk=order_hk,
                    product_hk=product_hk,
                    load_ts=load_ts,
                    record_source=source,
                )
            )
            seen_order_product_links.add(order_product_hk)

        order_store_hk = composite_md5_digest(order_hk, store_hk)
        if order_store_hk not in seen_order_store_links:
            mapped[TABLE_LNK_ORDER_STORE].append(
                LinkOrderStore(
                    link_hk=order_store_hk,
                    order_hk=order_hk,
                    store_hk=store_hk,
                    load_ts=load_ts,
                    record_source=source,
                )
            )
            seen_order_store_links.add(order_store_hk)

        if order_hk not in seen_order_headers:
            header_attrs = {
                "express_points_received": _nullable_decimal(row.get("express_points_received")),
                "express_points_spent": _nullable_decimal(row.get("express_points_spent")),
                "purchase_sum": _nullable_decimal(row.get("purchase_sum")),
                "regular_points_received": _nullable_decimal(row.get("regular_points_received")),
                "regular_points_spent": _nullable_decimal(row.get("regular_points_spent")),
                "transaction_datetime": _nullable_datetime(row.get("transaction_datetime")),
            }
            mapped[_sat_order_header_table(branch_code)].append(
                SatOrderHeader(
                    order_hk=order_hk,
                    load_ts=load_ts,
                    hash_diff=hash_diff(header_attrs),
                    record_source=source,
                    **header_attrs,
                )
            )
            seen_order_headers.add(order_hk)

        line_attrs = {
            "product_quantity": _nullable_decimal(row.get("product_quantity")),
            "trn_sum_from_iss": _nullable_decimal(row.get("trn_sum_from_iss")),
        }
        mapped[_sat_lnk_order_product_table(branch_code)].append(
            SatLinkOrderProduct(
                link_hk=order_product_hk,
                load_ts=load_ts,
                hash_diff=hash_diff(line_attrs),
                record_source=source,
                **line_attrs,
            )
        )

        client_attrs = client_lookup.get(customer_bk)
        customer_personal_key = (customer_bk, branch_code)
        if client_attrs and (
            seen_customer_personal is None or customer_personal_key not in seen_customer_personal
        ):
            mapped[_sat_customer_personal_table(branch_code)].append(
                map_customer_personal(customer_bk, branch_code, client_attrs, load_ts)
            )
            if seen_customer_personal is not None:
                seen_customer_personal.add(customer_personal_key)

    return dict(mapped)


def rows_to_dicts(rows: list[BaseModel]) -> list[dict[str, Any]]:
    return [row.model_dump(mode="python") for row in rows]


def _sat_customer_personal_table(branch_code: str) -> str:
    return f"sat_customer_personal__{SOURCE_SYSTEM}__{branch_code}"


def _sat_order_header_table(branch_code: str) -> str:
    return f"sat_order_header__{SOURCE_SYSTEM}__{branch_code}"


def _sat_lnk_order_product_table(branch_code: str) -> str:
    return f"sat_lnk_order_product__{SOURCE_SYSTEM}__{branch_code}"


def _resolve_branch(store_id: Any, store_branch_map: Mapping[Any, str]) -> str:
    if store_id in store_branch_map:
        return store_branch_map[store_id]

    normalized = normalize_store_id(store_id)
    if normalized in store_branch_map:
        return store_branch_map[normalized]

    for known_store_id, branch_code in store_branch_map.items():
        if normalize_store_id(known_store_id) == normalized:
            return branch_code

    raise KeyError(f"store_id {normalized!r} is missing from branch map")


def _canonical(value: Any) -> str:
    if _is_null(value):
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


def _is_null(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _clean_string(value: Any) -> str:
    if _is_null(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _nullable_string(value: Any) -> str | None:
    cleaned = _clean_string(value)
    return cleaned or None


def _nullable_int(value: Any) -> int | None:
    if _is_null(value):
        return None
    return int(float(value))


def _nullable_decimal(value: Any) -> Decimal | None:
    if _is_null(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _nullable_bool(value: Any) -> bool | None:
    if _is_null(value):
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "1.0", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "0.0", "false", "f", "no", "n"}:
        return False
    return None


def _nullable_date(value: Any) -> date | None:
    timestamp = _nullable_datetime(value)
    return timestamp.date() if timestamp else None


def _nullable_datetime(value: Any) -> datetime | None:
    if _is_null(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=False)
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.to_pydatetime().replace(tzinfo=None)
    if isinstance(parsed, datetime):
        return parsed.replace(tzinfo=None)
    return None
