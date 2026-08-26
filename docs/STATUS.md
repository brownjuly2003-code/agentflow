# Engineering Status

> Updated: **2026-08-26**. The golden topology remains a production candidate, not
> production accepted. Published release line **`v2.0.0`**; unpublished lockstep
> **2.1.0** is prepared locally. Numbers below come only from measured, in-repo
> evidence.

AgentFlow's product axis — **event → live metric** on the real streaming path
(Kafka → PyFlink → `events.validated` → serving bridge → ClickHouse → API
with Redis push invalidation) — is implemented, measured, and documented.

**Project lifecycle:** closure candidate. Scope, remaining acceptance program,
and release gates: [PROJECT_CLOSURE.md](PROJECT_CLOSURE.md). Machine-readable
claims: [`config/project_claims.toml`](../config/project_claims.toml).

**Latest delivery boundary:** digest-only staging promotion passed for exact
image identity and the offline production-promotion evidence verifier is
complete. No production workflow or deploy has been implemented or authorized;
target-dependent work is `BLOCKED_EXTERNAL_PRODUCTION_TARGET_CONTRACT` pending
the owner packet described in
[`f19d-production-rollout-acceptance.md`](../f19d-production-rollout-acceptance.md).

## Current gates

| Gate | Result | Evidence |
|------|--------|----------|
| Clean-checkout PyFlink OCI build + submission smoke | PASS clean-checkout OCI build + submission smoke on 2026-07-30 | [perf/golden-flink-submission-2026-07-30.md](perf/golden-flink-submission-2026-07-30.md) |
| Flink Kubernetes Operator + Helm golden deploy | PASS on exact HEAD `36ed1ec`; Kafka on the kind acceptance scaffold (`k8s/acceptance/kafka-kraft.yaml`), not production Kafka | [perf/golden-operator-acceptance-2026-07-30.md](perf/golden-operator-acceptance-2026-07-30.md) |
| Live Iceberg materialization from `events.validated` | PASS at the direct topic boundary | [perf/live-iceberg-materialization-2026-08-01.md](perf/live-iceberg-materialization-2026-08-01.md) |
| Full lake-to-serving single-event smoke | PASS on the mixed-SHA stand (single event, one hop chain) | [perf/full-lake-to-serving-e2e-2026-08-01.md](perf/full-lake-to-serving-e2e-2026-08-01.md) |
| Checkpoint restore/replay | PASS; exact-once lake/serving, DLQ 0, lag 0 | [perf/checkpoint-restore-replay-2026-08-02.md](perf/checkpoint-restore-replay-2026-08-02.md) |
| Readiness-baselined checkpoint hold | **`RUNTIME_HOLD_PASS`** (930 s, completed `7675→8614`, failed `1→1`; read-only, no traffic) | [perf/ready-baselined-checkpoint-hold-2026-08-03.md](perf/ready-baselined-checkpoint-hold-2026-08-03.md) |
| Kind residual canary | PASS | [perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md](perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md) |
| Latest 4h soak identity `-05` | **`SOAK_FAIL`** (producer PASS; dual-mean ABORT) | [perf/golden-4h-soak-05-failure-2026-08-08.md](perf/golden-4h-soak-05-failure-2026-08-08.md) |
| Corrected rollback mechanics | **PASS** (rev5 probe → rev6 = byte-identical rev3; no traffic) | [corrected-rollback-pair-runtime-20260823-01.md](../corrected-rollback-pair-runtime-20260823-01.md) |
| Full 4h soak + rollback after traffic | **`BLOCKED_HOST_CAPACITY`** | [ci-soak-f02-capacity-decision-20260823-01.md](../ci-soak-f02-capacity-decision-20260823-01.md) |
| GitHub Environment `npm` approval | PASS (one required reviewer; not a four-eyes claim) | [operations/npm-environment-approval-2026-08-03.md](operations/npm-environment-approval-2026-08-03.md) |
| Digest-only staging promotion | **PASS**; authorized run `33005146264`, exact staging-accepted digest, smoke/E2E and bounded artifact | [f19c-staging-digest-promotion.md](../f19c-staging-digest-promotion.md) |
| Offline production-promotion verifier | **PASS**; focused `32/32`, retained staging artifact validates, tampering fails closed | [f19d-production-rollout-acceptance.md](../f19d-production-rollout-acceptance.md) |
| Production rollout target | **`BLOCKED_EXTERNAL_PRODUCTION_TARGET_CONTRACT`**; no production workflow/deploy or acceptance claim | [f19d-production-rollout-acceptance.md](../f19d-production-rollout-acceptance.md) |
| External pentest | **`BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE`** | [operations/external-pentest-evidence-blocker-2026-08-01.md](operations/external-pentest-evidence-blocker-2026-08-01.md) |

Historical soak chronology (canary1 catch-up fail, resource blockers, kind residual) lives in those evidence files — it is not retold here. None of the rows above is production acceptance.

## Proven

