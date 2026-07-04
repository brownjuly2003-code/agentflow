# ADR 0012: Three-node demo topology on Hugging Face Spaces

## Status

Accepted - 2026-07-04 (design; F2 implements per `plan_endgame_02_07_26.md`,
deploy of the Spaces is an owner gate). Concrete build contract:
[`docs/three-node-demo-topology.md`](../three-node-demo-topology.md).

## Context

The public demo today is a **single** Hugging Face Docker Space
(`liovina/agentflow-demo`, live at `https://liovina-agentflow-demo.hf.space` -
`deploy/hf-space/`): one read-only container that seeds DuckDB on boot, runs in
demo mode (admin routes `404`, mutating routes `403` except `POST /v1/query`),
and tracks `main`. It demonstrates the event-native metrics story **within one
node** - the in-process pipeline (`src/processing/local_pipeline.py`) generates
events, and serving reads reflect them.

The production topology is multi-service and multi-branch, and none of it fits a
single Space:

- ADR 0006 fixes serving on **ClickHouse**; ADR 0007 makes **Kubernetes/Helm**
  the substrate; ADR 0009/0010 externalize the control plane to **PostgreSQL**
  so the API can run `replicaCount > 1`.
- The legend (`docs/domain.md` §1) is a **multi-branch** importer: `msk` (HQ,
  central warehouse, fulfils all three RU channels, main WMS), `spb`/`ekb` (RU
  regional warehouses), `dxb` (JAFZA re-export hub, UAE), `ala` (EAEU hub, KZ).
  Each branch is a separate legal entity, which is why per-jurisdiction PII
  satellites and per-branch row policies exist in the DV2 vault.

Phase F of the endgame plan calls for a **three-node** demo - a center plus two
edge branches, events flowing over HTTPS - so the public artifact *shows* the
distribution story (a branch produces operational events; the HQ's cross-branch
metrics reflect them live) rather than a single box plus a diagram.

### Hugging Face Spaces constraints (verified 2026-07-04)

