# DV2.0 Postgres OLTP — hot tier seed + CDC bridge

Closes the hot tier of the DV2.0 multi-branch flow described in
`docs/dv2-multi-branch/architecture.md`. Three SQL files, applied in
order, populate Postgres OLTP with per-branch operational data, expose
it to ClickHouse via the `PostgreSQL()` table engine, and promote it
into `rv.*` using the same idempotent hash pattern the synthetic seed
uses.

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
