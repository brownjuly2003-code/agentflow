# API Reference

`docs/openapi.json` currently covers the core public surface. This document is the maintained reference for the full v1 API, including admin, alerting, pagination, dead-letter, and operational endpoints added after the initial export flow.

## Base URL and Headers

- Base URL: `http://localhost:8000` (local dev)
- Public hosted URL: not provisioned in this repository snapshot. Replace `http://localhost:8000` in the examples below with your deployed base URL after deployment.
- Auth header for most endpoints: `X-API-Key: <key>`
- Admin header for `/v1/admin/*`: `X-Admin-Key: <admin-key>`
- Correlation headers: send `X-Correlation-ID` or `X-Request-Id`; the API always returns `X-Correlation-ID`
- Version pinning header: `X-AgentFlow-Version: YYYY-MM-DD`

Common response headers:
- `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- `X-AgentFlow-Version`, `X-AgentFlow-Latest-Version`, `X-AgentFlow-Deprecated`
- `X-AgentFlow-Deprecation-Warning` when a pinned version is deprecated
- `X-Cache` on metric requests
- `X-PII-Masked` when masking was applied

Auth exemptions:
- `GET /v1/health`
- `GET /docs`
- `GET /redoc`
- `GET /openapi.json`
- `GET /metrics`

## Query and Pagination Model

Natural-language queries support cursor pagination through `POST /v1/query`.

```json
{
  "question": "top 10 products by revenue this week",
  "context": null,
  "limit": 5,
  "cursor": null
}
```

Typical paginated response:

```json
{
  "rows": [{ "product_id": "PROD-001" }],
  "sql": "SELECT ...",
  "total_count": 42,
  "next_cursor": "eyJvZmZzZXQiOjV9",
  "has_more": true,
  "page_size": 5
}
```

## Core Agent API

| Method | Path | Purpose | Important parameters |
|--------|------|---------|----------------------|
| `GET` | `/v1/health` | Pipeline and serving health | No auth required |
| `GET` | `/v1/catalog` | Entities, metrics, streaming and audit sources | No required params |
| `GET` | `/v1/entity/{entity_type}/{entity_id}` | Current or historical entity lookup | `as_of` |
| `GET` | `/v1/metrics/{metric_name}` | Metric lookup | `window`, `as_of` |
| `POST` | `/v1/query/explain` | Translate NL to SQL without executing | Body: `question` |
| `POST` | `/v1/query` | Execute NL query | Body: `question`, `context`, `limit`, `cursor` |
| `POST` | `/v1/batch` | Execute up to 20 entity/metric/query items | Body: `requests[]` |

## Discovery and Governance

| Method | Path | Purpose | Important parameters |
|--------|------|---------|----------------------|
| `GET` | `/v1/search` | Semantic search across entities, metrics, and catalog fields | `q`, `limit`, `entity_types` |
| `GET` | `/v1/contracts` | List schema contracts | None |
| `GET` | `/v1/contracts/{entity}` | Latest stable contract for an entity | None |
| `GET` | `/v1/contracts/{entity}/{version}` | Specific contract version | `version` |
| `GET` | `/v1/contracts/{entity}/diff/{from_version}/{to_version}` | Compare two contract versions | Path params only |
| `POST` | `/v1/contracts/{entity}/validate` | Validate a candidate schema against the latest stable contract | Body: candidate schema |
| `GET` | `/v1/lineage/{entity_type}/{entity_id}` | Provenance chain from source to serving | Path params only |
| `GET` | `/v1/changelog` | Date-based API version history | None |

## Streaming and Operational Workflows

| Method | Path | Purpose | Important parameters |
|--------|------|---------|----------------------|
| `GET` | `/v1/stream/events` | SSE stream of validated events | `event_type`, `entity_id` |
| `GET` | `/v1/deadletter/stats` | Dead-letter aggregate status | None |
| `GET` | `/v1/deadletter` | Paginated dead-letter listing | `page`, `page_size`, `reason` |
| `GET` | `/v1/deadletter/{event_id}` | Dead-letter event detail | Path param only |
| `POST` | `/v1/deadletter/{event_id}/replay` | Replay one dead-letter event | Optional body: `corrected_payload` |
| `POST` | `/v1/deadletter/{event_id}/dismiss` | Mark a dead-letter event dismissed | Path param only |
| `POST` | `/v1/webhooks` | Register a webhook | Body: `url`, `filters` |
| `GET` | `/v1/webhooks` | List active webhooks for the caller tenant | None |
| `DELETE` | `/v1/webhooks/{webhook_id}` | Deactivate a webhook | Path param only |
| `POST` | `/v1/webhooks/{webhook_id}/test` | Trigger a synthetic webhook delivery | Path param only |
| `GET` | `/v1/webhooks/{webhook_id}/logs` | Delivery history for a webhook | Path param only |
| `POST` | `/v1/alerts` | Create an alert rule | Body: `name`, `metric`, `window`, `condition`, `threshold`, `webhook_url`, `cooldown_minutes` |
| `GET` | `/v1/alerts` | List active alerts for the caller tenant | None |
| `PUT` | `/v1/alerts/{alert_id}` | Update an alert rule | Partial alert body |
| `DELETE` | `/v1/alerts/{alert_id}` | Deactivate an alert | Path param only |
| `POST` | `/v1/alerts/{alert_id}/test` | Send a synthetic alert notification | Path param only |
| `GET` | `/v1/alerts/{alert_id}/history` | Alert evaluation and delivery history | Path param only |
| `GET` | `/v1/slo` | Current SLO compliance and error budget | None |
| `GET` | `/metrics` | Prometheus scrape endpoint | No auth required |

## Admin API

All admin endpoints require `X-Admin-Key`.

| Method | Path | Purpose | Important parameters |
|--------|------|---------|----------------------|
| `POST` | `/v1/admin/keys` | Create an API key | Body: `name`, `tenant`, `rate_limit_rpm`, `allowed_entity_types` |
| `GET` | `/v1/admin/keys` | List API keys and recent usage | None |
| `POST` | `/v1/admin/keys/{key_id}/rotate` | Rotate a key with a grace period | Path param only |
| `GET` | `/v1/admin/keys/{key_id}/rotation-status` | Check grace-period status and old-key traffic | Path param only |
| `POST` | `/v1/admin/keys/{key_id}/revoke-old` | Revoke the old key after migration | Path param only |
| `DELETE` | `/v1/admin/keys/{api_key}` | Revoke a key immediately | Path param only |
| `GET` | `/v1/admin/usage` | Request volume by tenant | None |
| `GET` | `/v1/admin/analytics/usage` | Usage analytics | `window`, `tenant` |
| `GET` | `/v1/admin/analytics/top-queries` | Most frequent queries | `limit`, `window` |
| `GET` | `/v1/admin/analytics/top-entities` | Most requested entities | `limit`, `window` |
| `GET` | `/v1/admin/analytics/latency` | Latency analytics | `window` |
| `GET` | `/v1/admin/analytics/anomalies` | Usage anomalies | `window` |

## Examples

### Historical entity lookup

```bash
curl -H "X-API-Key: <key>" \
  "http://localhost:8000/v1/entity/order/ORD-001?as_of=2026-04-11T12:00:00Z"
