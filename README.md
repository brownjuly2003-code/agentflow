# AgentFlow - Agent Data Serving Platform

[![CI workflow](https://img.shields.io/badge/CI-configured-0A66C2)](.github/workflows/ci.yml)
[![Security workflow](https://img.shields.io/badge/Security-configured-0A66C2)](.github/workflows/security.yml)
[![Load test workflow](https://img.shields.io/badge/Load%20test-configured-0A66C2)](.github/workflows/load-test.yml)
[![Chaos workflow](https://img.shields.io/badge/Chaos-configured-0A66C2)](.github/workflows/chaos.yml)
[![Mutation workflow](https://img.shields.io/badge/Mutation-configured-0A66C2)](.github/workflows/mutation.yml)
[![E2E workflow](https://img.shields.io/badge/E2E-configured-0A66C2)](.github/workflows/e2e.yml)
[![Coverage](https://img.shields.io/badge/Coverage-see%20quality%20report-0A66C2)](docs/quality.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> Real-time data layer for AI agents.
> Kafka -> Flink -> Iceberg or DuckDB -> FastAPI.
> Query entities, metrics, and natural-language questions without building one-off agent APIs.

## Why AgentFlow

Traditional warehouses answer dashboards well, but support, ops, and merch agents need live operational context while a conversation is still in flight.

AgentFlow keeps the agent-facing contract simple:
- fresh business entities such as orders, users, products, and sessions
- typed SDKs for Python and TypeScript
- one API surface for lookup, metrics, search, batch, streaming, lineage, and health

This repository is explicit about current state: the local demo path is production-shaped, but the published benchmark in `docs/benchmark.md` is the actual local baseline, not a marketing number.

## Quick Start (< 5 min)

Prerequisites:
- Python 3.11+
- Make
- Docker only if you want the full local stack instead of the no-Docker demo path

macOS / Linux:

```bash
git clone https://github.com/username/agentflow.git
cd agentflow
source ./scripts/setup.sh
make demo
```

PowerShell 7+:

```powershell
git clone https://github.com/username/agentflow.git
cd agentflow
. .\scripts\setup.ps1
make demo
```

`make demo` seeds 500 events into `agentflow_demo.duckdb` and starts the API on `http://localhost:8000`.

In a second terminal:

```python
from agentflow import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="dev-key")
result = client.query("Show me top 3 products")
metric = client.get_metric("revenue", "24h")
print(result.answer)
print(metric.value)
```

If API keys are configured, replace `dev-key` with a value from `config/api_keys.yaml` or `AGENTFLOW_API_KEYS`.

## How It Works

```text
Sources -> Kafka -> Flink -> Iceberg -> Semantic layer -> FastAPI -> Agent
                     \-> local pipeline -> DuckDB -------^
```

- Local demo: `src.processing.local_pipeline` validates, enriches, and writes to DuckDB, with optional local Iceberg writes when `config/iceberg.yaml` is present.
- Production path: Kafka + Flink feed Iceberg tables, while the API serves the same entity, metric, and query contract.
- The semantic layer hides raw tables behind entities, metrics, query translation, schema contracts, and lineage metadata.

## Agent Integrations

- Python SDK: `sdk/` provides `AgentFlowClient` and `AsyncAgentFlowClient`.
- TypeScript SDK: `sdk-ts/` provides `@agentflow/client` for Node.js and browser-side agents.
- Framework adapters: `integrations/` ships LangChain, LlamaIndex, and CrewAI helpers. See [docs/integrations.md](docs/integrations.md).
- Tool definitions: `docs/agent-tools/claude-tools.json` and `docs/agent-tools/openai-tools.json` export the core API surface for tool-calling agents.

## Core API

| Endpoint | What it does | Example | Latest local p50 |
|----------|--------------|---------|------------------|
| `GET /v1/entity/{type}/{id}` | Return current entity state, with optional `as_of` time travel | `/v1/entity/order/ORD-20260404-1001` | 8.7s |
| `GET /v1/metrics/{name}` | Return KPI value for a window, with optional `as_of` | `/v1/metrics/revenue?window=24h` | 8.7s |
| `POST /v1/query` | Translate natural language to SQL and return rows; supports cursor pagination | `{"question":"Show me top 3 products","limit":3}` | 8.7s |
| `GET /v1/health` | Return freshness, component health, and DuckDB pool stats | `/v1/health` | 9.6s |
| `GET /v1/catalog` | Discover entities, metrics, streaming sources, and audit sources | `/v1/catalog` | n/a |

Also available:
- `/v1/batch`
- `/v1/search`
- `/v1/stream/events`
- `/v1/contracts`
- `/v1/lineage/{entity_type}/{entity_id}`
- `/v1/deadletter`
- `/v1/webhooks`
- `/v1/alerts`
- `/v1/slo`
- `/v1/changelog`

The p50 values above come from the latest checked local benchmark in [docs/benchmark.md](docs/benchmark.md) on 2026-04-10.

## User Journeys

- Support agent: fetch `order` and `user` entities in one turn and answer "where is my order?" from live-ish operational data instead of stale warehouse snapshots.
- Ops agent: call `/v1/health`, `/v1/slo`, and `error_rate` metrics, then route signed webhooks or alert callbacks when freshness or latency drifts.
- Merch agent: use `/v1/metrics/revenue`, `/v1/query`, and `/v1/search` to pull KPI snapshots and ranked product answers without writing SQL by hand.

## Benchmarks

Latest benchmark file: [docs/benchmark.md](docs/benchmark.md)

- Environment: Windows 11, 18 logical cores, 15.5 GB RAM, Python 3.13.7
- Load profile: 50 users, spawn rate 10/s, duration 60s
- Aggregate result: p50 8.7s, p95 9.7s, p99 9.7s, 3.39 RPS, 0 failures
- Interpretation: this is the current local baseline; it does not yet match the target latencies described in `docs/product.md`

To regenerate the report:

```bash
python scripts/run_benchmark.py
```

## Architecture

- System design: [docs/architecture.md](docs/architecture.md)
- Quality dashboard: [docs/quality.md](docs/quality.md)
- Product framing and user journeys: [docs/product.md](docs/product.md)
- Integration quickstarts: [docs/integrations.md](docs/integrations.md)
- Runbook: [docs/runbook.md](docs/runbook.md)
- Release process: [RELEASING.md](RELEASING.md)

## Self-Hosted vs Cloud

| Area | In this repository | Not provided here |
|------|--------------------|-------------------|
| Local agent demo | DuckDB-backed demo path, FastAPI API, Python and TypeScript SDKs | Hosted sandbox or managed trial environment |
| Streaming stack | Docker compose files for Kafka, Flink, Iceberg, Redis, Prometheus, Grafana | Managed cloud control plane |
| Governance | API keys, rate limiting, schema contracts, lineage, dead-letter replay | SSO, hosted tenant admin, compliance workflow UI |
| Reliability tooling | Health endpoint, `/v1/slo`, benchmark script, webhook and alert dispatchers | Public SLA or managed on-call guarantees |

## Contributing

Run `make test` and `make lint` before opening changes. For broader setup and ops context, start with [docs/runbook.md](docs/runbook.md) and [docs/architecture.md](docs/architecture.md).
