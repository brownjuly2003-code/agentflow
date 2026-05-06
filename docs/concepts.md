# Concepts

## Streaming-first

AgentFlow treats fresh operational context as the default. Batch jobs can still
exist, but the agent-facing model is built around bounded or unbounded event
streams that flow through the same validation and enrichment concepts.

This matters for agents because stale state can cause the wrong action:
answering a support ticket from an old order status, escalating an already
resolved incident, or recommending inventory that has just changed.

## Semantic layer

Agents do not call DuckDB or Iceberg tables directly. They use stable concepts:

- entities such as `order`, `user`, `product`, and `session`
- metrics such as `revenue` or `error_rate`
- natural-language questions translated into constrained SQL
- search, lineage, and contracts for discovery and auditability

The semantic layer owns the mapping from those concepts to backing storage. That
keeps client code small and lets the storage path evolve behind the API.

## Contracts

AgentFlow keeps schema contracts explicit so callers can reason about response
shape and compatibility. The API exposes contract listing, version lookup,
diffing, and candidate validation routes under `/v1/contracts`.

Contracts are also a boundary against accidental data drift: a new field can be
additive, while a removed or type-changed field needs a migration path.

## Local versus production-shaped paths

The local path is optimized for fast developer feedback:

- synthetic events
- DuckDB serving database
- local Redis for cache/rate-limit behavior
- FastAPI running on `localhost:8000`

The production-shaped path documents how the same concepts map onto:

- Kafka and Debezium/Kafka Connect
- Flink validation and enrichment jobs
- Iceberg storage
- Helm/Kubernetes manifests
- Terraform reference modules
- Prometheus, OpenTelemetry, Jaeger, and Grafana

Production operation still requires owner-owned environment decisions:
hostnames, secrets, cloud account wiring, retention policy, monitoring ownership,
and rollback ownership.

## Query safety

Natural-language query execution is constrained. The server validates translated
SQL and restricts the operation to allowed read-only shapes before executing it.
Entity and metric lookup paths use parameterized queries for untrusted values.

## Evidence boundary

Local gates and checked-in evidence show a strong application baseline. They do
not prove external infrastructure controls. Treat cloud apply, third-party
security assessment, object-lock retention, and formal compliance status as
separate owner-evidence workflows.
