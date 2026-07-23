# ADR 0013: Containerized PyFlink as the golden production topology

- **Status:** Accepted
- **Date:** 2026-07-23
- **Owners:** AgentFlow maintainers

## Context

The repository had three incompatible production stories: a local PyFlink 2.3
job, an AWS Managed Flink 1.19 Terraform application expecting an unbuilt JAR,
and documentation that described a direct Flink-to-Iceberg path that the
deployed job did not implement. Runtime, artifact format, authentication, and
sink semantics therefore could not be reproduced from one clean checkout.

The version and capability facts governed by this decision live in the
[machine-readable project claims](../../config/project_claims.toml).

## Decision

The only golden runtime is **containerized PyFlink 2.3** on Kubernetes:

1. Kafka delivers an envelope that retains topic, partition, offset, timestamp,
   and value until tenant attribution is complete.
2. The OCI image built by `src/processing/flink_jobs/Dockerfile` extends the
   digest-pinned official Flink 2.3 Java 17 image, retains its Kubernetes
   `/docker-entrypoint.sh`, and runs `stream_processor.py` to emit
   `events.validated` or `events.deadletter`.
3. Independent consumers materialize `events.validated` into the immutable
   Iceberg lake and the ClickHouse serving store. Their checkpoints and
   idempotency boundaries are verified separately.
4. The API reads ClickHouse. Iceberg remains the durable analytical record, not
   an undocumented serving fallback.
5. Production Kafka authentication is an explicit SASL/TLS configuration; a
   missing tenant mapping or authentication setting fails closed.

The AWS Managed Flink module under `infrastructure/terraform/modules/flink` is
reference-only. It is not part of the production deployment contract because it
targets Flink 1.19 and a JAR artifact that this repository does not build.

## Delivery and failure boundaries

- Kafka offsets are committed only through successful Flink checkpoints.
- Schema-invalid and tenant-unresolved events go to the DLQ with distinct reason
  codes; neither silently falls back to a default tenant in production.
- Iceberg and serving consumers are independently replayable from
  `events.validated` and deduplicate by `(tenant_id, event_id)`, so equal event
  ids from different tenants remain distinct.
- A serving failure must not erase the durable validated event or lake record.
- Rollback selects the prior versioned OCI image and restores from its compatible
  checkpoint; incompatible state requires replay from the retained topic.

## Migration

1. Make tenant attribution fail closed while preserving Kafka metadata.
2. Add the Iceberg materialization consumer and replay acceptance.
3. Package the Flink job and materializers as versioned Kubernetes workloads.
4. Remove the Managed Flink module from current-state diagrams and deployment
   instructions; retain it only as historical/reference infrastructure.

## Acceptance gate

The topology is production-ready only when a clean checkout builds the images,
deploys the Kubernetes workloads, processes one tenant-scoped event through
Kafka, PyFlink, Iceberg, ClickHouse, and the API, and repeats the result after a
checkpoint restore and replay without a duplicate.
