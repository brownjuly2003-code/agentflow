/*
Purpose: Customer PII from 1C for the Yekaterinburg branch.
Sources: 1c.
Branch context: per-branch, hot jurisdictional PII.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__ekb
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_personal__1c__ekb (
    customer_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__ekb',
    first_name    String,
    last_name     String,
    email         String,
    phone         String,
    birth_date    Nullable(Date),
    pii_flag      Bool DEFAULT true,
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (customer_hk, load_ts);
