# X5 Retail Hero DV2.0 Loader

Loads the Kaggle `mvyurchenko/x5-retail-hero` CSV files into the AgentFlow DV2.0 raw vault tables in ClickHouse.

Download the dataset with Kaggle CLI:

```bash
kaggle datasets download -d mvyurchenko/x5-retail-hero -p /path/to/x5 --unzip
```

Expected files:

- `clients.csv`
- `products.csv`
- `purchases.csv`

Run:

```bash
python loader.py --csv-dir /path/to/x5 --clickhouse-host localhost --clickhouse-port 9000 --clickhouse-user default --clickhouse-password demo --batch-size 100000
```

Dry run parses and maps chunks without inserting:

```bash
python loader.py --csv-dir /path/to/x5 --clickhouse-host localhost --clickhouse-port 9000 --batch-size 100000 --dry-run
```

Replay with a fixed UTC load timestamp:

```bash
python loader.py --csv-dir /path/to/x5 --clickhouse-host localhost --clickhouse-port 9000 --clickhouse-user default --clickhouse-password demo --batch-size 100000 --load-ts 2026-05-23T10:15:30Z
```

## Schema Assumptions

The loader assumes the DV2.0 DDL has already been applied, normally via `warehouse/agentflow/dv2/__init.sql`, and that tables live in the `rv` database unless `--clickhouse-database` is provided.

Satellite idempotency is handled by the raw vault table engines. The loader always inserts mapped rows and relies on the expected `ReplacingMergeTree` or equivalent merge behavior for repeated hub/link keys and unchanged satellite `hk + hash_diff` pairs.

The X5 `clients.csv` file has no branch field, so `hub_customer` rows use `record_source = '1c__msk'`. Per-branch `sat_customer_personal__1c__{branch}` rows are emitted while processing purchases, using each customer's observed purchase branch.

`store_id` values are converted to store business keys as `{branch}-{store_id}` before hashing into `hub_store.store_hk` and writing `hub_store.store_bk`.

## Branch Distribution

Stores are sorted by `store_id` and assigned with deterministic weighted round-robin:

| Branch | Share |
|---|---:|
| `msk` | 40% |
| `spb` | 25% |
| `ekb` | 15% |
| `dxb` | 10% |
| `ala` | 10% |

Given the same set of `store_id` values, the mapping is stable across runs.
