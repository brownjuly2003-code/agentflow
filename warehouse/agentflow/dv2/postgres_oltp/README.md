# DV2.0 Postgres OLTP — hot tier seed + vault promotion

Closes the hot tier of the DV2.0 multi-branch flow described in
`docs/dv2-multi-branch/architecture.md`: per-branch operational data in
Postgres OLTP (`ops_<branch>` schemas), promoted into the `rv.*` raw vault
with the same idempotent hash pattern the synthetic seed uses.

## PostgreSQL-native promotion (current)

The raw vault now lives on **PostgreSQL** (see `dv2/postgres/README.md`), the
same engine as this OLTP hot tier. So the ClickHouse `PostgreSQL()` bridge that
the older promotion needed **collapses**: promotion is a plain in-database
`INSERT ... SELECT` straight from `ops_<branch>` into `rv.*` — no bridge, no
second engine.

| File | Where it runs | What it does |
| ---- | ------------- | ------------ |
| `seed.sql`                     | PostgreSQL | Creates `ops_msk` / `ops_dxb` schemas (`customers` + `orders`), seeds 50 + 200 (MSK) and 20 + 80 (DXB). Idempotent via `ON CONFLICT DO NOTHING`. |
| `promote_to_raw_vault_pg.sql`  | PostgreSQL | `INSERT ... SELECT` from `ops_<branch>.{customers,orders}` into `rv.hub_customer`, `rv.hub_order`, `rv.lnk_order_customer`, `rv.sat_customer_personal__1c__{msk,dxb}`, `rv.sat_order_header__bitrix__{msk,dxb}`. Hash keys are `decode(md5(...), 'hex')` (BYTEA, join-identical to the other DV2 vault feeds); `record_source = pg_ops__<branch>`. One transaction → one stable `load_ts`. |

```bash
# single-node Mac demo, after dv2/postgres/apply.sh
PGHOST=localhost PGUSER=agentflow PGDATABASE=agentflow psql -v ON_ERROR_STOP=1 -f seed.sql
PGHOST=localhost PGUSER=agentflow PGDATABASE=agentflow psql -v ON_ERROR_STOP=1 -f promote_to_raw_vault_pg.sql
```

Idempotency: hubs/links collide on their BYTEA primary key
(`ON CONFLICT DO NOTHING`); satellites insert a version only when the
`(hash key, hash_diff)` pair is absent, so a re-run is a no-op. No-Docker
validation parses every statement with sqlglot and checks each inserted column
exists in the committed vault DDL (`tests/unit/test_dv2_postgres_ingestion.py`);
a live apply + `bv_order_canonical` query is the single-node Mac smoke.

## PostgreSQL-native push freshness (LISTEN/NOTIFY)

With both the OLTP hot tier and the raw vault on PostgreSQL, freshness no longer
needs a replication slot, a WAL consumer, or a second engine. An
`AFTER INSERT/UPDATE` trigger on each `ops_<branch>` table issues `pg_notify` on
the `dv2_vault_refresh` channel; a listener LISTENs and runs the idempotent
promotion the moment a change lands — **event driven, not polled**.

| File | Where it runs | What it does |
| ---- | ------------- | ------------ |
| `freshness_listen_notify.sql` | PostgreSQL | `rv.notify_oltp_change()` + one idempotent `AFTER INSERT/UPDATE` trigger per OLTP table. The payload carries `branch` / `source_table` / `op` / `emitted_at` (`clock_timestamp()` at emit, so the lag is the real emit instant, not the transaction start). |
| `freshness_listener.py`       | host (psycopg) | LISTENs on `dv2_vault_refresh`, runs `promote_to_raw_vault_pg.sql` per change, and reports the emit → vault-visible lag. The pure core (`parse_notification` / `lag_ms` / `process_notifications`) is driver-agnostic and no-Docker tested; psycopg is guarded like `pg_vault_writer`. |

```bash
# single-node Mac demo, after dv2/postgres/apply.sh + seed.sql + this file
psql -v ON_ERROR_STOP=1 -f freshness_listen_notify.sql
python -m warehouse.agentflow.dv2.postgres_oltp.freshness_listener \
    --dsn "postgresql://agentflow:...@localhost/agentflow" --stop-after 1
# ... then INSERT one row into ops_msk.orders elsewhere; the listener promotes
# it and prints e.g.  promoted branch=msk table=orders op=INSERT lag=8.4ms
```

