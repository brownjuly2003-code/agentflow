/*
Purpose: Marking-code scan state from WMS.
Sources: wms.
Branch context: global warehouse traceability.
SCD2: yes.
Anonymization: hot.
record_source value: wms__global
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_marking_code_wms__wms__global (
    marking_code_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'wms__global',
    last_scan_at  Nullable(DateTime64(3)),
    last_scan_location Nullable(String),
    scan_status   LowCardinality(String),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (marking_code_hk, load_ts);