- Free `cpu-basic` hardware: **16 GB RAM, 2 vCPU, 50 GB non-persistent disk**;
  a Space **sleeps after 48 h of inactivity** and cold-starts on the next HTTP
  request (the image is already built - a wake is seconds, not a rebuild). Free
  hardware cannot configure a custom sleep timer.
  ([Spaces Overview](https://huggingface.co/docs/hub/en/spaces-overview))
- Non-persistent disk is the load-bearing constraint: **local state does not
  survive a restart**, so every node must re-seed on boot. This is a property to
  design *with*, not around.
- **Multiple public Spaces per free account** need no organization and no second
  account - proven empirically: the `liovina` account already runs
  `agentflow-demo`, `nl-sql`, and `vacancyradar` as concurrent public Spaces.

## The honesty boundary (what this demo does and does NOT show)

This section is the crux for the Phase G adversarial audit. There are **two
orthogonal axes**, and conflating them would be a claim the system does not run:

1. **Branch distribution / event federation** - *this* is what the three-node
   HF demo demonstrates: distinct geographic branch nodes emit operational
   events to a hub that aggregates a cross-branch view.
2. **Horizontal scaling of one logical node** - ADR 0007/0009/0010: `replicaCount
   > 1` pods of the *same* service sharing an externalized PostgreSQL control
   plane. This is the Kubernetes scale profile and is **not** what the HF demo
   shows. The demo's three nodes are three *different* single-replica services,
   each with its own **embedded** control plane - which is exactly the correct,
   documented single-replica profile per ADR 0009 §Decision(2).

Three substitutions the demo makes, to be stated plainly in the node READMEs so
the artifact never over-claims:

- **Transport:** direct HTTPS `POST` replaces Kafka -> Flink as the inter-node
  event carrier. Event *semantics* are preserved (the same canonical events
  drive the same `pipeline_events` journal and metric freshness); only the
  transport differs, because Spaces cannot run Kafka.
- **State:** each node is single-replica with the embedded control plane, **not**
  the PostgreSQL scale profile. No shared database spans the Spaces.
- **Liveness:** the federated cross-branch layer is **ephemeral** - it re-seeds
  to a deterministic baseline on every restart; live events that arrived since
  the hub last booted are lost on the hub's next restart.

## Options considered

### 1. Keep one node; describe multi-node only in docs

Rejected. Phase F's entire value is a *running* distribution, not a diagram; a
live cross-branch reflection is what makes the portfolio point.

### 2. One Space, three processes (supervisord / compose inside the image)

Rejected. HF Docker Spaces run a single app on one `app_port`; three processes
inside one container share a kernel and filesystem, so they are not real nodes,
do not cross a network boundary, and never exercise the HTTPS event path the
design is meant to show. Less honest than three real Spaces, for more plumbing.

### 3. Three Spaces, one per node, federated over HTTPS - chosen

A real network boundary and real per-node isolation; each node is a real
deployment of the **same image** differentiated only by environment. Matches how
production separates branches, at demo scale.

### 4. Second HF account / paid persistent Spaces for the branches

Rejected as unnecessary. One free account hosts all three public Spaces (proven
above), and ephemerality is acceptable for an on-demand demo given the sleep
choreography below. No second account, no paid tier, no organization required.

## Decision

**1. Node roles and legend mapping.**

- **Center = `msk`** (HQ). Runs the full serving API in demo mode **plus** an
  authenticated node-ingest endpoint, and hosts the cross-branch aggregated
  view. It is the hub analog of the production control plane - but embedded and
  single-replica, **not** the PostgreSQL scale profile (see honesty boundary).
- **Edge 1 = `spb`, Edge 2 = `ekb`** - both RU regional warehouses. Each runs
  the same image in edge role: seeds its branch slice, serves its own read
  surface, and emits its operational events to the center over HTTPS.
- **Foreign branches `dxb`/`ala` stay narrative, not live nodes - deliberately.**
  The legend's load-bearing governance claim is "RU PII never crosses the
  border" (`domain.md` §1 - per-jurisdiction legal entities; §6 - the
  PII-officer persona: "prove RU data never crosses the border"). Standing up a
  live UAE/KZ Space
  that receives faux-PII-bearing events over the public internet would visually
  contradict that claim. Cross-jurisdiction is demonstrated where it actually
  lives - DV2 vault governance (per-jurisdiction PII satellites, per-branch row
  policies) - not the node graph. A future foreign node is a **non-goal** here;
  if ever added it must carry zero PII in its event payloads.

**2. One image, three roles, differentiated by environment.** The existing
`deploy/hf-space` image is extended (not forked). New env, consistent with the
`AGENTFLOW_*` convention:

- `AGENTFLOW_NODE_ROLE = center | edge` (unset or `standalone` = today's
  single-node demo, unchanged - a strict superset, so the current Space keeps
  working with no new env).
- `AGENTFLOW_NODE_BRANCH = msk | spb | ekb` (scopes the boot seed to that
  branch's slice).
- `AGENTFLOW_NODE_CENTER_URL` (edge only - where to emit, e.g.
  `https://liovina-agentflow-center.hf.space`).
- `AGENTFLOW_NODE_TOKEN` (shared secret, stored as an HF Space **secret**, never
  a public variable; authenticates edge->center ingest - distinct from the
  public `demo-key`).

**3. Event flow is push, edge -> center, over HTTPS.**

- A new endpoint on the center - `POST /v1/node/events` (bearer =
  `AGENTFLOW_NODE_TOKEN`) - accepts a batch of the **same canonical events**
  `local_pipeline._process_event` already understands (order / payment / click /
  product), tagged with the originating branch. The center applies them through
  that existing path (`_process_event` -> `pipeline_events` journal + serving
  tables), so cross-branch metrics, Order 360 timeline, and freshness update
  with **no new serving logic** - it reuses the event->metric axis that already
  exists (ADR 0006 Phase 1).
- The endpoint is **allow-listed in the demo-mode guard** exactly like
  `/v1/query` (`src/serving/api/main.py:286-299`), so public callers with the
  `demo-key` still get `403` on it; only the node token authorizes it. It is
  mounted **only** in center role; in edge/standalone role it does not exist.
- **Push, not pull:** edges emit on their own activity (the existing background
  generator tick, reused). This is what makes sleep choreography work.

**4. Statelessness + re-seed.**

- Every node seeds deterministically on boot (`AGENTFLOW_SEED_ON_BOOT=true`,
  already the demo default). Edges seed their branch slice; the center seeds the
  catalog plus an **aggregate baseline covering all three branches**, so a
  center visitor sees a coherent cross-branch picture even before any live event
  arrives.
- The federated live layer sits **on top of** the re-seeded baseline and is
  **ephemeral**: a restart re-seeds the baseline and resets the live layer to
  zero. Stated in the READMEs/UI. No shared database, no cross-Space persistence
  - that is the point of stateless + re-seed.
- **Determinism + idempotency:** the seed is a fixed function of
  `AGENTFLOW_NODE_BRANCH` plus the pinned demo dataset, so any node comes up with
  the same baseline on any restart; event application is idempotent (order upsert
  by id, journal keyed by `event_id`), so a retried push after a wake never
  double-counts.

**5. Sleep choreography (no keep-alive).**

- Push + on-demand is self-healing without any cron. A visitor hits a sleeping
  edge -> the edge wakes, seeds, and its generator emits to the center; if the
  center is asleep, **the first emit wakes it** (it seeds its baseline, then
  applies the event).
- The edge emitter treats a cold center **tolerantly**: short timeout + a couple
  of backoff retries so the first (wake) request that times out is retried once
  the center is up; on give-up it drops the event (best-effort for a demo,
  logged) rather than failing the visitor's page.
- The center's cross-branch view **degrades gracefully**: a branch that has sent
  nothing this lifecycle (asleep or just booted) shows its re-seeded baseline
  plus a "branch waking / no live events yet" state and a per-branch last-seen
  timestamp - the sleep behavior is **visible by design**, never an error.
- **No keep-alive scheduler** is part of the design. A GitHub Actions cron
  pinging all three to fight sleep is possible but an explicit non-goal: it burns
  minutes for no demo value and hides the honest sleep story. Always-warm, if
  ever wanted, is an ops toggle, not this design.

**6. Namespaces.** Three Spaces under the single existing `liovina` account:
`liovina/agentflow-center`, `liovina/agentflow-edge-spb`,
`liovina/agentflow-edge-ekb`. **No second account and no HF organization are
required** (proven above). An HF org (free) would only buy a prettier
`agentflow/center` namespace and shared secret management - recorded as an
**optional** nicety for F2, not a requirement.

## Consequences

### Positive

- The public demo shows the distribution story **live**, on real network
  boundaries, with per-node isolation.
- One image, three environments (DRY); no new infrastructure, account, tier, or
  organization.
- New code is thin and low-risk: an ingest endpoint, an edge emitter hook, a
  node-mode config, and a cross-branch view - all reusing the existing event
  path (`_process_event`, the background generator, the `pipeline_events`
  journal) rather than adding serving logic.
- Honest by construction: transport substitution, single-replica embedded state,
  and ephemeral liveness are all stated where a viewer meets them.

### Negative

- Real F2 surface to build and test (ingest endpoint, emitter, node config,
  aggregation, graceful degradation) - not a config-only change.
- The federated live layer is ephemeral (the baseline is not); a hub restart
  resets it.
- Sleep adds first-request latency and a "waking" UX state; a center-first
  visitor sees only the baseline until an edge is awake and emitting (mitigated
  by UI copy directing "open a branch Space to see its events flow to the hub";
  an optional center-initiated wake-poke is noted in the spec, with its
  sleep-timeout cost).
- Three Spaces to deploy and refresh instead of one.

### Non-goals (recorded so they are not mistaken for gaps)

- Not the multi-replica PostgreSQL scale profile (that is ADR 0010 + the K8s
  cutover, verified separately).
- No live foreign-branch (`dxb`/`ala`) node - PII border.
- No keep-alive / always-warm; no cross-Space shared database.

## Follow-up (F2 - `plan_endgame_02_07_26.md` Phase F)

- Implement per the build contract in `docs/three-node-demo-topology.md`
  (Space matrix, env matrix, endpoint contract, event payload, boot/emit/sleep
  sequences, node invariants N1-Nx as the test spec, deploy runbook,
  verify-live checklist).
- **Deploy of the three Spaces is an owner gate** (external publish under
  `liovina`, `HF_TOKEN` from `D:/VacancyRadar/.env` - never printed).
- Verify-live: health of all three, plus an edge->center event visibly moving a
  center cross-branch metric.
- ADR 0007/0009/0010 remain accepted and unchanged; this ADR neither relaxes nor
  depends on the multi-replica gate - it is a different axis (distribution, not
  scaling).