```

### Paginated NL query

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <key>" \
  -d '{"question":"all orders today","limit":5}'
```

### Rotate an API key

```bash
curl -X POST \
  -H "X-Admin-Key: <admin-key>" \
  http://localhost:8000/v1/admin/keys/<key_id>/rotate
```

## SDK Coverage Notes

First-class SDK helpers currently cover the core read/query surface:
- Python: `health()`, `catalog()`, `get_order()`, `get_user()`, `get_product()`, `get_session()`, `get_metric()`, `query()`, `batch()`
- TypeScript: `health()`, `catalog()`, `getOrder()`, `getUser()`, `getProduct()`, `getSession()`, `getMetric()`, `query()`, `batch()`, `streamEvents()`

Operational, governance, and admin routes are present in the HTTP API but do not yet expose first-class helpers in the current Python/TypeScript client code. For those routes, the examples below use direct HTTP from Python (`httpx`) and TypeScript (`fetch`) so the documentation stays aligned with the actual SDK surface.

## Narrative Reference

### GET /v1/health

**Use case:** an ops or support agent checks freshness before answering a time-sensitive question.

**curl**

```bash
curl http://localhost:8000/v1/health
```

**Python SDK**

```python
from agentflow import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
health = client.health()
print(health.status)
```

**TypeScript SDK**

