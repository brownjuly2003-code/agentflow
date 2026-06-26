/*
Purpose: Employee HR profile from 1C ZUP.
Sources: 1c_zup.
Branch context: per-branch employee context.
SCD2: yes.
Anonymization: hot.
record_source value: 1c_zup__msk
record_source format: {source_system}__{branch_code}.
Dialect: postgresql (raw vault on PostgreSQL; see dv2/postgres/README.md).
*/
CREATE TABLE IF NOT EXISTS rv.sat_employee_profile__1c_zup__msk (
    employee_hk BYTEA NOT NULL,
    load_ts       TIMESTAMP(3) NOT NULL DEFAULT now(),
    hash_diff     BYTEA NOT NULL,
    record_source TEXT NOT NULL DEFAULT '1c_zup__msk',
    first_name      TEXT,
    last_name       TEXT,
    role_name       TEXT,
    employment_status TEXT,
    is_deleted    SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (employee_hk, load_ts)
);
