# AgentFlow

> Event-native metrics layer: business metrics that move when events happen — measured **1.1 s p50** event-to-metric freshness on production defaults. Live entity lookups, typed contracts, dual-language SDKs, and release-gated delivery for people, dashboards, services, and AI agents alike.

[![Release gate](https://img.shields.io/badge/release_gate-v1.4_published-brightgreen)](docs/dv2-multi-branch/RELEASE_STATUS.md)
[![codecov](https://codecov.io/gh/brownjuly2003-code/agentflow/branch/main/graph/badge.svg)](https://codecov.io/gh/brownjuly2003-code/agentflow)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

## Why this exists

BI on a replica answers yesterday's questions. Support, ops, and merch workflows need *current* orders, metrics, and health signals at the moment of decision — not a stale warehouse snapshot, not a pile of one-off service adapters, and not a cache that quietly serves 30-second-old numbers.

AgentFlow's axis is **event → live metric**: every metric declares which events move it (a contract-tested lineage graph), and the serving layer keeps reads fresh by invalidating its cache when events arrive — a measured behavior, not a slogan ([docs/freshness-benchmark.md](docs/freshness-benchmark.md)). One serving boundary on top of that axis:

- streaming ingestion for operational events (validated, enriched, journaled)
- a semantic layer that exposes entities, metrics, lineage, and query endpoints
- typed, versioned contracts — each metric ships with its source events and a staleness budget
- Python and TypeScript clients that speak the same API surface

Consumers are whoever needs the number now: humans, dashboards, downstream services, and AI agents — agents are one consumer, not the product.

## Highlights

- **Measured event-to-metric freshness**: an event entering the pipeline is reflected in `GET /v1/metrics/*` in **1.06 s p50 / 1.99 s p95** on production defaults (event-driven cache invalidation, no webhook registration required), tunable to **238 ms p50**; a plain TTL cache on the same pipeline sits at ~15 s p50. Reproducible: `python scripts/benchmark_freshness.py` → [docs/freshness-benchmark.md](docs/freshness-benchmark.md)
- **Event→metric lineage as a contract**: all six metrics (`revenue`, `order_count`, `avg_order_value`, `conversion_rate`, `active_sessions`, `error_rate`) declare their source events and serving table in versioned contracts with a 2.5 s p95 staleness budget, exposed through `/v1/catalog` and `/v1/contracts` and pinned by tests against the actual write path
- **Release line through `v1.4.0`** on PyPI (`agentflow-runtime`, `agentflow-client`) and npm (`@yuliaedomskikh/agentflow-client`), published via OIDC Trusted Publishers with SLSA provenance attestations on every artifact. Live registry table + re-verify recipe: [docs/dv2-multi-branch/RELEASE_STATUS.md](docs/dv2-multi-branch/RELEASE_STATUS.md)
- **561 unit tests and the 842-test Windows no-Docker suite green locally**; CI runs 12 required status checks (lint, schema-check, test-unit, test-integration, helm-schema-live, perf-check, terraform-validate, bandit, safety, npm-audit, trivy, contract). Branch protection requires every one of them
- **Sub-second entity lookups**: entity p50 `38-55 ms`, entity p99 `167 ms` on local hardware (–82% from the 2026-04-23 baseline after the PII masker + tenant qualification cache wins). CI runner thresholds are documented separately in [docs/perf/ci-hardware-gap-2026-05-24.md](docs/perf/ci-hardware-gap-2026-05-24.md)
- **Dual SDK parity** for Python (`agentflow-client`) and TypeScript (`@yuliaedomskikh/agentflow-client`), including retry policies, circuit breakers, batching, pagination, contract pinning, idempotency keys, and `as_of` historical reads
- **Two CDC paths**: production-grade Debezium + Kafka Connect (Helm chart hardened with NetworkPolicy + PDB + securityContext, schema-validated on every deploy), and a ClickHouse `MaterializedPostgreSQL` per-branch fan-out for the DV2 demo cluster
- **Security hardening in the hot path**: tenant isolation across every read surface, parameterized queries, `sqlglot` AST validation for NL-to-SQL, fail-closed auth middleware, plaintext secret scrubbing, and a Bandit baseline gate for new findings only
- **On-call playbooks for production incidents** in [docs/runbooks/](docs/runbooks/README.md): symptom-keyed runbooks for API 5xx spikes, auth fail-closed regressions, CDC lag, Load Test gate failures, and PyPI/npm release rollback
- **DV2 demo triptych**: voice-narrated terminal cast ([demo_voiced.mp4](docs/dv2-multi-branch/demo_voiced.mp4), 92s) + web-UI screencast covering Argo Workflows and MinIO ([demo_webui.mp4](docs/dv2-multi-branch/demo_webui.mp4), 60s) + dbt docs lineage walk-through ([demo_dbt_docs.mp4](docs/dv2-multi-branch/demo_dbt_docs.mp4), 55s)

## Quick start

> **Upgrading from v1.0.x?** See the [v1.1 migration guide](docs/migration/v1.1.md) before installing.

Prerequisites:

- Python `3.11+`
- `make`
- Docker Compose (`make demo` starts Redis)

PowerShell 7+:

```powershell
git clone https://github.com/brownjuly2003-code/agentflow.git
cd agentflow
. .\scripts\setup.ps1
make demo
```

macOS / Linux:

```bash
git clone https://github.com/brownjuly2003-code/agentflow.git
cd agentflow
source ./scripts/setup.sh
make demo
```

`make demo` seeds local data, starts Redis, and serves the API on `http://localhost:8000`. Swagger UI is available at `http://localhost:8000/docs`.

Try it:

```bash
curl http://localhost:8000/v1/entity/order/ORD-20260404-1001

curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question":"Show me top 3 products"}'
```

Local demo runs without API-key enforcement unless you explicitly configure `AGENTFLOW_API_KEYS_FILE`.

## Architecture

```text
Event sources -> Kafka -> Flink -> Iceberg ----\
                                                -> Semantic layer -> FastAPI -> Agent / SDK
Local demo   -> local_pipeline -> DuckDB ------/
```

Stack:

- **Ingestion**: Kafka producers, Debezium/Kafka Connect CDC, and a local synthetic pipeline
- **Processing**: Flink plus validation and enrichment stages
- **Storage**: Iceberg for production-shaped tables, DuckDB for the local serving path
- **Serving**: FastAPI, contract registry, lineage, search, and operational endpoints
- **Orchestration**: Dagster
- **IaC**: Terraform, Helm, Docker Compose, and a Fly.io demo config

See [docs/architecture.md](docs/architecture.md) for the detailed design, trade-offs, and deployment topologies.

CDC source capture is standardized on Debezium/Kafka Connect; downstream consumers use the canonical AgentFlow CDC contract defined in [ADR 0005](docs/decisions/0005-cdc-ingestion-strategy.md).

## What's inside

| Area | Files |
|------|-------|
| API core | `src/serving/api/` |
| Semantic layer | `src/serving/semantic_layer/` |
| Python SDK | `sdk/agentflow/` |
| TypeScript SDK | `sdk-ts/src/` |
| Agent integrations | `integrations/agentflow_integrations/` (LangChain, LlamaIndex, CrewAI, MCP) |
| Flink jobs | `src/processing/flink_jobs/` |
| Test suites | `tests/` |
| Planning trail | `docs/plans/` |
| Public site | `site/` |
| IaC | `infrastructure/terraform/`, `infrastructure/dv2/`, `helm/`, `k8s/` |
| DV2.0 warehouse | `warehouse/agentflow/dv2/` (hubs / links / satellites + X5 loader) |

## Documentation

**Core**
- [Architecture](docs/architecture.md) — system context, data flow, failure modes
- [API Reference](docs/api-reference.md) — endpoint-by-endpoint curl / Python / TypeScript examples
- [Operational Runbook](docs/runbook.md) + [On-Call Runbooks](docs/runbooks/README.md) — local stack, CDC capture, and production-incident playbooks
- [Security Audit](docs/security-audit.md) — threat model, controls, and evidence
- [Glossary](docs/glossary.md) — interview-ready explanations of the core technical terms
- [Interactive Technical Walkthrough](docs/index.md) — MkDocs Material guide (Mermaid architecture, SDK, deployment, observability)

**Deep dives**
- [DV2.0 Multi-Branch Extension](docs/dv2-multi-branch/SESSION_HANDOFF.md) — Data Vault 2.0 model for mid-market e-com (5 locations / 3 jurisdictions): [schema](docs/dv2-multi-branch/schema_dv2.md), [end-to-end flow](docs/dv2-multi-branch/architecture.md), [demo evidence](docs/dv2-multi-branch/demo_evidence.md)
- [CDC Deployment Plan](docs/plans/2026-04-debezium-kafka-connect-deployment-plan.md) — Debezium/Kafka Connect rollout and implementation trail
- [Competitive Analysis](docs/competitive-analysis.md) · [Release Readiness](docs/release-readiness.md) · [Audit History](docs/audit-history.md)
- [Fly.io Demo Deploy](deploy/fly/README.md) — minimal hosted demo
- [Session Handoff](docs/SESSION_HANDOFF.md) — pick-up-cold state, open items, recent lessons
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Development

```bash
# verified release slice
python -m pytest tests/unit tests/integration tests/sdk -q

# benchmark and regression gate
python scripts/run_benchmark.py
python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current .artifacts/load/results.json --max-regress 20

# benchmark trend: [.github/perf-history.json](.github/perf-history.json) is appended on every main push;
# render the history locally with `make perf-plot` (writes docs/perf/history.html).

# contracts and security
python scripts/generate_contracts.py --check
bandit -r src sdk --ini .bandit --severity-level medium -f json -o .tmp/bandit-current.json
python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json
```

## Status

**`v1.4.0` is the current release line** (PyPI `agentflow-runtime` /
`agentflow-client`, npm `@yuliaedomskikh/agentflow-client`, all three
published 2026-05-24T21:05Z via OIDC Trusted Publishers with SLSA
provenance attestations). Live registry table and re-verify recipe live in
[docs/dv2-multi-branch/RELEASE_STATUS.md](docs/dv2-multi-branch/RELEASE_STATUS.md).

The `v1.1.0` → `v1.4.0` arc landed in four increments on top of the
2026-04-27 audit closure sprint:

- **`v1.1.0`** — audit closure: tenant isolation across every read
  surface, SQL guard centralization on `sqlglot`, entity allowlist
  enforcement, fail-closed auth, secrets rotated, Helm hardening,
  `npm audit` clean, vulnerable dep bumps, OpenAPI drift gate, 12
  required status checks, Python SDK alignment with server v1
  contract (F1–F10).
- **`v1.2.0`** — DV2 multi-branch warehouse merged to `main`: 38 DV2.0
  tables (8 hubs / 8 links / 22+ satellites), Argo Workflows
  `dv2-refresh` template, dbt project with 3 mart models + 12 tests,
  per-branch CDC fan-out via ClickHouse `MaterializedPostgreSQL`, and
  the first voice-narrated terminal cast demo.
- **`v1.3.0`** — `helm/kafka-connect` chart hardening matched to
  `helm/agentflow` (NetworkPolicy + PDB + pod/container securityContext
  + `/tmp` emptyDir, all schema-required and off-by-default), Helm live
  validation parametrized across both charts, A03 CI hardware-gap
  acceptance with Load Test gates raised to 1.3x baseline, and the DV2
  demo triptych completed (terminal + web-UI + dbt docs screencasts).
- **`v1.4.0`** — maintenance release: top-level handoff and release docs,
  on-call runbooks, `SECURITY.md`, issue/PR templates, contract/DORA CI
  hardening, Dependabot/editorconfig repo hygiene, type-stub adoption, and
  the Tier A dependency wave (`mypy`, Terraform AWS provider, TypeScript,
  GitHub Actions, Vitest). No runtime API changes from `v1.3.0`.

CI on `main` is fully green across all 12 required checks. Local
hardware sustains entity p99 `167 ms` (the local SLO target); CI runner
thresholds are intentionally divergent and documented in
[docs/perf/ci-hardware-gap-2026-05-24.md](docs/perf/ci-hardware-gap-2026-05-24.md).

**Remaining external gates** require inputs outside this repository. AWS is not
one of them for the current plan: Terraform apply is intentionally out of scope
for this portfolio project — provisioning a paid managed-AWS environment adds
recurring cloud cost without demonstrating new engineering capability, so the
Helm / Terraform / k8s artifacts are validated on a local kind cluster in CI
instead. The DV2/X5 demo uses the documented HF Datasets/Backblaze-compatible
cold-tier path for derived/anonymized parquet.

- Production CDC source onboarding (hostnames, credentials, owners,
  private network path) — runbook ready in
  [docs/operations/cdc-production-onboarding.md](docs/operations/cdc-production-onboarding.md).
- Real PMF / pricing evidence and a public benchmark on
  production-grade hardware (`c8g.4xlarge+`).
- External pen-test attestation.
- Optional: paid larger GHA runner or self-hosted runner if the CI
  hardware-gap thresholds need to be tightened.

The project-local Pi skill at
`.pi/skills/external-gate-evidence-intake` and the
[External Gate Evidence Intake Checklist](docs/operations/external-gate-evidence-intake.md)
codify what evidence must arrive before any of those gates close.

## Screenshots

| Admin UI | API docs |
|----------|----------|
| <img src="docs/screenshots/admin-ui.png" alt="AgentFlow admin UI" width="420"> | <img src="docs/screenshots/swagger-docs.png" alt="AgentFlow API docs" width="420"> |

| Landing page | Benchmark run |
|--------------|---------------|
| <img src="docs/screenshots/landing-page.png" alt="AgentFlow landing page" width="420"> | <img src="docs/screenshots/benchmark-terminal.png" alt="AgentFlow benchmark terminal" width="420"> |

Capture notes and publish-time checks are listed in [docs/publication-checklist.md](docs/publication-checklist.md).

## License

MIT. See [LICENSE](LICENSE).

## Credits

Built as a data-engineering reference project. Initial release cycle
`2026-04-10` → `2026-04-20`, post-audit hardening and DV2 extension
through `2026-05-25` (`v1.4.0`). Full implementation trail preserved in
`docs/plans/`, `docs/codex-tasks/`, and `docs/lessons/`.
