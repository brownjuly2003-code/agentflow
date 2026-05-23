/*
Purpose: Raw vault link for order sales attribution to employee or manager.
Sources: 1c_zup, bitrix.
Branch context: per-branch employee attribution.
SCD2: no.
Anonymization: hot HR-sensitive link.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.lnk_order_employee (
    link_hk       FixedString(16),
    order_hk      FixedString(16),
    employee_hk   FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String)
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (link_hk);
