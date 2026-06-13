# DV2.0 — Session Handoff 2026-06-02

## ✅ UPDATE 2026-06-07 — plan B EXECUTED: mat loaded 5/5, dbt marts green at X5, marts load-tested

Plan B (staged materialization, see the 2026-06-06 section below) is done
end-to-end:

- **`rv.bv_order_canonical_mat` loaded clean, all 5 branches in 11.5 min,
  zero retries** (run 15 of `~/bv_mat_load15.log` on the iMac): msk 3,225,686 /
  spb 2,016,186 / ekb 1,202,248 / dxb 814,334 / ala 796,767 — exactly the
  2026-06-06 view audit counts + the 10K synthetic seed (40/25/15/10/10),
  revenue matches per branch to the kopeck.
- **dbt at X5: 3/3 marts in seconds + 12/12 tests** (branch_pnl 4-6s,
  customer_360 10-14s, returns_velocity 6-8s) — the same DAG that OOM'd four
  times on 2026-06-06 against the live view.
- **Why 8 loader runs failed before run 15** (each fix evidence-based, all
  committed): (1) nohup env without kubectl in PATH; (2) `delete pod
  --wait=false` meant stage queries ran against the TERMINATING server inside
  its 30s grace window; (3) the decisive one — ClickHouse server-level memory
  accounting on this stack (Lima VM + jemalloc + CH 25.5) is broken three
  ways: the memory worker imports garbage `jemalloc stats.resident`
  (sampled 274→4241→956 MiB in 6 s while OS VmRSS never exceeded 1.06 GiB),
  the cgroup reader counts reclaimable page cache, and correction-off drifts.
  **Resolution: server-level limit disabled** (`max_server_memory_usage` 100
  GiB sentinel + `max_server_memory_usage_to_ram_ratio` 20 to defeat the
  startup clamp); safety = per-query `max_memory_usage` (honest accounting,
  87-880 MiB peaks) + the 5Gi cgroup pod limit. `MALLOC_CONF
  dirty_decay_ms:0` keeps real RSS ≈ allocated. Full story in the
  `clickhouse-sts.yaml` ConfigMap comments.
- **Load test at X5 re-shaped and re-captured** (see
  `load-test-baseline.md`): raw-vault recomputes (01, 02, 05) reclassified as
  non-gating `adhoc` capacity references at c=1×2 iterations — at X5 they run
  80-350 s/query on the 2-vCPU host, which IS the demo argument for the mat
  path. 05 switched `uniqExact`→`uniq` (exact distinct of 8M keys needs >3
  GiB, off-box territory). Serving gates stay on the marts: two real X5
  findings fixed — `customer_360` sort key was `(branch, customer_hk)` so the
  bk point lookup full-scanned the mart (p99 250-468 ms → fixed to
  `(customer_bk, branch)` + `index_granularity` 1024 → p99 42/100/197 ms at
  c=1/4/8), and the point budget moved 200→250 ms for c=8 on a 2-vCPU host
  (queueing, not data path; rationale in `load-test/job.yaml`). Final gating
  run: **`LOAD TEST: PASS`** (full capture in `load-test-baseline.md`).
- Loader hardening committed: `fresh_server` waits for the real pod
  replacement + condition-based settle (`MemoryTracking` < 1.5 GiB with
  jemalloc purges) instead of fixed sleeps.

Commits this session: `d306444` (loader + sts memory saga), `b6194a0`
(marts → mat), plus the load-test/mart-tuning/docs commit on top.
Remaining: PR — push/PR is gated on the operator.

## ✅ UPDATE 2026-06-06 — option A EXECUTING: cluster rebuilt with merge throttle, full re-load RUNNING

Operator chose **option A** (re-load with merges ON but bounded). Executed
2026-06-06 afternoon:

