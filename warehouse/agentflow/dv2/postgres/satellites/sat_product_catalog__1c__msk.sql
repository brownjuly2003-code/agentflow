/*
Purpose: Product catalog attributes from 1C.
Sources: 1c.
Branch context: global product with branch-qualified source feed.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_catalog__1c__msk (
    product_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__msk',
    product_name    TEXT,
    brand           TEXT,
    category        TEXT,
    size_code       TEXT,
    color           TEXT,
    tnved_code      TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (product_hk, load_ts)
);
