---
title: AgentFlow — Center (msk hub)
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
---

# AgentFlow — Center node (`msk` hub)

The **hub** of the three-node demo (ADR 0012). It runs the serving API in demo
mode and additionally accepts operational events pushed by the regional edge
branches over HTTPS, aggregating a **live cross-branch view**. Built from the
public source at
[github.com/brownjuly2003-code/agentflow](https://github.com/brownjuly2003-code/agentflow),
tracking `main` — the same image as the edges, differentiated only by
environment.

The other two nodes:

- **Edge `spb`** — https://liovina-agentflow-edge-spb.hf.space
- **Edge `ekb`** — https://liovina-agentflow-edge-ekb.hf.space

## What this node adds over the standalone demo

- `GET /v1/node/branches` — the cross-branch summary: per branch a seeded
  baseline, the live delta accrued this lifecycle, and a last-seen timestamp. A
  branch that has sent nothing shows a `waking` status — open its Space to see
  its events flow here.
- `POST /v1/node/events` — token-authenticated ingest for edge→center events
  (not the public `demo-key`; internal node-to-node, hidden from `/docs`).

## What this demo shows — and what it does NOT

This is a demo of **branch distribution / event federation**: distinct
geographic branch nodes emit operational events to a hub that aggregates a
cross-branch view. Stated plainly so the artifact never over-claims:

- **Transport:** direct HTTPS `POST` stands in for Kafka → Flink. The event
  *semantics* are identical (the same canonical events drive the same journal
  and metric freshness); only the transport differs, because Spaces cannot run
  Kafka.
- **State:** each node is single-replica with an **embedded** control plane —
  the correct single-replica profile, **not** the multi-replica PostgreSQL
  scale profile (that is the Kubernetes cutover, verified separately). No
  database spans the Spaces.
- **Liveness:** the federated live layer is **ephemeral**. Free Spaces have
  non-persistent disk and sleep after 48 h of inactivity; on a restart the hub
  re-seeds a deterministic baseline and the live layer resets to zero.

## Environment (set in Space **Settings**, not the image)

| Variable                | Value                          | Kind     |
|-------------------------|--------------------------------|----------|
| `AGENTFLOW_NODE_ROLE`   | `center`                       | variable |
| `AGENTFLOW_NODE_BRANCH` | `msk`                          | variable |
| `AGENTFLOW_NODE_TOKEN`  | shared node token              | **secret** |
| `AGENTFLOW_DEMO_MODE`   | `true`                         | variable |
| `AGENTFLOW_SEED_ON_BOOT`| `true`                         | variable |

## Try it

```bash
SPACE=https://liovina-agentflow-center.hf.space

# Liveness
curl -fsS $SPACE/v1/health

# Cross-branch view (public demo key)
curl -fsS -H "X-API-Key: demo-key" $SPACE/v1/node/branches

# Public callers cannot push events — the node token is required (403)
curl -i -X POST -H "X-API-Key: demo-key" -H "Content-Type: application/json" \
  -d '{"origin_branch":"spb","events":[]}' $SPACE/v1/node/events
```
