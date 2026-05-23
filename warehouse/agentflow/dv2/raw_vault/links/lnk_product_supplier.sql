/*
Purpose: Raw vault link between products and suppliers.
Sources: 1c.
Branch context: global sourcing attribution.
SCD2: no.
Anonymization: hot commercial link.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.lnk_product_supplier (
    link_hk       FixedString(16),
    product_hk    FixedString(16),
    supplier_hk   FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String)
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (link_hk);
