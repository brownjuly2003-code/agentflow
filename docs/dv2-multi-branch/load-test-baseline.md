# DV2.0 ClickHouse load test — baseline

Captured **2026-06-07** against the `hq-demo` kind cluster on the iMac demo
host, **real X5 Retail Hero data**: 8.06M orders / 45.8M line items across 5
branches (`rv.*` raw vault ≈ 3.5 GiB on disk, `rv.bv_order_canonical_mat`
≈ 538 MiB). Harness: [`infrastructure/dv2/load-test/`](../../infrastructure/dv2/load-test/)
— `clickhouse-benchmark` run as a Kubernetes Job in namespace `dv2`, driving
the in-cluster `clickhouse` service over the native protocol (9000).

VM at capture time: 6 GiB RAM, 2 vCPU; ClickHouse pod limit 5 Gi. Server-level
memory accounting is disabled on this stack (see `clickhouse-sts.yaml` — the
2026-06-07 saga); the per-query cap and the cgroup limit guard the pod.
Serving scenarios sweep concurrency 1 / 4 / 8 × 60 iterations; raw-vault
`adhoc` scenarios run **c=1 × 2 iterations** — at X5 a single recompute runs
for minutes (below), so a concurrency sweep would measure nothing but a queue.

## Results (X5, 2026-06-07 — final gating run)

| Scenario | Class | c=1 p99 | c=4 p99 | c=8 p99 | c=8 QPS | Verdict |
|----------|-------|--------:|--------:|--------:|--------:|---------|
| `01_branch_pnl_adhoc` — live `bv_order_canonical` recompute | adhoc | **238 s** | — | — | — | INFO |
| `02_top_products_adhoc` — `lnk_order_product` ⋈ `hub_order` top-N | adhoc | **102 s** | — | — | — | INFO |
| `03_customer360_point` — single-row mart lookup by `customer_bk` | point | 42 ms | 100 ms | 197 ms | 44.3 | PASS |
| `04_returns_velocity` — mart aggregation | heavy | 108 ms | 92 ms | 141 ms | 62* | PASS |
| `05_line_items_reach_adhoc` — 45.8M-row join + `uniq` | adhoc | **294 s** | — | — | — | INFO |
| `06_branch_pnl_mart` — **materialized** `marts.branch_pnl` | heavy | 20 ms | 72 ms | 293 ms | 41.3 | PASS |

Budgets: point p99 ≤ 250 ms, heavy p99 ≤ 1000 ms, adhoc p99 ≤ 2000 ms (adhoc
is informational — reported, never gates). `LOAD TEST: PASS`.

\* between-run variance on this shared 2-vCPU host is ~2× on sibling cells
(e.g. 04 c=8 p99 ranged 141→396 ms across four captures the same day); single
cells are indicative, the gate verdicts were stable across runs once the real
findings below were fixed.

## What the X5 run surfaced (three real findings)

**1. `customer_360` had the wrong sort key for its serving pattern.** The
mart was `ORDER BY (branch, customer_hk)`, but its point query — and the
realistic serving access — looks up by **`customer_bk`**, which was not in
the key at all: every lookup full-scanned the 402K-row mart. At the synthetic
800 rows this was invisible; at X5 it was p99 250–468 ms vs the 200 ms point
budget. Fixed in the dbt model: `ORDER BY (customer_bk, branch)` +
`index_granularity 1024` (a point lookup now reads one ~1K-row granule)
→ p99 42 / 100 / 197 ms at c=1/4/8.

**2. Exact distinct at X5 is not an interactive query on this host.**
`05_line_items_reach` used `uniqExact(order_hk)` over 45.8M rows — the state
holds every one of 8M keys and needs > 3 GiB even with spill; it OOM'd its
per-query cap at every setting tried. Switched to `uniq()` (HyperLogLog,
~KB per group, ~1% error): completes in ~5 min as a capacity reference.
The exact-count use case belongs in a mart or an offline job.

**3. The point budget is a queueing budget at c=8 on 2 vCPU.** With the sort
key fixed, c=1 p99 is 42 ms but c=8 p50 is ~127 ms with QPS plateaued from
c=4 — past the box's concurrency design point, p99 measures the queue, not
the data path. Budget moved 200 → 250 ms with the rationale recorded in
`load-test/job.yaml`; the pre-fix full-scan regression (276–468 ms at c=1/4)
would still fail it.

## Architecture takeaway — the X5 numbers ARE the pitch

The same business question (branch P&L):

- **materialized mart** (`06`): p99 **20 ms** at c=1, still ≤ 293 ms with 8
  concurrent clients;
- **live raw-vault recompute** (`01`): **238 seconds** for a single client —
  a ~10,000× gap, and it only runs at all with hand-tuned spill settings.

At the 10K synthetic seed this gap was 3–9×; real volume widened it by three
orders of magnitude. Materialization is the serving path; the live view is an
exploration/debug convenience. The speed comes from **materialization**, not
from dbt: `marts.*` are physical `MergeTree` tables sorted for their access
pattern, the expensive UNION ALL + argMax SCD2 collapse + joins are paid once
at build time — by the staged loader for `bv_order_canonical_mat`
(`warehouse/agentflow/dv2/business_vault/load_bv_order_canonical_mat.sh`) and
by dbt for the marts (dependency DAG, tests, docs). dbt contributes
reproducibility and testability; the latency comes from the physical layout.

The mart build itself tells the same story: against the live view the three
dbt marts OOM'd four runs in a row at X5; against the materialized canonical
they build in **4–14 seconds each** with 12/12 tests green on the same 5Gi
pod.

## Previous capture (2026-06-02, synthetic 10K seed)

Kept for contrast; budgets then: point ≤ 200 ms.

| Scenario | c=1 p99 | c=4 p99 | c=8 p99 | c=8 QPS | Verdict |
|----------|--------:|--------:|--------:|--------:|---------|
| `01_branch_pnl_adhoc` | 302 ms | 530 ms | 886 ms | 11.8 | PASS (info) |
| `02_top_products` | 115 ms | 148 ms | 421 ms | 36.5 | PASS |
| `03_customer360_point` | 38 ms | 77 ms | 70 ms | 122 | PASS |
| `04_returns_velocity` | 50 ms | 72 ms | 92 ms | 94 | PASS |
| `05_line_items_reach` | 275 ms | 397 ms | 310 ms | 45.8 | PASS |
| `06_branch_pnl_mart` | 61 ms | 68 ms | 97 ms | 91.7 | PASS |

That capture's two findings (pod memory limit was the ceiling, not the VM;
the live 5-join view needs frugal join settings under load) are preserved in
git history and remain true — the X5 capture extends both.

## Re-run / refresh

```bash
bash infrastructure/dv2/load-test/apply.sh
```