```typescript
import { AgentFlowClient } from "@agentflow/client";

const client = new AgentFlowClient("http://localhost:8000", "demo-key");
const health = await client.health();
console.log(health.status);
```

**Response 200**

```json
{"status":"healthy","components":[{"name":"duckdb_pool","status":"healthy"}]}
```

**Errors:** `500` only if the service itself cannot produce a health payload.  
**Rate limit:** no API key required; no per-key rate-limit headers are guaranteed on this route.

### GET /v1/catalog

**Use case:** a merch or support agent discovers which entities, metrics, and streaming sources exist before issuing lookups or queries.

**curl**

```bash
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/catalog
```

**Python SDK**

```python
from agentflow import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
catalog = client.catalog()
print(sorted(catalog.entities.keys()))
```

**TypeScript SDK**

```typescript
import { AgentFlowClient } from "@agentflow/client";

const client = new AgentFlowClient("http://localhost:8000", "demo-key");
const catalog = await client.catalog();
console.log(Object.keys(catalog.entities));
```

**Response 200**

```json
{"entities":{"order":{"primary_key":"order_id"}},"metrics":{"revenue":{"unit":"USD"}}}
```

**Errors:** `401`, `429`.  
**Rate limit:** per API key; default server-side baseline is `120 rpm` unless overridden on the key.

### GET /v1/entity/{entity_type}/{entity_id}

**Use case:** support agent needs the latest order state for `ORD-20260404-1001` before replying to a customer.

**curl**

```bash
curl -H "X-API-Key: demo-key" \
  http://localhost:8000/v1/entity/order/ORD-20260404-1001
```

**Python SDK**

```python
from agentflow import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
order = client.get_order("ORD-20260404-1001")
print(order.status, order.total_amount)
```

**TypeScript SDK**

```typescript
import { AgentFlowClient } from "@agentflow/client";

const client = new AgentFlowClient("http://localhost:8000", "demo-key");
const order = await client.getOrder("ORD-20260404-1001");
console.log(order.status, order.total_amount);
```

**Response 200**

```json
{"entity_type":"order","entity_id":"ORD-20260404-1001","data":{"status":"delivered"},"freshness_seconds":12.4}
```

**Errors:** `401`, `403`, `404`, `422` for future `as_of`, `503` if the serving table is unavailable.  
**Rate limit:** per API key; response may also include `X-Cache` and `X-PII-Masked`.

### GET /v1/metrics/{metric_name}

**Use case:** ops agent checks `revenue` or `error_rate` over a specific window before escalating an incident.

**curl**

```bash
curl -H "X-API-Key: demo-key" \
  "http://localhost:8000/v1/metrics/revenue?window=1h"
```

**Python SDK**

```python
from agentflow import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
metric = client.get_metric("revenue", window="1h")
print(metric.value, metric.unit)
```

**TypeScript SDK**

```typescript
import { AgentFlowClient } from "@agentflow/client";

const client = new AgentFlowClient("http://localhost:8000", "demo-key");
const metric = await client.getMetric("revenue", "1h");
console.log(metric.value, metric.unit);
```

**Response 200**

```json
{"metric_name":"revenue","value":984.91,"unit":"USD","window":"1h","components":null}
```

