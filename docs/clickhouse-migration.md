# DuckDB to ClickHouse Migration Guide

## Overview

Task 8 adds a pluggable serving backend. `DuckDB` remains the default for local and single-node deployments, while `ClickHouse` is available for higher read concurrency and larger datasets.

## When to switch

- Tenant data is moving past roughly 100 GB.
- Read traffic is trending beyond what a single local `DuckDB` file can handle comfortably.
- You need a path to horizontal scale without changing the API contract.

## Backend selection

Use either the environment variable or `config/serving.yaml`.

```yaml
backend: clickhouse

clickhouse:
  host: localhost
  port: 8123
  user: default
  password: ""
  database: agentflow
  secure: false
  timeout_seconds: 10
```

Environment variables override the file:

```bash
SERVING_BACKEND=clickhouse
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_DATABASE=agentflow
```

## Local bring-up

Start the optional `ClickHouse` service with its dedicated profile:

```bash
docker compose -f docker-compose.prod.yml --profile clickhouse up -d clickhouse
```

Then run the API against it:

```bash
SERVING_BACKEND=clickhouse docker compose -f docker-compose.prod.yml up -d agentflow-api
```

The bundled production compose file provisions a local development user:

```text
user: agentflow
password: agentflow
```

The backend initializes the demo tables on first start so entity lookups and metric reads work immediately in a fresh local environment.

## Migration steps

1. Provision `ClickHouse` and verify `http://<host>:8123/ping` returns `Ok.`.
2. Copy the serving backend config into `config/serving.yaml` or set the equivalent environment variables.
3. Start the API with `SERVING_BACKEND=clickhouse`.
4. Validate health at the backend layer:

```python
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine

engine = QueryEngine(catalog=DataCatalog())
print(engine.health())
```

5. Validate read parity through the API:

```bash
curl http://localhost:8000/v1/entity/order/ORD-20260404-1001
curl "http://localhost:8000/v1/metrics/revenue?window=24h"
curl http://localhost:8000/v1/query/explain -H "Content-Type: application/json" -d "{\"question\":\"What is the revenue today?\"}"
```

## Rollback

Rollback is configuration-only:

```bash
SERVING_BACKEND=duckdb
```

or:

```yaml
backend: duckdb
```

Restart the API and it will resume serving from the existing `DuckDB` path without code changes.

## Notes

- `DuckDB` remains available as the compatibility store for components that still read `query_engine._conn` directly.
- Task 8 only abstracts entity, metric, NL query, pagination, and backend health reads behind the new serving backend contract.