1. **Committed ConfigMap had a startup bug** — CH 25.5 fails its
   `MergeTreeSettingsImpl::sanityCheck` with `background_pool_size=2` because
   `number_of_free_entries_in_pool_to_execute_mutation` (20) and
   `..._to_lower_max_size_of_merge` (8) exceed the tiny pool → crash-loop on
   boot. Fixed in `c98ace0` (pins those + `..._execute_optimize_entire_partition`).
2. Old unserveable PVC `data-clickhouse-0` (`pvc-24cc28ae…`, tens of thousands
   of parts) **deleted**; fresh PVC `pvc-440543a2…` created by the sts.
   `postgres`/`minio`/`argo` stay at replicas=0 during the load.
3. New sts + merge-throttle ConfigMap applied; settings verified live in
   `system.merge_tree_settings` (pool=2, merge cap 1.5G, delay 2000/throw 5000).
4. Full DDL re-applied from the branch tree (init, hubs, links, satellites,
   business_vault) + synthetic seed: 66 objects in `rv`, `hub_order`=10000,
   `bv_order_canonical`=10000.
5. Loader unit tests passed on the Mac py3.13 (3/3, incl. PartsThrottle).
6. **Full X5 re-load launched** with backpressure:
   `--batch-size 50000 --max-active-parts 1500 --load-ts 2026-06-06T00:00:00Z`,
   log `~/x5_full_load_optA.log`. Early health: ~9 active parts, CH cgroup
   0.34 GiB.

Gotcha: AdGuard VPN **on the Windows side** kills long LAN SSH sessions —
`Stop-Service "Adguard VPN Service"` before babysitting the load.

### RESULT (2026-06-06 evening): option A SUCCEEDED — load clean, COLD RESTART PASSES

- Load finished **clean in 2:15:47** (916/916 purchase chunks, 0 errors/tracebacks
  in `~/x5_full_load_optA.log`; note: this run logs no `FULL_EXIT` marker — check
  the per-table "inserted N rows" summary block instead).
- Inserted: `lnk_order_product` 45,786,568; `hub_order` 8,045,985;
  branch sats msk 3.22M / spb 2.01M / ekb 1.20M / dxb 0.81M / ala 0.80M.
- Post-load state: **98 active parts, 3.48 GiB on disk** (PVC 5Gi) — the
  backpressure held the whole run (peak ~101 active parts, CH cgroup ≤ ~2.1 GiB).
- **COLD-RESTART GATE PASSED**: `kubectl delete pod clickhouse-0` → Ready →
  first `SELECT 1` answered on try 1 (~25 s after Ready). This was the failure
  mode that killed the 2026-06-02 load (crash-loop on part-metadata OOM).
- Counts after restart (ReplacingMergeTree converging, incl. 10K synthetic seed):
  `hub_order` 8,055,233 · `lnk_order_product` 45,811,505 · `hub_customer` 402,162.
- **Branch split on real X5 via `bv_order_canonical`** (orders / revenue):
  msk 3,221,691 / 1.380B; spb 2,013,691 / 864.7M; ekb 1,200,748 / 512.5M;
  dxb 813,336 / 349.5M; ala 795,767 / 337.9M. Full argMax scan: 1m52s
  (mart-build query, not interactive).
- Verify script for re-runs: `~/x5_optionA/postload_verify.sh` on the iMac
  (use `kubectl exec -i` for piped SQL — without `-i` queries silently no-op).

### dbt marts at X5 scale: 4 runs failed → STOP infra-tuning; next = staged materialization (plan B)

All four 2026-06-06 evening dbt runs failed with CH `Code: 241` (memory), each
revealing a distinct layer (all fixes are committed and live in the cluster):

1. **v1** — per-query OOM in `branch_pnl`; root: `bv_order_canonical` argMax
   view aggregates 8M+ order keys. → users.d spill profile (`9a53720`).
2. **v2** — server-TOTAL tracker (RSS 4.5/4.5, OvercommitTracker kills all):
   default **5 GB mark cache** pinned RSS after full X5 scans. → cache caps
   256/64/256 MiB (`93b3df1`).
