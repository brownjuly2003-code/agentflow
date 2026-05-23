/*
Purpose: Raw vault link between products and GS1/Chestny Znak marking codes.
Sources: 1c, wms.
Branch context: global product traceability.
SCD2: no.
Anonymization: hot non-PII traceability link.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.lnk_product_marking (
    link_hk         FixedString(16),
    product_hk      FixedString(16),
    marking_code_hk FixedString(16),
    load_ts         DateTime64(3) DEFAULT now64(3),
    record_source   LowCardinality(String)
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (link_hk);
