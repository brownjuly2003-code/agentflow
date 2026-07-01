# ADR 0007: Kubernetes as the deployment substrate, API scaling gated on the serving engine

## Status

Accepted - 2026-07-01

> **Update (2026-07-02, ADR 0009):** the scaling gate below is *necessary but
> not sufficient*. Even with an external serving engine, the control plane
> (webhook queue, alert history, outbox, usage) is an embedded per-pod DuckDB
> store, so `replicaCount > 1` would fork it. See
> [ADR 0009](0009-control-plane-state-and-scaling-gate.md) for the full gate.

## Context

The repository already ships a Kubernetes deployment surface:

- `helm/agentflow` (Chart + `values.yaml` + `templates/` for deployment,
  ingress, networkpolicy) — a security-hardened chart: non-root, read-only root
  filesystem, seccomp `RuntimeDefault`, dropped capabilities, a default-deny
  NetworkPolicy with explicit egress (redis, kafka, clickhouse, otlp), a
  PodDisruptionBudget, and pod anti-affinity.
- `helm/kafka-connect` (Debezium/Kafka Connect per ADR 0005).
- `k8s/kind-config.yaml` and `scripts/k8s_staging_up.sh` / `_down.sh` /
  `k8s_smoke_test.sh` for a local kind staging cluster.

`docs/architecture.md` lists "kind staging" and "managed production via
Helm/Terraform" as topologies. The chart is real and production-shaped, so the
deployment substrate is effectively already decided — but it was never recorded
as a decision, and one load-bearing constraint is implicit and easy to miss.

That constraint: the chart advertises horizontal scaling (`autoscaling`,
`targetCPUUtilizationPercentage`, PDB, anti-affinity) but `config.duckdbPath`
mounts an **embedded DuckDB file on a ReadWriteOnce PVC**. ReadWriteOnce permits
exactly one writing pod, so `replicaCount > 1` cannot work; `autoscaling` is
therefore hard-pinned `min = max = 1`. The scaling knobs are present but inert.
Whether the API can scale horizontally is entirely a function of the serving
engine (ADR 0006), not of the chart.

## Options considered

### 1. Leave the topology undocumented

Rejected: the constraint above keeps biting — a future contributor sees the
autoscaling block, bumps `maxReplicas`, and gets silent PVC write contention or a
pod that can't schedule. The coupling between "can we scale" and "which serving
engine" must be written down.

### 2. Kubernetes/Helm as the substrate, with scaling explicitly gated on an
external serving engine

Record what already exists and make the gate explicit: the API scales
horizontally **only** when the serving engine is external (ClickHouse), because
only then are the pods stateless.

### 3. Drop Kubernetes and ship only Docker Compose

Rejected: the chart is already hardened and used for staging/production shape;
removing it loses the production-shaped staging path (`kind`) and the managed
production story for no benefit.

## Decision

**Kubernetes (via the `helm/agentflow` chart) is the canonical deployment
substrate** for staging (local `kind`) and managed production. Docker Compose
profiles remain for local demo, observability, chaos, and E2E — not production.

**API horizontal scaling is explicitly gated on an external serving engine:**

- While the serving backend is **embedded DuckDB** (RWO PVC), the API runs
  `replicaCount = 1` with `autoscaling` disabled. This is a correctness
  constraint, not a tuning choice — do not raise `maxReplicas` on this path.
- When the serving backend is **ClickHouse** (ADR 0006), the API pods are
  stateless (no local write PVC in the request path; ClickHouse is an external
  service reached over the NetworkPolicy egress already declared for port 8123).
  Horizontal scaling, HPA, and `maxReplicas > 1` are enabled **together with**
  the ClickHouse cutover, not before it.

The `values.yaml` DuckDB defaults (`config.duckdbPath`, `usageDbPath`,
`replicaCount: 1`, `autoscaling.enabled: false`) are retained as the safe
single-node profile and flipped as part of executing ADR 0006, not independently.

## Consequences

### Positive

- the deployment substrate is recorded, not folklore
- the "why is autoscaling pinned to 1" trap is documented at the decision level
- the ClickHouse cutover (ADR 0006) has a clear, single place where scaling turns on

### Negative

- the two ADRs are coupled: the scaling benefit of Kubernetes is not realized
  until the ClickHouse cutover lands
- until then, the chart's autoscaling section is intentionally dormant

## Follow-up

- As part of `docs/clickhouse-cutover-plan.md`: flip the Helm serving config to
  ClickHouse, remove the request-path write PVC, and enable `autoscaling` with a
  sane `minReplicas`/`maxReplicas` and HPA target.
- Add a values-schema note (or comment) that `autoscaling` requires an external
  serving engine, so the constraint is visible at the point of edit.
