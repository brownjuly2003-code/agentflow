/*
Purpose: Raw vault hub for GS1/Chestny Znak marking codes.
Sources: 1c, wms.
Branch context: global marking-code anchor.
SCD2: no.
Anonymization: hot non-PII traceability anchor.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.hub_marking_code (
    marking_code_hk FixedString(16),
    marking_code_bk String,
    load_ts         DateTime64(3) DEFAULT now64(3),
    record_source   LowCardinality(String),
    INDEX idx_marking_code_bk marking_code_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (marking_code_hk);
