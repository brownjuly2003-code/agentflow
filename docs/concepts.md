# Concepts

This walkthrough explains stable platform ideas. Business entity and metric
meanings belong to the [detailed domain model](domain.md), runtime and backend
choices to the [detailed architecture reference](architecture.md), exact routes
and parameters to the [full API reference](api-reference.md), and current
evidence and gates to [engineering status](STATUS.md).

## Streaming-first

AgentFlow treats fresh operational context as the default. Batch jobs can still
exist, but the agent-facing model is built around bounded or unbounded event
streams that flow through the same validation and enrichment concepts.

This matters for agents because stale state can cause the wrong action:
answering a support ticket from an old order status, escalating an already
resolved incident, or recommending inventory that has just changed.

## Semantic layer

Agents use stable business entities, metrics, constrained questions, search,
lineage, and contracts instead of calling storage tables directly. The detailed
domain model owns their names and business interpretation. The semantic layer
maps those concepts to backing storage so client code stays small while the
runtime can evolve behind the API.

## Contracts

AgentFlow keeps schema contracts explicit so callers can reason about response
shape and compatibility. The full API reference owns the exact listing,
version, diff, and candidate-validation routes.

Contracts are also a boundary against accidental data drift: a new field can be
additive, while a removed or type-changed field needs a migration path.

## Local versus production-shaped paths

The local path optimizes developer feedback; a production-shaped path exercises
external processing, storage, deployment, and observability boundaries. Both
preserve the same validation and semantic contracts. Architecture owns the
component choices; the [deployment walkthrough](deployment.md) selects a
runnable path.

Production operation still requires owner-owned hostnames, secrets, cloud
account wiring, retention policy, monitoring, and rollback decisions.

## Query safety

Natural-language query execution is constrained. The server validates translated
SQL and restricts the operation to allowed read-only shapes before executing it.
Entity and metric lookup paths use parameterized queries for untrusted values.

## Evidence boundary

Checked-in gates and local evidence establish only the claims recorded in
engineering status. External infrastructure, security assessment, retention,
and compliance controls require separate owner evidence.
