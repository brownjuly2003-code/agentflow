/*
Purpose: Customer PII from 1C for the Moscow branch.
Sources: 1c.
Branch context: per-branch, hot jurisdictional PII.
SCD2: yes.
Anonymization: hot.
record_source value: 1c__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_customer_personal__1c__msk (
    customer_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c__msk',
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    phone           TEXT,
    birth_date      DATE,
    pii_flag        BOOLEAN DEFAULT TRUE,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (customer_hk, load_ts)
);
