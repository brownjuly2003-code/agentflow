/*
Purpose: Store directory attributes from 1C.
Sources: 1c.
Branch context: global reference context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__global
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_store_master__1c__global (
    store_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__global',
    store_name      TEXT,
    branch_code     TEXT,
    city            TEXT,
    country_code    CHAR(2),
    opened_at       DATE,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (store_hk, load_ts)
);
