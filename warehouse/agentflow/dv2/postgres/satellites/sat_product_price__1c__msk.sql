/*
Purpose: Active product price list from 1C.
Sources: 1c.
Branch context: branch-qualified price context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_price__1c__msk (
    product_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__msk',
    retail_price    NUMERIC(18, 2),
    wholesale_price NUMERIC(18, 2),
    currency_code   CHAR(3),
    valid_from      TIMESTAMP(3),
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (product_hk, load_ts)
);
