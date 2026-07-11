# Engineering Status

> Updated: **2026-07-11** (post S13 + #183 live re-verify) · release line **`v2.0.0`** ·
> `main` green across all 13 required checks. Numbers below come only from
> measured, in-repo evidence — see the linked reports for methodology and
> reproduction commands.

AgentFlow's product axis — **event → live metric** on the real streaming path
(Kafka → Flink → serving bridge → ClickHouse → API with Redis push
invalidation) — is implemented, measured, and documented. Current work is
raising the write-path throughput ceiling and turning documented limits into
passed ones (endurance, scale, delivery topology).

## Proven

| Claim | Result | Evidence |
|-------|--------|----------|
| Real-path freshness e2e | **3.02 s p50 / 5.70 s p95** (n=20) | [perf/freshness-e2e-realpath.md](perf/freshness-e2e-realpath.md) |
| In-process demo freshness | 1.06 s p50 / 1.99 s p95 | [freshness-benchmark.md](freshness-benchmark.md) |
| Real-path throughput measured | produce ~700 eps; bridge apply is the ceiling (see below) | [perf/throughput-realpath.md](perf/throughput-realpath.md) |
| 2-pod control plane on kind | webhook registered on pod A visible on pod B; verify script PASS | [perf/e4-2pod-topology-2026-07-09.md](perf/e4-2pod-topology-2026-07-09.md) |
| 4 h endurance soak (real path + API reads) | bounded lag (peak 2 915 → 0), bridge RSS/FD flat, one faulted batch replayed exactly-once by the journal guard, **zero cache drift** | [perf/soak-s11-2026-07-10.md](perf/soak-s11-2026-07-10.md) |
| At-scale on own data (S13) | **51.2 M rows / 2.87 M orders / 4 years of legend history**, analyst queries 20–730 ms, all 17 §12 invariants pass incl. full-scan GTIN validation | [perf/scale-own-data-2026-07-11.md](perf/scale-own-data-2026-07-11.md) |
| Security pass (offline/unit remainder) | closed; third-party pen-test **not** claimed | [security-s12-2026-07-09.md](security-s12-2026-07-09.md), [security-audit.md](security-audit.md) |

## Bridge write-path throughput — burst target met

The bridge apply rate is the honest product ceiling; it has been raised in
measured steps on the same stand:

| Step | Bridge apply | State |
|------|-------------:|-------|
| Baseline (per-event apply) | ~8 eps | measured |
| Q1.2 — ClickHouse-only sink, no scratch lake | 11.4 eps | measured |
| Q1.3 — multi-row batch apply | 22.9 eps | measured — [perf/throughput-realpath-q13-2026-07-09.md](perf/throughput-realpath-q13-2026-07-09.md) |
| Q1.4 — batched session/user read-modify-writes (constant round-trips per batch) | **87.4 eps** | measured — [perf/throughput-realpath-q14-2026-07-10.md](perf/throughput-realpath-q14-2026-07-10.md) |

The series target of **≥ 80 eps** is met on the 400-burst profile (peak lag 0 —
the burst drains inside one catch-up window). The 4 h soak then held the
delivered produce rate (~47 eps avg) with bounded lag and no bridge leak —
the apply path idled between batches, so the burst ceiling was never
stressed; the ≥ 100 eps stretch bar stays open. Semantics of the batched path
(fold rules, idempotency, replay) are in [serving-bridge.md](serving-bridge.md).

## Known issues

- **Multi-tenant ClickHouse — implemented, not yet proven live.** Tenant
  isolation used to be a schema qualification that nothing provisioned: no
  `CREATE SCHEMA` existed anywhere in `src/`, so on DuckDB every *authenticated*
  entity read failed on a relation that was never created, and on ClickHouse the
  same name meant a database nobody creates. With the qualification dropped, two
  tenants sharing an `order_id` were two versions of one `ReplacingMergeTree`
  row and the later insert destroyed the earlier — data loss no read filter can
  undo. The boundary is now the `tenant_id` **column**, leading each serving
  table's write key on both stores
  ([ADR-004](decisions/004-tenant-id-column-over-schema-per-tenant.md)).
  **DuckDB is proven**: two tenants with identical entity ids resolve to
  different rows, cross-tenant lookups 404, aggregates sum only the caller's
  rows, and an unscoped read against a shared store is refused — asserted both
  by example (`tests/integration/test_tenant_isolation.py`) and over generated
  tenant/entity ids (`tests/property/test_tenant_isolation_properties.py`).
  **ClickHouse is not**: its adversarial two-tenant suite
  (`tests/integration/test_clickhouse_tenant_isolation_live.py`) needs a live
  server and has not been run yet. Until it is green, multi-tenant ClickHouse is
  not a supported claim; the single-tenant profile is unaffected.

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

1. **Delivery topology** — exactly-one webhook delivery across replicas
   (store-level behavior is already unit-proven; the topology-level proof is
   scripted next).
2. **≥ 100 eps stretch bar** — sustained (not burst) bridge apply above 100
   eps; requires a stand window with a healthy Flink hop.

External gates remain unchanged and are listed in the README scope note:
production CDC onboarding, a benchmark on production-grade hardware, and a
third-party pen-test attestation.

---

*Keep this file to one page. Add a number only after the measurement doc it
links to exists; retired claims move to the [changelog](../CHANGELOG.md).*
