# DV2 Raw Vault on PostgreSQL

The DV2 raw vault runs on **PostgreSQL**, not ClickHouse.

## Why PostgreSQL, not ClickHouse

A Data Vault is **reconstruction-heavy**: `bv_order_canonical` collapses each
satellite to its latest version (`argMax`/`DISTINCT ON` by `load_ts`) over a
`UNION ALL` of per-branch satellites, then joins header + pricing +
marketplace + customer + store — five `LEFT JOIN`s. Multi-way joins are
PostgreSQL's strength and ClickHouse's weak spot; the earlier "ClickHouse is
good for heavy branch aggregates" argument was really an argument for flat
**marts** on ClickHouse, not for the **raw vault** on ClickHouse. So the vault
lives where joins are cheap (PostgreSQL/MPP), and ClickHouse is kept only as an
optional flat-mart serving backend.

This also makes the OLTP `postgres_oltp/` layer and the vault share one engine:
PostgreSQL is the common root from which both CDC→Kafka→serving and the vault
are fed.

## ClickHouse -> PostgreSQL translation

DDL is generated from the single source of truth, `spec.yaml`:

```bash
# from warehouse/agentflow/dv2
python generate_satellites.py --dialect postgres   # -> postgres/satellites/
```

Type mapping lives in `dialects.py` (`clickhouse_to_postgres_type`):

| ClickHouse | PostgreSQL |
|---|---|
| `FixedString(16)` (hash key) | `BYTEA` |
| `FixedString(2)` (code) | `CHAR(2)` |
| `String`, `LowCardinality(String)` | `TEXT` |
| `Nullable(X)` | `X` (PG columns nullable by default) |
| `DateTime64(3)` | `TIMESTAMP(3)` |
| `Decimal(p, s)` | `NUMERIC(p, s)` |
| `UInt8` / `UInt16` / `UInt32` | `SMALLINT` / `INTEGER` / `BIGINT` |
| `Bool DEFAULT true` | `BOOLEAN DEFAULT TRUE` |

Engine / physical-model translation:

- `ReplacingMergeTree ORDER BY (hk)` (hubs/links) → `PRIMARY KEY (hk)` with
  idempotent `INSERT ... ON CONFLICT (hk) DO NOTHING`;
- `MergeTree ORDER BY (hk, load_ts)` (satellites) → `PRIMARY KEY (hk, load_ts)`;
- `PARTITION BY toYYYYMM(load_ts)` → PostgreSQL declarative `RANGE (load_ts)`
  monthly partitioning, available when volume warrants (not materialised in the
  base DDL to keep the demo single-command);
- `argMax(col, load_ts) ... GROUP BY hk` → `DISTINCT ON (hk) ... ORDER BY hk,
  load_ts DESC`; `splitByString('__', record_source)[2]` → `split_part(..., 2)`;
  `if(hk != toFixedString('',16), ..)` → `CASE WHEN hk IS NOT NULL THEN ..`.

Foreign keys between links and hubs are intentionally **not** enforced (Data
Vault loads arrive out of order and in parallel; integrity is by hash
construction). Member hash keys are indexed so the business-vault joins are
index-driven.

## Layout

```
postgres/
  00_schema.sql          CREATE SCHEMA rv
  01_hubs.sql            8 hubs
  02_links.sql           8 links
  satellites/*.sql       43 satellites (generated from spec.yaml)
  03_business_vault.sql  bv_order_canonical + bv_customer_mdm__<branch> views
  apply.sh               apply all of the above, in order
  governance/            PII boundary: roles, allow-list grants, row-level
                         security + verify_live.sh (PostgreSQL port of the
                         ClickHouse governance layer; applied manually after
                         apply.sh — see governance/README.md)
```

## Apply and verify

Apply to a running PostgreSQL (single-node demo on the Mac):

```bash
PGHOST=localhost PGUSER=agentflow PGDATABASE=agentflow ./apply.sh
```

No-Docker validation (Windows / CI): every generated and hand-authored DDL
statement — plus the `bv_order_canonical` smoke seed (`smoke/order_smoke_seed.sql`)
— is parsed with sqlglot's PostgreSQL dialect by
`tests/unit/test_dv2_postgres_ddl.py`. `apply.sh` itself has been applied
live end-to-end (standalone PostgreSQL 17.5 on Windows, no Docker) as part of
the governance verification —
`docs/perf/vault-pii-governance-pg-verify-2026-07-02.md`.

A live `bv_order_canonical` query is exercised by `smoke/verify_bv_order.sh`
against a deterministic order seed (see `smoke/README.md` for the recipe and the
hand-derived expected output). The single-node Mac run is the remaining
sub-step, mirroring how the Flink and ClickHouse smokes are run live on the Mac;
the standalone no-Docker recipe from the governance verify applies unchanged.
