---
title: AgentFlow — Edge (spb)
colorFrom: gray
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
---

# AgentFlow — Edge node (`spb`)

A regional-warehouse **edge** of the three-node demo (ADR 0012). It runs the
serving API in demo mode over its own `spb` branch slice and, while awake, emits
operational events over HTTPS to the **center hub**, whose cross-branch view
reflects them live. Same image as the hub and the other edge, differentiated
only by environment; built from
[github.com/brownjuly2003-code/agentflow](https://github.com/brownjuly2003-code/agentflow),
tracking `main`.

- **Center hub** — https://liovina-agentflow-center.hf.space (open it to see the
  cross-branch view)
- **Edge `ekb`** — https://liovina-agentflow-edge-ekb.hf.space

## How the federation works

A slow background generator produces the same canonical events the in-process
pipeline makes; each is applied to this edge's own read surface **and** forwarded
to the hub's `POST /v1/node/events`. Push-on-activity is what makes the sleep
choreography self-healing: if the hub is asleep, the first forwarded event wakes
it; a cold hub is tolerated (bounded retries, then drop) so this page stays live
regardless.

## What this demo shows — and what it does NOT

Branch distribution / event federation, **not** horizontal scaling of one node:

- **Transport:** HTTPS `POST` stands in for Kafka → Flink; event semantics are
  identical, only the transport differs (Spaces cannot run Kafka).
- **State:** single-replica, embedded control plane — **not** the multi-replica
  PostgreSQL scale profile (the Kubernetes cutover, verified separately).
- **Liveness:** ephemeral. Free Spaces sleep after 48 h and have non-persistent
  disk; a restart re-seeds a deterministic baseline and resets the live layer.

## Environment (set in Space **Settings**, not the image)

| Variable                   | Value                                         | Kind     |
|----------------------------|-----------------------------------------------|----------|
| `AGENTFLOW_NODE_ROLE`      | `edge`                                        | variable |
| `AGENTFLOW_NODE_BRANCH`    | `spb`                                         | variable |
| `AGENTFLOW_NODE_CENTER_URL`| `https://liovina-agentflow-center.hf.space`   | variable |
| `AGENTFLOW_NODE_TOKEN`     | shared node token (same value as the hub)     | **secret** |
| `AGENTFLOW_DEMO_MODE`      | `true`                                        | variable |
| `AGENTFLOW_SEED_ON_BOOT`   | `true`                                        | variable |

## Try it

```bash
SPACE=https://liovina-agentflow-edge-spb.hf.space

# Liveness (also wakes the edge, which starts emitting to the hub)
curl -fsS $SPACE/v1/health

# This edge's own read surface (public demo key)
curl -fsS -H "X-API-Key: demo-key" $SPACE/v1/entity/order/ORD-20260404-1001
```
