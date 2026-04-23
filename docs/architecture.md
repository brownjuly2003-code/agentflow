# Architecture Overview

## Context

AgentFlow is a real-time data platform designed to serve AI agents — not dashboards, not analysts. AI agents need sub-second data freshness, semantic context, and quality guarantees that traditional batch-oriented platforms don't provide.

## System Context (C4 Level 1)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Web Store   │     │   Payment    │     │  Inventory   │
│  (events)    │     │   Gateway    │     │   Service    │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌─────────────────────────────────────────────────────────┐
│                    AgentFlow Platform                    │
│                                                         │
│  Kafka → Flink → Iceberg → Semantic Layer → Agent API   │
└─────────────────────────────┬───────────────���───────────┘
                              │
                    ┌─────────▼──────────┐
                    │    AI Agents       │
                    │  (customer support,│
                    │   analytics,       │
                    │   automation)      │
                    └────────────────────┘
```

## Key Design Principles

1. **Streaming-first**: Batch is a special case of streaming (bounded stream). One codebase, one semantics.
2. **Quality gates before storage**: Bad data never reaches the serving layer. Agents never see it.
3. **Semantic over raw**: Agents query entities and metrics, not tables and columns.
4. **Cost-aware**: Every component has autoscaling and lifecycle policies. We measure $/GB processed.
5. **Observable**: If you can't measure it, you can't operate it. Every stage emits latency, throughput, and error metrics.

## Data Flow

### Production: Kafka → Flink → Iceberg (p50 latency: ~220ms)

1. **Ingestion**: Events arrive via Kafka producers (orders, payments, clicks) or Debezium CDC connectors running on Kafka Connect
2. **Processing**: Flink validates (schema + semantic), enriches, deduplicates, and routes events
3. **Storage**: Valid events land in Iceberg tables; production uses AWS Glue as the catalog over object storage
4. **Quality**: Pre-storage gates check schema + semantic rules. Failures → dead letter topic
5. **Serving**: Agent API reads from Iceberg via Trino / Athena

For CDC sources, Debezium/Kafka Connect handles source capture while a shared normalizer converts Postgres/MySQL envelopes into one canonical AgentFlow CDC contract before validation. See [ADR 0005](decisions/0005-cdc-ingestion-strategy.md).

### Local: Generate → Validate → Enrich → DuckDB + Iceberg

Same pipeline logic, no infrastructure dependencies:

1. **Generate**: `local_pipeline.py` creates realistic e-commerce events
2. **Validate**: Schema validation (Pydantic) + semantic validation (business rules)
3. **Enrich**: Domain enrichment per event type (order sizing, click classification, payment risk)
4. **Store**: Validated events written to DuckDB for serving and to Iceberg via PyIceberg
5. **Serve**: Agent API reads from DuckDB while `/v1/health` reports Iceberg row counts
6. **Catalog**: Development uses the local REST catalog from `docker-compose.iceberg.yml`; production uses AWS Glue

Both paths use the **same validator and enrichment code** (`src/quality/`, `src/processing/transformations/`).

### Batch Path (daily)

1. **Orchestration**: Dagster triggers compaction, aggregation, and quality reports
2. **User profiles**: Materialized from `orders_v2` → `users_enriched`
3. **Quality report**: Row counts, null rates, dead letter ratio
4. **Compaction**: Iceberg snapshot expiry + data file compaction (production only)

## Serving & Control Plane

The serving layer has grown beyond the original read-only surface. The current API groups into four slices:

- **Core agent reads**: `/v1/entity`, `/v1/metrics`, `/v1/query`, `/v1/catalog`, `/v1/health`
- **Discovery and audit**: `/v1/search`, `/v1/contracts`, `/v1/lineage`, `/v1/changelog`
- **Operational workflows**: `/v1/batch`, `/v1/stream/events`, `/v1/deadletter`, `/v1/webhooks`, `/v1/alerts`, `/v1/slo`
- **SDK contract**: Python sync/async clients and a TypeScript client wrap the same HTTP surface

The API process also starts several background components:

- **DuckDBPool**: shared read cursors plus serialized writes for the local serving path
- **QueryCache**: Redis-backed metric cache with invalidation on new events
- **WebhookDispatcher**: polls validated pipeline events and delivers signed webhook callbacks
- **AlertDispatcher**: evaluates metric thresholds and records alert history
- **OutboxProcessor**: retries replay delivery from DuckDB outbox rows to Kafka

These components keep the local demo and the production architecture aligned around one agent-facing contract, even when the backing infrastructure differs.

## Technology Choices

See [Architecture Decision Records](decisions/) for detailed trade-off analysis.

| Component | Choice | Runner-up | Key differentiator |
|-----------|--------|-----------|-------------------|
| Streaming | Kafka 3.7 (KRaft) | Pulsar | Ecosystem maturity, MSK managed service |
| CDC capture | Debezium + Kafka Connect | Python-native connectors | Mature Postgres/MySQL CDC, built-in offsets/schema history, one ops model |
| Processing | Flink 1.19 | Spark Structured Streaming | True event-time, lower latency, native watermarks |
| Storage | Iceberg 1.5 | Delta Lake | Vendor-neutral, hidden partitioning, time-travel |
| Local query | DuckDB | SQLite | Columnar, fast analytics, Iceberg support |
| Orchestration | Dagster | Airflow | Software-defined assets, better testing, type safety |
| API | FastAPI | Flask | Async, auto-docs, Pydantic integration |
| IaC | Terraform | Pulumi | Team familiarity, HCL readability, module ecosystem |

## Failure Modes & Mitigations

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Kafka broker down | Reduced throughput | 3-broker cluster, replication factor 3, min.insync.replicas=2 |
| Flink job crash | Processing stops | Exactly-once checkpointing (30s), auto-restart on failure |
| Bad data in source | Incorrect agent answers | Pre-storage quality gates, dead letter topic, alerting |
| S3 outage | No new data in serving | Flink checkpoints to S3 pause; resumes on recovery |
| API overload | Agent queries fail | Per-key rate limiting, DuckDB connection pooling, horizontal scaling |
| Redis unavailable | Cache or rate-limit degradation | Metric cache misses fall back to source queries; rate limiter fail-opens instead of blocking the API |
| Webhook target failure | Lost downstream notification | Signed delivery logs, retries with backoff, alert/webhook history in DuckDB |

## Security

### Implemented
- **API authentication**: API key via `X-API-Key` header (set `AGENTFLOW_API_KEYS` env var)
- **Rate limiting**: Per-key sliding window with Redis backing when available and in-memory fallback for local/test, configurable via `AGENTFLOW_RATE_LIMIT_RPM` (default: 120/min)
- **Health/docs exempt**: `/v1/health`, `/docs`, `/metrics` don't require auth
- **No secrets in code**: All credentials via environment variables
- **Terraform state**: Encrypted S3 backend with DynamoDB locking

### Production (via infrastructure)
- Kafka: TLS in-transit, SASL authentication (MSK config)
- S3: SSE-KMS encryption, bucket policy restricts to VPC endpoints
- Network: Private subnets, security groups per component

## Observability & Operations

- **Metrics**: Prometheus scrapes `/metrics`; Grafana dashboards cover pipeline health plus support, ops, and merch journeys.
- **Tracing**: OpenTelemetry spans export to Jaeger through `OTEL_EXPORTER_OTLP_ENDPOINT`; the production-like compose stack exposes Jaeger on `:16686`.
- **Logs**: Structlog emits JSON logs with `trace_id`, `span_id`, `correlation_id`, and tenant context so incidents can be traced across API, cache, and background loops.
- **Operational APIs**: `/v1/alerts`, `/v1/webhooks`, `/v1/deadletter`, `/v1/slo`, and `/v1/stream/events` are part of the control plane, not side tooling.

## Deployment Topologies

| Environment | Primary components | Purpose |
|-------------|--------------------|---------|
| Local demo | `src.processing.local_pipeline` + DuckDB + FastAPI | Fastest path for developers and SDK examples |
| Prod-like Docker | `docker-compose.prod.yml` with Kafka, Redis, Jaeger, Prometheus, Grafana, API | Observability, E2E, and smoke coverage against a realistic stack |
| Chaos harness | `docker-compose.chaos.yml` + Toxiproxy + pytest chaos suite | Validate graceful degradation under Kafka/Redis failures |
| kind staging | `helm/agentflow`, `k8s/`, `scripts/k8s_staging_up.sh` | Production-shaped staging on a local Kubernetes cluster |
| Production | Managed Kafka/Flink/Iceberg/object storage + Helm/Terraform | Durable, autoscaled multi-service deployment |

## v1-v6 Capability Map

| Capability | Implementation | Architectural impact |
|------------|----------------|----------------------|
| Durable replay and outbox | `OutboxProcessor`, dead-letter replay, DuckDB outbox rows | Background delivery is retried without coupling API latency to Kafka availability |
| Redis-backed rate limiting | `AuthManager` + `RateLimiter` with fail-open fallback | Per-key throttling stays centralized in prod, while local/test can continue when Redis is absent |
| Typed SDK surface | `sdk/` and `sdk-ts/` | Python and TypeScript agents consume one HTTP contract instead of bespoke adapters |
| Distributed observability | OTel tracing, structlog correlation, `/metrics`, Grafana, Jaeger | API, background jobs, and streaming workflows share the same debugging context |
| Chaos engineering | `tests/chaos/`, `docker-compose.chaos.yml`, `config/toxiproxy.json` | Failure handling is exercised continuously rather than assumed from code review |
| Kubernetes staging | `helm/agentflow`, `k8s/kind-config.yaml`, staging scripts | Helm releases, image loading, and smoke validation can be rehearsed before production |
| DevContainer DX | `.devcontainer/` with Docker-in-Docker, Helm/kubectl, `kind`, `toxiproxy-cli` | Contributors get one workspace that can run local demo, chaos, and staging workflows |
