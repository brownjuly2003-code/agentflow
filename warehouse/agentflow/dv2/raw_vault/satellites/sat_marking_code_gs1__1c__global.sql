/*
Purpose: GS1 marking-code attributes from 1C.
Sources: 1c.
Branch context: global traceability context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__global
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_marking_code_gs1__1c__global (
    marking_code_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__global',
    gs1_gtin      String,
    serial_number Nullable(String),
    marking_status LowCardinality(String),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (marking_code_hk, load_ts);
