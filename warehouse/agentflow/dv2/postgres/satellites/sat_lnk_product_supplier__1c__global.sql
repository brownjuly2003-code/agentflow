/*
Purpose: Effectivity satellite for product-supplier sourcing.
Sources: 1c.
Branch context: global sourcing effectivity.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__global
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_lnk_product_supplier__1c__global (
    link_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__global',
    valid_from      TIMESTAMP(3),
    valid_to        TIMESTAMP(3),
    supplier_priority INTEGER,
    purchase_price  NUMERIC(18, 2),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (link_hk, load_ts)
);
