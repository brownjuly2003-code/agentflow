# AgentFlow — Market-Grade v3: CLI, Observability, Compliance
**Date**: 2026-04-10  
**Phase**: After v1 + v2 (SDK, integrations, webhooks, SSE, Redis cache, SLO, CI)  
**Goal**: Fill remaining operational gaps — CLI, tracing, batch API, CrewAI, PII masking, dead-letter browser, Flink runner  
**Executor**: Codex

## Context for Codex

Done in v1+v2:
- Routers: agent_query, stream, admin, lineage, webhooks, search, slo
- Integrations: langchain/, llamaindex/
- SDK: sync + async client, PyPI-installable
- Auth: multi-tenant YAML, per-key rate limits
- Redis cache, SSE streaming, time-travel queries
- Production Docker Compose (3-broker Kafka, Redis, Grafana)
- Testcontainers, CI coverage gate + perf regression

Still missing:
- No CLI tool
- No CrewAI integration
- No OpenTelemetry traces
- No batch query endpoint
- No CORS middleware
- No dead-letter browser/replay
- No PII masking
- No Flink local Docker runner
- No query explain endpoint

---

## TASK 1 — `agentflow` CLI Tool

**Priority**: P0 — DevX: agents and developers need terminal access without writing Python  
**Time estimate**: 2h  

### What to build

A `agentflow` CLI command installed alongside the SDK.

### Files to create/modify

```
sdk/agentflow/
  cli.py                 # NEW: Click-based CLI
sdk/
  pyproject.toml         # add console_scripts entry point
```

### Commands spec

```
agentflow health                        → show pipeline health + freshness
agentflow entity <type> <id>            → get entity (order/user/product/session)
agentflow metric <name> [--window 1h]   → get metric value
agentflow query "<question>"            → NL→SQL query
agentflow search "<terms>"              → semantic entity search
agentflow catalog                       → list all entities + metrics
agentflow slo                           → show SLO compliance table
agentflow stream [--type order]         → stream events to stdout (Ctrl+C to stop)
agentflow config                        → show current base_url + masked api_key
```

### Global flags

```
--url    TEXT    Base URL [env: AGENTFLOW_URL, default: http://localhost:8000]
--key    TEXT    API key  [env: AGENTFLOW_API_KEY]
--json           Output raw JSON (default: human-readable table)
--quiet          Suppress headers/decorations
```

### Implementation spec

```python
# sdk/agentflow/cli.py
import click, json, os
from agentflow import AgentFlowClient

def get_client(url, key):
    url = url or os.environ.get("AGENTFLOW_URL", "http://localhost:8000")
    key = key or os.environ.get("AGENTFLOW_API_KEY", "")
    return AgentFlowClient(url, key)

@click.group()
@click.option("--url", default=None)
@click.option("--key", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def cli(ctx, url, key, as_json):
    ctx.ensure_object(dict)
    ctx.obj["client"] = get_client(url, key)
    ctx.obj["json"] = as_json

@cli.command()
@click.pass_context
def health(ctx):
    """Show pipeline health and data freshness."""
    h = ctx.obj["client"].health()
    if ctx.obj["json"]:
        click.echo(h.model_dump_json(indent=2))
    else:
        # Rich table: component | status | details
        ...
```

Human-readable output uses `rich` tables (already in ecosystem or add as dep):
```
$ agentflow health
Component       Status     Details
─────────────────────────────────────
Pipeline        healthy    freshness: 4.2s
API             healthy    p95: 18ms
Kafka           healthy    lag: 0
Quality score   0.994      dead_letter_rate: 0.6%

$ agentflow metric revenue --window 24h
Metric: revenue (24h window)
Value:  $142,847.00
Unit:   USD
As of:  2026-04-10T14:23:01Z (fresh: 3.1s ago)

$ agentflow entity order ORD-1
Order ORD-1
  Status:       delivered
  Total:        $249.99
  Customer:     USR-42
  Items:        3
  Created:      2026-04-09T11:30:00Z
```

### pyproject.toml addition

```toml
[project.scripts]
agentflow = "agentflow.cli:cli"
```

### Acceptance criteria

