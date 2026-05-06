# Troubleshooting

## Docker is not running

Symptoms:

- `docker compose up -d redis` fails
- `make demo` cannot start Redis
- compose health checks never start

Checks:

```bash
docker version
docker compose version
docker compose ps
```

Fix:

- Start Docker Desktop or the local Docker daemon.
- Re-run the command after Docker reports a healthy engine.
- If ports are occupied, stop the conflicting local process or choose a
  narrower compose stack.

## API port is already in use

AgentFlow API defaults to `8000`, and `mkdocs serve` also defaults to `8000`.
Run docs on another port when the API is active:

```bash
mkdocs serve -a 127.0.0.1:8010
```

Run the API on another port when needed:

```bash
uvicorn src.serving.api.main:app --host 0.0.0.0 --port 8001
```

## Kafka or Flink startup is slow

Symptoms:

- Kafka health check retries
- Flink dashboard at `http://localhost:8081` is not ready
- topic bootstrap fails because the broker is not healthy yet

Checks:

```bash
docker compose ps
docker compose logs kafka
docker compose logs flink-jobmanager
```

Fix:

- Wait for health checks to settle before registering connectors or producing
  events.
- Use the local demo path when you only need API/SDK walkthrough behavior.
- Recreate the compose stack only when stale volumes are the suspected cause:
  `docker compose down -v`.

## DuckDB file path problems

Symptoms:

- `/v1/health` reports an unhealthy serving component
- entity lookups return unavailable storage errors
- local runs appear to use an unexpected database

Checks:

```bash
echo $DUCKDB_PATH
ls *.duckdb*
```

Fix:

- For the demo path, use `DUCKDB_PATH=agentflow_demo.duckdb`.
- Re-run `make demo` to seed the expected fixture data.
- Avoid sharing the same DuckDB file between long-running writers.

## Auth headers fail locally

The demo path disables API-key enforcement. Configured environments require
`X-API-Key: <key>` for most v1 routes and `X-Admin-Key: <admin-key>` for
admin routes.

Check whether you are using the demo path or a configured API-key file before
debugging SDK behavior.

## Common verification commands

Docs-only changes:

```bash
mkdocs build --strict
git diff --check
```

Python quality checks requested for this walkthrough:

```bash
python -m ruff check src/ tests/
python -m ruff format --check src/ tests/
```

Full pytest is useful when backend or SDK behavior changes:

```bash
python -m pytest -p no:schemathesis --basetemp=.tmp/docs-walkthrough-basetemp -o cache_dir=.tmp/docs-walkthrough-cache
```

## When to use the existing runbook

Use the operational runbook for incident-style workflows:

- API unavailable
- pipeline lag
- dead-letter growth
- webhook delivery failures
- alert storms
- key rotation issues

The walkthrough is a learning path. The runbook is the operator procedure.
