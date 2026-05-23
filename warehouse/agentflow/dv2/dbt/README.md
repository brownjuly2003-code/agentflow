# DV2.0 dbt Mart Layer

Three materialized marts built on top of the DV2.0 business vault views in
the `rv` database. Demonstrates how downstream BI / finance / analytics
consume the multi-branch warehouse without ever touching the raw vault
sources directly.

## Marts

| Model               | Grain                    | Purpose                                                                     |
| ------------------- | ------------------------ | --------------------------------------------------------------------------- |
| `customer_360`      | (customer_hk, branch)    | MDM customer + order aggregates (LTV, return rate, first/last order)        |
| `branch_pnl`        | (branch, month)          | Per-branch monthly P&L with effective tax rate (validates jurisdictions)   |
| `returns_velocity`  | (branch, channel, week)  | Returns rate per channel/week for fraud + supply-chain alerting             |

## Sources

All marts read from the business vault views — they never touch the raw
vault satellites directly. This keeps mart logic decoupled from
satellite source-system fan-out:

- `rv.bv_customer_mdm__{msk,spb,ekb,dxb,ala}` — five branch-scoped views,
  PII stays in branch, RBAC-friendly
- `rv.bv_order_canonical` — UNION ALL of header + pricing across all five
  branches with `argMax` SCD2 collapse

## Tests

Each mart has structural tests in `models/marts/schema.yml`:

- `not_null` on key columns
- `accepted_values` on `branch` (must be one of the 5 known codes)

Run them with `dbt test`.

## Running locally

```bash
pip install dbt-core==1.8.7 dbt-clickhouse==1.8.7
export DBT_PROFILES_DIR="$(pwd)"
cp profiles.example.yml profiles.yml
# point host:port at the ClickHouse instance (port-forward in dev:
#   kubectl port-forward -n dv2 svc/clickhouse 9000:9000)
dbt run
dbt test
```

## Running on the cluster

```bash
bash infrastructure/dv2/dbt/run.sh
```

This packages the dbt project into a ConfigMap and submits a Kubernetes
Job that runs `dbt deps && dbt run && dbt test` inside the `dv2`
namespace. Same image, same ClickHouse credentials, same network path
as the Argo workflow's steps.

## Effective tax rate sanity check

After `dbt run`, the `branch_pnl` table can validate the multi-branch
tax wiring end-to-end:

```sql
SELECT branch, effective_tax_rate
FROM marts.branch_pnl
GROUP BY branch, effective_tax_rate
ORDER BY branch;
```

Expected: `0.20` for `msk/spb/ekb` (RU), `0.05` for `dxb` (UAE), `0.12`
for `ala` (KZ).

## Schema

dbt writes marts to a separate ClickHouse database (`marts`). The raw
vault stays untouched — anyone with read access to `marts` doesn't see
`rv.*` and vice versa. Production RBAC layers on top of this split.
