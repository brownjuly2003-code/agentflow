/*
Purpose: Supplier master data from the cloud supplier reference (HF Dataset).
Sources: ref.
Branch context: global supplier reference context.
SCD2: yes.
Anonymization: hot commercial reference.
record_source value: ref__global
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_supplier_profile__ref__global (
    supplier_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'ref__global',
    supplier_name   TEXT,
    tax_country_code CHAR(2),
    supplier_status TEXT,
    gln             TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (supplier_hk, load_ts)
);