This is the PostgreSQL-native equivalent of the ClickHouse
`MaterializedPostgreSQL` push-CDC below: the same "push, not poll" property, but
the whole mechanism is a NOTIFY plus an in-database `INSERT ... SELECT`, because
the vault lives in the same PostgreSQL instance. No-Docker tests parse the
trigger SQL and drive the listener with fake notifications
(`tests/unit/test_dv2_freshness_listen_notify.py`); a live trigger → NOTIFY →
promote → `bv_order_canonical` round-trip with a measured lag is the single-node
Mac smoke.

## Legacy: ClickHouse-bridge promotion (vault-on-ClickHouse era)

The files below are kept for reference from when the raw vault was on
ClickHouse. They reach Postgres OLTP through the ClickHouse `PostgreSQL()` /
`MaterializedPostgreSQL()` table engines and promote into a **ClickHouse** `rv.*`.
With the vault on PostgreSQL they are no longer the active path — ClickHouse is
retained only as an optional flat-mart serving backend, which is fed from the
vault, not from this OLTP bridge.

## Layout

| File | Where it runs | What it does |
| ---- | ------------- | ------------ |
| `seed.sql`                  | Postgres pod | Creates `ops_msk` and `ops_dxb` schemas, each with `customers` + `orders`. Seeds 50 + 200 (MSK) and 20 + 80 (DXB) rows. Idempotent via `ON CONFLICT DO NOTHING`. |
| `bridge.sql`                | ClickHouse pod | Creates `oltp_live.{msk,dxb}_{customers,orders}` — four `Engine = PostgreSQL(...)` tables that read Postgres live. |
| `promote_to_raw_vault.sql`  | ClickHouse pod | INSERTs from the `oltp_live.*` bridge into `rv.hub_customer`, `rv.hub_order`, `rv.lnk_order_customer`, `rv.sat_customer_personal__1c__{msk,dxb}`, and `rv.sat_order_header__bitrix__{msk,dxb}`. Uses `record_source = pg_ops__<branch>` so the BV view's `splitByString('__', record_source)[2]` extracts the branch correctly. |

## Apply order

```bash
# 1) Hot tier: seed Postgres
cat seed.sql | kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d ops

# 2) Wire ClickHouse to Postgres
cat bridge.sql | kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client \
    --user default --password demo --multiquery

# 3) Promote hot rows into warm raw_vault
cat promote_to_raw_vault.sql | kubectl exec -i -n dv2 clickhouse-0 -- \
    clickhouse-client --user default --password demo --multiquery
```

## Why `PostgreSQL()` engine instead of Debezium / PeerDB

This is the lightest CDC equivalent that fits on a 3-node kind cluster
without giving up the architectural shape. Trade-offs:

- **Pull, not push.** ClickHouse reads Postgres on demand instead of
  streaming changes. For a demo where the warehouse runs scheduled jobs
  this is functionally equivalent to scheduled CDC.
- **No delete capture.** The `PostgreSQL()` engine returns the current
  table state, so deletes in Postgres are invisible to historical
  satellites. Real CDC (Debezium / PeerDB) preserves tombstones; for the
  demo we deliberately treat OLTP as append-only.
- **No replication slot to manage.** No `wal_level = logical`, no
  publication / subscription state. Re-running the bridge SQL is safe.

In production the swap path is one engine type — `Engine =
MaterializedPostgreSQL(...)` keeps the same DDL surface, or the bridge
is dropped entirely and replaced by a PeerDB / Debezium connector
writing to the same raw_vault tables. The `record_source = pg_ops__*`
convention survives either way.

## Push-based CDC variant

A drop-in `MaterializedPostgreSQL` variant lives in three companion
files. It demonstrates the production shape on the same cluster:

| File                          | Where it runs   | What it does                                                                                                          |
| ----------------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------- |
| `cdc_setup.sql`               | Postgres pod    | Creates `rep_user` (REPLICATION) + grants + transfers table ownership + sets `REPLICA IDENTITY DEFAULT`               |
| `cdc_bridge.sql`              | ClickHouse pod  | Drops legacy `oltp_live`, creates `oltp_cdc` (`MaterializedPostgreSQL`) covering both `ops_msk` + `ops_dxb` schemas   |
| `promote_to_raw_vault_cdc.sql`| ClickHouse pod  | Same hub/link/satellite shape as the pull variant, sourced from `oltp_cdc."ops_<branch>.<table>"` (FINAL-deduplicated) |

Prerequisites:

1. `infrastructure/dv2/postgres-sts.yaml` already declares
   `wal_level=logical`, `max_replication_slots=10`, `max_wal_senders=10`
   on the postgres args.
2. After the first apply the postgres pod must be restarted
   (`kubectl rollout restart statefulset/postgres -n dv2`) so the
   new postgres.conf flags take effect.

