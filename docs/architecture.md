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

1. **Ingestion**: Events arrive via Kafka producers (orders, payments, clicks) or CDC (product catalog)
2. **Processing**: Flink validates (schema + semantic), enriches, deduplicates, and routes events
3. **Storage**: Valid events land in Iceberg tables on S3, partitioned by date/entity
4. **Quality**: Pre-storage gates check schema + semantic rules. Failures → dead letter topic
5. **Serving**: Agent API reads from Iceberg via Trino / Athena

### Local: Generate → Validate → Enrich → DuckDB

Same pipeline logic, no infrastructure dependencies:

1. **Generate**: `local_pipeline.py` creates realistic e-commerce events
2. **Validate**: Schema validation (Pydantic) + semantic validation (business rules)
3. **Enrich**: Domain enrichment per event type (order sizing, click classification, payment risk)
4. **Store**: Validated events written to DuckDB file (`agentflow_demo.duckdb`)
5. **Serve**: Agent API reads from same DuckDB via `QueryEngine`

Both paths use the **same validator and enrichment code** (`src/quality/`, `src/processing/transformations/`).

### Batch Path (daily)

1. **Orchestration**: Dagster triggers compaction, aggregation, and quality reports
2. **User profiles**: Materialized from `orders_v2` → `users_enriched`
3. **Quality report**: Row counts, null rates, dead letter ratio
4. **Compaction**: Iceberg snapshot expiry + data file compaction (production only)

## Technology Choices

See [Architecture Decision Records](decisions/) for detailed trade-off analysis.

| Component | Choice | Runner-up | Key differentiator |
|-----------|--------|-----------|-------------------|
| Streaming | Kafka 3.7 (KRaft) | Pulsar | Ecosystem maturity, MSK managed service |
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
| API overload | Agent queries fail | Rate limiting, connection pooling, horizontal scaling |

## Security

### Implemented
- **API authentication**: API key via `X-API-Key` header (set `AGENTFLOW_API_KEYS` env var)
- **Rate limiting**: Per-key sliding window, configurable via `AGENTFLOW_RATE_LIMIT_RPM` (default: 120/min)
- **Health/docs exempt**: `/v1/health`, `/docs`, `/metrics` don't require auth
- **No secrets in code**: All credentials via environment variables
- **Terraform state**: Encrypted S3 backend with DynamoDB locking

### Production (via infrastructure)
- Kafka: TLS in-transit, SASL authentication (MSK config)
- S3: SSE-KMS encryption, bucket policy restricts to VPC endpoints
- Network: Private subnets, security groups per component
