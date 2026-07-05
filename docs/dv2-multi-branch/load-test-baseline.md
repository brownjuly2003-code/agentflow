# DV2.0 ClickHouse load test — baseline

Captured **2026-06-02** against the `hq-demo` kind cluster on the iMac demo
host, **synthetic demo seed** (~10K orders across 5 branches). Harness:
[`infrastructure/dv2/load-test/`](../../infrastructure/dv2/load-test/) —
`clickhouse-benchmark` run as a Kubernetes Job in namespace `dv2`, driving
the in-cluster `clickhouse` service over the native protocol (9000).

VM at capture time: 6 GiB RAM, 2 vCPU; ClickHouse pod limit 5 Gi. Budgets at
capture time: point p99 ≤ 200 ms (since moved to 250 ms — see finding 3
below), heavy p99 ≤ 1000 ms, adhoc p99 ≤ 2000 ms (adhoc is informational —
reported, never gates).

> **Refresh pending.** This capture predates the 2026-07-03 legend reset
> (kitchen-appliance wholesaler seed). Re-run `apply.sh` on the Mac demo
> host against the current seed and replace the table below; harness
> mechanics and budgets are unchanged.

## Results (synthetic seed, 2026-06-02)

| Scenario | c=1 p99 | c=4 p99 | c=8 p99 | c=8 QPS | Verdict |
|----------|--------:|--------:|--------:|--------:|---------|
| `01_branch_pnl_adhoc` | 302 ms | 530 ms | 886 ms | 11.8 | PASS (info) |
| `02_top_products` | 115 ms | 148 ms | 421 ms | 36.5 | PASS |
| `03_customer360_point` | 38 ms | 77 ms | 70 ms | 122 | PASS |
| `04_returns_velocity` | 50 ms | 72 ms | 92 ms | 94 | PASS |
| `05_line_items_reach` | 275 ms | 397 ms | 310 ms | 45.8 | PASS |
| `06_branch_pnl_mart` | 61 ms | 68 ms | 97 ms | 91.7 | PASS |

Scenarios `02` and `05` have since been reclassified as informational
`*_adhoc` scenarios (c=1 only); the next capture will report them that way.
This capture's two findings (pod memory limit was the ceiling, not the VM;
the live 5-join view needs frugal join settings under load) are preserved in
git history.

Even at seed scale the mart-vs-live-view boundary is measurable: the same
business question (branch P&L) answers 3–9× faster off the materialized
`marts.branch_pnl` (`06`) than through the live `rv.bv_order_canonical`
recompute (`01`), and the gap widens superlinearly with volume. The
materialized mart is the serving path; the live view is an exploration/debug
convenience.

## Retired at-scale capture (2026-06-07)

A one-off capture against a bulk public seed dataset (tens of millions of
raw-vault rows; dataset and loader retired with the 2026-07-03 legend reset)
ran on this same harness. The full report lives in the git history of this
file. Its three engineering findings are permanent and survive in the
current code:

1. **`customer_360` had the wrong sort key for its serving pattern.** The
   mart was `ORDER BY (branch, customer_hk)` while its point query looks up
   by `customer_bk` — invisible at seed scale, a full mart scan at volume
   (p99 250–468 ms vs the then-200 ms budget). Fixed in the dbt model:
   `ORDER BY (customer_bk, branch)` + `index_granularity 1024` (a point
   lookup reads one ~1K-row granule).
2. **Exact distinct is not an interactive query at volume.**
   `05_line_items_reach` originally used `uniqExact(order_hk)`; the state
   OOM'd its per-query cap at every setting tried. Switched to `uniq()`
   (HyperLogLog, ~KB per group, ~1 % error). The exact-count use case
   belongs in a mart or an offline job.
3. **The point budget is a queueing budget at c=8 on 2 vCPU.** Past the
   box's concurrency design point, p99 measures the queue, not the data
   path. The point budget moved 200 → 250 ms with the rationale recorded in
   `load-test/job.yaml`; the pre-fix full-scan regression (276–468 ms)
   would still fail it.

## Re-run / refresh

```bash
bash infrastructure/dv2/load-test/apply.sh
```
