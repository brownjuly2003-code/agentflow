/*
Purpose: GS1 GTIN attributes from the cloud product reference (HF Dataset).
Sources: ref.
Branch context: global traceability reference context.
SCD2: yes.
Anonymization: hot non-PII reference.
record_source value: ref__global
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_marking_code_gs1__ref__global (
    marking_code_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'ref__global',
    gs1_gtin        TEXT,
    marking_status  TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (marking_code_hk, load_ts)
);
