/*
Purpose: Product catalog attributes from 1C.
Sources: 1c.
Branch context: global product with branch-qualified source feed.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_catalog__1c__msk (
    product_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__msk',
    product_name  String,
    brand         LowCardinality(String),
    category      LowCardinality(String),
    size_code     LowCardinality(String),
    color         LowCardinality(String),
    tnved_code    Nullable(String),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (product_hk, load_ts);
