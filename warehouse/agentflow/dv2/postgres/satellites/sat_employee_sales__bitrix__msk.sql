/*
Purpose: Employee sales attribution state from Bitrix24.
Sources: bitrix.
Branch context: per-branch sales attribution.
SCD2: yes.
Anonymization: hot.
record_source value: bitrix__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_employee_sales__bitrix__msk (
    employee_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT 'bitrix__msk',
    bitrix_user_id  TEXT,
    sales_team      TEXT,
    manager_flag    BOOLEAN DEFAULT FALSE,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (employee_hk, load_ts)
);
