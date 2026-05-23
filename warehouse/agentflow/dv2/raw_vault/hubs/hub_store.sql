/*
Purpose: Raw vault hub for store and branch attribution codes.
Sources: 1c store directory.
Branch context: global reference hub.
SCD2: no.
Anonymization: hot non-PII anchor.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.hub_store (
    store_hk      FixedString(16),
    store_bk      String,
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String),
    INDEX idx_store_bk store_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (store_hk);
