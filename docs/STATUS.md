# Engineering Status

> Updated: **2026-07-10** · release line **`v2.0.0`** · `main` green across all
> 13 required checks. Numbers below come only from measured, in-repo evidence —
> see the linked reports for methodology and reproduction commands.

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
| Security pass (offline/unit remainder) | closed; third-party pen-test **not** claimed | [security-s12-2026-07-09.md](security-s12-2026-07-09.md), [security-audit.md](security-audit.md) |

## In progress — bridge write-path throughput

The bridge apply rate is the honest product ceiling and is being raised in
measured steps on the same stand:

| Step | Bridge apply | State |
|------|-------------:|-------|
| Baseline (per-event apply) | ~8 eps | measured |
| Q1.2 — ClickHouse-only sink, no scratch lake | 11.4 eps | measured |
| Q1.3 — multi-row batch apply | **22.9 eps** | measured — [perf/throughput-realpath-q13-2026-07-09.md](perf/throughput-realpath-q13-2026-07-09.md) |
| Q1.4 — batched session/user read-modify-writes (constant round-trips per batch) | merged (`main`); **not yet re-measured** | next stand window |

Target for this series: **≥ 80 eps** sustained apply on the same stand.
Semantics of the batched path (fold rules, idempotency, replay) are in
[serving-bridge.md](serving-bridge.md).

## Next

1. **Throughput re-measure** after the Q1.4 apply path (new report next to the
   old ones, never overwritten).
2. **Endurance soak** — multi-hour Kafka → Flink → bridge → ClickHouse run with
   API read traffic; criteria: bounded lag, flat RSS, zero apply-failure growth.
3. **At-scale proof on own data** — volume + query latency + correctness
   spot-checks on the project's synthetic generator.
4. **Delivery topology** — exactly-one webhook delivery across replicas
   (store-level behavior is already unit-proven; the topology-level proof is
   scripted next).

External gates remain unchanged and are listed in the README scope note:
production CDC onboarding, a benchmark on production-grade hardware, and a
third-party pen-test attestation.

---

*Keep this file to one page. Add a number only after the measurement doc it
links to exists; retired claims move to the [changelog](../CHANGELOG.md).*
