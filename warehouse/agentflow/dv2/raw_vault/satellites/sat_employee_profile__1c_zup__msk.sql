/*
Purpose: Employee HR profile from 1C ZUP.
Sources: 1c_zup.
Branch context: per-branch employee context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c_zup__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_employee_profile__1c_zup__msk (
    employee_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c_zup__msk',
    first_name    String,
    last_name     String,
    role_name     LowCardinality(String),
    employment_status LowCardinality(String),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (employee_hk, load_ts);
