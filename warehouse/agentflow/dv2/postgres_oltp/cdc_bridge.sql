-- ClickHouse-side CDC bridge using MaterializedPostgreSQL.
-- Logical-replication push-based replacement for the old `oltp_live`
-- PostgreSQL() table engine (pull-based). The Postgres side must have
-- `wal_level=logical` AND `cdc_setup.sql` applied first.
--
-- One CH database (`oltp_cdc`) consumes both `ops_msk` and `ops_dxb`
-- Postgres schemas via `materialized_postgresql_schema_list`. CH 25.x
-- MaterializedPostgreSQL does NOT expose `publication_name`, so two
-- CH databases on the same Postgres source collide on the
-- auto-generated `<src_db>_ch_publication` — the schema_list pattern
-- is the supported way to handle multi-schema CDC into a single
-- consumer. For a fully isolated multi-branch CDC fan-out (each
-- branch on its own logical replica) PeerDB / Debezium is the right
-- tool.

SET allow_experimental_database_materialized_postgresql = 1;

-- ============ Drop legacy pull-based bridge ============
DROP DATABASE IF EXISTS oltp_live;

-- ============ Multi-schema CDC ============
DROP DATABASE IF EXISTS oltp_cdc;
CREATE DATABASE oltp_cdc
ENGINE = MaterializedPostgreSQL(
    'postgres:5432', 'ops', 'rep_user', 'rep_demo'
)
SETTINGS
    materialized_postgresql_schema_list = 'ops_msk,ops_dxb';
