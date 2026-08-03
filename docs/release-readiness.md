# AgentFlow Release Readiness

**Release line**: `v2.0.0`

**Package status**: published to PyPI (`agentflow-runtime`, `agentflow-client`) and npm
(`@yuliaedomskikh/agentflow-client`) via OIDC Trusted Publishers with SLSA
provenance attestations — see
[dv2-multi-branch/RELEASE_STATUS.md](dv2-multi-branch/RELEASE_STATUS.md) for
registry links and upload evidence.

**Golden-topology status (2026-08-02)**: production candidate, not production
accepted. Repository implementation and local contract gates are complete;
clean-checkout OCI build + real Flink job submission smoke is **PASS**
([perf/golden-flink-submission-2026-07-30.md](perf/golden-flink-submission-2026-07-30.md));
clean kind + Flink Kubernetes Operator + Helm deployment of the verified image
on exact HEAD `36ed1ec` is **PASS**
([perf/golden-operator-acceptance-2026-07-30.md](perf/golden-operator-acceptance-2026-07-30.md));
live Iceberg materialization from direct `events.validated` is **PASS** at the
narrow materializer boundary
([perf/live-iceberg-materialization-2026-08-01.md](perf/live-iceberg-materialization-2026-08-01.md));
and full one-event lake-to-serving smoke is **PASS**
([perf/full-lake-to-serving-e2e-2026-08-01.md](perf/full-lake-to-serving-e2e-2026-08-01.md)).
Isolated checkpoint restore/replay is also **PASS** with distinct J1/J2,
savepoint restore linkage, exact-once E1/E2 counts across all measured
lake/serving surfaces, DLQ `0`, and lag `0`
([perf/checkpoint-restore-replay-2026-08-02.md](perf/checkpoint-restore-replay-2026-08-02.md)).
Operator acceptance used live Kafka runtime fixes; the kind acceptance scaffold
is tracked at `k8s/acceptance/kafka-kraft.yaml` with a unit contract (not a
production Kafka claim). A later isolated golden soak canary reached zero
baseline **PASS** and producer delivery `2000/2000`, then failed closed at
**`FAIL_CANARY_CATCHUP_RATE_FLOOR`**; the 4h producer, observer, and rollback
were **not started**
([perf/golden-4h-soak-canary-failure-2026-08-02.md](perf/golden-4h-soak-canary-failure-2026-08-02.md)).
A subsequent preflight found clean rev1/rev2 already deployed with corrected
interval/CPU, but returned **`BLOCKED_RUNTIME_MIN_PAUSE_NOT_RENDERED`**:
runtime source `ed03fc47` omits effective checkpoint min-pause and still
checkpoints at ~30 s. Canary2 was not started.
Tracked commit `78742d0` and its verified pack now add min-pause `0 ms` plus a
default-preserving anti-replay `group-offsets` cutover. The authorized apply
preflight stopped before remote mutation at
**`BLOCKED_RESOURCE_HEADROOM_BEFORE_SAFE_CUTOVER`**: Kind
`MemAvailable=1,683,140 kB` was below the required `1,900,000 kB`.
External security evidence remains pending as listed below. Read-only
external-pentest evidence/readiness audit at `2026-08-01T17:11:58Z` returned
**`BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE`** — see
[operations/external-pentest-evidence-blocker-2026-08-01.md](operations/external-pentest-evidence-blocker-2026-08-01.md).
Read-only GitHub Environment `npm` verification recorded at
`2026-08-03T03:18:11Z` is **PASS**: the Environment exists and its non-empty
`required_reviewers` rule names user `brownjuly2003-code` — see
[operations/npm-environment-approval-2026-08-03.md](operations/npm-environment-approval-2026-08-03.md).
Tracked full-smoke evidence is recorded in local evidence commit `cf247ba`
(local-only, unpushed).

## Summary

AgentFlow ships an event-native metrics layer: business metrics that move when
events happen, served over typed contracts to people, dashboards, services, and
AI agents. The repository-level blockers from the 2026-07-23 audit are
implemented: fail-closed CDC attribution, one operator-compatible PyFlink
runtime, tenant-scoped replay identity, explicit lake and serving
materializers, role-aware lifecycle cleanup, deterministic partial search, one
canonical session job, narrow control-plane capabilities, and a verified
common SDK surface with explicit language-specific differences. Runtime,
evidence, Python-version, quality-gate, and SDK capability statements are
tracked in the
[machine-readable project claims](../config/project_claims.toml).
Architecture decisions are recorded as ADRs in [docs/decisions/](decisions/).

## Performance baseline

Source: [`docs/benchmark-baseline.json`](benchmark-baseline.json).

