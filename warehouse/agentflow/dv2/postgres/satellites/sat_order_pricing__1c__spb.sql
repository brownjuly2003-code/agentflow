/*
Purpose: Order pricing recalculations from 1C (Saint Petersburg).
Sources: 1c.
Branch context: per-branch pricing context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__spb
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_order_pricing__1c__spb (
    order_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__spb',
    subtotal_amount NUMERIC(18, 2),
    discount_amount NUMERIC(18, 2),
    tax_amount      NUMERIC(18, 2),
    shipping_cost   NUMERIC(18, 2),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (order_hk, load_ts)
);
