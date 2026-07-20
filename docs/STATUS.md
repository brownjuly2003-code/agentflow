# Engineering Status

> Updated: **2026-07-20** (4 h @ 100 eps soak **r4 PASS**; July security
> hardening wave merged) · release line **`v2.0.0`** · `main` green across
> required checks. Numbers below come only from measured, in-repo evidence —
> see the linked reports for methodology and reproduction commands.

AgentFlow's product axis — **event → live metric** on the real streaming path
(Kafka → Flink → serving bridge → ClickHouse → API with Redis push
invalidation) — is implemented, measured, and documented. The write-path
ceiling is proven **sustained** (4 h @ 100 eps, exactly-once); remaining work
is packaging hygiene for the next breaking release plus the external gates
listed below.

## Proven

| Claim | Result | Evidence |
|-------|--------|----------|
| Real-path freshness e2e | **3.02 s p50 / 5.70 s p95** (n=20) | [perf/freshness-e2e-realpath.md](perf/freshness-e2e-realpath.md) |
| In-process demo freshness | 1.06 s p50 / 1.99 s p95 | [freshness-benchmark.md](freshness-benchmark.md) |
| Real-path throughput measured | produce ~700 eps; bridge apply is the ceiling (see below) | [perf/throughput-realpath.md](perf/throughput-realpath.md) |
| 2-pod control plane on kind | webhook registered on pod A visible on pod B; verify script PASS | [perf/e4-2pod-topology-2026-07-09.md](perf/e4-2pod-topology-2026-07-09.md) |
| E4 Checks 1–4 (2 pods, delivery + alert single-page) | **PASS** on kind | [perf/e4-check4-alert-single-page-2026-07-17.md](perf/e4-check4-alert-single-page-2026-07-17.md) |
| 4 h endurance soak (real path + API reads) | bounded lag (peak 2 915 → 0), bridge RSS/FD flat, one faulted batch replayed exactly-once by the journal guard, **zero cache drift** | [perf/soak-s11-2026-07-10.md](perf/soak-s11-2026-07-10.md) |
| At-scale on own data (S13) | **51.2 M rows / 2.87 M orders / 4 years of legend history**, analyst queries 20–730 ms, all 17 §12 invariants pass incl. full-scan GTIN validation | [perf/scale-own-data-2026-07-11.md](perf/scale-own-data-2026-07-11.md) |
| Security pass (offline/unit remainder) | closed; third-party pen-test **not** claimed | [security-s12-2026-07-09.md](security-s12-2026-07-09.md), [security-audit.md](security-audit.md) |
| Multi-tenant ClickHouse write key | adversarial two-tenant suite green on live CH 25.3 (CI `test-integration` + audit stand) | [security-audit.md](security-audit.md), `tests/integration/test_clickhouse_tenant_isolation_live.py` |

## Bridge write-path throughput — drain ceiling measured

The bridge apply rate is the honest product ceiling; it has been raised in
measured steps on the same Mac compose stand (Kafka → Flink → bridge → CH):

| Step | Bridge apply | State |
|------|-------------:|-------|
| Baseline (per-event apply) | ~8 eps | measured |
| Q1.2 — ClickHouse-only sink, no scratch lake | 11.4 eps | measured |
| Q1.3 — multi-row batch apply | 22.9 eps | measured — [perf/throughput-realpath-q13-2026-07-09.md](perf/throughput-realpath-q13-2026-07-09.md) |
| Q1.4 — batched session/user read-modify-writes (constant round-trips per batch) | **87.4 eps** | measured — [perf/throughput-realpath-q14-2026-07-10.md](perf/throughput-realpath-q14-2026-07-10.md) |
| Stretch try — 2000-event drain on same Mac class | **107.3 eps** | measured — [perf/throughput-realpath-100eps-try-2026-07-17.md](perf/throughput-realpath-100eps-try-2026-07-17.md) |
| Paced 10 min @ 100 eps produce | **96.5 apply / 97.1 flink / 100 produce** | measured — [perf/throughput-realpath-paced100-2026-07-17.md](perf/throughput-realpath-paced100-2026-07-17.md) |
| Paced **1 h** @ 100 eps produce | **99.5 apply / 99.5 flink / 100 produce** | measured — [perf/throughput-realpath-paced100-1h-2026-07-17.md](perf/throughput-realpath-paced100-1h-2026-07-17.md) |
| Paced **4 h** @ 100 eps produce (r4) | **99.9 apply / 99.9 flink / 100.0 produce** — 1 440 000 events, dup = 0, failures = 0, lag 0 → 0, 0 Flink restarts | measured — [perf/throughput-realpath-paced100-4h-r4-2026-07-19.md](perf/throughput-realpath-paced100-4h-r4-2026-07-19.md) |

