# S2a decision — fate of the "45.8M" X5-scale load benchmark

**Decision: RETIRE the at-scale benchmark as historical. Keep the load-test
harness alive at synthetic-seed scale. No synthetic bulk generator is built.**

- Date: 2026-07-05 · Step: S2a of `new_plen_05_07_26.md` · Decider: Fable 5
  (authority delegated per plan §4.3; git-revertable call).
- Scope: resolves the G2 audit's "Открытый вопрос" (load/benchmark at X5
  scale). The X5 loader removal itself is S2b's task regardless; this doc
  fixes the benchmark-scale sub-decision and gives S2b a mechanical
  disposition list.
- **This file is a process document.** It intentionally contains the string
  "X5" (paths, instructions). **S2b MUST delete this file in its final
  commit** so the S8 gate `grep -ri x5` (clean outside CHANGELOG.md) passes.
  The decision record survives in git history and the PR.

---

## 1. The decision and why

**Retire.** The 2026-06-07 "45.8M line items / 8.06M orders" ClickHouse
capture is retired as a historical, no-longer-reproducible event. The
load-test harness (`infrastructure/dv2/load-test/` — queries, `run-bench.sh`,
`job.yaml`, `apply.sh`) stays fully runnable and gating, against the
synthetic kitchen seed. No 45.8M-row kitchen generator is built, now or later.

