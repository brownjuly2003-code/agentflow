# Quickstart

This path runs AgentFlow locally, seeds demo data, starts the API, and verifies
the main read/query surface. It uses only local tooling and Docker for Redis.

## Prerequisites

- Python `3.11+`
- `make`
- Docker Compose
- Optional docs tooling: `mkdocs-material` for this site

Install the docs tooling if it is not already available:

```bash
python -m pip install "mkdocs-material>=9.5,<10"
```

## Clone and set up

=== "PowerShell"

    ```powershell
    git clone https://github.com/brownjuly2003-code/agentflow.git
    cd agentflow
    . .\scripts\setup.ps1
    ```

=== "macOS / Linux"

    ```bash
    git clone https://github.com/brownjuly2003-code/agentflow.git
    cd agentflow
    source ./scripts/setup.sh
    ```

## Start the demo API

`make demo` seeds local data, starts Redis, and runs FastAPI on
`http://localhost:8000`.

```bash
make demo
```

The command runs the API in the foreground. Leave it open while trying the
requests below.

## Verify health

```bash
curl http://localhost:8000/v1/health
```

Expected shape:

```json
{
  "status": "healthy",
  "components": [
    {
      "name": "duckdb_pool",
      "status": "healthy"
    }
  ]
}
```

The exact component list can vary by configuration. The important signal is an
HTTP `200` response with an overall healthy status.

## Query live entities and metrics

```bash
curl http://localhost:8000/v1/entity/order/ORD-20260404-1001
curl "http://localhost:8000/v1/metrics/revenue?window=24h"
```

The local demo disables API-key enforcement through its demo environment. In a
configured environment, send `X-API-Key: <key>` on protected routes.

## Ask a natural-language query

```bash
curl -X POST http://localhost:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question":"top products by revenue today","limit":5}'
```

The response includes result rows, translated SQL metadata, and pagination
fields when the query supports cursor pagination.

## Serve this documentation site

```bash
mkdocs serve
```

Open `http://127.0.0.1:8000` if that port is free. If the AgentFlow API is
already using port `8000`, run:

```bash
mkdocs serve -a 127.0.0.1:8010
```

Build the static site:

```bash
mkdocs build --strict
```
