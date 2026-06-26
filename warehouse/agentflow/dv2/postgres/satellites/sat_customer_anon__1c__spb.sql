/*
Purpose: Cold anonymized customer projection derived from hot 1C PII (Saint Petersburg).
Sources: 1c.
Branch context: derived cold projection for Saint Petersburg.
SCD2: yes.
Anonymization: cold.
record_source value: 1c__spb
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_anon__1c__spb (
    customer_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__spb',
    age_bucket      TEXT,
    geo_region      TEXT,
    customer_segment TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (customer_hk, load_ts)
);
