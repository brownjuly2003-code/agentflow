/*
Purpose: Supplier master data from 1C.
Sources: 1c.
Branch context: global supplier context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__global
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_supplier_profile__1c__global (
    supplier_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__global',
    supplier_name   TEXT,
    tax_country_code CHAR(2),
    supplier_status TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (supplier_hk, load_ts)
);