The series target of **≥ 80 eps** is met on the 400-burst profile. A
**2000-event** drain cleared at **107.3 eps**. Paced ingress at 100 eps held
for 10 min, 1 h, and — closing the multi-hour gate — **4 h** (r4:
`produced = validated = applied = 1 440 000` exactly, 0 duplicates,
0 failures, lag ends at 0, zero Flink restarts). The two failed 4 h attempts
before r4 are written up honestly in the r4 report (stand disk exhaustion;
bench producer losing a broker self-fence) — neither was an apply-path
defect. Semantics of the batched path are in
[serving-bridge.md](serving-bridge.md).

## Known issues

- **Multi-tenant ClickHouse — proven live (audit P0-1).** The boundary is the
  `tenant_id` **column**, leading each serving table's write key on both stores
  ([ADR-004](decisions/004-tenant-id-column-over-schema-per-tenant.md)). DuckDB
  remains covered by example and property suites; ClickHouse is covered by
  `tests/integration/test_clickhouse_tenant_isolation_live.py` on live server
  25.3 (CI `test-integration` service + audit Mac stand). Cross-tenant lookups
  404, aggregates stay tenant-scoped, and `assert_tenant_key()` refuses an old
  single-column sorting key. Broader isolation across every external dependency
  is still out of scope — see [security-audit.md](security-audit.md).

- **API RSS growth under steady load — fixed and verified live** (was 175 MB
  → 1.67 GB over the 4 h soak; the bridge stayed flat). The webhook
  dispatcher re-materialized the whole `pipeline_events` journal every 2 s
  and the scan/push dedup sets grew one entry per event forever; journal
  scans are now cursor-bounded and the seen-sets capped (issue #183, details
  in [serving-bridge.md](serving-bridge.md#journal-scans-are-bounded-issue-183)).
  Unit scale: per-scan allocation flat ≤ 0.8 MB against a journal growing
  50 k → 400 k rows (was 35.5 → 283.6 MB). **Live re-verification
  2026-07-11:** 97 min at the soak read/apply profile against a 1.37 M-row
  journal — RSS slope **+7.5 MB/h**, plateaued (was ~+370 MB/h monotonic);
  [perf/rss-reverify-183-2026-07-11.md](perf/rss-reverify-183-2026-07-11.md).

## Next

1. **P2-6 packaging** (breaking) — Phase 0 inventory + defaults done; Phase 1
   (tree/`agentflow_runtime` + shim) waits for a release branch:
   [plans/p2-6-runtime-namespace-migration.md](plans/p2-6-runtime-namespace-migration.md).
2. **Flink-runtime dependency bump** — the pinned `apache-flink==2.3.0` job
   environment holds a `safety` ignore for a non-fixable transitive `pyarrow`
   advisory (isolated to the Flink image, core pins `pyarrow>=17`); retire the
   ignore when the upstream flink/beam chain allows it.

External gates remain unchanged and are listed in the README scope note:
production CDC onboarding, a benchmark on production-grade hardware, and a
third-party pen-test attestation.

---

*Keep this file to one page. Add a number only after the measurement doc it
links to exists; retired claims move to the [changelog](../CHANGELOG.md).*
