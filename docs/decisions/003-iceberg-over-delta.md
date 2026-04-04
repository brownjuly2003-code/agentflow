# ADR-003: Apache Iceberg over Delta Lake

## Status
Accepted

## Context
We need an open table format for our data lake that supports:
- Streaming writes from Flink
- ACID transactions
- Schema evolution
- Time-travel for debugging
- Efficient partitioning for agent queries

Candidates:
1. Apache Iceberg 1.5
2. Delta Lake 3.x
3. Apache Hudi (ruled out: weaker Flink integration)

## Decision
**Apache Iceberg** as the table format for all warehouse tables.

## Comparison

| Criterion | Iceberg | Delta Lake |
|-----------|---------|------------|
| Vendor neutrality | Fully open, multi-engine | Databricks-originated, open-sourced |
| Flink integration | Native Flink connector | Community connector, less mature |
| Hidden partitioning | Yes (partition transforms) | No (explicit partition columns) |
| Schema evolution | Full (add, drop, rename, reorder) | Add/rename only |
| Time-travel | By snapshot ID or timestamp | By version number |
| Engine support | Flink, Spark, Trino, DuckDB, Athena | Spark, Trino (via connector), Athena |
| AWS integration | Athena, Glue, EMR native support | Databricks, EMR |
| Partition evolution | Change partitioning without rewrite | Requires data rewrite |

## Consequences

### Positive
- Vendor-neutral: no lock-in to Databricks ecosystem
- Hidden partitioning: agent queries don't need to know partition scheme
- Partition evolution: can change partitioning strategy as query patterns evolve
- Native Flink connector for streaming writes
- DuckDB support for fast local development

### Negative
- Smaller community than Delta Lake
- Fewer tutorials and blog posts available
- Iceberg maintenance (snapshot expiry, compaction) requires explicit orchestration

### Mitigations
- Dagster DAGs for automated compaction and snapshot management
- Iceberg REST catalog for metadata management
- Comprehensive documentation of our Iceberg configuration
