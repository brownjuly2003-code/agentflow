/*
Purpose: Supplier master data from the cloud supplier reference (HF Dataset).
Sources: ref.
Branch context: global supplier reference context.
SCD2: yes.
Anonymization: hot commercial reference.
record_source value: ref__global
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_supplier_profile__ref__global (
    supplier_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'ref__global',
    supplier_name String,
    tax_country_code FixedString(2),
    supplier_status LowCardinality(String),
    gln           String,
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (supplier_hk, load_ts);
