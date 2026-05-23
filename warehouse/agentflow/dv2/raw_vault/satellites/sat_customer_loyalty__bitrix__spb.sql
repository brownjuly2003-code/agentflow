/*
Purpose: Customer loyalty state from Bitrix24 (Saint Petersburg).
Sources: bitrix.
Branch context: per-branch loyalty context.
SCD2: yes.
Anonymization: hot.
record_source value: bitrix__spb
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_loyalty__bitrix__spb (
    customer_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'bitrix__spb',
    loyalty_segment LowCardinality(String),
    loyalty_points Decimal(18, 2),
    last_visit_at Nullable(DateTime64(3)),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (customer_hk, load_ts);
