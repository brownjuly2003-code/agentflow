/*
Purpose: Order header and status flow from Bitrix24 (Yekaterinburg).
Sources: bitrix.
Branch context: per-branch order state.
SCD2: yes.
Anonymization: hot.
record_source value: bitrix__ekb
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_order_header__bitrix__ekb (
    order_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'bitrix__ekb',
    order_date      TIMESTAMP(3),
    channel         TEXT,
    order_status    TEXT,
    total_amount    NUMERIC(18, 2),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (order_hk, load_ts)
);
