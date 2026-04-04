# ADR-001: Streaming-First Architecture

## Status
Accepted

## Context
AI agents serving customer queries need fresh data. A traditional batch ETL pipeline with hourly or daily refreshes means agents answer with stale information, leading to incorrect responses and poor user experience.

We need to decide: batch-first with streaming add-ons, or streaming-first with batch as a special case?

## Decision
**Streaming-first.** All data enters through Kafka, is processed by Flink in real-time, and lands in Iceberg tables continuously. Batch workloads (aggregations, compaction) run on top of the same data using the same Flink engine with bounded sources.

## Consequences

### Positive
- Sub-second data freshness for agent queries
- Single processing semantics (no batch/stream divergence bugs)
- Natural fit for event-driven microservices
- Exactly-once processing with Flink checkpointing

### Negative
- Higher operational complexity than pure batch
- Flink has a steeper learning curve than Spark for batch workloads
- Debugging streaming jobs is harder than batch (no "re-run from start" simplicity)
- Cost: always-on Flink cluster vs. ephemeral Spark clusters

### Mitigations
- Iceberg time-travel for debugging (replay any point in time)
- Comprehensive monitoring with Prometheus + Grafana
- Autoscaling Flink to reduce cost during low-traffic periods