- [ ] `pip install -e sdk/` → `agentflow --help` works
- [ ] `agentflow health` shows table with pipeline components
- [ ] `agentflow entity order ORD-1` returns formatted order
- [ ] `agentflow metric revenue --window 24h` returns value
- [ ] `agentflow stream --type order` prints events until Ctrl+C
- [ ] `--json` flag on any command outputs raw JSON
- [ ] `AGENTFLOW_URL` + `AGENTFLOW_API_KEY` env vars respected
- [ ] `tests/unit/test_cli.py` — 8+ tests with `CliRunner` (Click's test utility)

---

## TASK 2 — CrewAI Integration

**Priority**: P0 — completes "big 3" agent frameworks (LangChain + LlamaIndex + CrewAI)  
**Time estimate**: 1.5h  

### What to build

AgentFlow tools for CrewAI agents.

### Files to create

```
integrations/agentflow_integrations/
  crewai/
    __init__.py
    tools.py             # AgentFlow tools for CrewAI
tests/unit/
  test_crewai_tools.py
docs/integrations.md     # add CrewAI section
```

### Implementation spec

```python
# integrations/agentflow_integrations/crewai/tools.py
from crewai_tools import BaseTool
from agentflow import AgentFlowClient

class OrderLookupTool(BaseTool):
    name: str = "AgentFlow Order Lookup"
    description: str = (
        "Look up real-time order details by order ID. "
        "Returns status, total amount, customer ID, items count, and timestamps."
    )
    client: AgentFlowClient

    def _run(self, order_id: str) -> str:
        order = self.client.get_order(order_id)
        return order.model_dump_json(indent=2)

class MetricQueryTool(BaseTool):
    name: str = "AgentFlow Metric Query"
    description: str = (
        "Query business metrics from the data platform. "
        "Available metrics: revenue, order_count, avg_order_value, "
        "conversion_rate, active_sessions, error_rate. "
        "Specify metric_name and optional window (1h, 24h, 7d)."
    )
    client: AgentFlowClient

    def _run(self, metric_name: str, window: str = "1h") -> str:
        result = self.client.get_metric(metric_name, window)
        return f"{metric_name} ({window}): {result.value} {result.unit}"

class NLQueryTool(BaseTool):
    name: str = "AgentFlow Natural Language Query"
    description: str = (
        "Ask business questions in natural language. "
        "The platform translates to SQL and returns results. "
        "Example: 'Top 5 products by revenue today'"
    )
    client: AgentFlowClient

    def _run(self, question: str) -> str:
        result = self.client.query(question)
        return result.model_dump_json()

def get_agentflow_tools(base_url: str, api_key: str) -> list:
    """Return all AgentFlow tools configured for a CrewAI agent."""
    client = AgentFlowClient(base_url, api_key)
    return [
        OrderLookupTool(client=client),
        MetricQueryTool(client=client),
        NLQueryTool(client=client),
    ]
```

Usage in docs/integrations.md:
```python
from crewai import Agent, Task, Crew
from agentflow_integrations.crewai import get_agentflow_tools

tools = get_agentflow_tools("http://localhost:8000", api_key="af-dev-key")

support_agent = Agent(
    role="Customer Support Specialist",
    goal="Answer customer questions about orders using real-time data",
    tools=tools,
)
```

### Acceptance criteria

- [ ] `from agentflow_integrations.crewai import get_agentflow_tools` works
- [ ] `get_agentflow_tools(url, key)` returns 3 BaseTool instances
- [ ] Each tool's `_run()` calls real SDK (mocked in tests)
- [ ] `tests/unit/test_crewai_tools.py` — 6+ tests with mocked client
- [ ] `docs/integrations.md` — CrewAI quickstart section with full agent example

---

## TASK 3 — OpenTelemetry Distributed Tracing

**Priority**: P1 — production systems need request-level traces, not just Prometheus metrics  
**Time estimate**: 2h  

### What to build

Instrument the FastAPI API with OpenTelemetry traces. Export to OTLP (Jaeger/Tempo in prod, stdout in dev).

### Files to create/modify

```
src/serving/api/
  telemetry.py           # NEW: OTel setup
  main.py                # call setup_telemetry() on startup
src/serving/api/routers/
  agent_query.py         # add manual span for NL→SQL translation
  stream.py              # trace SSE connections
docker-compose.prod.yml  # add Jaeger or Tempo service
requirements.txt         # add opentelemetry-sdk, opentelemetry-instrumentation-fastapi
```

### Implementation spec

```python
# src/serving/api/telemetry.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
import os

def setup_telemetry(app) -> None:
    provider = TracerProvider()

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
        )
    else:
        # Dev mode: print to stdout (structured JSON)
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()   # traces outbound HTTP (NL→SQL calls)
```

Manual spans for high-value operations:
```python
# In agent_query.py — NL→SQL endpoint
tracer = trace.get_tracer("agentflow.api")

async def nl_query(...):
    with tracer.start_as_current_span("nl_to_sql") as span:
        span.set_attribute("query.text", question)
        span.set_attribute("query.engine", "claude" if use_llm else "rule_based")
        result = await engine.translate(question)
        span.set_attribute("query.sql", result.sql)
        span.set_attribute("query.rows", result.row_count)
```

### Docker Compose addition

Add Jaeger to `docker-compose.prod.yml`:
```yaml
jaeger:
  image: jaegertracing/all-in-one:1.55
  ports:
    - "16686:16686"   # Jaeger UI
    - "4317:4317"     # OTLP gRPC
  environment:
    COLLECTOR_OTLP_ENABLED: "true"
```

### Environment variables

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317   # set in docker-compose.prod.yml
OTEL_SERVICE_NAME=agentflow-api                   # add to .env.example
```

### Acceptance criteria

- [ ] Every API request generates a trace (FastAPI auto-instrumentation)
- [ ] NL→SQL endpoint has manual span with `query.text`, `query.engine`, `query.sql` attributes
- [ ] Outbound HTTP calls (to Claude API) appear as child spans
- [ ] `OTEL_EXPORTER_OTLP_ENDPOINT` unset → traces printed to stdout (dev mode)
- [ ] Jaeger added to `docker-compose.prod.yml`, visible at http://localhost:16686
- [ ] `.env.example` updated with OTel variables
- [ ] `tests/unit/test_telemetry.py` — 3 tests: setup doesn't crash, spans created, attributes set

---

## TASK 4 — Batch Query Endpoint

**Priority**: P1 — agents fetch multiple entities/metrics in one request instead of N round trips  
**Time estimate**: 1.5h  

### What to build

`POST /v1/batch` — execute multiple queries in one HTTP call.

### Files to create/modify

```
src/serving/api/routers/
  batch.py               # NEW: batch router
src/serving/api/
  main.py                # register batch router
sdk/agentflow/
  client.py              # add batch() method
  async_client.py        # add async batch() method
tests/integration/
  test_batch.py          # NEW
```

### API spec

```python
class BatchRequest(BaseModel):
    requests: list[BatchItem] = Field(..., max_length=20)

class BatchItem(BaseModel):
    id: str                          # client-assigned correlation ID
    type: Literal["entity", "metric", "query"]
    params: dict                     # type-specific params

class BatchResponse(BaseModel):
    results: list[BatchResult]
    duration_ms: float

class BatchResult(BaseModel):
    id: str                          # matches BatchItem.id
    status: Literal["ok", "error"]
    data: dict | None
    error: str | None
```

Example request:
```json
POST /v1/batch
{
  "requests": [
    {"id": "r1", "type": "entity",  "params": {"entity_type": "order", "entity_id": "ORD-1"}},
    {"id": "r2", "type": "metric",  "params": {"name": "revenue", "window": "1h"}},
    {"id": "r3", "type": "metric",  "params": {"name": "active_sessions", "window": "1h"}},
    {"id": "r4", "type": "query",   "params": {"question": "top 3 products today"}}
  ]
}
```

Example response:
```json
{
  "results": [
    {"id": "r1", "status": "ok", "data": {...order...}},
    {"id": "r2", "status": "ok", "data": {"value": 142847.0, "unit": "USD"}},
    {"id": "r3", "status": "ok", "data": {"value": 312, "unit": "count"}},
    {"id": "r4", "status": "error", "data": null, "error": "NL query timeout"}
  ],
  "duration_ms": 34.2
}
```

### Implementation

Execute all batch items concurrently with `asyncio.gather()`. Individual item errors do NOT fail the whole batch — return `status: "error"` for that item only.

```python
@router.post("/batch")
async def batch_query(req: BatchRequest, _auth=Depends(require_api_key)):
    tasks = [execute_item(item) for item in req.requests]
    t0 = time.monotonic()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    duration_ms = (time.monotonic() - t0) * 1000
    return BatchResponse(results=results, duration_ms=duration_ms)
```

### SDK addition

```python
# client.py
def batch(self, requests: list[dict]) -> BatchResponse:
    """Execute multiple queries in one request."""
    ...

# Convenience builder:
client.batch([
    client.batch_entity("order", "ORD-1"),
    client.batch_metric("revenue", "1h"),
    client.batch_query("top products today"),
])
```

### Acceptance criteria

- [ ] `POST /v1/batch` with 4 items → 4 results, concurrent execution
- [ ] One item failing → other items still return `status: "ok"`
- [ ] Max 20 items per batch (422 if exceeded)
- [ ] `duration_ms` reflects actual wall time (not sum of individual times)
- [ ] Auth required
- [ ] `client.batch([...])` works in SDK
- [ ] `tests/integration/test_batch.py` — 6+ tests: success, partial failure, over-limit, auth

---

## TASK 5 — CORS + Request Origin Validation

**Priority**: P1 — browser-based agents fail without CORS; missing from main.py  
**Time estimate**: 0.5h  

### What to build

Add `CORSMiddleware` to FastAPI with configurable allowed origins.

### Files to modify

```
src/serving/api/
  main.py                # add CORSMiddleware
.env.example             # add AGENTFLOW_CORS_ORIGINS
```

### Implementation

```python
# src/serving/api/main.py
from fastapi.middleware.cors import CORSMiddleware
import os

cors_origins = os.getenv("AGENTFLOW_CORS_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type", "Authorization"],
    expose_headers=["X-Cache", "X-Request-Id", "X-Process-Time"],
)
```

`.env.example` addition:
```
# CORS: comma-separated list of allowed origins
# Use * for development only (never in production)
AGENTFLOW_CORS_ORIGINS=http://localhost:3000,http://localhost:8080
```

### Acceptance criteria

- [ ] `OPTIONS /v1/health` returns `Access-Control-Allow-Origin` header
- [ ] `AGENTFLOW_CORS_ORIGINS=*` allows all origins (dev mode)
- [ ] Default: `localhost:3000` allowed, other origins blocked
- [ ] `X-Cache`, `X-Request-Id` exposed to browser (in `expose_headers`)
- [ ] `tests/unit/test_cors.py` — 3 tests: allowed origin, blocked origin, preflight OPTIONS

---

## TASK 6 — Dead-Letter Queue Browser + Event Replay

**Priority**: P1 — ops teams need visibility into failed events  
**Time estimate**: 2h  

### What to build

API to browse dead-letter events and replay them back into the pipeline.

### Files to create/modify

```
src/serving/api/routers/
  deadletter.py          # NEW: dead-letter browser
