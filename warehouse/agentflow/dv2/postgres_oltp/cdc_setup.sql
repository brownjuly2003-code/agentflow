-- Postgres-side setup for ClickHouse MaterializedPostgreSQL CDC.
-- Replaces the pull-based PostgreSQL() bridge with push-based logical
-- replication. Run AFTER the Postgres pod has been restarted with
-- `wal_level=logical` (postgres-sts.yaml `args`).
--
-- Idempotent: re-running is safe; CREATE USER / GRANT / ALTER are
-- guarded with conditional logic.

-- ============ Replication user ============
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rep_user') THEN
        CREATE ROLE rep_user WITH REPLICATION LOGIN PASSWORD 'rep_demo';
    END IF;
END$$;

-- Allow read of all tables in OLTP schemas. ClickHouse's
-- MaterializedPostgreSQL engine needs CONNECT + SELECT to snapshot
-- existing rows before streaming the WAL.
GRANT CONNECT ON DATABASE ops TO rep_user;
GRANT USAGE   ON SCHEMA ops_msk TO rep_user;
GRANT USAGE   ON SCHEMA ops_dxb TO rep_user;
GRANT SELECT  ON ALL TABLES IN SCHEMA ops_msk TO rep_user;
GRANT SELECT  ON ALL TABLES IN SCHEMA ops_dxb TO rep_user;

-- ============ Replica identity ============
-- ClickHouse's MaterializedPostgreSQL engine requires REPLICA IDENTITY
-- DEFAULT (primary key) or a non-NULL unique index — `FULL` is parsed
-- as "no key" and the table is skipped from the replication stream
-- with the warning:
--   "Table has replica identity f - not supported. A table must have
--    a primary key or a replica identity index"
-- All four OLTP tables already have `text PRIMARY KEY`, so DEFAULT is
-- the right value. (For downstream consumers that DO want full
-- pre-images, a separate audit publication can be created on the same
-- tables with `REPLICA IDENTITY FULL` — but not for the CH stream.)
ALTER TABLE ops_msk.customers REPLICA IDENTITY DEFAULT;
ALTER TABLE ops_msk.orders    REPLICA IDENTITY DEFAULT;
ALTER TABLE ops_dxb.customers REPLICA IDENTITY DEFAULT;
ALTER TABLE ops_dxb.orders    REPLICA IDENTITY DEFAULT;

-- ============ Publication ownership ============
-- ClickHouse MaterializedPostgreSQL issues `CREATE PUBLICATION ... FOR
-- TABLE ...` from its replication user — and Postgres requires the
-- publication's listed tables to be owned by the user that creates the
-- publication. Hand ownership of the OLTP tables to rep_user so the
-- engine can self-bootstrap.
--
-- This is safe for the demo because the original `ops` superuser
-- retains all privileges via the postgres role.
--
-- NOTE: ClickHouse 25.5 does NOT accept a custom publication name —
-- `materialized_postgresql_publication_name` is rejected with
-- `Code 115. Unknown setting`. The engine always creates
-- `<source_db>_ch_publication`. The workaround is one Postgres
-- database per branch, demoed in `fanout/` (see README there).
ALTER TABLE ops_msk.customers OWNER TO rep_user;
ALTER TABLE ops_msk.orders    OWNER TO rep_user;
ALTER TABLE ops_dxb.customers OWNER TO rep_user;
ALTER TABLE ops_dxb.orders    OWNER TO rep_user;
