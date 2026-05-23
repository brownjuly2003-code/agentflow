/*
Purpose: Effectivity satellite for order line quantity and price.
Sources: 1c.
Branch context: per-branch line item effectivity.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_lnk_order_product__1c__msk (
    link_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__msk',
    qty           Decimal(18, 3),
    unit_price    Decimal(18, 2),
    discount_pct  Decimal(5, 2),
    line_total    Decimal(18, 2),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (link_hk, load_ts);
