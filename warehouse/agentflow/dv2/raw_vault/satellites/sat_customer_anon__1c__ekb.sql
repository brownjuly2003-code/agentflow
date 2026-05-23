/*
Purpose: Cold anonymized customer projection derived from hot 1C PII (Yekaterinburg).
Sources: 1c.
Branch context: derived cold projection for Yekaterinburg.
SCD2: yes.
Anonymization: cold.
record_source value: 1c__ekb
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_anon__1c__ekb (
    customer_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__ekb',
    age_bucket    LowCardinality(String),
    geo_region    LowCardinality(String),
    customer_segment LowCardinality(String),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (customer_hk, load_ts);