**Legend-fit.** The kitchen legend deliberately walked away from volume:
`docs/generator-spec.md` states the demo's value "lives in customers, PII,
loyalty, shipments and B2B orders, not in marketplace order volume", and §11
pins the DV2 seed at ~10K orders / ~14.6K `lnk_order_product` rows. The legend
company does ~2,800 orders/day; 45.8M line items would imply decades of
history. A generator forcing kitchen-appliance data to grocery-retailer scale
would manufacture exactly the kind of fake-scale story the 2026-07-03 legend
reset removed (`demo_evidence.md` already retired the "1.1 s over 8.06M X5
rows" claim).

**Nobody runs it.** The DV2 bench is not wired into CI —
`.github/workflows/load-test.yml` is the unrelated API-tier locust/DuckDB
gate. The DV2 bench is a manual `apply.sh` against the Mac kind cluster
(`hq-demo`), Docker/Mac-only, and the only planned future run is S6's
re-capture. A multi-day at-scale generator build (generate ~46M rows, load
them for hours onto a 2-vCPU/6-GiB VM, re-tune spill settings, re-capture)
would exist solely to keep one doc's headline number.

**Honesty.** With the dataset deleted, the 45.8M numbers become
unreproducible. Presenting them as the *current* baseline would violate the
project's own evidence discipline. The three engineering findings the at-scale
run produced are already banked in code (`customer_360` sort key, `uniq()` vs
`uniqExact()`, the 250 ms point budget) and keep their de-branded rationale;
the full report survives in git history.

**What is NOT lost.** The mart-vs-live-view boundary — the load test's whole
point — is measurable at seed scale too: the 2026-06-02 synthetic capture
(same harness, PASS) already showed a 3–9× gap. S6 re-captures on the kitchen
seed and that becomes the standing baseline.

## 2. File dispositions — load-test / benchmark scope (S2b executes)

### 2.1 DELETE (no replacement)

| Path | Action |
|---|---|
| `warehouse/agentflow/dv2/loaders/x5_retail_hero/` (all: `__init__.py`, `loader.py`, `mappers.py`, `schemas.py`, `branch_distributor.py`, `README.md`, `requirements.txt`) | Delete the package. **No successor generator** — that is this decision. Demo-scale data is already covered by `warehouse/agentflow/dv2/synthetic_seed.sql` + `satellite_seed_all_branches.sql`, the kitchen live generator in `src/ingestion/`, and `reference/load_postgres.py`. |
| `tests/unit/test_x5_retail_hero_loader.py` | Delete. |
| `x5-benchmark-decision.md` (this file) | Delete in S2b's final commit. |

### 2.2 KEEP + edit comments only (exact replacement text in §3)

| Path | Action |
|---|---|
| `infrastructure/dv2/load-test/run-bench.sh` | Keep. One comment edit (lines 52–54). Mechanics unchanged, incl. adhoc c=1×2 special-casing (harmless at seed scale; informational anyway). |
| `infrastructure/dv2/load-test/job.yaml` | Keep, incl. `P99_MS_POINT: "250"` (queueing rationale is host-bound — 2 vCPU — not data-bound). Two comment edits (lines 49–50 and 55–60). |
| `infrastructure/dv2/load-test/README.md` | Keep. Replace the closing "Baseline numbers" paragraph (lines 79–81). Also fix two stale scenario filenames in the table: `02_top_products.sql` → `02_top_products_adhoc.sql` (class `adhoc`), `05_line_items_reach.sql` → `05_line_items_reach_adhoc.sql` (class `adhoc`); note in the class cell that adhoc is informational, c=1 only. |
| `docs/dv2-multi-branch/load-test-baseline.md` | **Rewrite entirely** with the ready-made content in §4. |

### 2.3 NO ACTION (verified X5-free at 63a585f)

- `infrastructure/dv2/load-test/queries/*.sql`, `infrastructure/dv2/load-test/apply.sh`
- `docs/benchmark.md`, `docs/benchmark_pool16.md`, `docs/benchmark_pool16_60s.md`, `docs/benchmark_pool24_60s.md`, `docs/freshness-benchmark.md` — API-tier benchmark family; the audit's "docs/benchmark*.md" line was over-broad, zero X5 content.
- `docs/runbooks/load-test-regression.md`, `.github/workflows/load-test.yml`, `tests/load/` — API-tier.
- `docs/dataflow.html` — already de-branded in commit 63a585f (M2); verified clean.

### 2.4 Overlap notes — files S2b de-brands anyway; benchmark-specific guidance

| Path | Guidance from this decision |
|---|---|
| `warehouse/agentflow/dv2/dbt/models/sources.yml:21`, `dbt/README.md:26`, `dbt/profiles.example.yml:12` | Replace "at X5 scale (8M orders)" with scale-neutral "at large raw-vault volumes". Do **not** invent a kitchen-legend 8M equivalent. `threads: 1` and its memory rationale stay. |
| `warehouse/agentflow/dv2/spec.yaml` (~742–807, 5× "1c (X5 Retail Hero)") | → "1c (branch order feed)" per `domain.md` §5.3. No scale claims. |
| `docs/dv2-multi-branch/schema_dv2.md` lines 7, 185–187, 192 (m9) | Remove "45.8 млн строк" / "45М транзакций"; re-point the Sources table to the synthetic seed / `mp__` feed. No at-scale row counts survive anywhere. |
| `docs/dv2-multi-branch/demo_evidence.md` | De-brand the "X5-era" flags (suggest "retired-seed-era"); the sentence about the retired "1.1 s over 8.06M X5 rows" block keeps its meaning, loses the brand and numbers. Pending-Mac sections get refreshed at **kitchen-seed scale** in S6 — there will never be an at-scale re-capture. |
| `docs/domain.md` §5.4 | The clause "Dataset attribution stays in the loader README" is void (Julia's override: X5 nowhere except CHANGELOG). No "high-volume external dataset replay" framing survives. |
| `warehouse/agentflow/dv2/loaders/pg_vault_writer.py` (docstring ~line 22) | Reword "guarded exactly the way the X5 loader guards" → "guarded the same way the other DV2 loaders guard the optional driver import". |
| `warehouse/agentflow/dv2/reference/vault_mapping.py` (docstring lines 3–6, comment line 41) | With the loader gone, `vault_mapping`'s own `_canonical`/`md5_digest`/`composite_md5_digest` become the canonical definition. Reword to describe the convention itself (MD5 of canonicalised value, `"||"` joiner, `key=value` sorted for hash_diff) instead of referencing the X5 loader. |
| `CHANGELOG.md` | Untouched by S2a. S2b adds an `[Unreleased]` entry recording the loader removal and benchmark retirement — CHANGELOG is the one sanctioned place where "X5 Retail Hero" may appear. |

### 2.5 Dependency discoveries the audit's file list missed (S2b must handle)

1. **`tests/unit/test_dv2_postgres_ingestion.py` (549 lines) functionally
   imports the X5 package** (`loader`, `schemas as x5`) and is the **only**
   test coverage for `PostgresVaultWriter` — which stays (used by the live
   `postgres_oltp/freshness_listener.py` and `reference/load_postgres.py`).
   Do not delete the file. Surgical edit: (a) keep the `PostgresVaultWriter`
   test section by replacing `x5.HubCustomer`-based fixtures with equivalent
   pydantic row models; (b) the DDL-column-coverage tests
   (`test_x5_insert_columns_exist_in_postgres_ddl` parametrization) pin the
   standing Postgres DDL and are worth keeping — recommended: relocate the
   vault-generic row models (`VaultRow`, `Hub*`, `Link*`, `SatOrderHeader`,
   `SatOrderPricing`, `SatLinkOrderProduct`) from `x5_retail_hero/schemas.py`
   into a neutral module, e.g. `warehouse/agentflow/dv2/loaders/vault_rows.py`,
   and re-point both the tests and any remaining users; (c) the loader-sink
   tests (`_open_sink` / `_DryRunSink` / `_PostgresSink` / `_ClickHouseSink`)
   die with the loader — delete them. The grocery-shaped models
   (`SatCustomerPersonal`, `SatProductCatalog`) are part of the loader-removal
   scope, not the benchmark scope; their fate follows S2b's schema handling.
2. **`tests/unit/test_dv2_supplier_reference.py` imports
   `x5_retail_hero.mappers` (`md5_digest`, `composite_md5_digest`)** to pin
   hash-equality between the reference loader and the X5 loader. Replace the
   equality assertions with self-contained expected-digest fixtures
   (precomputed hex digests of known inputs) pinning `vault_mapping`'s own
   functions, or drop only the x5-equality parametrization; keep the rest of
   the file.

## 3. Ready-made comment replacements (§2.2)

`infrastructure/dv2/load-test/run-bench.sh`, replace lines 52–54:

```
    # At large raw-vault volumes a single live-view recompute can run for
    # minutes on the 2-vCPU demo host — adhoc scenarios therefore sweep
    # c=1 only, with their own (small) iteration count.
```

`infrastructure/dv2/load-test/job.yaml`, replace the comment at lines 49–50:

```
            # adhoc (raw-vault capacity reference) scenarios can run minutes
            # per query at large volumes — c=1 only, two iterations (see
            # run-bench.sh).
```

`infrastructure/dv2/load-test/job.yaml`, replace the comment at lines 55–60:

```
            # 250 (was 200) for the 2-vCPU demo host: at c=8 the box is past
            # its concurrency design point and p99 measures queueing, not the
            # data path (established by a retired at-scale capture — see the
            # git history of docs/dv2-multi-branch/load-test-baseline.md;
            # ambient variance between runs is ~2x on sibling scenarios).
            # The gate still catches real regressions: the pre-fix full-scan
            # lookup ran 276-468 ms.
```

`infrastructure/dv2/load-test/README.md`, replace lines 79–81 (the text after
"Captured results live in […] load-test-baseline.md).") with:

```
The current baseline is against the synthetic demo seed (~10K orders). An
earlier at-scale capture (tens of millions of raw-vault rows, retired with
the 2026-07-03 legend reset) is preserved in the git history of that file;
its three engineering findings are summarized there.
```

## 4. Ready-made full replacement for `docs/dv2-multi-branch/load-test-baseline.md`

Replace the entire file content with:

````markdown
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
````

## 5. Consequences for later plan steps

- **S6 ("live-бенчмарк по итогу S2")** = run
  `bash infrastructure/dv2/load-test/apply.sh` on the Mac kind cluster
  against the current kitchen seed, then replace the 2026-06-02 table in
  `load-test-baseline.md` with the fresh capture (same budgets; `02`/`05`
  will report as adhoc c=1 INFO rows). Nothing at scale is ever re-run.
- **S8 re-audit**: after S2b (including deleting this file), `grep -ri x5`
  outside `CHANGELOG.md` must be clean; the strings "45.8", "8.06M", "402K"
  and "Retail Hero" should also be gone outside CHANGELOG and git history.
- **Out of scope / do not touch** (S1 owns their currency/catalog logic, in
  flight): `contracts/entities/product.yaml`, `contracts/entities/user.yaml`,
  `docker/postgres-source/init.sql`, `scripts/nl_sql_eval/dataset.py`,
  `scripts/nl_sql_eval/warehouse.py`, `scripts/run_benchmark.py`,
  `tests/load/run_load_test.py`. Nothing in this decision depends on them:
  the retained DV2 bench needs no Python generator at all.
