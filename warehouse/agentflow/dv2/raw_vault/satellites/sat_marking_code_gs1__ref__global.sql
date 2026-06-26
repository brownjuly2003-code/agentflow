/*
Purpose: GS1 GTIN attributes from the cloud product reference (HF Dataset).
Sources: ref.
Branch context: global traceability reference context.
SCD2: yes.
Anonymization: hot non-PII reference.
record_source value: ref__global
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_marking_code_gs1__ref__global (
    marking_code_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'ref__global',
    gs1_gtin      String,
    marking_status LowCardinality(String),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (marking_code_hk, load_ts);
