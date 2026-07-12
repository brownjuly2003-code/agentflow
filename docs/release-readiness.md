# AgentFlow Release Readiness

**Release line**: `v2.0.0`

**Status**: published to PyPI (`agentflow-runtime`, `agentflow-client`) and npm
(`@yuliaedomskikh/agentflow-client`) via OIDC Trusted Publishers with SLSA
provenance attestations — see
[dv2-multi-branch/RELEASE_STATUS.md](dv2-multi-branch/RELEASE_STATUS.md) for
registry links and upload evidence. `main` is protected by 13 required status
checks and is green.

## Summary

AgentFlow ships an event-native metrics layer: business metrics that move when
events happen, served over typed contracts to people, dashboards, services, and
AI agents. The technical blockers from the initial internal audit are closed;
subsequent work hardened security (tenant isolation, `sqlglot` SQL validation,
fail-closed auth), added the DV2 multi-branch Data Vault 2.0 warehouse, hardened
the Helm/CDC path, and brought the Python and TypeScript SDKs to parity.
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

`main` is protected with 13 required status checks — `lint`, `test-unit`,
`test-integration`, `perf-check`, `helm-schema-live`, `schema-check`,
`terraform-validate`, `bandit`, `safety`, `npm-audit`, `trivy`, `contract`,
`build-smoke`. Branch protection requires every one of them; force-pushes and
deletions are disabled.

## Scope

The streaming, warehouse, and deployment artifacts (Flink, Iceberg, Helm,
Terraform, k8s) are validated against a local pipeline and a kind cluster in CI
rather than a paid managed cloud — a deliberate non-goal for this reference
project. Wiring AgentFlow to a live production source needs inputs that live
outside the repo: CDC source onboarding (runbook in
[docs/operations/cdc-production-onboarding.md](operations/cdc-production-onboarding.md)),
a public benchmark on production-grade hardware, and an external pen-test
attestation. None of the claims those would unlock are made here.