| Endpoint | p50 (ms) | p99 (ms) | RPS | Gate | Status |
|----------|----------|----------|-----|------|--------|
| GET /v1/entity/order/{id} | 55 | 300 | 4.24 | p50 < 100, p99 < 500 | ✅ |
| GET /v1/entity/product/{id} | 49 | 320 | 2.39 | p50 < 100, p99 < 500 | ✅ |
| GET /v1/entity/user/{id} | 38 | 290 | 3.07 | p50 < 100, p99 < 500 | ✅ |
| GET /v1/metrics/{name} | 53 | 220 | 7.27 | informational | ✅ |
| POST /v1/query | 74 | 370 | 5.22 | informational | ✅ |
| POST /v1/batch | 62 | 340 | 5.56 | informational | ✅ |

**Aggregate run:** 569 requests, 0 failures, 27.76 RPS, p50 56 ms, p95 260 ms,
p99 330 ms. CI-runner thresholds are intentionally divergent from local hardware
and documented in
[docs/perf/ci-hardware-gap-2026-05-24.md](perf/ci-hardware-gap-2026-05-24.md).

## Code health

- God-class split completed for auth, alerts, and query modules with
  compatibility imports preserved.
- SQL injection exposure closed via parameterized queries and `sqlglot` AST
  validation. Tenant scoping is applied at every read surface, but the mechanism
  behind it was rebuilt after this release: what shipped here was a schema
  qualification that nothing provisioned, so it isolated nothing. The boundary is
  now a `tenant_id` column in each table's write key
  ([ADR-004](decisions/004-tenant-id-column-over-schema-per-tenant.md)); see
  [STATUS.md](STATUS.md#known-issues) for what is proven on which store.
- Flink critical paths covered by unit tests (`session_aggregator`,
  `stream_processor`).

## CI gates

`main` is protected with 15 required status checks — `lint`, `test-unit`,
`test-integration`, `perf-check`, `helm-schema-live`, `schema-check`,
`terraform-validate`, `bandit`, `safety`, `npm-audit`, `trivy`, `contract`,
`build-smoke`, `sdk-ts`, `lock-check`. Branch protection requires every one of
them; force-pushes and deletions are disabled. Dependabot security updates
(vulnerability alerts + automated security fixes) are enabled alongside the
weekly version-update schedule in `.github/dependabot.yml`.

The required `lint` job now contains strict MkDocs and claims validation. The
required `test-unit` job contains the 80% changed-code coverage gate and depends
on the 3.11/3.12/3.13 `python-compat` matrix, so a failed compatibility lane
cannot be bypassed merely because its job name is not a separate protected
context. The same job enforces a 60% full-suite line/branch floor and separate
90% floors for security-critical modules. Codecov upload is non-blocking
reporting until the repository is enabled in that external service; see
[operations/codecov-setup.md](operations/codecov-setup.md).

The 2026-07-30 closing remediation additionally covers two clean-install
boundaries: the core-only API imports and serves health/entity/query without
the optional `pyiceberg` package, and the final API image removes
`pip`/`setuptools`/`wheel` after its hash-locked install and `pip check`.
The cloud profile separately includes `pyiceberg-core==0.7.0`, whose
stable-ABI build supports the full Python matrix and restores PyIceberg 0.11
write transforms; the optional MCP integration is capped below the breaking
2.0 API. Clean Mac Python 3.13 verification passed with MCP 1.29 and all 39
selected contract/MCP/Iceberg tests.
Independent Mac validation with Trivy 0.70.0 reported zero HIGH/CRITICAL
findings; details and evidence limits are in
[security-runtime-image-trivy-2026-07-30.md](security-runtime-image-trivy-2026-07-30.md)
and
[dependency-compatibility-2026-07-30.md](dependency-compatibility-2026-07-30.md).
All required GitHub checks must still be green on the exact final pushed SHA.

## Scope

Component, contract, Helm, and replay tests validate the checked-in streaming,
lake, serving, and deployment artifacts. They do not substitute for full live
production-acceptance evidence.

**Completed (limited scope):**

1. clean-checkout PyFlink OCI build and real job submission smoke on
   `deproject-mac` (2026-07-30) — see
   [perf/golden-flink-submission-2026-07-30.md](perf/golden-flink-submission-2026-07-30.md);
2. clean kind + Flink Kubernetes Operator + Helm golden-topology deployment of
   the verified OCI image on exact HEAD `36ed1ec` (stable hold, checkpoints
   growing, zero leadership flaps; 2026-07-30) — see
   [perf/golden-operator-acceptance-2026-07-30.md](perf/golden-operator-acceptance-2026-07-30.md);
3. live Iceberg materialization from direct `events.validated` injection into
   live Iceberg `agentflow.validated_events` with exact identity observed once
   (2026-08-01) — see
   [perf/live-iceberg-materialization-2026-08-01.md](perf/live-iceberg-materialization-2026-08-01.md);
4. full one-event lake-to-serving smoke through `orders.raw` → PyFlink →
   `events.validated` → {Iceberg; bridge → ClickHouse → API} on the mixed-SHA
   stand (2026-08-01) — see
   [perf/full-lake-to-serving-e2e-2026-08-01.md](perf/full-lake-to-serving-e2e-2026-08-01.md);
5. isolated checkpoint restore/replay with E1 accepted on J1, non-empty
   savepoint, byte-identical E1 replay plus E2 while suspended, distinct J2
   restored from that savepoint, and exact no-duplicate lake/serving counts
   (2026-08-02) — see
   [perf/checkpoint-restore-replay-2026-08-02.md](perf/checkpoint-restore-replay-2026-08-02.md).

These close submission smoke, Operator/Helm deploy, the narrow direct-topic
Iceberg materialization gate, the full single-event hop chain, and checkpoint
restore/replay. They are **not** full production acceptance. The direct-Iceberg
gate remains valid and is now complemented by the full one-event path. Kafka on the acceptance stand
required evidence-backed scaffold fixes (`enableServiceLinks: false` and
controller quorum voters at `127.0.0.1:29093`); that is recorded as
acceptance-scaffold reproducibility debt, not a product source of truth from
untracked prompts.

**Still required for production acceptance (exactly two gates):**

1. a fresh four-hour soak at **100 delivered eps** for **14_400 s**
   (**1_440_000** events) through the full post-Iceberg path with exact
   lake/serving counts, plus Helm rollback rehearsal to verified rev **2**
   (never rev 1). The latest canary reached baseline and exact producer
   delivery, then returned **`FAIL_CANARY_CATCHUP_RATE_FLOOR`**; 4h
   soak/rollback was **not started**
   ([perf/golden-4h-soak-canary-failure-2026-08-02.md](perf/golden-4h-soak-canary-failure-2026-08-02.md)).
   The earlier
   [resource preflight](perf/golden-4h-soak-rollback-resource-blocker-2026-08-01.md)
   is retained as historical evidence for its stand. Clean rev1/rev2 is now
   present with corrected interval/CPU but still omits effective min-pause.
   The corrected anti-replay pack is verified; its apply is
   **`BLOCKED_RESOURCE_HEADROOM_BEFORE_SAFE_CUTOVER`** before mutation. Restore
   Kind `MemAvailable >= 1,900,000 kB`, then apply that exact pack and require
   canary2 PASS.
   The existing 2026-07-19 soak predates the Iceberg materializer and is
   advisory only;
2. an external penetration-test report and remediation/retest evidence.
   Read-only evidence/readiness audit at `2026-08-01T17:11:58Z` (local HEAD
   before documentation `ebde86f`; public repo `brownjuly2003-code/agentflow`)
   returned **`BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE`**. Canonical intake remains
   **not present / unclaimed** with empty decision-record fields and all
   acceptance checklist boxes open. Bounded tracked scan found only the blank
   intake; GitHub unified `search/issues` returned `total_count = 0` for
   `pentest`, exact phrase `penetration test`, `retest`, and `assessor`; nine
   releases have zero assets; Actions artifacts (`total_count = 3106`) had zero
   name matches after full pagination. All seven gate criteria fail. Internal
   Bandit/Safety/Trivy, Scorecard, S12/offline tests, and runtime image scans
   are not third-party pen-test evidence. This audit was **not** a penetration
   test. Evidence:
   [operations/external-pentest-evidence-blocker-2026-08-01.md](operations/external-pentest-evidence-blocker-2026-08-01.md).
   Minimum owner packet: independent assessor + independence statement;
   engagement type; exact target/artifact/commit; dates; scope/exclusions/RoE;
   credential owner/rotation plan without secrets; data-handling confirmation;
   remediation owner; immutable full-report location; redacted summary; finding
   inventory; remediation/risk-acceptance map; retest confirmations;
   residual-risk record; access revocation evidence. After receipt: redacted
   summary under `docs/operations/`, complete intake, evidence-linked
   security/status/readiness updates, then read-only re-audit. Do not procure,
   simulate, or perform a pen-test from documentation work.

The GitHub Environment `npm` gate is closed. A read-only GET recorded at
`2026-08-03T03:18:11Z` returned the exact Environment with one non-empty
`required_reviewers` rule for user `brownjuly2003-code`; `prevent_self_review`
is `false`, so this is approval protection but not a four-eyes claim. See
[operations/npm-environment-approval-2026-08-03.md](operations/npm-environment-approval-2026-08-03.md).
The prior
[absence audit](operations/npm-environment-approval-blocker-2026-08-01.md)
remains historical evidence, not current state. Current tracked evidence leaves
the two remaining gates dependent on sufficient Kind memory for the exact
safe-cutover pack or an external pentest owner.

Wiring AgentFlow to a live production source also needs inputs that live
outside the repo: CDC source onboarding (runbook in
[docs/operations/cdc-production-onboarding.md](operations/cdc-production-onboarding.md)),
a public benchmark on production-grade hardware, and operator-owned
credentials. None of the claims those would unlock are made here.
