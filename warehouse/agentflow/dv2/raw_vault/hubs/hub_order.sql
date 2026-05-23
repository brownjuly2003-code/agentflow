/*
Purpose: Raw vault hub for composite order id {source}__{local_id}.
Sources: 1c, bitrix, site, wb, ozon.
Branch context: per-branch satellites.
SCD2: no.
Anonymization: hot operational anchor.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.hub_order (
    order_hk      FixedString(16),
    order_bk      String,
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String),
    INDEX idx_order_bk order_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (order_hk);
