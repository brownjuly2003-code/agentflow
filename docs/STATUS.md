# Engineering Status

> Updated: **2026-07-10** (post Q1.4 re-measure) · release line **`v2.0.0`** ·
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

- **API RSS growth under steady load — root-caused and fixed at unit scale**
  (was 175 MB → 1.67 GB over the 4 h soak; the bridge stayed flat). The
  webhook dispatcher re-materialized the whole `pipeline_events` journal every
  2 s and the scan/push dedup sets grew one entry per event forever; journal
  scans are now cursor-bounded and the seen-sets capped (issue #183, details
  in [serving-bridge.md](serving-bridge.md#journal-scans-are-bounded-issue-183)).
  Measured at unit scale: per-scan allocation flat ≤ 0.8 MB against a journal
  growing 50 k → 400 k rows (was 35.5 → 283.6 MB). **Live stand
  re-verification is still pending** — scheduled for the next stand window.

## Next

1. **Live re-verification of the API leak fix** — re-run a soak-profile RSS
   sample on the Docker stand alongside the S13 scale work.
2. **At-scale proof on own data** — volume + query latency + correctness
   spot-checks on the project's synthetic generator.
3. **Delivery topology** — exactly-one webhook delivery across replicas
   (store-level behavior is already unit-proven; the topology-level proof is
   scripted next).

External gates remain unchanged and are listed in the README scope note:
production CDC onboarding, a benchmark on production-grade hardware, and a
third-party pen-test attestation.

---

*Keep this file to one page. Add a number only after the measurement doc it
links to exists; retired claims move to the [changelog](../CHANGELOG.md).*