**Errors:** `401`, `404`, `422` for invalid historical anchor, `503` if metric computation cannot run.  
**Rate limit:** per API key; response may include `X-Cache`.

### POST /v1/query/explain

**Use case:** merch or ops agent wants to inspect the translated SQL before running a natural-language question.

**curl**

```bash
curl -X POST http://localhost:8000/v1/query/explain \
  -H "Content-Type: application/json" \
  -H "X-API-Key: demo-key" \
  -d '{"question":"top 5 products by revenue today"}'
```

**Python (HTTP)**

```python
import httpx

response = httpx.post(
    "http://localhost:8000/v1/query/explain",
    headers={"X-API-Key": "demo-key"},
    json={"question": "top 5 products by revenue today"},
)
print(response.json()["sql"])
```

**TypeScript (HTTP)**

```typescript
const response = await fetch("http://localhost:8000/v1/query/explain", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": "demo-key",
  },
  body: JSON.stringify({ question: "top 5 products by revenue today" }),
});
const plan = await response.json();
console.log(plan.sql);
```

**Response 200**

```json
{"question":"top 5 products by revenue today","sql":"SELECT ...","tables_accessed":["orders_v2"],"engine":"rule_based"}
```

**Errors:** `400` invalid question or unsafe translation, `401`, `429`.  
**Rate limit:** per API key.

### POST /v1/query

**Use case:** merch agent asks "top products by revenue today" and needs rows plus pagination metadata.

**curl**

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: demo-key" \
  -d '{"question":"top products by revenue today","limit":5}'
```

**Python SDK**

```python
from agentflow import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
result = client.query("top products by revenue today", limit=5)
print(result.metadata)
```

**TypeScript SDK**

```typescript
import { AgentFlowClient } from "@agentflow/client";

const client = new AgentFlowClient("http://localhost:8000", "demo-key");
const result = await client.query("top products by revenue today");
console.log(result.metadata);
```

**Response 200**

```json
{"rows":[{"product_id":"PROD-001"}],"sql":"SELECT ...","has_more":false,"page_size":5}
```

**Errors:** `400`, `401`, `429`.  
**Rate limit:** per API key; paginated responses include `total_count`, `next_cursor`, `has_more`, and `page_size`.

### POST /v1/batch

**Use case:** support agent resolves order, user, and a fallback query in one round-trip.

**curl**

```bash
curl -X POST http://localhost:8000/v1/batch \
  -H "Content-Type: application/json" \
  -H "X-API-Key: demo-key" \
  -d '{"requests":[{"id":"order-1","type":"entity","params":{"entity_type":"order","entity_id":"ORD-20260404-1001"}}]}'
```

**Python SDK**

```python
from agentflow import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
payload = [client.batch_entity("order", "ORD-20260404-1001", request_id="order-1")]
result = client.batch(payload)
print(result["results"][0]["status"])
```

**TypeScript SDK**

```typescript
import { AgentFlowClient } from "@agentflow/client";

const client = new AgentFlowClient("http://localhost:8000", "demo-key");
const payload = [client.batchEntity("order", "ORD-20260404-1001", "order-1")];
const result = await client.batch(payload);
console.log(result.results[0].status);
```

**Response 200**

```json
{"results":[{"id":"order-1","status":"ok","data":{"entity_type":"order"}}],"duration_ms":14.8}
```

**Errors:** request-level `401` and `429`; item-level failures are returned inside `results[].error`.  
**Rate limit:** per API key; max `20` batch items per request.

### GET /v1/search

**Use case:** merch agent searches for the right metric/entity name before building a prompt or dashboard card.

**curl**

```bash
curl -H "X-API-Key: demo-key" \
  "http://localhost:8000/v1/search?q=revenue&limit=5"
```

**Python (HTTP)**

```python
import httpx

