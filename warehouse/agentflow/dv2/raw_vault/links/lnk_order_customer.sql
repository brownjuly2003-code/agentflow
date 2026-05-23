/*
Purpose: Raw vault link between orders and customers.
Sources: 1c, bitrix, site, wb, ozon.
Branch context: per-branch order/customer attribution.
SCD2: no.
Anonymization: hot link; customer PII remains only in customer satellites.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.lnk_order_customer (
    link_hk       FixedString(16),
    order_hk      FixedString(16),
    customer_hk   FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String)
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (link_hk);
