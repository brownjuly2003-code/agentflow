# Per-branch CDC fan-out

This directory adds a second CDC pattern to the demo: one Postgres database
per branch, each replicated into its own ClickHouse MaterializedPostgreSQL
database.

## Why a second pattern

Session 4 stood up CDC via a **single** CH MaterializedPostgreSQL database
(`oltp_cdc`) that subscribed to two schemas in a single Postgres database
(`ops`):

```
materialized_postgresql_schema_list = 'ops_msk,ops_dxb'
```

That works for a unified stream but blocks fan-out. Every CH
MaterializedPostgreSQL DB pointed at the same Postgres DB tries to create a
publication named `<src>_ch_publication`. Two CH DBs on the same Postgres DB
collide. Session 4 pitfall #5 captured this; verified again on 2026-05-23
against ClickHouse 25.5.11:

```
CREATE DATABASE ... ENGINE = MaterializedPostgreSQL(...)
    SETTINGS materialized_postgresql_publication_name='...'
→ Code 115. Unknown setting 'materialized_postgresql_publication_name'.
```

The architectural goal — per-branch publication isolation so a single
branch's stream can be paused, re-snapshotted, or rotated without touching
the others — needs either an external CDC tool (PeerDB / Debezium) or one
Postgres database per branch. The 8 GB demo iMac cannot host PeerDB OSS
alongside the existing kind cluster (Temporal + flow-api + flow-worker +
catalog PG together need ~3 GB; iMac is already at swap with kind running),
so this demo takes the per-database path.

## What lives here

| File | Purpose |
|------|---------|
| `01_schema.sql` | Create tables (`customers`, `orders`) in `ops_msk_db` + `ops_dxb_db` |
| `02_seed.sql`   | Seed each branch DB with ~10 customers + ~30 orders |
| `03_cdc_setup.sql` | Per-DB grants, REPLICA IDENTITY DEFAULT, table OWNERSHIP for `rep_user` |
| `04_ch_bridge.sql` | CH side: `oltp_cdc_msk` + `oltp_cdc_dxb` MaterializedPostgreSQL DBs |

The two new Postgres databases (`ops_msk_db`, `ops_dxb_db`) are owned by
`ops`. The pre-existing `ops` database with its `ops_msk` / `ops_dxb`
**schemas** is untouched — the single-DB CDC pattern still runs through
`oltp_cdc`. Both patterns coexist so the demo can show "unified stream"
vs "per-branch stream" side by side.

## Apply

```bash
# Postgres-side (MUST be applied in this order)
kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d postgres \
  < warehouse/agentflow/dv2/postgres_oltp/fanout/01_schema.sql
kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d postgres \
  < warehouse/agentflow/dv2/postgres_oltp/fanout/02_seed.sql
kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d postgres \
  < warehouse/agentflow/dv2/postgres_oltp/fanout/03_cdc_setup.sql

# ClickHouse-side
kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client \
  --user default --password demo --multiquery \
  < warehouse/agentflow/dv2/postgres_oltp/fanout/04_ch_bridge.sql
```

Pre-req: the `rep_user` role from session 4 (`cdc_setup.sql`) must already
exist. The fan-out scripts grant *additional* per-DB privileges to that
role; they do not create it.

## Verify

```bash
# Snapshot count
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client \
  --user default --password demo --multiline --query "
    SELECT (SELECT count() FROM oltp_cdc_msk.customers FINAL) AS msk_c,
           (SELECT count() FROM oltp_cdc_msk.orders    FINAL) AS msk_o,
           (SELECT count() FROM oltp_cdc_dxb.customers FINAL) AS dxb_c,
           (SELECT count() FROM oltp_cdc_dxb.orders    FINAL) AS dxb_o
    FORMAT Vertical"

# Replication slots — one per branch DB
kubectl exec -n dv2 postgres-0 -- psql -U ops -d postgres -c \
  "SELECT slot_name, database, active, confirmed_flush_lsn
     FROM pg_replication_slots
    WHERE database IN ('ops_msk_db','ops_dxb_db')"

# Live edit + propagation
kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d ops_msk_db <<'SQL'
INSERT INTO customers (customer_id, first_name, last_name, email)
VALUES ('msk-c-LIVE','LIVE','TEST','live@test.ru');
UPDATE customers SET phone='+74950000000' WHERE customer_id='msk-c-001';
SQL
sleep 8
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client \
  --user default --password demo --query "
    SELECT count(), max(updated_at) FROM oltp_cdc_msk.customers FINAL"

# Isolation: MSK CH must not see DXB rows
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client \
  --user default --password demo --query "
    SELECT count() FROM oltp_cdc_msk.customers WHERE customer_id LIKE 'dxb-%'"
# expected: 0
```

## Why not PeerDB

PeerDB OSS would be the cleaner production choice: it manages publications
and slots externally, supports per-mirror configuration, and exposes a UI
for operators. Three constraints pushed this demo to the native path:

1. **iMac 2017 / 8 GB RAM.** PeerDB stack (Temporal + cassandra/elasticsearch
   + catalog Postgres + flow-api + flow-worker + flow-snapshot-worker +
   peerdb-server) is documented at ~3 GB resident; the iMac is already at
   swap with kind + ClickHouse + Postgres + MinIO + Argo running.
2. **Demo continuity.** Adding PeerDB would require either standing up a
   second cluster or restarting the existing pods to free memory. Session 4
   verification on the live `hq-demo` cluster would have been lost.
3. **Same observable outcome.** The architectural property the production
   choice needs to deliver is *per-branch publication isolation*. The
   per-DB split delivers that property natively, with two distinct
   publications, two distinct replication slots, and pause/restart
   semantics scoped to a single branch.

In production: PeerDB / Debezium remain the natural choice. The per-DB
pattern shown here would still work — it would just live behind PeerDB's
mirror configuration instead of `MaterializedPostgreSQL`.
