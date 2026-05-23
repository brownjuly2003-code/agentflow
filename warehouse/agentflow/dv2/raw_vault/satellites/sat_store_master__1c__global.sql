/*
Purpose: Store directory attributes from 1C.
Sources: 1c.
Branch context: global reference context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__global
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_store_master__1c__global (
    store_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__global',
    store_name    String,
    branch_code   LowCardinality(String),
    city          LowCardinality(String),
    country_code  FixedString(2),
    opened_at     Nullable(Date),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (store_hk, load_ts);
