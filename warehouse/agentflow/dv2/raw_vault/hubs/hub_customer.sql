/*
Purpose: Raw vault hub for canonical customers deduplicated by email/phone.
Sources: 1c, bitrix, site, wb, ozon.
Branch context: per-branch satellites; hub key is canonical across branches.
SCD2: no.
Anonymization: hot identity anchor; cold exports must not carry direct PII mappings.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.hub_customer (
    customer_hk   FixedString(16),
    customer_bk   String,
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String),
    INDEX idx_customer_bk customer_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (customer_hk);
