# Fly.io Demo Deployment

This deploy target runs the public demo API in read-only mode.

Demo-mode behavior:
- `AGENTFLOW_DEMO_MODE=true` injects a public demo key
- admin routes under `/v1/admin/*` and `/admin/*` return `404`
- mutating routes are blocked in demo mode, except `POST /v1/query` and `POST /v1/query/explain`
- seeded DuckDB demo data remains available on first boot

## Prerequisites

- Fly CLI installed
- Docker installed locally for image builds
- Access to the target Fly organization

## Initial setup

```bash
fly auth login
fly launch --copy-config --no-deploy
fly volumes create agentflow_demo_data --size 1 --region fra
```

Optional: override the default public API key.

If `DEMO_API_KEY` is unset, the app falls back to `demo-key`.

```bash
fly secrets set DEMO_API_KEY=demo-key
```

## Deploy

From the repository root:

```bash
fly deploy -c deploy/fly/fly.toml
```

## Smoke check

The current seeded order ID in the repository demo data is `ORD-20260404-1001`.

```bash
curl https://agentflow-demo.fly.dev/v1/health

curl -H "X-API-Key: demo-key" \
  https://agentflow-demo.fly.dev/v1/entity/order/ORD-20260404-1001
```

Expected demo-mode behavior:

```bash
curl -i -H "X-Admin-Key: admin-secret" \
  https://agentflow-demo.fly.dev/v1/admin/usage
# 404

curl -i -X POST \
  -H "X-API-Key: demo-key" \
  -H "Content-Type: application/json" \
  -d '{"requests":[]}' \
  https://agentflow-demo.fly.dev/v1/batch
# 403
```

## Local verification

```bash
python -c "import tomllib, pathlib; tomllib.loads(pathlib.Path('deploy/fly/fly.toml').read_text(encoding='utf-8'))"
docker build -t agentflow-demo -f Dockerfile.api .
docker run --rm -p 8000:8000 \
  -e DUCKDB_PATH=/data/agentflow-demo.duckdb \
  -e AGENTFLOW_USAGE_DB_PATH=/data/agentflow-demo-api.duckdb \
  -e AGENTFLOW_DEMO_MODE=true \
  -e AGENTFLOW_SEED_ON_BOOT=true \
  agentflow-demo
```

In another terminal:

```bash
curl -H "X-API-Key: demo-key" http://localhost:8000/v1/entity/order/ORD-20260404-1001
```

## Teardown

```bash
fly apps destroy agentflow-demo
```