response = httpx.get(
    "http://localhost:8000/v1/search",
    headers={"X-API-Key": "demo-key"},
    params={"q": "revenue", "limit": 5},
)
print(response.json()["results"])
```

**TypeScript (HTTP)**

```typescript
const response = await fetch(
  "http://localhost:8000/v1/search?q=revenue&limit=5",
  { headers: { "X-API-Key": "demo-key" } },
);
const payload = await response.json();
console.log(payload.results);
```

**Response 200**

```json
{"query":"revenue","results":[{"type":"metric","id":"revenue","score":0.98,"endpoint":"/v1/metrics/revenue"}]}
```

**Errors:** `401`, `422` for invalid `q`/`limit`, `429`.  
**Rate limit:** per API key.

### Contract and Lineage Routes

Use these routes when the caller is building or validating integrations, not when it just needs live values.

- `GET /v1/contracts`: list every registered contract summary.
- `GET /v1/contracts/{entity}`: fetch the latest stable contract for one entity.
- `GET /v1/contracts/{entity}/{version}`: fetch a specific contract version.
- `GET /v1/contracts/{entity}/diff/{from_version}/{to_version}`: compare two versions and see additive vs breaking changes.
- `POST /v1/contracts/{entity}/validate`: validate a candidate schema against the latest stable contract.
- `GET /v1/lineage/{entity_type}/{entity_id}`: reconstruct the provenance chain from source to serving.

**Representative curl**

```bash
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/contracts/order
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/lineage/order/ORD-20260404-1001
```

**Python (HTTP)**

```python
import httpx

contract = httpx.get(
    "http://localhost:8000/v1/contracts/order",
    headers={"X-API-Key": "demo-key"},
).json()
print(contract["version"])
```

**TypeScript (HTTP)**

```typescript
const response = await fetch("http://localhost:8000/v1/contracts/order", {
  headers: { "X-API-Key": "demo-key" },
});
const contract = await response.json();
console.log(contract.version);
```

**Representative responses**

```json
{"entity":"order","version":"2","status":"stable","fields":[{"name":"order_id","required":true}]}
{"entity_type":"order","entity_id":"ORD-20260404-1001","lineage":[{"layer":"source","system":"postgres_cdc"}]}
```

**Common errors:** `400` schema/entity mismatch, `401`, `404`, `429`.  
**Rate limit:** per API key.

### GET /v1/changelog

**Use case:** platform engineer checks current date-based version history before pinning `X-AgentFlow-Version`.

**curl**

```bash
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/changelog
```

**Python (HTTP)**

```python
import httpx

payload = httpx.get(
    "http://localhost:8000/v1/changelog",
    headers={"X-API-Key": "demo-key"},
).json()
print(payload["latest_version"])
```

**TypeScript (HTTP)**

```typescript
const response = await fetch("http://localhost:8000/v1/changelog", {
  headers: { "X-API-Key": "demo-key" },
});
const payload = await response.json();
console.log(payload.latest_version);
```

**Response 200**

```json
{"latest_version":"2026-04-11","versions":[{"date":"2026-04-11","status":"latest","changes":[]}]}
```

**Errors:** `401`, `429`.  
**Rate limit:** per API key.

### GET /v1/stream/events

**Use case:** ops agent or dashboard listens for validated events without polling.

**curl**

```bash
curl -N -H "X-API-Key: demo-key" \
  "http://localhost:8000/v1/stream/events?event_type=order"
```

**Python (HTTP)**

```python
import httpx

with httpx.stream(
    "GET",
    "http://localhost:8000/v1/stream/events",
    headers={"X-API-Key": "demo-key"},
    params={"event_type": "order"},
) as response:
    for line in response.iter_lines():
        if line.startswith("data: "):
            print(line)
            break
```

**TypeScript SDK**

```typescript
import { AgentFlowClient } from "@agentflow/client";

