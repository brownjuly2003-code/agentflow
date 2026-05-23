/*
Purpose: Raw vault link for store/branch that fulfilled an order.
Sources: 1c, bitrix, site, wb, ozon.
Branch context: per-branch fulfillment attribution.
SCD2: no.
Anonymization: hot non-PII link.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.lnk_order_store (
    link_hk       FixedString(16),
    order_hk      FixedString(16),
    store_hk      FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String)
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (link_hk);
