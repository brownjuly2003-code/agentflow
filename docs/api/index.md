# API

This walkthrough gives application developers the shortest path from a running
service to a useful read. It demonstrates only the stable core flow. The
[full API reference](../api-reference.md) owns the exact authentication and
correlation headers, endpoint inventory, parameters, request limits, response
fields, status codes, and operational or admin surfaces. Use the generated
[OpenAPI document](../openapi.json) when a machine-readable core contract is
required.

## Before you start

Complete the [quickstart](../quickstart.md) and start the API. The commands
below use the local URL `http://localhost:8000` and the quickstart's
`demo-key`; use deployment-specific values instead. See the reference's
[base URL and headers](../api-reference.md#base-url-and-headers) section for
the complete authentication contract.

## 1. Check the service

Confirm that the API can answer before issuing a data request:

```bash
curl http://localhost:8000/v1/health
```

The detailed response and error contract belongs to the
[health reference](../api-reference.md#get-v1health).

## 2. Discover available data

Read the catalog before hard-coding an entity or metric name:

```bash
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/catalog
```

Choose an entity type and identifier from the catalog for the next request.

## 3. Read an entity

Fetch the current state through the semantic entity boundary:

```bash
curl -H "X-API-Key: demo-key" \
  http://localhost:8000/v1/entity/order/ORD-20260404-1001
```

For historical reads, response fields, and failure cases, continue in the
[entity lookup reference](../api-reference.md#get-v1entityentity_typeentity_id).

## 4. Ask a constrained question

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: demo-key" \
  -d '{"question":"top products by revenue today","limit":5}'
```

The [query and pagination reference](../api-reference.md#query-and-pagination-model)
defines the complete request and response shape. Inspect a query before running
it when the reference calls for the explain workflow.

## Continue by task

| Goal | Detailed owner |
| --- | --- |
| Historical reads and pagination | [Query and pagination model](../api-reference.md#query-and-pagination-model) |
| Contracts, search, and lineage | [Discovery and governance](../api-reference.md#discovery-and-governance) |
| Streaming and operator workflows | [Streaming and operational workflows](../api-reference.md#streaming-and-operational-workflows) |
| Platform administration | [Admin API](../api-reference.md#admin-api) |

For typed client setup and language-specific calls, continue with the
[SDK guide](../sdk.md). The full reference remains authoritative when a client
helper and the HTTP surface differ.
