-- PostgreSQL-native push freshness for the OLTP -> raw-vault path.
--
-- With both the OLTP hot tier and the raw vault on PostgreSQL, the freshness
-- mechanism no longer needs a replication slot, a WAL consumer, or a second
-- engine. An AFTER INSERT/UPDATE trigger on each ops_<branch> table issues
-- pg_notify on the `dv2_vault_refresh` channel; the listener
-- (freshness_listener.py) LISTENs on that channel and runs the idempotent
-- promotion (promote_to_raw_vault_pg.sql) the moment a change lands -- event
-- driven, not polled.
--
-- This is the PostgreSQL-native equivalent of the ClickHouse
-- MaterializedPostgreSQL push-CDC (cdc_setup.sql): same "push, not poll"
-- property, but the whole mechanism is a NOTIFY plus an in-database
-- INSERT ... SELECT, because the vault is in the same PostgreSQL instance.
--
-- Idempotent: CREATE OR REPLACE for the function, DROP TRIGGER IF EXISTS before
-- each CREATE TRIGGER, so re-applying is safe.
--
-- Apply (single-node Mac demo, after dv2/postgres/apply.sh + seed.sql):
--   PGHOST=localhost PGUSER=agentflow PGDATABASE=agentflow \
--       psql -v ON_ERROR_STOP=1 -f freshness_listen_notify.sql

-- ============ Notify function ============
-- The payload carries the branch (passed as a trigger argument), the source
-- table, the operation, and clock_timestamp() at emit time so the listener can
-- measure the emit -> vault-visible lag. clock_timestamp() (not now()) is used
-- so the timestamp reflects the actual emit instant, not the transaction start.
CREATE OR REPLACE FUNCTION rv.notify_oltp_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'dv2_vault_refresh',
        json_build_object(
            'branch', TG_ARGV[0],
            'source_table', TG_TABLE_NAME,
            'op', TG_OP,
            'emitted_at', extract(epoch FROM clock_timestamp())
        )::text
    );
    RETURN NULL;  -- AFTER trigger: return value is ignored
END;
$$;

-- ============ Triggers (one per OLTP table, branch passed as argument) ============
DROP TRIGGER IF EXISTS trg_notify_oltp_change ON ops_msk.customers;
CREATE TRIGGER trg_notify_oltp_change AFTER INSERT OR UPDATE ON ops_msk.customers
    FOR EACH ROW EXECUTE FUNCTION rv.notify_oltp_change('msk');

DROP TRIGGER IF EXISTS trg_notify_oltp_change ON ops_msk.orders;
CREATE TRIGGER trg_notify_oltp_change AFTER INSERT OR UPDATE ON ops_msk.orders
    FOR EACH ROW EXECUTE FUNCTION rv.notify_oltp_change('msk');

DROP TRIGGER IF EXISTS trg_notify_oltp_change ON ops_dxb.customers;
CREATE TRIGGER trg_notify_oltp_change AFTER INSERT OR UPDATE ON ops_dxb.customers
    FOR EACH ROW EXECUTE FUNCTION rv.notify_oltp_change('dxb');

DROP TRIGGER IF EXISTS trg_notify_oltp_change ON ops_dxb.orders;
CREATE TRIGGER trg_notify_oltp_change AFTER INSERT OR UPDATE ON ops_dxb.orders
    FOR EACH ROW EXECUTE FUNCTION rv.notify_oltp_change('dxb');
