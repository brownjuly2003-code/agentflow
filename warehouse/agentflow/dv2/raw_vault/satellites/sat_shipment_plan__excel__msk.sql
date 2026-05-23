/*
Purpose: Shipment plan data from logistics Excel files.
Sources: excel.
Branch context: per-branch logistics plan.
SCD2: yes.
Anonymization: hot.
record_source value: excel__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_shipment_plan__excel__msk (
    shipment_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'excel__msk',
    planned_ship_date Nullable(Date),
    planned_delivery_date Nullable(Date),
    route_code    Nullable(String),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (shipment_hk, load_ts);
