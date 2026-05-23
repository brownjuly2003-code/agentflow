/*
Purpose: Raw vault hub for sales employees and managers.
Sources: 1c_zup, bitrix.
Branch context: per-branch satellites.
SCD2: no.
Anonymization: hot HR identity anchor.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.hub_employee (
    employee_hk   FixedString(16),
    employee_bk   String,
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String),
    INDEX idx_employee_bk employee_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (employee_hk);
