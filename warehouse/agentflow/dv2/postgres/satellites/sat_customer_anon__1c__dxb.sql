/*
Purpose: Cold anonymized customer projection derived from hot 1C PII (Dubai).
Sources: 1c.
Branch context: derived cold projection for Dubai.
SCD2: yes.
Anonymization: cold.
record_source value: 1c__dxb
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_anon__1c__dxb (
    customer_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__dxb',
    age_bucket      TEXT,
    geo_region      TEXT,
    customer_segment TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (customer_hk, load_ts)
);
