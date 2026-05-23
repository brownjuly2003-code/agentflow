/*
Purpose: Aggregated cart and view behavior from site XML exchange.
Sources: site.
Branch context: per-branch behavioral aggregate.
SCD2: yes.
Anonymization: hot with cold anonymized replica.
record_source value: site__msk
record_source format: {source_system}__{branch_code}.
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_behavior__site__msk (
    customer_hk FixedString(16),
    load_ts       DateTime64(3) DEFAULT now64(3),
    hash_diff     FixedString(16),
    record_source LowCardinality(String) DEFAULT 'site__msk',
    cart_events_30d UInt32,
    view_events_30d UInt32,
    last_event_at Nullable(DateTime64(3)),
    is_deleted    UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(load_ts)
ORDER BY (customer_hk, load_ts);
