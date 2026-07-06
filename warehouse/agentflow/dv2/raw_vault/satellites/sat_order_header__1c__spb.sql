/*
Purpose: Order header from 1C / branch order feed ingest.
Sources: 1c (branch order feed).
Branch context: per-branch order state.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__spb
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_order_header__1c__spb (
    order_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__spb',
    order_date    DateTime64(3),
    channel       LowCardinality(String),
    order_status  LowCardinality(String),
    total_amount  Decimal(18, 2),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (order_hk, load_ts);