src/serving/api/
  main.py                # register dead-letter router
src/processing/
  event_replayer.py      # NEW: replay logic
tests/integration/
  test_deadletter.py     # NEW
```

### Data model

Dead-letter events are already in DuckDB (from stream_processor). Extend the schema:

```sql
-- If not already present, add to query_engine initialization:
CREATE TABLE IF NOT EXISTS dead_letter_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT,
    payload JSON,
    failure_reason TEXT,     -- "schema_validation", "semantic_validation", "enrichment_error"
    failure_detail TEXT,     -- specific error message
    received_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    last_retried_at TIMESTAMP,
    status TEXT DEFAULT 'failed'  -- "failed", "replayed", "dismissed"
);
```

### API endpoints (`/v1/deadletter`)

```
GET  /v1/deadletter                    — list failed events (paginated)
GET  /v1/deadletter?reason=schema_validation  — filter by failure reason
GET  /v1/deadletter/{event_id}         — get single failed event with full payload
POST /v1/deadletter/{event_id}/replay  — fix and resubmit to pipeline
POST /v1/deadletter/{event_id}/dismiss — mark as acknowledged (won't retry)
GET  /v1/deadletter/stats              — counts by reason + trend (last 24h)
```

### Replay logic (`event_replayer.py`)

```python
class EventReplayer:
    def replay(self, event_id: str, corrected_payload: dict | None = None) -> ReplayResult:
        """
        Replay a dead-letter event:
        1. Load original payload from dead_letter_events
        2. Apply corrected_payload overrides (optional)
        3. Re-validate with schema + semantic validators
        4. If valid → produce to Kafka events.raw topic
        5. Update dead_letter_events: status="replayed", retry_count++
        """
```

### Acceptance criteria

- [ ] `GET /v1/deadletter` returns paginated list with failure_reason + failure_detail
- [ ] `GET /v1/deadletter/stats` returns breakdown: `{"schema_validation": 12, "semantic_validation": 3}`
- [ ] `POST /v1/deadletter/{id}/replay` re-validates before submitting (returns 422 if still invalid)
- [ ] `POST /v1/deadletter/{id}/dismiss` marks event as acknowledged
- [ ] Auth required (read-only key can browse, cannot replay/dismiss)
- [ ] `tests/integration/test_deadletter.py` — 7+ tests: list, filter, stats, replay valid, replay still-invalid, dismiss

---

## TASK 7 — PII Field Masking

**Priority**: P1 — compliance requirement; agents must not see raw PII  
**Time estimate**: 1.5h  

### What to build

Configurable PII masking applied to API responses before they leave the serving layer.

### Files to create/modify

```
src/serving/
  masking.py             # NEW: PiiMasker
config/
  pii_fields.yaml        # NEW: which fields to mask per entity type
src/serving/api/routers/
  agent_query.py         # apply masking to entity responses
tests/unit/
  test_masking.py        # NEW
```

### config/pii_fields.yaml

```yaml
masking:
  default_strategy: partial   # partial | full | hash | none

  entity_fields:
    user:
      - field: email
        strategy: partial       # "j***@example.com"
      - field: phone
        strategy: partial       # "***-***-1234"
      - field: full_name
        strategy: partial       # "J*** D***"
      - field: ip_address
        strategy: hash          # SHA-256, non-reversible

    order:
      - field: shipping_address
        strategy: partial       # "123 *** St, ***"

  # Tenants with PII clearance bypass masking
  pii_exempt_tenants:
    - "internal-analytics"
    - "compliance-audit"
```

### Implementation spec

```python
# src/serving/masking.py
class PiiMasker:
    def __init__(self, config_path: str = "config/pii_fields.yaml"):
        self._config = yaml.safe_load(open(config_path))

    def mask(self, entity_type: str, data: dict, tenant: str) -> dict:
        """Apply PII masking to entity response dict."""
        if tenant in self._config["masking"]["pii_exempt_tenants"]:
            return data
        fields = self._config["masking"]["entity_fields"].get(entity_type, [])
        masked = data.copy()
        for rule in fields:
            if rule["field"] in masked:
                masked[rule["field"]] = self._apply_strategy(
                    masked[rule["field"]], rule["strategy"]
                )
        return masked

    def _apply_strategy(self, value: str, strategy: str) -> str:
        if strategy == "full":
            return "***"
        if strategy == "hash":
            return hashlib.sha256(str(value).encode()).hexdigest()[:12]
        if strategy == "partial":
            return self._partial_mask(value)
        return value
```

Response header: `X-PII-Masked: true` when masking was applied.

### Acceptance criteria

- [ ] `GET /v1/entity/user/USR-1` — email shows as `j***@example.com` by default
- [ ] PII-exempt tenant (from `config/api_keys.yaml` + `config/pii_fields.yaml`) sees full data
- [ ] `X-PII-Masked: true` header present when masking applied
- [ ] `config/pii_fields.yaml` is the single source of truth (no hardcoding in code)
- [ ] `tests/unit/test_masking.py` — 8+ tests: partial mask, full mask, hash, exempt tenant, missing field

---

## TASK 8 — Flink Local Docker Runner

**Priority**: P2 — closes the original P2 audit gap: "Flink jobs can't run locally"  
**Time estimate**: 2h  

### What to build

Docker Compose service + wrapper script that runs the PyFlink stream processor in a Python 3.11 container.

### Files to create/modify

```
docker-compose.flink.yml # NEW: Flink-specific compose override
scripts/
  run_flink_local.sh     # NEW: start Flink job in Docker
  run_flink_local.ps1    # NEW: Windows version
src/processing/flink_jobs/
  Dockerfile             # NEW: Python 3.11 + PyFlink image
Makefile.py              # add flink-local target
docs/runbook.md          # add "Running Flink locally" section
```

### docker-compose.flink.yml

```yaml
version: "3.8"
services:
  flink-jobmanager:
    image: flink:1.18-python3.11
    command: jobmanager
    ports:
      - "8081:8081"   # Flink Web UI
    environment:
      FLINK_PROPERTIES: |
        jobmanager.rpc.address: flink-jobmanager

  flink-taskmanager:
    image: flink:1.18-python3.11
    command: taskmanager
    depends_on: [flink-jobmanager]
    environment:
      FLINK_PROPERTIES: |
        jobmanager.rpc.address: flink-jobmanager
        taskmanager.numberOfTaskSlots: 2

  flink-job-runner:
    build:
      context: src/processing/flink_jobs
      dockerfile: Dockerfile
    depends_on: [flink-jobmanager, kafka-1]
    environment:
      KAFKA_BOOTSTRAP: kafka-1:9092
      FLINK_JOBMANAGER: flink-jobmanager:8081
    command: >
      python submit_job.py
        --kafka-bootstrap kafka-1:9092
        --input-topic events.raw
        --output-topic events.validated
        --deadletter-topic events.deadletter
```

### src/processing/flink_jobs/Dockerfile

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y openjdk-11-jre-headless && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
RUN pip install apache-flink==1.18.* confluent-kafka pydantic structlog
WORKDIR /app
COPY . .
```

### scripts/run_flink_local.sh

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "Starting AgentFlow Flink job locally via Docker..."
docker compose -f docker-compose.yml -f docker-compose.flink.yml up -d
echo "Flink Web UI: http://localhost:8081"
echo "Job running. Press Ctrl+C to stop."
docker compose -f docker-compose.yml -f docker-compose.flink.yml logs -f flink-job-runner
```

### Acceptance criteria

- [ ] `make flink-local` starts Flink + runs stream_processor.py inside Docker
- [ ] Flink Web UI accessible at http://localhost:8081 showing the running job
- [ ] Events produced to `events.raw` → validated events appear in `events.validated`
- [ ] Dead-letter events (invalid) appear in `events.deadletter`
- [ ] `docs/runbook.md` has "Running Flink locally with Docker" section with `make flink-local`
- [ ] Works on any host Python version (job runs in Python 3.11 container)

---

## TASK 9 — Query Explain Endpoint

**Priority**: P2 — debugging tool: agents see SQL before executing  
**Time estimate**: 1h  

### What to build

`POST /v1/query/explain` — returns the SQL that would be executed without running it.

### Files to create/modify

```
src/serving/api/routers/
  agent_query.py         # add /query/explain endpoint
src/serving/semantic_layer/
  query_engine.py        # add explain() method
tests/integration/
  test_query_explain.py  # NEW
```

### API spec

```python
class ExplainRequest(BaseModel):
    question: str

class ExplainResponse(BaseModel):
    question: str
    sql: str
    tables_accessed: list[str]
    estimated_rows: int | None    # EXPLAIN QUERY PLAN row estimate if available
    engine: Literal["llm", "rule_based"]
    warning: str | None           # e.g. "Full table scan on orders_v2 (no index)"
```

Request:
```
POST /v1/query/explain
{"question": "top 5 products by revenue today"}
```

Response:
```json
{
  "question": "top 5 products by revenue today",
  "sql": "SELECT product_id, SUM(total_amount) as revenue FROM orders_v2 WHERE DATE(created_at) = DATE('now') GROUP BY product_id ORDER BY revenue DESC LIMIT 5",
  "tables_accessed": ["orders_v2"],
  "estimated_rows": 8,
  "engine": "llm",
  "warning": null
}
```

Use DuckDB's `EXPLAIN` to get row estimates:
```python
explain_result = conn.execute(f"EXPLAIN {sql}").fetchall()
```

### SDK addition

```python
def explain(self, question: str) -> ExplainResponse:
    """Return SQL that would be executed for this NL question (dry run)."""
    ...
```

### Acceptance criteria

- [ ] `POST /v1/query/explain` returns SQL + tables_accessed without executing the query
- [ ] `engine: "llm"` when Claude translated, `engine: "rule_based"` when fallback used
- [ ] `estimated_rows` populated from EXPLAIN output
- [ ] Auth required
- [ ] `client.explain("top products today")` works in SDK
- [ ] `tests/integration/test_query_explain.py` — 5+ tests

---

## TASK 10 — Agent Session Analytics

**Priority**: P2 — platform visibility: who queries what, patterns, abuse detection  
**Time estimate**: 1.5h  

### What to build

Track API usage per tenant/key and expose analytics endpoint.

### Files to create/modify

```
src/serving/api/
  analytics.py           # NEW: session tracking middleware
  main.py                # register analytics middleware
src/serving/api/routers/
  admin.py               # add /v1/admin/analytics endpoints
tests/integration/
  test_analytics.py      # NEW
```

### DuckDB schema

```sql
CREATE TABLE IF NOT EXISTS api_sessions (
    request_id TEXT PRIMARY KEY,
    tenant TEXT,
    key_name TEXT,
    endpoint TEXT,
    method TEXT,
    status_code INTEGER,
    duration_ms FLOAT,
    cache_hit BOOLEAN,
    entity_type TEXT,       -- for entity requests
    metric_name TEXT,       -- for metric requests
    query_engine TEXT,      -- "llm" / "rule_based" / null
    ts TIMESTAMP DEFAULT NOW()
);
```

### Analytics endpoints (under `/v1/admin/analytics`)

```
GET /v1/admin/analytics/usage
    ?window=24h                    — usage summary for all tenants
    ?tenant=acme-corp              — filter by tenant

GET /v1/admin/analytics/top-queries?limit=10
    → top NL queries by frequency

GET /v1/admin/analytics/top-entities?limit=10
    → most-accessed entity IDs

GET /v1/admin/analytics/latency
    → p50/p95/p99 per endpoint over last 24h

GET /v1/admin/analytics/anomalies
    → tenants with unusual spike (>3× their hourly average)
```

Example response for `/usage`:
```json
{
  "window": "24h",
  "tenants": [
    {
      "tenant": "acme-corp",
      "total_requests": 4821,
      "error_rate": 0.002,
      "cache_hit_rate": 0.71,
      "top_endpoints": ["/v1/entity/order", "/v1/metrics/revenue"],
      "avg_duration_ms": 23.4
    }
  ]
}
```

### Acceptance criteria

- [ ] Every API request logged to `api_sessions` (async, non-blocking)
- [ ] `GET /v1/admin/analytics/usage` returns per-tenant stats
- [ ] `GET /v1/admin/analytics/latency` returns p50/p95/p99 per endpoint
- [ ] `GET /v1/admin/analytics/anomalies` flags >3× spike
- [ ] Admin key required (not regular API key)
- [ ] Logging adds < 2ms to request latency (async insert)
- [ ] `tests/integration/test_analytics.py` — 5+ tests

---

## Execution Order

```
TASK 1  (CLI)              ← independent, high-impact DX
TASK 2  (CrewAI)           ← independent, extends integrations/
TASK 3  (OpenTelemetry)    ← independent, instrumentation
TASK 4  (Batch endpoint)   ← independent, new router
TASK 5  (CORS)             ← independent, 30-min task — do first
TASK 6  (Dead-letter)      ← independent, new router
TASK 7  (PII masking)      ← independent, middleware layer
TASK 8  (Flink Docker)     ← independent, Docker/infra
TASK 9  (Query explain)    ← independent, extends query engine
TASK 10 (Session analytics)← depends on auth.py tenant tracking (Task 4 of v2, already done)
```

**Parallelizable**: All tasks are independent.  
**Fastest first**: Task 5 (CORS, 30 min) → unblocks browser-based agents immediately.

---

## Definition of Done for v3

1. `agentflow health` → colored table from terminal
2. `from agentflow_integrations.crewai import get_agentflow_tools` works
3. Every API request has an OpenTelemetry trace visible in Jaeger UI
4. `POST /v1/batch` with 10 items executes concurrently in < 50ms
5. `GET /v1/entity/user/USR-1` → email is `j***@example.com`
6. `GET /v1/deadletter/stats` → breakdown of failed events by reason
7. `POST /v1/deadletter/{id}/replay` → re-validates and resubmits
8. `make flink-local` → Flink Web UI at localhost:8081 with running job
9. `POST /v1/query/explain` → returns SQL without executing
10. `GET /v1/admin/analytics/usage` → per-tenant request stats
11. `pytest tests/` → 130+ passed