const client = new AgentFlowClient("http://localhost:8000", "demo-key");
for await (const event of client.streamEvents({ eventType: "order" })) {
  console.log(event);
  break;
}
```

**Response 200**

```text
data: {"event_id":"evt-001","topic":"events.validated"}
```

**Errors:** `401`, `429`.  
**Rate limit:** per API key; streaming clients should reconnect on network failure.

### Dead-letter, Webhook, Alert, and SLO Routes

These routes are primarily for operators and integration owners.

**Dead-letter routes**
- `GET /v1/deadletter/stats`
- `GET /v1/deadletter`
- `GET /v1/deadletter/{event_id}`
- `POST /v1/deadletter/{event_id}/replay`
- `POST /v1/deadletter/{event_id}/dismiss`

**Webhook routes**
- `POST /v1/webhooks`
- `GET /v1/webhooks`
- `DELETE /v1/webhooks/{webhook_id}`
- `POST /v1/webhooks/{webhook_id}/test`
- `GET /v1/webhooks/{webhook_id}/logs`

**Alert routes**
- `POST /v1/alerts`
- `GET /v1/alerts`
- `PUT /v1/alerts/{alert_id}`
- `DELETE /v1/alerts/{alert_id}`
- `POST /v1/alerts/{alert_id}/test`
- `GET /v1/alerts/{alert_id}/history`

**SLO route**
- `GET /v1/slo`

**Representative curl**

```bash
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/deadletter/stats
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/slo
```

**Representative Python (HTTP)**

```python
import httpx

slo = httpx.get(
    "http://localhost:8000/v1/slo",
    headers={"X-API-Key": "demo-key"},
).json()
print(slo["slos"])
```

**Representative TypeScript (HTTP)**

```typescript
const response = await fetch("http://localhost:8000/v1/slo", {
  headers: { "X-API-Key": "demo-key" },
});
const slo = await response.json();
console.log(slo.slos);
```

**Representative responses**

```json
{"counts":{"schema_validation":2},"last_24h":3}
{"slos":[{"name":"freshness","target":0.99,"current":1.0,"status":"healthy"}]}
```

**Common errors:** `401`, `403` for write actions with read-only keys, `404`, `422`, `429`.  
**Rate limit:** per API key.

### Admin Routes

All admin routes require `X-Admin-Key` and are intended for platform owners, not end-user agents.

**Key management**
- `POST /v1/admin/keys`
- `GET /v1/admin/keys`
- `POST /v1/admin/keys/{key_id}/rotate`
- `GET /v1/admin/keys/{key_id}/rotation-status`
- `POST /v1/admin/keys/{key_id}/revoke-old`
- `DELETE /v1/admin/keys/{api_key}`

**Usage and analytics**
- `GET /v1/admin/usage`
- `GET /v1/admin/analytics/usage`
- `GET /v1/admin/analytics/top-queries`
- `GET /v1/admin/analytics/top-entities`
- `GET /v1/admin/analytics/latency`
- `GET /v1/admin/analytics/anomalies`

**Representative curl**

```bash
curl -H "X-Admin-Key: admin-secret" http://localhost:8000/v1/admin/keys
curl -H "X-Admin-Key: admin-secret" http://localhost:8000/v1/admin/usage
```

**Representative Python (HTTP)**

```python
import httpx

payload = httpx.get(
    "http://localhost:8000/v1/admin/analytics/usage",
    headers={"X-Admin-Key": "admin-secret"},
    params={"window": "24h"},
).json()
print(payload)
```

**Representative TypeScript (HTTP)**

```typescript
const response = await fetch(
  "http://localhost:8000/v1/admin/analytics/top-queries?limit=10&window=24h",
  { headers: { "X-Admin-Key": "admin-secret" } },
);
const payload = await response.json();
console.log(payload);
```

**Representative responses**

```json
{"keys":[{"key_id":"acme-support-1234","tenant":"acme","rate_limit_rpm":100}]}
{"usage":[{"tenant":"acme","requests_last_24h":1284}]}
```

**Errors:** `401` invalid/missing admin key, `404`, `409` on invalid rotation state, `422` on invalid analytics params.  
**Rate limit:** admin routes currently require admin auth but are not documented as returning the standard per-key rate-limit headers from the user auth middleware.
