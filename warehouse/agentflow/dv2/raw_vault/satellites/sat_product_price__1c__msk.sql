/*
Purpose: Active product price list from 1C.
Sources: 1c.
Branch context: branch-qualified price context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_price__1c__msk (
    product_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__msk',
    retail_price  Decimal(18, 2),
    wholesale_price Nullable(Decimal(18, 2)),
    currency_code FixedString(3),
    valid_from    DateTime64(3),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (product_hk, load_ts);
