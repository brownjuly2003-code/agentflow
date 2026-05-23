/*
Purpose: Raw vault hub for physical shipments.
Sources: wms, excel.
Branch context: per-branch.
SCD2: no.
Anonymization: hot logistics anchor.
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.hub_shipment (
    shipment_hk   FixedString(16),
    shipment_bk   String,
    load_ts       DateTime64(3) DEFAULT now64(3),
    record_source LowCardinality(String),
    INDEX idx_shipment_bk shipment_bk TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplacingMergeTree(load_ts)
ORDER BY (shipment_hk);
