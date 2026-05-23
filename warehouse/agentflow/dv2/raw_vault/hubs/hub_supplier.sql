/*
Purpose: Raw vault hub for supplier tax identifiers.
Sources: 1c.
Branch context: global supplier anchor.
SCD2: no.
Anonymization: hot commercial reference.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.hub_supplier (
    supplier_hk   FixedString(16),
    supplier_bk   String,
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String),
    INDEX idx_supplier_bk supplier_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (supplier_hk);
