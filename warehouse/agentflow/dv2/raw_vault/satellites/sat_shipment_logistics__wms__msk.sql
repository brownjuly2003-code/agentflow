/*
Purpose: Physical shipment status from WMS.
Sources: wms.
Branch context: per-branch shipment context.
SCD2: yes.
Anonymization: hot.
record_source value: wms__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_shipment_logistics__wms__msk (
    shipment_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'wms__msk',
    shipment_status LowCardinality(String),
    carrier_name  LowCardinality(String),
    shipped_at    Nullable(DateTime64(3)),
    delivered_at  Nullable(DateTime64(3)),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (shipment_hk, load_ts);
