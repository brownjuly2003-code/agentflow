/*
Purpose: Customer loyalty state from Bitrix24 (Yekaterinburg).
Sources: bitrix.
Branch context: per-branch loyalty context.
SCD2: yes.
Anonymization: hot.
record_source value: bitrix__ekb
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_loyalty__bitrix__ekb (
    customer_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'bitrix__ekb',
    loyalty_segment TEXT,
    loyalty_points  NUMERIC(18, 2),
    last_visit_at   TIMESTAMP(3),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (customer_hk, load_ts)
);
