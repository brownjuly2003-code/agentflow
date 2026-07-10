# AgentFlow

> Event-native metrics layer: business metrics that move when events happen — measured **3.0 s p50** event-to-metric on the real Kafka→Flink→bridge path, **1.1 s p50** on the in-process demo shortcut. Live entity lookups, typed contracts, dual-language SDKs, and release-gated delivery for people, dashboards, services, and AI agents alike.

[![Release gate](https://img.shields.io/badge/release_gate-v2.0_published-brightgreen)](docs/dv2-multi-branch/RELEASE_STATUS.md)
[![codecov](https://codecov.io/gh/brownjuly2003-code/agentflow/branch/main/graph/badge.svg)](https://codecov.io/gh/brownjuly2003-code/agentflow)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

## Why this exists

BI on a replica answers yesterday's questions. Support, ops, and merch workflows need *current* orders, metrics, and health signals at the moment of decision — not a stale warehouse snapshot, not a pile of one-off service adapters, and not a cache that quietly serves 30-second-old numbers.

AgentFlow's axis is **event → live metric**: every metric declares which events move it (a contract-tested lineage graph), and the serving layer keeps reads fresh by invalidating its cache when events arrive — a measured behavior, not a slogan ([docs/freshness-benchmark.md](docs/freshness-benchmark.md), [real-path S8](docs/perf/freshness-e2e-realpath.md)). One serving boundary on top of that axis:

- streaming ingestion for operational events (validated, enriched, journaled)
- a semantic layer that exposes entities, metrics, lineage, and query endpoints
- typed, versioned contracts — each metric ships with its source events and a staleness budget
- Python and TypeScript clients that speak the same API surface

Consumers are whoever needs the number now: humans, dashboards, downstream services, and AI agents — agents are one consumer, not the product.

## Highlights

- **Measured event-to-metric freshness** — two measured arms, not one number:
  - **Real path** (Kafka → Flink 2.3.0 → serving bridge → ClickHouse → `GET /v1/metrics/*` with Redis push invalidation): **3.02 s p50 / 5.70 s p95** (n=20, Mac/Colima) — [S8 e2e](docs/perf/freshness-e2e-realpath.md), `python scripts/benchmark_freshness_e2e.py`
  - **In-process demo shortcut** (`local_pipeline` → DuckDB, no Kafka/Flink): **1.06 s p50 / 1.99 s p95**, tunable to **238 ms p50**; TTL-only ~15 s — [demo benchmark](docs/freshness-benchmark.md), `python scripts/benchmark_freshness.py`
  Do not present the 1.06 s figure as the production streaming path.
- **Measured write-path throughput** — bridge apply **87.4 events/s** on a 400-event burst (catch-up 4.6 s, peak lag 0) after three measured optimization steps (8 → 11.4 → 22.9 → 87.4), and a **4 h endurance soak** at the delivered ~47 eps with bounded lag, flat bridge RSS/FDs, one live fault replayed exactly-once, and zero cache drift — [q14 report](docs/perf/throughput-realpath-q14-2026-07-10.md), [S11 soak](docs/perf/soak-s11-2026-07-10.md)
- **At scale on its own data** — 4 years of the synthetic legend's history (**51.2 M rows, 2.87 M orders, 10.66 M Chestny Znak marking codes**) generated deterministically into the real raw-vault DDL; analyst queries answer in 20–730 ms and all 17 generator-spec invariants hold, including a full-scan GS1 check-digit validation — [S13 report](docs/perf/scale-own-data-2026-07-11.md), `python scripts/benchmark_scale_own_data.py`
- **Lineage as a contract** — all six metrics declare their source events, serving table, and a 2.5 s p95 staleness budget in versioned contracts, exposed through `/v1/catalog` and `/v1/contracts` and pinned by tests against the actual write path
- **Published release line through `v2.0.0`** on PyPI (`agentflow-runtime`, `agentflow-client`) and npm (`@yuliaedomskikh/agentflow-client`) via OIDC Trusted Publishers with SLSA provenance on every artifact
- **Tested and gated** — 1,500+ unit tests plus a broad Windows no-Docker suite; CI enforces 13 required status checks (lint, schema, unit, integration, helm, perf, terraform, bandit, safety, npm-audit, trivy, contract, build-smoke) through branch protection
- **Dual SDK parity** across Python and TypeScript — retries, circuit breakers, batching, pagination, contract pinning, idempotency keys, `as_of` historical reads — over sub-second entity lookups (p50 `38–55 ms`, p99 `167 ms` on local hardware)
- **Security in the hot path** — tenant isolation on every read surface, parameterized queries, `sqlglot` AST validation for NL-to-SQL, fail-closed auth, secret scrubbing, and a Bandit gate for new findings
- **Production-shaped extras** — two CDC paths (hardened Debezium/Kafka Connect + a ClickHouse per-branch fan-out), on-call [runbooks](docs/runbooks/README.md), and a [narrated demo](docs/dv2-multi-branch/) of the DV2 multi-branch warehouse

## Quick start

> **Upgrading from v1.0.x?** See the [v1.1 migration guide](docs/migration/v1.1.md) before installing.

Prerequisites:

- Python `3.11+`
- `make`
- Docker Compose (`make demo` starts Redis and the ClickHouse serving store)

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

`make demo` starts Redis and ClickHouse, seeds demo data through the full pipeline (validated events land in the ClickHouse serving store), and serves the API on `http://localhost:8000`. Swagger UI is available at `http://localhost:8000/docs`.

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
Event sources -> Kafka -> Flink -> Iceberg --------\
                                                    -> Semantic layer -> FastAPI -> Agent / SDK
Local demo   -> local_pipeline -> ClickHouse ------/
                       (DuckDB stays the local lake / test store)
```

Stack:

- **Ingestion**: Kafka producers, Debezium/Kafka Connect CDC, and a local synthetic pipeline
- **Processing**: Flink plus validation and enrichment stages
- **Storage**: Iceberg for production-shaped tables; **ClickHouse is the serving store** (ADR 0006 — ReplacingMergeTree upserts, `final=1` reads), DuckDB the local-dev / test store
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
| Design decisions | `docs/decisions/` (ADRs) |
| Public site | `site/` |
| IaC | `infrastructure/terraform/`, `infrastructure/dv2/`, `helm/`, `k8s/` |
| DV2.0 warehouse | `warehouse/agentflow/dv2/` (hubs / links / satellites + real-dataset loader) |

## Documentation

**Core**
- [Architecture](docs/architecture.md) — system context, data flow, failure modes
- [API Reference](docs/api-reference.md) — endpoint-by-endpoint curl / Python / TypeScript examples
- [Operational Runbook](docs/runbook.md) + [On-Call Runbooks](docs/runbooks/README.md) — local stack, CDC capture, and production-incident playbooks
- [Security Audit](docs/security-audit.md) — threat model, controls, and evidence
- [Glossary](docs/glossary.md) — interview-ready explanations of the core technical terms
- [Interactive Technical Walkthrough](docs/index.md) — MkDocs Material guide (Mermaid architecture, SDK, deployment, observability)

**Deep dives**
- [DV2.0 Multi-Branch Extension](docs/dv2-multi-branch/architecture.md) — Data Vault 2.0 model for mid-market e-com (5 locations / 3 jurisdictions): [schema](docs/dv2-multi-branch/schema_dv2.md), [end-to-end flow](docs/dv2-multi-branch/architecture.md), [demo evidence](docs/dv2-multi-branch/demo_evidence.md)
- [CDC Deployment Plan](docs/plans/2026-04-debezium-kafka-connect-deployment-plan.md) — Debezium/Kafka Connect rollout
- [Competitive Analysis](docs/competitive-analysis.md) · [Release Readiness](docs/release-readiness.md) · [Cost Analysis](docs/cost-analysis.md)
- [Fly.io Demo Deploy](deploy/fly/README.md) — minimal hosted demo
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

**`v2.0.0` is the current release line** — PyPI `agentflow-runtime` /
`agentflow-client` and npm `@yuliaedomskikh/agentflow-client`, all
published via OIDC Trusted Publishers with SLSA provenance attestations.
CI on `main` is green across all 13 required checks. The living
engineering status — what is proven, what is in progress, what is next —
is tracked in [docs/STATUS.md](docs/STATUS.md).

The `v1.1.0` → `v2.0.0` arc landed in seven increments on top of a security
audit-closure sprint:

- **`v1.1.0`** — audit closure: tenant isolation across every read
  surface, SQL guard centralized on `sqlglot`, entity allowlist
  enforcement, fail-closed auth, secret rotation, Helm hardening,
  OpenAPI drift gate, and the required status checks.
- **`v1.2.0`** — DV2 multi-branch warehouse: 38 Data Vault 2.0 tables
  (8 hubs / 8 links / 22+ satellites), an Argo Workflows `dv2-refresh`
  template, a dbt project (3 mart models + 12 tests), and per-branch CDC
  fan-out via ClickHouse `MaterializedPostgreSQL`.
- **`v1.3.0`** — `helm/kafka-connect` hardening matched to `helm/agentflow`
  (NetworkPolicy + PDB + securityContext), live Helm validation across both
  charts, and the narrated DV2 demo (terminal + web-UI + dbt docs).
- **`v1.4.0`** — maintenance: on-call runbooks, `SECURITY.md`, issue/PR
  templates, contract/DORA CI hardening, repo hygiene, and a dependency
  wave (`mypy`, Terraform AWS provider, TypeScript, GitHub Actions,
  Vitest). No runtime API changes from `v1.3.0`.
- **`v1.5.0`** — security & correctness hardening: argon2id key hashing
  with an O(1) peppered lookup index (M-C4), an NL→SQL guard bypass fix
  (typed `read_csv` / `read_parquet` scan functions now denied in
  projection position), `sqlglot` control-byte and mutation-target
  repairs, and a strict-`mypy` expansion across the orchestration and
  freshness slices. No public API changes.
- **`v1.6.0`** — the architecture-fixing release: ClickHouse becomes the
  shipped serving engine (pipeline sink, `ReplacingMergeTree` row versions,
  backend-routed event scan, a dedicated CI E2E lane against a real
  ClickHouse), PII protection moves from the removed app-level string-parse
  gate to engine-enforced vault governance (fail-closed column grants,
  per-jurisdiction officer roles, row policies, `SQL SECURITY DEFINER`
  views — every live adversarial probe green), plus the vendored NL→SQL
  generation engine (LangGraph, routed through GraceKelly), the DV2 raw
  vault on PostgreSQL with `LISTEN`/`NOTIFY` freshness, the MinIO-backed
  PyIceberg catalog, and the OpenSSF Scorecard channel (5.8 → 7.0).
- **`v2.0.0`** — the demo universe re-founded and the scale path shipped:
  the business legend re-pinned end-to-end to an own-brand
  kitchen-appliance importer in ₽ (breaking for the retired
  fashion-retail/USD surfaces), the external real-retailer dataset removed
  outright (breaking: loader deleted, its at-scale benchmark retired as
  historical), the control plane externalized to PostgreSQL behind the
  `ControlPlaneStore` port (ADR 0010, six slices incl. the Helm scale
  profile), three operational read surfaces split out of the agent catalog
  (ADR 0011: Order 360, stuck-orders worklist, exception inbox), and the
  three-node demo topology (ADR 0012) implemented and deployed to Hugging
  Face Spaces (the `center` hub and the `spb` edge answer live; `ekb` and
  the standalone demo Space are paused — the free tier caps how many
  `cpu-basic` Spaces one account runs at once, and other projects hold the
  rest) — plus the G2 audit closure (spec/seed
  consistency, journal-scan hardening, live evidence re-captures).

The tagged line and `main` are in sync as of `v2.0.0`. See the
[changelog](CHANGELOG.md) for full detail.

### Scope

This is a reference data-engineering project. The streaming, warehouse, and
deployment artifacts (Flink, Iceberg, Helm, Terraform, k8s) are exercised
against a local pipeline and a kind cluster in CI rather than a managed
cloud. Wiring it to a live production source needs inputs that live outside
the repo — CDC source onboarding (runbook ready in
[docs/operations/cdc-production-onboarding.md](docs/operations/cdc-production-onboarding.md)),
a public benchmark on production-grade hardware, and an external pen-test
attestation.

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
`2026-04-10` → `2026-04-20`, with post-audit hardening and the DV2
extension landing through `v1.4.0`. Architecture decisions are recorded as
ADRs in [docs/decisions/](docs/decisions/).
