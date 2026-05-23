/*
Purpose: Employee sales attribution state from Bitrix24.
Sources: bitrix.
Branch context: per-branch sales attribution.
SCD2: yes.
Anonymization: hot.
record_source value: bitrix__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_employee_sales__bitrix__msk (
    employee_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'bitrix__msk',
    bitrix_user_id String,
    sales_team    LowCardinality(String),
    manager_flag  Bool DEFAULT false,
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (employee_hk, load_ts);
