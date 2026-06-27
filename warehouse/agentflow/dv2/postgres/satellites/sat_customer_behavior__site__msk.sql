/*
Purpose: Aggregated cart and view behavior from site XML exchange.
Sources: site.
Branch context: per-branch behavioral aggregate.
SCD2: yes.
Anonymization: hot with cold anonymized replica.
record_source value: site__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_behavior__site__msk (
    customer_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'site__msk',
    cart_events_30d BIGINT,
    view_events_30d BIGINT,
    last_event_at   TIMESTAMP(3),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (customer_hk, load_ts)
);
