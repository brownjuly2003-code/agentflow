-- DV2.0 fan-out CDC: per-branch Postgres databases.
--
-- WHY a separate file (and a separate database per branch).
--
-- Session 4 stood up CDC via a single ClickHouse MaterializedPostgreSQL
-- database (`oltp_cdc`) that subscribed to two schemas in one Postgres
-- database (`ops`):
--     materialized_postgresql_schema_list = 'ops_msk,ops_dxb'
-- That works, but every CH MaterializedPostgreSQL DB pointed at the same
-- Postgres DB tries to create a publication named `<src>_ch_publication`.
-- Two CH DBs on the same Postgres DB collide on that name and the second
-- one fails to start. Session 4 pitfall #5 documented this.
--
-- Verified again on 2026-05-23 against ClickHouse 25.5.11:
--     CREATE DATABASE ... ENGINE = MaterializedPostgreSQL(...)
--         SETTINGS materialized_postgresql_publication_name='...'
-- → Code 115. Unknown setting 'materialized_postgresql_publication_name'.
--
-- So a per-branch CH DB cannot disambiguate by publication name; the only
-- way to fan-out without an external CDC tool (PeerDB / Debezium) is to
-- give each branch its own Postgres database. `<src>_ch_publication` then
-- becomes naturally unique because the source DB name differs.
--
-- This file creates the table layout in two new Postgres databases
-- (`ops_msk_db`, `ops_dxb_db`). The pre-existing `ops` database with its
-- schema-based layout stays in place — the single-DB CDC pattern is still
-- demoed via `oltp_cdc` in CH. This file adds the second pattern.
--
-- Apply with:
--   kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d postgres \
--     < warehouse/agentflow/dv2/postgres_oltp/fanout/01_schema.sql

\c ops_msk_db

CREATE TABLE IF NOT EXISTS customers (
    customer_id    text PRIMARY KEY,
    first_name     text NOT NULL,
    last_name      text NOT NULL,
    email          text,
    phone          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    order_id       text PRIMARY KEY,
    customer_id    text NOT NULL REFERENCES customers(customer_id),
    order_ts       timestamptz NOT NULL DEFAULT now(),
    status         text NOT NULL,
    total          numeric(12,2) NOT NULL,
    currency       text NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

\c ops_dxb_db

CREATE TABLE IF NOT EXISTS customers (
    customer_id    text PRIMARY KEY,
    first_name     text NOT NULL,
    last_name      text NOT NULL,
    email          text,
    phone          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    order_id       text PRIMARY KEY,
    customer_id    text NOT NULL REFERENCES customers(customer_id),
    order_ts       timestamptz NOT NULL DEFAULT now(),
    status         text NOT NULL,
    total          numeric(12,2) NOT NULL,
    currency       text NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now()
);
