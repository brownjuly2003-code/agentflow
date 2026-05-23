-- ClickHouse-side bridge for fan-out CDC.
--
-- Creates two MaterializedPostgreSQL databases, each pointed at its own
-- Postgres database. Because the source DB names differ, the auto-created
-- publications (`<src>_ch_publication`) and replication slots
-- (`<src>_ch_replication_slot`) do not collide.
--
-- This is the architectural payoff of the per-branch DB split: a
-- production-style fan-out where each branch's CDC stream can be paused,
-- restarted, or re-snapshotted without touching the other branch.
--
-- Apply with:
--   kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client \
--     --user default --password demo --multiquery \
--     < warehouse/agentflow/dv2/postgres_oltp/fanout/04_ch_bridge.sql

SET allow_experimental_database_materialized_postgresql=1;

DROP DATABASE IF EXISTS oltp_cdc_msk;
DROP DATABASE IF EXISTS oltp_cdc_dxb;

CREATE DATABASE oltp_cdc_msk
  ENGINE = MaterializedPostgreSQL('postgres:5432', 'ops_msk_db', 'rep_user', 'rep_demo');

CREATE DATABASE oltp_cdc_dxb
  ENGINE = MaterializedPostgreSQL('postgres:5432', 'ops_dxb_db', 'rep_user', 'rep_demo');
