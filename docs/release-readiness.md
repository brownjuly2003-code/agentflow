# AgentFlow Release Readiness

**Release line**: `v2.0.0`

**Package status**: published to PyPI (`agentflow-runtime`, `agentflow-client`) and npm
(`@yuliaedomskikh/agentflow-client`) via OIDC Trusted Publishers with SLSA
provenance attestations — see
[dv2-multi-branch/RELEASE_STATUS.md](dv2-multi-branch/RELEASE_STATUS.md) for
registry links and upload evidence.

**Golden-topology status (2026-07-30)**: production candidate, not production
accepted. Repository implementation and local contract gates are complete;
clean-checkout OCI build + real Flink job submission smoke is **PASS**
([perf/golden-flink-submission-2026-07-30.md](perf/golden-flink-submission-2026-07-30.md));
clean kind + Flink Kubernetes Operator + Helm deployment of the verified image
on exact HEAD `36ed1ec` is also **PASS**
([perf/golden-operator-acceptance-2026-07-30.md](perf/golden-operator-acceptance-2026-07-30.md)).
That acceptance used live Kafka runtime fixes; the kind acceptance scaffold is
now tracked at `k8s/acceptance/kafka-kraft.yaml` with a unit contract (not a
production Kafka claim). Lake-to-serving E2E, recovery, soak, rollback, and
external security evidence remain pending as listed below.

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
context.

The 2026-07-30 closing remediation additionally covers two clean-install
boundaries: the core-only API imports and serves health/entity/query without
the optional `pyiceberg` package, and the final API image removes
`pip`/`setuptools`/`wheel` after its hash-locked install and `pip check`.
Independent Mac validation with Trivy 0.70.0 reported zero HIGH/CRITICAL
findings; details and evidence limits are in
[security-runtime-image-trivy-2026-07-30.md](security-runtime-image-trivy-2026-07-30.md).
All required GitHub checks must still be green on the exact final pushed SHA.

## Scope

Component, contract, Helm, and replay tests validate the checked-in streaming,
lake, serving, and deployment artifacts. They do not substitute for full live
production-acceptance evidence.

**Completed (limited scope, 2026-07-30):**

1. clean-checkout PyFlink OCI build and real job submission smoke on
   `deproject-mac` — see
   [perf/golden-flink-submission-2026-07-30.md](perf/golden-flink-submission-2026-07-30.md);
2. clean kind + Flink Kubernetes Operator + Helm golden-topology deployment of
   the verified OCI image on exact HEAD `36ed1ec` (stable hold, checkpoints
   growing, zero leadership flaps) — see
   [perf/golden-operator-acceptance-2026-07-30.md](perf/golden-operator-acceptance-2026-07-30.md).

These close submission smoke and Operator/Helm deploy only. They are **not**
lake-to-serving E2E or production acceptance. Kafka on the acceptance stand
required evidence-backed scaffold fixes (`enableServiceLinks: false` and
controller quorum voters at `127.0.0.1:29093`); that is recorded as
acceptance-scaffold reproducibility debt, not a product source of truth from
untracked prompts.

**Still required for production acceptance:**

1. one tenant-scoped event observed through Kafka → PyFlink → Iceberg →
   ClickHouse → API, then replayed after checkpoint restore without duplicate
   `(tenant_id, event_id)` rows;
2. a fresh four-hour soak, backup/restore, and rollback rehearsal on that same
   artifact and topology (the existing 2026-07-19 soak predates the Iceberg
   materializer);
3. an external penetration-test report and remediation/retest evidence;
4. GitHub Environment `npm` created with approval protection. The workflow now
   requires `environment: npm` and a matching release tag, but the repository
   settings API returned `404` for that environment on 2026-07-23, so approval
   protection is not yet evidenced.

Wiring AgentFlow to a live production source also needs inputs that live
outside the repo: CDC source onboarding (runbook in
[docs/operations/cdc-production-onboarding.md](operations/cdc-production-onboarding.md)),
a public benchmark on production-grade hardware, and operator-owned
credentials. None of the claims those would unlock are made here.
