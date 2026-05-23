/*
Purpose: Raw vault hub for canonical product SKU.
Sources: 1c, wms, site, wb, ozon.
Branch context: global hub; source-specific attributes stay in satellites.
SCD2: no.
Anonymization: hot non-PII anchor.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.hub_product (
    product_hk    FixedString(16),
    product_bk    String,
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String),
    INDEX idx_product_bk product_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (product_hk);