3. **v3** — models 1+2 started in the same second: `threads: 2` lives in the
   **Job's inline profiles.yml heredoc** (`dbt-run-job.yaml`), the earlier
   `profiles.example.yml` fix silently no-oped. → threads=1 in the Job +
   query cap 3 GiB (`143967a`).
4. **v4** — serial confirmed, but **each mart alone** exceeds 3 GiB: the argMax
   view (8M keys × ~15 String agg-states) is re-computed inside every mart;
   external GROUP BY spill does not bound the arena growth enough.

**Plan B (next session, do NOT retry tuning):** materialize the canonical once,
then point the marts at the table:
- `CREATE TABLE rv.bv_order_canonical_mat (... same columns ...) ENGINE =
  MergeTree ORDER BY (branch, order_bk)` + **5 staged inserts**
  `INSERT INTO ... SELECT * FROM rv.bv_order_canonical WHERE branch = '<b>'`
  (largest branch msk ≈ 3.2M orders ≈ 40% of the working set → ~1.5-2 GiB,
  fits the 3 GiB cap; the manual full-view scan needed ~4+ GiB).
- Switch `dbt/models/sources.yml` (or the three mart FROMs) to the mat table;
  re-run the dbt Job (threads=1 path is fixed); then `dbt test`.
- Then: load-test Job (`infrastructure/dv2/load-test/apply.sh`), refresh
  `load-test-baseline.md` + `demo_evidence.md`/`pitch.md` real-X5 numbers, PR.

