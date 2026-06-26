/*
Purpose: Product-supplier sourcing terms from the cloud reference (HF Dataset).
Sources: ref.
Branch context: global sourcing reference effectivity.
SCD2: yes.
Anonymization: hot commercial reference.
record_source value: ref__global
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_lnk_product_supplier__ref__global (
    link_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'ref__global',
    valid_from    DateTime64(3),
    valid_to      Nullable(DateTime64(3)),
    supplier_priority UInt16,
    purchase_price Decimal(18, 2),
    min_order_qty UInt32,
    lead_time_days UInt16,
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (link_hk, load_ts);
