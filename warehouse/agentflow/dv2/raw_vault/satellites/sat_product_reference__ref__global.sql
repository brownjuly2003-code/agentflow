/*
Purpose: Product catalog, packaging and customs reference (HF Dataset).
Sources: ref.
Branch context: global product reference context.
SCD2: yes.
Anonymization: hot non-PII reference.
record_source value: ref__global
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_reference__ref__global (
    product_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'ref__global',
    product_name  String,
    brand         LowCardinality(String),
    category      LowCardinality(String),
    tnved_code    Nullable(String),
    gpc_brick_code Nullable(String),
    gross_weight_g UInt32,
    net_weight_g  UInt32,
    length_mm     UInt32,
    width_mm      UInt32,
    height_mm     UInt32,
    units_per_pack UInt16,
    pack_type     LowCardinality(String),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (product_hk, load_ts);