Cluster is left RUNNING and healthy (CH up, 98 parts, cold-start-safe; pg/minio/
argo still at 0). Staged files live on the iMac at `~/x5_optionA/`. Windows-side
note: "Adguard VPN Service" was stopped for the LAN SSH work — re-enable
manually if needed (long-lived ssh sessions to the Mac die either way; use
short probes in a loop, pattern in this session's monitors).

Branch: `feat/dv2-x5-real-data` (off `main`). Two themes: **(1)** VM/cluster
capacity + a Kubernetes-native load test; **(2)** wiring the X5 Retail Hero
loader through to the marts (option B), then loading the full 45.8M rows.

## ⚠️ STATE AT HANDOFF (UPDATED 2026-06-02 evening) — load DONE, but full dataset HITS A HARD 8GB-iMac CEILING; cluster PARKED at replicas=0, data SAFE on PVC

**Load finished cleanly** (`FULL_EXIT=0` in `~/x5_full_load.log`). Raw row counts
(pre-dedup, merges were off): `hub_order` 8.70M, `lnk_order_product` 49.41M (~45.8M
after dedup), `lnk_order_customer` 8.65M, `lnk_order_store` 8.69M.

**The "re-enable merges" plan below is NOT achievable on this host as written.**
A 2026-06-02-evening session executed it and discovered a hard hardware ceiling:

1. `SYSTEM START MERGES` succeeded, but within ~8 s the merges drove ClickHouse to
   its 5 Gi cgroup limit and **starved the kube control plane** (apiserver TLS-handshake
   timeout). The 8 GB-physical / 5.8 GiB-VM cannot run merges on this 49M-row,
   tens-of-thousands-of-parts dataset while keeping the control plane alive.
2. A clean VM stop/start to recover then revealed a **deeper ceiling**: ClickHouse
   **cannot even cold-start** with this part set. On boot it loads all parts'
   in-memory metadata, pins ~5.8 GiB, gets **OOM-killed at the 5 Gi cgroup limit, and
   crash-loops** (observed: mem climbs 1.4→3.6→5.9 GiB → pod restart → repeat).
   Part-metadata load is largely **untracked** by `max_server_memory_usage`, so it
   blows past the soft cap into hard cgroup-OOM. Lowering the limit kills it sooner;
   raising it is impossible (host is 5.8 GiB). Before the restart CH had been **warm**
   (loaded incrementally during the insert) so it had served `count()` queries — a cold
   start cannot reproduce that.
3. Shedding RAM (scaled `postgres`/`minio`/`argo` to 0) did **not** help: CH alone
   cold-loading the parts still exceeds host RAM.

**Root cause:** the no-merge bulk-load (`SYSTEM STOP MERGES` for the *whole* load)
created tens of thousands of parts, more than an 8 GB host can hold metadata for at
cold start. Merges would collapse them but merges OOM the host — a catch-22 on this
hardware.

**Current state (left stable on purpose):** `clickhouse`/`postgres`/`minio` StatefulSets
and `argo` deployments are **scaled to 0**; the 3 kind nodes are `Ready`, apiserver is
responsive, host mem ~1.3 GiB used / ~4.7 GiB free. **No data lost** — `data-clickhouse-0`
PVC (5 Gi, `pvc-24cc28ae…`) is `Bound` and intact. The cluster is parked, not broken.

### Recovery options for next session (pick one; do NOT just re-run `SYSTEM START MERGES`)
- **A — re-load smarter (cleanest):** rebuild/clear `rv.*` and re-run the loader with
  merges **throttled, not fully off** — keep `SYSTEM START MERGES` on but set a small
  `background_pool_size` (e.g. 2) and keep `max_bytes_to_merge_at_max_space_in_pool`
  low. Part count stays bounded during load → CH can cold-start and the dataset stays
  serveable. Best long-term fix; needs a re-load.
- **B — rescue current on-disk data (needs explicit go; data-adjacent):** before
  starting CH, move the giant `lnk_order_product` (and other high-part tables) data
  directories aside on the PVC so CH boots with far fewer parts, bring CH up, then
  `OPTIMIZE` / re-attach incrementally. The **P&L marts do not need `lnk_order_product`**
  (`branch_pnl` ← `bv_order_canonical` ← order-header + pricing satellites), so the
  financial demo can come up on real X5 data without the 49M line-items link.
- **C — bigger ClickHouse host:** the 8 GB iMac is the ceiling. Out of budget (no cloud card).
- **D — keep the demo synthetic:** `bootstrap.sh` + synthetic seed already reproduce the
  full DV2 demo within RAM; the real-45.8M load is an ambitious extension that can be
  parked. The committed artifacts (DDL, manifests, marts SQL, screencasts) are unaffected.

`bv_order_canonical` uses `argMax`, so once CH can serve, the *view* is correct even
with un-collapsed duplicate parts; only clean raw hub/link `count()`s need merges done.

### Check load status / restart loader (still valid for a re-load)
```bash
ssh julia@192.168.1.133 'pgrep -fl loader.py || echo "loader done"; grep -E "FULL_EXIT|Code:" ~/x5_full_load.log | tail'
```
If re-loading (option A), the loader command below is restart-safe; `argMax`/ReplacingMergeTree
dedup repeated rows.

## Config changes made this session (cluster is in this state NOW)
- VM (Lima `docker`, vz, iMac): RAM 4→**6 GiB**, disk 20→**60 GiB**, **+16 GiB swap**
  (`/swapfile`, persisted in `/etc/fstab`). Full VM-disk backup: `~/.lima/docker/disk.bak-20260602`.
  (iMac has **8 GB physical RAM total** — that is the hard ceiling; swap covers overflow.)
- ClickHouse pod memory limit **1500Mi→3Gi→5Gi** (`infrastructure/dv2/clickhouse-sts.yaml`,
  committed at 5Gi). CH self-caps at 0.9×limit ≈ 4.5 GiB.
- Per-table (17 X5-volume tables): `max_bytes_to_merge_at_max_space_in_pool=1.5GB`,
  `parts_to_throw_insert=50000`, `parts_to_delay_insert=50000`, `max_parts_in_total=200000`
  (set via `ALTER TABLE MODIFY SETTING` — live, NOT in repo DDL; reapply if cluster rebuilt).
- **`SYSTEM STOP MERGES`** was the load-time setting; it is now moot — the cluster is
  parked at `replicas=0` (see UPDATED state block above). It resets to default (merges ON)
  whenever CH next starts, which is exactly why a naive cold start crash-loops.

## Loader run command (restart-safe)
```bash
ssh julia@192.168.1.133 'export PATH=$HOME/lima/bin:$HOME/bin:$PATH
  pgrep -f "port-forward.*clickhouse" || (nohup kubectl port-forward -n dv2 svc/clickhouse 9000:9000 >/tmp/pf.log 2>&1 & disown; sleep 5)
  cd ~/x5_loader/x5_retail_hero
  nohup /usr/local/bin/python3.13 loader.py --csv-dir ~/x5 --clickhouse-host localhost --clickhouse-port 9000 --clickhouse-password demo --batch-size 50000 --load-ts 2026-06-02T00:00:00Z > ~/x5_full_load.log 2>&1 & disown'
```
`/usr/local/bin/python3.13` (system py3.9 lacks `datetime.UTC`); CSVs in `~/x5/`;
connects via Mac-local `kubectl port-forward svc/clickhouse 9000` (`nohup`, `/tmp/pf.log`).

## TODO — gated on a recovery option (A/B/C/D above) being chosen first
Once CH can actually *serve* the real X5 data (option A re-load, or option B rescue):
1. **Verify counts**: `hub_order`, `lnk_order_product` (~45.8M), branch split via
   `bv_order_canonical` (`SELECT branch,count(),sum(total_amount) ... WHERE order_bk LIKE '1c__%' GROUP BY branch`).
   Use `FINAL`/`argMax` for logical counts if parts are not yet merged.
2. **Refresh `branch_pnl` mart** — dbt-materialized *table*, does NOT auto-update.
   Re-run dbt (`infrastructure/dv2/dbt/dbt-run-job.yaml`).
3. **Re-run load test** on real volume: `bash infrastructure/dv2/load-test/apply.sh`;
   refresh `docs/dv2-multi-branch/load-test-baseline.md` (committed baseline is synthetic).
4. **Refresh `demo_evidence.md` / `pitch.md`** with real X5 counts.
5. **PR** `feat/dv2-x5-real-data` → main.

> Do not attempt steps 1–5 before the cold-start ceiling is resolved — `SYSTEM START MERGES`
> on the current on-disk part set OOMs the host (proven 2026-06-02 evening).

## What was DONE and COMMITTED this session
- Capacity + **k8s-native load test** `infrastructure/dv2/load-test/` (clickhouse-benchmark
  Job, p99 gates) + baseline doc. CH pod memory raised.
- **X5 integration (option B, Codex plan, bounded)** — the loader had never run and was
  misaligned with the deployed DDL. Fixed the **branch_pnl path**:
  `schemas.py` (`HubProduct.product_bk`, `SatOrderHeader`→deployed cols, new `SatOrderPricing`);
  `mappers.py` (synthesize pricing from `purchase_sum`, tax 20/20/20/5/12%; stop emitting
  X5-incompatible product/customer/lnk satellites); 5 new `sat_order_header__1c__*` DDLs
  (`.gitignore /warehouse/agentflow/` → `git add -f`); `bv_order_canonical` UNIONs the
  `__1c__` headers. **200K smoke verified clean** (0 null subtotal, correct per-jurisdiction tax).

## Deferred / known limitations
- Only the **financial P&L path** is wired. `customer_360` / product marts stay synthetic
  (X5 lacks PII / catalog fields matching deployed satellites). Follow-up: X5-shaped
  satellites + rewire those marts, if needed.
- X5 orders: `channel='retail'`, `order_status='completed'` (X5 has no such columns);
  returns = 0 for X5 in `returns_velocity`.

## Other notes
- Interview-prep reference (not in repo): `D:\Dif_Mat\ch_dbt_details.pdf`.
- Second opinions: Codex (deep) + MiniMax via OpenRouter (`D:\TXT\Py_files\_minimax_ask.py`).
- **Stray files in repo root** `p1..p8.md`, `p_res1.md`, `p_res2.md` (2026-06-02 ~15:22,
  technical-writer prompts) are **NOT from this work** — not committed; clean up if scratch.
