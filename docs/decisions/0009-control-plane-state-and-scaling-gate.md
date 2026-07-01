# ADR 0009: Control-plane state and the real horizontal-scaling gate

## Status

Accepted - 2026-07-02

## Context

ADR 0006 fixed the serving engine on ClickHouse and ADR 0007 gated API
horizontal scaling on that engine being external: "when the serving backend is
ClickHouse the API pods are stateless". The 2026-07-02 architecture audit
found that gate **incomplete**: the serving *reads* become external, but the
API process also hosts a control plane whose state is an **embedded, per-pod
DuckDB store** reached directly through `query_engine._conn`:

- webhook delivery queue and deliveries log
  (`src/serving/api/webhook_dispatcher.py`)
- alert history and escalation state (`src/serving/api/alerts/`)
- replay outbox (`src/processing/outbox.py`, wired in `main.py`)
- dead-letter read/write paths (`src/serving/api/routers/deadletter.py`)
- usage/analytics accounting (`AuthManager` usage table, `analytics.py`)

With `replicaCount > 1`, each pod would run its **own** WebhookDispatcher and
AlertDispatcher over its **own** local queue: duplicate webhook deliveries,
forked alert history, and an outbox that silently splits across pods and is
lost on rescale. Stateless reads do not make stateful loops safe to replicate.

Two things *were* fixed as part of executing ADR 0006 (this change set):

- the freshness-critical **event scan** now goes through the serving backend
  (`QueryEngine.fetch_pipeline_events`), so webhook dispatch, metric-cache
  invalidation, and the SSE stream watch the store the API serves from — the
  event→metric axis survives the engine flip;
- the local pipeline writes the serving tables and the `pipeline_events`
  journal to ClickHouse when it is the configured backend
  (`src/processing/clickhouse_sink.py`), so an out-of-process writer drives
  live freshness across process boundaries.

What is *not* fixed — and is the subject of this ADR — is where the
control-plane **state** lives.

## Options considered

### 1. Pretend ADR 0007's gate is sufficient and enable autoscaling with the ClickHouse cutover

Rejected. It ships a correctness bug (duplicate deliveries, forked alert
state) behind a green-looking scaling knob — exactly the "claiming what you
don't run" failure mode the road-to-9.8 rubric exists to prevent.

### 2. Externalize control-plane state now (Redis/PostgreSQL/ClickHouse tables)

Correct end-state for a multi-replica deployment, but it is a full workstream:
five subsystems, durable-delivery semantics to preserve (audit_28 #3), and a
migration for each. Not needed for the demo profile, which is single-replica
by design.

### 3. Split the dispatch loops into a singleton worker

Run webhook/alert/outbox loops in a dedicated single-replica worker Deployment
(or behind leader election) while API pods stay read-only and scale. Smaller
than option 2 but still a topology change with its own failure modes; also not
needed for the demo profile.

## Decision

1. **Record the honest gate.** API horizontal scaling requires **both** an
   external serving engine (ADR 0006/0007) **and** control-plane state that is
   not embedded per-pod (option 2 or 3 above). Until the second half lands,
   `replicaCount: 1` and `autoscaling.enabled: false` stay pinned **even on
   the ClickHouse serving profile** — this is a correctness constraint, not a
   tuning choice. The Helm values document it at the point of edit.
2. **Keep control-plane state embedded for the single-replica profile.** For
   the demo and the default chart profile, the embedded DuckDB control-plane
   store is correct, durable across restarts (file-backed), and keeps the
   bring-up light. This is a deliberate, documented scope — not an oversight.
3. **Defer the externalization choice** (option 2 vs 3) until a deployment
   actually needs `replicaCount > 1`. The decision then should start from the
   durable-delivery semantics pinned by the webhook/alert regression suites.

## Consequences

### Positive

- The scaling knob can no longer ship a split-brain control plane by accident;
  the constraint is recorded at decision level and in the chart.
- The demo stays light: no extra stateful service for a single-replica bring-up.
- The freshness axis is engine-agnostic (event scan through the backend), so
  the ClickHouse cutover did not orphan webhooks, alerts, or cache invalidation.

### Negative

- The K8s scaling benefit promised by ADR 0007 remains deferred until the
  control-plane workstream lands.
- The API pod keeps a writable volume for the control-plane store even when
  serving reads are external.

## Follow-up

- When multi-replica is actually required: pick option 2 or 3, migrate the
  five subsystems, and only then enable autoscaling (cutover plan Phase 3).
- ADR 0007 remains accepted; its scaling gate is **extended** by this ADR
  (engine-external is necessary, not sufficient).
