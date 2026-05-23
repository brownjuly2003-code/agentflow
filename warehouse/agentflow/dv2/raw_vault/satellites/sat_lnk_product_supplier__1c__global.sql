/*
Purpose: Effectivity satellite for product-supplier sourcing.
Sources: 1c.
Branch context: global sourcing effectivity.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__global
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_lnk_product_supplier__1c__global (
    link_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__global',
    valid_from    DateTime64(3),
    valid_to      Nullable(DateTime64(3)),
    supplier_priority UInt16,
    purchase_price Nullable(Decimal(18, 2)),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (link_hk, load_ts);
