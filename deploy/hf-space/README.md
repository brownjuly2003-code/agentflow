---
title: AgentFlow Demo
colorFrom: gray
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
---

# AgentFlow — live demo

An event-native metrics layer: business metrics are produced by operational
events and stay live — the serving cache is invalidated when events arrive, so
reads reflect the latest state rather than a batch snapshot.

This Space runs the serving API as a single read-only container, seeded with
demo data on boot. It is built from the public source at
[github.com/brownjuly2003-code/agentflow](https://github.com/brownjuly2003-code/agentflow).

## Demo-mode behaviour

- A public demo key (`demo-key`) is injected; no signup needed.
- Admin routes (`/v1/admin/*`, `/admin/*`) return `404`.
- Mutating routes are blocked, except `POST /v1/query` and `POST /v1/query/explain`.
- DuckDB demo data is seeded on first boot.

## Try it

`{SPACE}` is the Space URL (e.g. `https://liovina-agentflow-demo.hf.space`).

```bash
# Liveness
curl -fsS {SPACE}/v1/health

# Entity point-lookup (seeded order)
curl -fsS -H "X-API-Key: demo-key" \
  {SPACE}/v1/entity/order/ORD-20260404-1001

# Natural-language query (rule-based by default)
curl -fsS -X POST -H "X-API-Key: demo-key" -H "Content-Type: application/json" \
  -d '{"question": "revenue in the last hour"}' \
  {SPACE}/v1/query

# Demo-mode guards
curl -i -H "X-Admin-Key: admin-secret" {SPACE}/v1/admin/usage   # 404
curl -i -X POST -H "X-API-Key: demo-key" -H "Content-Type: application/json" \
  -d '{"requests":[]}' {SPACE}/v1/batch                          # 403
```

Interactive API docs are at `{SPACE}/docs`.