| Claim | Result | Evidence |
|-------|--------|----------|
| Real-path freshness e2e | **3.02 s p50 / 5.70 s p95** (n=20) | [perf/freshness-e2e-realpath.md](perf/freshness-e2e-realpath.md) |
| In-process demo freshness | 1.06 s p50 / 1.99 s p95 | [freshness-benchmark.md](perf/freshness-benchmark.md) |
| Real-path throughput measured | produce ~700 eps; bridge apply is the ceiling (see below) | [perf/throughput-realpath.md](perf/throughput-realpath.md) |
| 2-pod control plane on kind | webhook registered on pod A visible on pod B; verify script PASS | [perf/e4-2pod-topology-2026-07-09.md](perf/e4-2pod-topology-2026-07-09.md) |
| E4 Checks 1–4 (2 pods, delivery + alert single-page) | **PASS** on kind | [perf/e4-check4-alert-single-page-2026-07-17.md](perf/e4-check4-alert-single-page-2026-07-17.md) |
| 4 h endurance soak (real path + API reads) | bounded lag (peak 2 915 → 0), bridge RSS/FD flat, one faulted batch replayed exactly-once by the journal guard, **zero cache drift** | [perf/soak-s11-2026-07-10.md](perf/soak-s11-2026-07-10.md) |
| At-scale on own data (S13) | **51.2 M rows / 2.87 M orders / 4 years of legend history**, analyst queries 20–730 ms, all 17 at-scale correctness checks pass | [perf/scale-own-data-2026-07-11.md](perf/scale-own-data-2026-07-11.md) |
| Security pass (offline/unit remainder) | closed; third-party pen-test **not** claimed | [security-s12-2026-07-09.md](evidence/security-s12-2026-07-09.md), [security-audit.md](security-audit.md) |
| Multi-tenant ClickHouse write key | adversarial two-tenant suite green on live CH 25.3 (CI `test-integration` + audit stand) | [security-audit.md](security-audit.md), `tests/integration/test_clickhouse_tenant_isolation_live.py` |
| Hardened API runtime image (local acceptance) | core-only API import/HTTP smoke PASS; Trivy 0.70.0 reports 0 HIGH/CRITICAL after runtime installer removal | [security-runtime-image-trivy-2026-07-30.md](evidence/security-runtime-image-trivy-2026-07-30.md) |
| Python cloud/MCP dependency compatibility (local + isolated Mac) | 2170 unit/property tests PASS; MCP 1.29 + PyIceberg 0.11.1/core 0.7.0 clean environment and 39 focused tests PASS | [dependency-compatibility-2026-07-30.md](evidence/dependency-compatibility-2026-07-30.md) |

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

The series target of **≥ 80 eps** is met. Paced 4 h (r4) is valid evidence for
its measured pre-materializer path only — advisory for the post-Iceberg golden
gate, which remains `BLOCKED_HOST_CAPACITY`. Semantics of the batched path:
[serving-bridge.md](serving-bridge.md).

## Known issues

- **Multi-tenant ClickHouse — proven live (audit P0-1).** The boundary is the
  `tenant_id` **column**, leading each serving table's write key on both stores
  ([ADR-004](decisions/004-tenant-id-column-over-schema-per-tenant.md)). DuckDB
  remains covered by example and property suites; ClickHouse is covered by
  `tests/integration/test_clickhouse_tenant_isolation_live.py` on live server
  25.3. Broader isolation across every external dependency is still out of
  scope — see [security-audit.md](security-audit.md).

- **API RSS growth under steady load — fixed and verified live** (was 175 MB
  → 1.67 GB over the 4 h soak; the bridge stayed flat). Journal scans are
  cursor-bounded and the seen-sets capped (issue #183). **Live re-verification
  2026-07-11:** 97 min at the soak read/apply profile — RSS slope **+7.5 MB/h**,
  plateaued; [perf/rss-reverify-183-2026-07-11.md](perf/rss-reverify-183-2026-07-11.md).

## Post-closure remaining work

Not active engineering backlog for the closing release. Each item needs a
separately authorized acceptance, deployment, or breaking-release program.

1. **Production rollout owner packet** —
   **`BLOCKED_EXTERNAL_PRODUCTION_TARGET_CONTRACT`**. Cluster, namespace,
   release, credential-delivery, values, externally managed Secrets,
   ingress/TLS/proxy, smoke, monitoring, maintenance-window, and exact rollback
   identities are not supplied. Do not create or dispatch a production workflow
   until the packet passes the read-only preflight in
   [f19d-production-rollout-acceptance.md](../f19d-production-rollout-acceptance.md).
2. **Full 4h soak + rollback after traffic** —
   **`BLOCKED_HOST_CAPACITY`** on the current host
   ([ci-soak-f02-capacity-decision-20260823-01.md](../ci-soak-f02-capacity-decision-20260823-01.md)).
   Rollback *mechanics* are a separate **PASS**
   ([corrected-rollback-pair-runtime-20260823-01.md](../corrected-rollback-pair-runtime-20260823-01.md))
   and do not close this gate. Historical Helm revisions 1, 2, 4, and 5 are not
   rollback targets.
3. **External pentest** — **`BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE`**. Do not
   procure, simulate, or perform a pen-test from docs work.
4. **P2-6 Phase 3** — drop the deprecated `src` shim in the next **major**
   release ([plans/p2-6-runtime-namespace-migration.md](plans/p2-6-runtime-namespace-migration.md);
   consumer notes: [migration/v2.1.md](migration/v2.1.md)).
5. **Flink-runtime dependency bump** — pinned `apache-flink==2.3.0` holds a
   `safety` ignore for a non-fixable transitive `pyarrow` advisory (isolated to
   the Flink image). Retire the ignore when the upstream flink/beam chain allows
   it.

---

*Keep this file to one page. Add a number only after the measurement doc it
links to exists; retired claims move to the [changelog](../CHANGELOG.md).*
