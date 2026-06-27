/*
Purpose: Product catalog, packaging and customs reference (HF Dataset).
Sources: ref.
Branch context: global product reference context.
SCD2: yes.
Anonymization: hot non-PII reference.
record_source value: ref__global
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_product_reference__ref__global (
    product_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'ref__global',
    product_name    TEXT,
    brand           TEXT,
    category        TEXT,
    tnved_code      TEXT,
    gpc_brick_code  TEXT,
    gross_weight_g  BIGINT,
    net_weight_g    BIGINT,
    length_mm       BIGINT,
    width_mm        BIGINT,
    height_mm       BIGINT,
    units_per_pack  INTEGER,
    pack_type       TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (product_hk, load_ts)
);
