/*
Purpose: Product marketplace listing state from Wildberries.
Sources: wb.
Branch context: marketplace listing for Moscow fulfillment.
SCD2: yes.
Anonymization: hot.
record_source value: wb__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_marketplace__wb__msk (
    product_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'wb__msk',
    wb_id         String,
    wb_price      Decimal(18, 2),
    wb_status     LowCardinality(String),
    wb_rating     Nullable(Decimal(5, 2)),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (product_hk, load_ts);
