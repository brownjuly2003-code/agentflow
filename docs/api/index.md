# API

The local base URL is `http://localhost:8000`. The detailed maintained
reference remains the repository
[API Reference](https://github.com/brownjuly2003-code/agentflow/blob/main/docs/api-reference.md);
this page focuses on the core walkthrough surface.

## Headers

| Header | Use |
| --- | --- |
| `X-API-Key: <key>` | Required for protected user routes unless local demo auth is disabled |
| `X-Admin-Key: <admin-key>` | Required for `/v1/admin/*` |
| `X-AgentFlow-Version: YYYY-MM-DD` | Optional API version pin |
| `X-Correlation-ID` or `X-Request-Id` | Optional request correlation input |

## Core endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/health` | Service and pipeline health |
| `GET` | `/v1/catalog` | Entities, metrics, streaming, and audit sources |
| `GET` | `/v1/entity/{entity_type}/{entity_id}` | Current or historical entity lookup |
| `GET` | `/v1/metrics/{metric_name}` | Metric lookup with optional window/as-of parameters |
| `POST` | `/v1/query/explain` | Translate a natural-language question without executing |
| `POST` | `/v1/query` | Execute a constrained natural-language query |
| `POST` | `/v1/batch` | Batch up to 20 entity, metric, or query requests |
| `GET` | `/v1/search` | Search entities, metrics, and catalog fields |
| `GET` | `/v1/stream/events` | Server-sent event stream for validated events |

## Entity lookup

=== "curl"

    ```bash
    curl -H "X-API-Key: demo-key" \
      http://localhost:8000/v1/entity/order/ORD-20260404-1001
    ```

=== "Python"

    ```python
    import httpx

    response = httpx.get(
        "http://localhost:8000/v1/entity/order/ORD-20260404-1001",
        headers={"X-API-Key": "demo-key"},
        timeout=10,
    )
    print(response.json())
    ```

=== "TypeScript"

    ```typescript
    const response = await fetch(
      "http://localhost:8000/v1/entity/order/ORD-20260404-1001",
      { headers: { "X-API-Key": "demo-key" } },
    );
    console.log(await response.json());
    ```

Representative response shape:

```json
{
  "entity_type": "order",
  "entity_id": "ORD-20260404-1001",
  "data": {
    "status": "delivered"
  },
  "freshness_seconds": 12.4
}
```

## Natural-language query

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: demo-key" \
  -d '{"question":"top products by revenue today","limit":5}'
```

Representative response shape:

```json
{
  "rows": [
    {
      "product_id": "PROD-001"
    }
  ],
  "sql": "SELECT ...",
  "total_count": 42,
  "next_cursor": null,
  "has_more": false,
  "page_size": 5
}
```

## Contract and lineage routes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/contracts` | List schema contracts |
| `GET` | `/v1/contracts/{entity}` | Latest stable contract for one entity |
| `GET` | `/v1/contracts/{entity}/{version}` | Specific contract version |
| `GET` | `/v1/contracts/{entity}/diff/{from_version}/{to_version}` | Contract diff |
| `POST` | `/v1/contracts/{entity}/validate` | Validate a candidate schema |
| `GET` | `/v1/lineage/{entity_type}/{entity_id}` | Source-to-serving provenance |

## Operational routes

| Area | Routes |
| --- | --- |
| Dead letters | `/v1/deadletter`, `/v1/deadletter/stats`, replay, dismiss |
| Webhooks | `/v1/webhooks`, test delivery, logs |
| Alerts | `/v1/alerts`, test delivery, history |
| SLO | `/v1/slo` |
| Metrics scrape | `/metrics` |
| Admin | `/v1/admin/*` with `X-Admin-Key` |

Operational and admin routes are HTTP API surfaces. The SDKs focus on the core
agent read/query contract; use direct HTTP for routes that are not wrapped by a
typed client helper.
