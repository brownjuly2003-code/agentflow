# Jaeger

Production-like tracing is exposed through Jaeger in `docker-compose.prod.yml`.

## Start

```bash
docker compose -f docker-compose.prod.yml up -d jaeger agentflow-api
```

Open `http://localhost:16686` and select the `agentflow-api` service.

## Generate traces

Run a query request:

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: af_demo_key" \
  -d "{\"question\":\"top 5 products by revenue today\"}"
```

Replay a dead-letter event to verify Kafka propagation:

```bash
curl -X POST http://localhost:8000/v1/deadletter/<event_id>/replay \
  -H "Content-Type: application/json" \
  -H "X-API-Key: af_demo_key" \
  -d "{}"
```

Expected spans in the same trace:

- `http.request`
- `query_engine.translate`
- `duckdb.query`
- `kafka.produce`

## Configuration

- `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317` sends spans to Jaeger OTLP gRPC.
- `OTEL_SERVICE_NAME=agentflow-api` controls the service name in Jaeger.
- `OTEL_SDK_DISABLED=true` disables tracing without changing application code.
