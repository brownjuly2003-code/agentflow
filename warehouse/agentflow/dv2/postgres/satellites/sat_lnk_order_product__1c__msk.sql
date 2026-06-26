/*
Purpose: Effectivity satellite for order line quantity and price.
Sources: 1c.
Branch context: per-branch line item effectivity.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_lnk_order_product__1c__msk (
    link_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__msk',
    qty             NUMERIC(18, 3),
    unit_price      NUMERIC(18, 2),
    discount_pct    NUMERIC(5, 2),
    line_total      NUMERIC(18, 2),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (link_hk, load_ts)
);
