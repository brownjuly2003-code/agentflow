/*
Purpose: Wildberries order lifecycle and commission state.
Sources: wb.
Branch context: marketplace order state.
SCD2: yes.
Anonymization: hot.
record_source value: wb__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_order_marketplace__wb__msk (
    order_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'wb__msk',
    wb_status     LowCardinality(String),
    wb_commission Decimal(18, 2),
    return_window_until Nullable(Date),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (order_hk, load_ts);
