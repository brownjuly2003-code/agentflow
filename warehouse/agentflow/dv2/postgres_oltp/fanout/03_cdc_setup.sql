-- Postgres-side CDC setup for per-branch fan-out databases.
--
-- Each per-branch database needs:
--   1. rep_user with CONNECT + CREATE (so CH can CREATE PUBLICATION)
--   2. table OWNERSHIP transferred to rep_user (Postgres requires the
--      publication owner to also own the listed tables — see session 4
--      pitfall #2)
--   3. REPLICA IDENTITY DEFAULT on every table (PRIMARY KEY satisfies it;
--      FULL is not supported by MaterializedPostgreSQL — see pitfall #3)
--
-- The `rep_user` role itself was already created cluster-wide by
-- cdc_setup.sql in session 4 (CREATE ROLE rep_user WITH REPLICATION
-- LOGIN PASSWORD 'rep_demo'). This file only adds per-database grants
-- and per-table ownership/identity for the two new fan-out DBs.
--
-- Apply with:
--   kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d postgres \
--     < warehouse/agentflow/dv2/postgres_oltp/fanout/03_cdc_setup.sql

\c ops_msk_db

GRANT CONNECT ON DATABASE ops_msk_db TO rep_user;
GRANT CREATE  ON DATABASE ops_msk_db TO rep_user;
GRANT USAGE   ON SCHEMA public TO rep_user;
GRANT SELECT  ON ALL TABLES IN SCHEMA public TO rep_user;

ALTER TABLE customers REPLICA IDENTITY DEFAULT;
ALTER TABLE orders    REPLICA IDENTITY DEFAULT;

ALTER TABLE customers OWNER TO rep_user;
ALTER TABLE orders    OWNER TO rep_user;

\c ops_dxb_db

GRANT CONNECT ON DATABASE ops_dxb_db TO rep_user;
GRANT CREATE  ON DATABASE ops_dxb_db TO rep_user;
GRANT USAGE   ON SCHEMA public TO rep_user;
GRANT SELECT  ON ALL TABLES IN SCHEMA public TO rep_user;

ALTER TABLE customers REPLICA IDENTITY DEFAULT;
ALTER TABLE orders    REPLICA IDENTITY DEFAULT;

ALTER TABLE customers OWNER TO rep_user;
ALTER TABLE orders    OWNER TO rep_user;
