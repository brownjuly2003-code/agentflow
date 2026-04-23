# ADR 0005: Standardize CDC ingestion on Debezium + Kafka Connect

## Status

Accepted - 2026-04-23

## Context

AgentFlow already ships a Debezium-based PostgreSQL connector configuration in `src/ingestion/connectors/postgres_cdc.py`, but the v1.1 backlog task `docs/codex-tasks/2026-04-22/T09-cdc-connectors.md` had drifted toward a separate Python-native WAL/binlog implementation.

Leaving both directions open creates architectural debt:

- Postgres and MySQL can end up with different capture semantics
- offset management and restart behavior can diverge by source
- schema change handling can fork between connector implementations
- downstream consumers can receive incompatible payload shapes
- the team would need to support two different operational models

The decision needs to cover both Postgres and MySQL and define one downstream CDC contract instead of exposing source-specific envelopes.

## Options considered

### 1. Debezium connectors on Kafka Connect

Pros:

- mature Postgres and MySQL CDC support
- built-in offset management, snapshot handling, and restart semantics
- schema history support already aligned with CDC use cases
- one capture model for both databases
- matches the existing placeholder code in the repository

Cons:

- adds Kafka Connect and Debezium plugins to the deployment footprint
- local CDC demos are heavier than a pure-Python process

### 2. Python-native Postgres and MySQL connectors

Pros:

- superficially consistent with the rest of the Python codebase
- no Kafka Connect runtime to operate

Cons:

- requires us to own WAL/binlog protocol handling, offsets, retries, and failover logic
- Postgres logical replication and MySQL binlog behavior would still need separate implementations
- schema change handling becomes custom project code instead of commodity CDC infrastructure
- higher maintenance burden for a feature that is not core product differentiation

### 3. Mixed strategy: Debezium for one source, Python-native for the other

Rejected immediately because it creates two payload contracts and two operational playbooks without a meaningful product benefit.

## Decision

Standardize CDC source capture on **Debezium running in Kafka Connect** for both Postgres and MySQL.

AgentFlow-owned Python code remains responsible for:

- connector configuration templates and registration workflow
- table-to-entity mapping
- normalization from raw Debezium envelopes into one AgentFlow CDC contract
- downstream validation, enrichment, and routing

AgentFlow will **not** build Python-native WAL/binlog consumers as part of the v1.1 CDC roadmap.

## Canonical CDC contract

Raw Debezium payloads are an internal capture format, not the contract consumed by the rest of the platform. Both Postgres and MySQL must be normalized into one canonical event shape before downstream processing.

Required fields:

| Field | Meaning |
| --- | --- |
| `event_id` | Stable unique id for the normalized CDC record |
| `event_type` | Domain event name from table mapping, or `ddl_change` for schema-control records |
| `operation` | `snapshot`, `insert`, `update`, `delete`, or `ddl` |
| `timestamp` | Source commit/change timestamp |
| `source` | `postgres_cdc` or `mysql_cdc` |
| `entity_type` | Domain entity mapped from source table |
| `entity_id` | Business key extracted from the mapped key column |
| `before` | Previous row image when available |
| `after` | New row image when available |
| `source_metadata` | Database, schema, table, connector, snapshot flag, and source position metadata |

Contract rules:

- Postgres and MySQL use the same field names and operation semantics
- Debezium-specific envelope details stay behind the normalizer boundary
- DDL/schema-change records use the same contract with `event_type = "ddl_change"`
- downstream Flink and serving code consume the normalized contract only

## Operational model

### Deployment dependencies

- Kafka cluster
- Kafka Connect worker(s)
- Debezium PostgreSQL and MySQL connector plugins
- Kafka Connect internal topics for config, offsets, and status
- connector-specific schema history topics

### Observability

- monitor connector/task health from Kafka Connect status and task-state metrics
- expose CDC lag and error-rate metrics per connector
- alert on connector failures, rising replication lag, and dead-letter growth in normalization

### Failure handling

- at-least-once delivery is acceptable for CDC ingestion
- offsets are stored by Kafka Connect, not by custom `cdc-offsets` application logic
- malformed or unmappable records go to a dead-letter path instead of forcing connector crash loops
- replay uses Kafka offsets and connector restart semantics, not source-specific custom recovery code

### Schema changes

- Debezium schema history is the system of record for source DDL
- the normalizer emits `ddl_change` control events for downstream awareness
- v1.1 consumers may ignore `ddl_change`, but the contract must preserve it

## Impact on source paths

### Postgres

- keep `src/ingestion/connectors/postgres_cdc.py` as the Debezium/Kafka Connect path
- follow-up work should extend it toward canonical topic naming, secrets handling, and normalization inputs
- do not add a separate Python logical-replication consumer

### MySQL

- add a matching Debezium MySQL connector configuration path
- reuse the same normalization layer, mapping rules, observability model, and failure handling
- do not add a standalone Python binlog reader

## Consequences

### Positive

- one CDC capture strategy across Postgres and MySQL
- mature connector semantics for offsets, snapshots, and schema history
- repo-owned code stays focused on domain normalization rather than low-level replication protocols
- future CDC tasks can share one payload contract and one ops playbook

### Negative

- Kafka Connect becomes a first-class deployment dependency for CDC
- local CDC demos need a heavier compose profile than the pure local pipeline
- debugging now spans Connect plus the downstream normalizer

## Rejected alternatives

- **Python-native connectors:** rejected because they duplicate hard CDC infrastructure work in project code and still do not produce a cleaner cross-database story.
- **Mixed Postgres/MySQL strategy:** rejected because it formalizes drift instead of resolving it.
- **Raw Debezium payload as the platform contract:** rejected because it leaks connector-specific structure into downstream processing and keeps the payload unstable.

## Follow-up

- Re-scope `T09` to implement Debezium/Kafka Connect connectors plus the shared normalizer.
- Add a MySQL Debezium connector configuration module alongside the existing Postgres one.
- Document CDC operations, schema-change handling, and monitoring for the chosen model.
