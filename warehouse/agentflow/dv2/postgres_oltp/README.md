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
