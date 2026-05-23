/*
Purpose: Product stock snapshot from WMS.
Sources: wms.
Branch context: branch warehouse stock.
SCD2: yes.
Anonymization: hot.
record_source value: wms__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_stock__wms__msk (
    product_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'wms__msk',
    qty_on_hand   Decimal(18, 3),
    qty_reserved  Decimal(18, 3),
    qty_available Decimal(18, 3),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (product_hk, load_ts);
