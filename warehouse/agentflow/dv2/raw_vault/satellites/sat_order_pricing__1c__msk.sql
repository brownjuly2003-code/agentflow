/*
Purpose: Order pricing recalculations from 1C.
Sources: 1c.
Branch context: per-branch pricing context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_order_pricing__1c__msk (
    order_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT '1c__msk',
    subtotal_amount Decimal(18, 2),
    discount_amount Decimal(18, 2),
    tax_amount    Decimal(18, 2),
    shipping_cost Decimal(18, 2),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (order_hk, load_ts);