Apply:

```bash
# 1) wal_level=logical takes effect after restart (idempotent)
kubectl rollout restart statefulset/postgres -n dv2
kubectl rollout status  statefulset/postgres -n dv2 --timeout=120s

# 2) Postgres-side: rep_user + REPLICA IDENTITY FULL
cat cdc_setup.sql | kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d ops

# 3) ClickHouse-side: switch from PostgreSQL() to MaterializedPostgreSQL()
cat cdc_bridge.sql | kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client \
    --user default --password demo --multiquery

# 4) Re-run promotion against the new bridge
cat promote_to_raw_vault_cdc.sql | kubectl exec -i -n dv2 clickhouse-0 -- \
    clickhouse-client --user default --password demo --multiquery
```

Verify the push path is live (insert in Postgres, observe in ClickHouse
within a few seconds, no manual refresh):

```bash
# Insert a synthetic row directly in Postgres
kubectl exec -n dv2 postgres-0 -- psql -U ops -d ops -c "
  INSERT INTO ops_msk.customers (customer_id, first_name, last_name, email)
  VALUES ('CUST-MSK-CDC-1', 'CDC', 'Test', 'cdc1@example.test')
  ON CONFLICT DO NOTHING;
"

# Wait <5s for WAL replay
sleep 5

# Read from ClickHouse — table name is `<schema>.<table>` (one CH
# database, multiple PG schemas), so the dot needs backticks:
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default \
    --password demo --query "
  SELECT customer_id, first_name, last_name
  FROM oltp_cdc.\`ops_msk.customers\` FINAL
  WHERE customer_id = 'CUST-MSK-CDC-1'
"
```

### Multi-branch isolation note

CH 25.x `MaterializedPostgreSQL` does NOT expose a
`publication_name` setting, so two CH databases targeting the same
Postgres database collide on the auto-generated
`<src_db>_ch_publication`. For multi-schema CDC into one warehouse
the supported pattern is the one used here: a single CH database +
`materialized_postgresql_schema_list`. Each replicated table appears
as `oltp_cdc."<schema>.<table>"` in CH (the schema name becomes part
of the table identifier — quote with backticks because of the dot).

For a fully-isolated per-branch CDC fan-out — each branch on its own
logical replica, its own slot, its own publication — switch to
PeerDB or Debezium. They reuse the same Postgres replication slot
plumbing but let each connector own its publication and stream
independently.

Why MaterializedPostgreSQL (and not Debezium / PeerDB) for the demo:

- **Zero extra pod.** Same ClickHouse instance hosts the consumer; no
  separate Kafka Connect cluster or PeerDB deployment to babysit. The
  WAL stream terminates inside the warehouse.
- **Same DDL surface.** The promotion SQL changes only the FROM clauses
  (`oltp_live.msk_customers` → `oltp_cdc_msk.customers`). The hub/link/
  satellite shape and `record_source = pg_ops__*` convention survive
  the swap.
- **Logical replication, not snapshots.** UPDATE / DELETE on Postgres
  is now visible to the warehouse; the old `PostgreSQL()` engine only
  ever saw "current row state" (no tombstones).

For higher throughput or fan-out to non-CH consumers, PeerDB or
Debezium become the right answer — they reuse the same replication
slot model from the Postgres side. The MaterializedPostgreSQL engine
shown here is the minimal-moving-parts variant.

## What the demo proves

After the three files apply against `hq-demo`:

| Surface | rows added by pg path |
| ------- | --------------------- |
| `rv.hub_customer` (record_source `pg_ops__msk`)             | +50  |
| `rv.hub_customer` (record_source `pg_ops__dxb`)             | +20  |
| `rv.hub_order` (record_source `pg_ops__msk`)                | +200 |
| `rv.hub_order` (record_source `pg_ops__dxb`)                | +80  |
| `rv.sat_order_header__bitrix__msk` (record_source `pg_ops__msk`) | +200 |
| `rv.sat_order_header__bitrix__dxb` (record_source `pg_ops__dxb`) | +80  |
| `rv.bv_order_canonical` (`order_bk LIKE 'OLTP-%'`)         | 280 (msk 200 + dxb 80) |

A sample row in `bv_order_canonical` shows the full chain:

```
OLTP-MSK-000144  branch=msk  channel=web  total=4964  header_source=bitrix__msk
```

The `header_source` column reports the destination satellite (which is
shared across Bitrix-and-Postgres-originating rows by design). The
upstream `record_source = pg_ops__msk` is preserved on the underlying
satellite row for audit / lineage.
