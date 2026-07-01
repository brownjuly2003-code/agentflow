# ClickHouse Serving Guide (default engine) / DuckDB rollback

## Overview

**ClickHouse is the shipped serving engine** ([ADR 0006](decisions/0006-fix-demo-serving-engine-on-clickhouse.md), executed 2026-07-02): `config/serving.yaml` defaults to `backend: clickhouse`, `make demo` and `docker-compose.prod.yml` bring the service up by default, and the local pipeline writes the serving tables + `pipeline_events` journal to it (`src/processing/clickhouse_sink.py`). `DuckDB` remains the local-dev / test and compatibility store — `pytest` pins it (`tests/conftest.py`) and the control-plane state (webhooks, alerts, outbox, usage) stays on it per [ADR 0009](decisions/0009-control-plane-state-and-scaling-gate.md).

Upsert model on ClickHouse: mutable serving tables are `ReplacingMergeTree` versioned by a `MATERIALIZED af_updated_at` column; an upsert is an appended row version and every backend read runs with the `final=1` setting, so queries always see the latest version. The journal stays append-only `MergeTree`. Live verification: [clickhouse-serving-verify-2026-07-02](perf/clickhouse-serving-verify-2026-07-02.md).

## When to roll back to DuckDB

- Zero-dependency offline development (no container / no server available).
- Test debugging against the pytest-pinned store.

Rollback is configuration-only: `SERVING_BACKEND=duckdb`.

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

`ClickHouse` is part of the default bring-up (no profile flag needed):

```bash
docker compose -f docker-compose.prod.yml up -d clickhouse
```

Then run the API against it (clickhouse is already the default backend):

```bash
docker compose -f docker-compose.prod.yml up -d agentflow-api
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
