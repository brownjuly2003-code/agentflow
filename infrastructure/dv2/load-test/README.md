# DV2.0 ClickHouse load test (Kubernetes-native)

A `clickhouse-benchmark`-based load test that runs **as a Kubernetes Job** in
the `dv2` namespace, driving real analytical traffic against the in-cluster
`clickhouse` service over the native protocol (port 9000) — i.e. the same
network path a BI tool or the AgentFlow serving API would take.

This is the warehouse-tier counterpart to the API-tier load test in
`tests/load/` (locust against the FastAPI service). It answers a different
question: **how fast does the Data Vault answer analytical queries, and how
does latency degrade as client concurrency rises?**

## Scenarios

| File | Class | What it exercises |
|------|-------|-------------------|
| `01_branch_pnl_adhoc.sql` | adhoc | Branch P&L rollup over `rv.bv_order_canonical` — recomputes the full business view (UNION ALL × 5 branches + argMax SCD2 collapse + 5 LEFT JOINs) on every call. Sub-second at low concurrency; the live-view recompute is the *ad-hoc* path, contrasted with the materialized mart below. |
| `02_top_products.sql` | heavy | Top-N products per branch — `lnk_order_product` ⋈ `hub_order`, GROUP BY + ORDER BY + LIMIT. |
| `03_customer360_point.sql` | point | Single-customer lookup in the materialized `marts.customer_360` mart (simulates an entity GET). |
| `04_returns_velocity.sql` | heavy | Returns-rate aggregation over `marts.returns_velocity`. |
| `05_line_items_reach.sql` | heavy | Line-items reach — join + `uniqExact` over the largest link table. |
| `06_branch_pnl_mart.sql` | heavy | Branch P&L off the **materialized** `marts.branch_pnl` — the serving path counterpart to `01_*_adhoc`. Demonstrates the latency gap between live-view recompute and pre-materialized marts. |

Each query ends in `FORMAT Null` so timing reflects server-side execution, not
result serialization to the client.

## How it gates

`run-bench.sh` sweeps each scenario across `CONCURRENCY_LEVELS` (default
`1 4 8`), parses `clickhouse-benchmark`'s text report, and compares p99 to a
per-class budget:

- point-lookup scenarios → `P99_MS_POINT` (default **200 ms**)
- ad-hoc raw-vault recompute → `P99_MS_ADHOC` (default **2000 ms**)
- heavy/analytical scenarios → `P99_MS_HEAVY` (default **1000 ms**)

The Job exits non-zero if any cell breaches its budget, so it can be wired into
CI or an Argo step as a pass/fail gate. Budgets are env-overridable on the Job.

> Concurrency is capped at 8 by default: the demo VM is 2 vCPU, so higher
> client concurrency measures queueing, not the engine. Raise `CONCURRENCY_LEVELS`
> only on bigger hardware.

## Run it

```bash
# from a machine with kubectl pointed at hq-demo:
bash infrastructure/dv2/load-test/apply.sh
```

This (re)creates the `dv2-load-test` ConfigMap from the local `run-bench.sh` +
`queries/*.sql`, (re)creates the Job, waits, and prints the report.

Manual equivalent:

```bash
kubectl -n dv2 create configmap dv2-load-test \
  --from-file=infrastructure/dv2/load-test/run-bench.sh \
  --from-file=infrastructure/dv2/load-test/queries \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n dv2 apply -f infrastructure/dv2/load-test/job.yaml
kubectl -n dv2 wait --for=condition=complete --timeout=600s job/dv2-load-test
kubectl -n dv2 logs job/dv2-load-test
```

## Tuning knobs (Job env)

| Env | Default | Meaning |
|-----|---------|---------|
| `CONCURRENCY_LEVELS` | `1 4 8` | space-separated client concurrency sweep |
| `ITERATIONS` | `60` | queries per (scenario × level) |
| `P99_MS_HEAVY` | `1000` | p99 budget for analytical / mart scenarios |
| `P99_MS_POINT` | `200` | p99 budget for point lookups |
| `P99_MS_ADHOC` | `2000` | p99 budget for raw-vault live-view recompute |

## Baseline numbers

Captured results live in
[`docs/dv2-multi-branch/load-test-baseline.md`](../../../docs/dv2-multi-branch/load-test-baseline.md).
The current baseline is against **synthetic seed data** (~10K orders); re-run
after loading the X5 Retail Hero subset to refresh the headline numbers.
