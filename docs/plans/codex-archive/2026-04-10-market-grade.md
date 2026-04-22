# AgentFlow — Market-Grade Upgrade Plan
**Date**: 2026-04-10  
**Goal**: Raise AgentFlow from showcase-grade (~8.5/10) to strong market product level  
**Executor**: Codex  
**Searched for**: agent data platform SDKs, streaming API patterns, multi-tenant FastAPI, OpenAPI tool definitions  
**Decision**: Build from scratch — no existing lib covers agent-data-platform-specific concerns

---

## Context for Codex

AgentFlow is a real-time data platform for AI agents: Kafka → Flink → Iceberg → Semantic Layer → FastAPI.

Current state (post two audits, verified by exploration):
- Auth middleware, rate limiting: **working** (`src/serving/api/main.py`)
- Quality validators in stream processor: **working** (`src/processing/flink_jobs/stream_processor.py`)
- Integration tests with `@pytest.mark.integration`: **working** (`tests/integration/test_pipeline.py`)
- Semantic catalog with real backing tables: **working** (`src/serving/semantic_layer/`)
- Batch assets in Dagster: **working with DuckDB**, Iceberg no-op in local mode (by design)
- CI pipeline: **working** (`.github/workflows/ci.yml`)

Missing for market-grade product (ordered by impact):

---

## TASK 1 — Agent Python SDK (`agentflow-client`)

**Priority**: P0 — without a client library, agents must implement HTTP boilerplate  
**Time estimate**: 2-3h  

### What to build

Create `sdk/` directory with a pip-installable Python client for AgentFlow API.

### Files to create

```
sdk/
  agentflow/
    __init__.py          # exports: AgentFlowClient
    client.py            # main client class
    models.py            # Pydantic response models
    exceptions.py        # AgentFlowError, AuthError, RateLimitError, DataFreshnesError
  pyproject.toml         # package metadata
  README.md              # quickstart (5 lines → first result)
tests/
  unit/
    test_sdk_client.py   # mock-based unit tests for SDK
```

### Implementation spec

```python
# sdk/agentflow/client.py
class AgentFlowClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0):
        ...

    # Entity lookups
    def get_order(self, order_id: str) -> OrderEntity: ...
    def get_user(self, user_id: str) -> UserEntity: ...
    def get_product(self, product_id: str) -> ProductEntity: ...
    def get_session(self, session_id: str) -> SessionEntity: ...

    # Metrics
    def get_metric(self, name: str, window: str = "1h") -> MetricResult: ...

    # Natural language query
    def query(self, question: str) -> QueryResult: ...

    # Health + trust
    def health(self) -> HealthStatus: ...
    def is_fresh(self, max_age_seconds: int = 60) -> bool:
        """Convenience: returns True only if data freshness < max_age_seconds"""
        ...

    # Catalog discovery
    def catalog(self) -> CatalogResponse: ...
```

### Pydantic models (sdk/agentflow/models.py)

Define typed response models matching the API responses. Use `model_validator` to compute derived fields (e.g., `is_overdue: bool` on OrderEntity based on status + created_at).

### Exceptions (sdk/agentflow/exceptions.py)

```python
class AgentFlowError(Exception): ...
class AuthError(AgentFlowError): ...
class RateLimitError(AgentFlowError):
    retry_after: int  # seconds
class DataFreshnessError(AgentFlowError): ...
class EntityNotFoundError(AgentFlowError):
    entity_type: str
    entity_id: str
```

### Acceptance criteria

- [ ] `pip install -e sdk/` works
- [ ] `AgentFlowClient("http://localhost:8000", api_key="dev-key").get_order("ORD-1")` returns typed object
- [ ] `client.is_fresh(60)` raises `DataFreshnessError` when pipeline is unhealthy
- [ ] All 4 entity types, 6 metrics, NL query, health covered
- [ ] `tests/unit/test_sdk_client.py` — min 10 tests, all with mocked HTTP (no real server needed)
- [ ] `sdk/README.md` — 5-line quickstart that actually works

---

## TASK 2 — OpenAPI Tool Definition for Claude/GPT

**Priority**: P0 — this is the main integration artifact for AI agent consumers  
**Time estimate**: 1h  

### What to build

Export the FastAPI OpenAPI schema and create a tool definition file that Claude/GPT agents can load directly.

### Files to create

```
docs/
  openapi.json           # auto-generated from FastAPI (script below)
  agent-tools/
    claude-tools.json    # Claude tool_use format
    openai-tools.json    # OpenAI functions format
scripts/
  export_openapi.py      # generates all three files
```

### Implementation spec

**scripts/export_openapi.py**:
```python
"""Export OpenAPI schema and agent tool definitions."""
import json
import sys
sys.path.insert(0, ".")

from src.serving.api.main import app

# 1. Export raw OpenAPI JSON
schema = app.openapi()
with open("docs/openapi.json", "w") as f:
    json.dump(schema, f, indent=2)

# 2. Convert to Claude tool_use format
claude_tools = []
for path, methods in schema["paths"].items():
    for method, op in methods.items():
        if method in ("get", "post"):
            claude_tools.append({
                "name": op["operationId"],
                "description": op.get("summary", "") + "\n" + op.get("description", ""),
                "input_schema": build_claude_schema(op, schema)
            })

with open("docs/agent-tools/claude-tools.json", "w") as f:
    json.dump(claude_tools, f, indent=2)

# 3. Convert to OpenAI functions format (similar structure)
...
```

The `build_claude_schema()` function should flatten path + query parameters + request body into a single `input_schema` object.

### Acceptance criteria

- [ ] `python scripts/export_openapi.py` runs without errors
- [ ] `docs/openapi.json` is valid OpenAPI 3.x
- [ ] `docs/agent-tools/claude-tools.json` — array of tools Claude can load directly
- [ ] `docs/agent-tools/openai-tools.json` — OpenAI functions format
- [ ] Add `make tools` target to Makefile.py that runs the export script

---

## TASK 3 — SSE Streaming Endpoint for Real-Time Events

**Priority**: P1 — agents need push-based data access, not just polling  
**Time estimate**: 2h  

### What to build

Add a Server-Sent Events endpoint that streams validated events in real-time.

### Files to create/modify

```
src/serving/api/routers/
  stream.py              # NEW: SSE router
src/serving/api/
  main.py                # add stream router (import + app.include_router)
tests/integration/
  test_streaming.py      # NEW: SSE integration tests
```

### Implementation spec

```python
# src/serving/api/routers/stream.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
import asyncio, json

router = APIRouter(prefix="/v1/stream", tags=["stream"])

@router.get("/events", summary="Stream real-time validated events via SSE")
async def stream_events(
    event_type: str | None = None,   # filter: order, payment, clickstream, inventory
    entity_id: str | None = None,    # filter: specific order/user/product ID
    request: Request = ...,
    _auth: None = Depends(require_api_key),
):
    """
    Server-Sent Events stream of validated pipeline events.
    Agents subscribe here to react to events in real-time.
    
    Returns SSE stream with data: {event JSON}\n\n
    Client disconnects by closing the connection.
    """
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            events = await fetch_recent_events(event_type, entity_id, limit=10)
            for evt in events:
                yield f"data: {json.dumps(evt)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

The `fetch_recent_events()` reads from DuckDB `pipeline_events` table ordered by `created_at DESC`.

### Acceptance criteria

- [ ] `GET /v1/stream/events` returns `Content-Type: text/event-stream`
- [ ] `?event_type=order` filters to order events only
- [ ] Auth required (same `X-API-Key` header)
- [ ] Client disconnect stops the generator (no resource leak)
- [ ] `tests/integration/test_streaming.py` — tests SSE response format and filtering
- [ ] Documented in `/v1/catalog` as a streaming data source

---

## TASK 4 — Multi-Tenant API Key Management

**Priority**: P1 — market products have per-agent access control  
**Time estimate**: 1.5h  

### What to build

Replace single-pool API keys with named, per-tenant keys with metadata and rate limit overrides.

### Files to create/modify

```
src/serving/api/
  auth.py                # NEW: tenant management logic (extracted from main.py)
  main.py                # use new auth module
src/serving/api/routers/
  admin.py               # NEW: admin endpoints for key management
tests/unit/
  test_auth.py           # NEW: auth unit tests
```

### Implementation spec

**Tenant key format** (stored in env / YAML file):
```yaml
# config/api_keys.yaml
keys:
  - key: "af-prod-agent-support-abc123"
    name: "Support Agent"
    tenant: "acme-corp"
    rate_limit_rpm: 60
    allowed_entity_types: ["order", "user"]
    created_at: "2026-04-10"
  - key: "af-prod-agent-ops-def456"
    name: "Ops Agent"
    tenant: "acme-corp"
    rate_limit_rpm: 300
    allowed_entity_types: null  # all
    created_at: "2026-04-10"
```

**Admin endpoints** (`/v1/admin/` — protected by separate `AGENTFLOW_ADMIN_KEY`):
```
POST /v1/admin/keys          — create new API key
GET  /v1/admin/keys          — list all keys with usage stats
DELETE /v1/admin/keys/{key}  — revoke key
GET  /v1/admin/usage         — per-tenant usage in last 24h
```

Usage stats tracked in DuckDB table `api_usage`:
```sql
CREATE TABLE IF NOT EXISTS api_usage (
    tenant TEXT,
    key_name TEXT,
    endpoint TEXT,
    ts TIMESTAMP DEFAULT NOW()
);
```

### Acceptance criteria

- [ ] `config/api_keys.yaml` loaded at startup, hot-reloaded on `SIGHUP`
- [ ] Each request logs `(tenant, key_name, endpoint)` to `api_usage`
- [ ] Rate limits are per-key, not global
- [ ] `allowed_entity_types: ["order"]` → `GET /v1/entity/user/X` returns 403
- [ ] Admin endpoints work with separate admin key
- [ ] `tests/unit/test_auth.py` — min 8 tests covering all auth scenarios
- [ ] `.env.example` updated with `AGENTFLOW_ADMIN_KEY`

---

## TASK 5 — DevContainer + One-Command Setup

**Priority**: P1 — every market product has zero-friction onboarding  
**Time estimate**: 1h  

### What to build

`.devcontainer/` for VS Code / GitHub Codespaces, and a `setup.sh` that works on Linux/macOS/Windows.

### Files to create

```
.devcontainer/
  devcontainer.json
  Dockerfile
scripts/
  setup.sh               # Linux/macOS
  setup.ps1              # Windows PowerShell
```

### Implementation spec

**devcontainer.json**:
```json
{
  "name": "AgentFlow Dev",
  "dockerFile": "Dockerfile",
  "features": {
    "ghcr.io/devcontainers/features/python:1": {"version": "3.11"},
    "ghcr.io/devcontainers/features/docker-in-docker:2": {}
  },
  "postCreateCommand": "pip install -e '.[dev]' && pip install -e sdk/",
  "forwardPorts": [8000, 8088, 9090, 3000],
  "customizations": {
    "vscode": {
      "extensions": ["ms-python.python", "ms-python.mypy-type-checker", "charliermarsh.ruff"]
    }
  }
}
```

**scripts/setup.sh**:
```bash
#!/usr/bin/env bash
set -euo pipefail
echo "=== AgentFlow Setup ==="

# 1. Check Python >= 3.11
python3 --version | grep -E "3\.(11|12|13)" || (echo "Need Python 3.11+" && exit 1)

# 2. Create venv
python3 -m venv .venv
source .venv/bin/activate

# 3. Install deps
pip install -e ".[dev]"
pip install -e sdk/

# 4. Copy env
cp -n .env.example .env || true

# 5. Run smoke test
python -c "from src.serving.api.main import app; print('OK')"

echo "=== Setup complete. Run: make demo ==="
```

### Acceptance criteria

- [ ] `.devcontainer/devcontainer.json` — opens in Codespaces without errors
- [ ] `scripts/setup.sh` runs end-to-end on clean Ubuntu
- [ ] `scripts/setup.ps1` runs on Windows PowerShell 7+
- [ ] After setup: `make demo` works without any manual steps
- [ ] `README.md` — add "Quick Start (30 seconds)" section using `setup.sh`

---

## TASK 6 — Benchmark Report

**Priority**: P1 — market products publish real numbers, not projections  
**Time estimate**: 1h  

### What to build

Run the existing Locust load test, capture real results, generate `docs/benchmark.md`.

### Files to create/modify

```
scripts/
  run_benchmark.py       # orchestrates: start API → seed data → run Locust → capture → report
docs/
  benchmark.md           # real measured numbers (generated by script)
```

### Implementation spec

**scripts/run_benchmark.py**:
1. Start API in subprocess: `uvicorn src.serving.api.main:app --port 8001`
2. Seed demo data: call `make demo` or equivalent
3. Run Locust headless: `locust -f tests/load/locustfile.py --headless -u 50 -r 10 --run-time 60s --host http://localhost:8001 --csv /tmp/agentflow_benchmark`
4. Parse CSV results
5. Generate `docs/benchmark.md` with:
   - System under test (CPU, RAM, Python version)
   - Test parameters (users, duration, host)
   - Results table: RPS, p50, p95, p99, failure rate per endpoint
   - Comparison to claims in README (`<12ms entity`, `<85ms metric`)

### Acceptance criteria

- [ ] `python scripts/run_benchmark.py` runs end-to-end automatically
- [ ] `docs/benchmark.md` contains real measured numbers (not "projected")
- [ ] Numbers align with or explain deviation from README claims
- [ ] Benchmark script is idempotent (reruns overwrite previous results)
- [ ] `make benchmark` target added to Makefile.py

---

## TASK 7 — Agent Demo Notebook

**Priority**: P2 — shows "aha moment" in 5 min for evaluators  
**Time estimate**: 1.5h  

### What to build

A Jupyter notebook demonstrating a complete agent workflow using the AgentFlow SDK.

### Files to create

```
notebooks/
  01-agent-demo.ipynb    # end-to-end agent workflow
  02-nl-query.ipynb      # NL→SQL exploration
```

### Implementation spec for `01-agent-demo.ipynb`

Cells:
1. **Setup** — `pip install -e sdk/`, create client
2. **Health check** — `client.health()`, show freshness
3. **Event-driven agent** — simulate: customer asks "where is my order ORD-1?" → `client.get_order()` → compose answer
4. **Metric query** — "what's today's revenue?" → `client.get_metric("revenue")` → show value
5. **NL query** — `client.query("top 5 products by revenue this week")` → display table
6. **Streaming** — subscribe to SSE, print 5 events (uses `sseclient-py`)
7. **Tenant comparison** — show same query with two different API keys → different rate limits

Each cell has markdown explaining WHY an agent would do this step.

### Acceptance criteria

- [ ] Notebook runs top-to-bottom with `make demo` running in background
- [ ] No hard-coded assumptions (reads `AGENTFLOW_API_KEY` from env)
- [ ] Uses `agentflow-client` SDK (not raw httpx)
- [ ] Cell outputs are pre-executed and committed (shows results without running)
- [ ] `README.md` links to notebook: "Try the interactive demo →"

---

## TASK 8 — Data Lineage Endpoint

**Priority**: P2 — differentiator: agents can audit where data came from  
**Time estimate**: 1h  

### What to build

`GET /v1/lineage/{entity_type}/{entity_id}` — returns the provenance chain for any entity.

### Files to create/modify

```
src/serving/api/routers/
  lineage.py             # NEW: lineage router
src/serving/api/
  main.py                # add lineage router
tests/integration/
  test_lineage.py        # NEW
```

### Implementation spec

```python
# Response model
class LineageNode(BaseModel):
    layer: str          # "source", "ingestion", "validation", "enrichment", "serving"
    system: str         # "postgres_cdc", "kafka", "flink", "duckdb", "fastapi"
    table_or_topic: str
    processed_at: datetime | None
    quality_score: float | None

class LineageResponse(BaseModel):
    entity_type: str
    entity_id: str
    lineage: list[LineageNode]  # ordered source → serving
    freshness_seconds: float
    validated: bool
    enriched: bool
```

For local/DuckDB mode: lineage is reconstructed from `pipeline_events` table where `entity_id` matches. For each event found, trace through the known pipeline layers.

### Acceptance criteria

- [ ] `GET /v1/lineage/order/ORD-1` returns lineage chain
- [ ] Response includes at least 3 layers (ingestion → processing → serving)
- [ ] Documented in `/v1/catalog`
- [ ] Auth required
- [ ] `tests/integration/test_lineage.py` — min 4 tests

---

## TASK 9 — Product Docs: ICP + User Journeys

**Priority**: P2 — market products have clear who/what/why  
**Time estimate**: 1h  

### What to build

Enhance `docs/product.md` with concrete, specific content that a VC or engineering lead would read and immediately understand.

### Spec for docs/product.md additions

**Section: Ideal Customer Profile (ICP)**
```markdown
## Who AgentFlow is for

**Primary ICP**: Engineering teams (5-50 people) building AI agents that need 
to answer questions about business operations (orders, inventory, users, 
revenue) with sub-minute data freshness.

**Trigger**: "Our support agent is answering questions about order status 
with 6-hour-old data because we're still on batch ETL."

**Decision maker**: Head of Data Engineering or VP Engineering.
**Economic buyer**: Same, or CTO at early-stage.
**Champion**: Staff/Senior Data Engineer who owns the platform.

**Anti-ICP**: Teams that only need BI dashboards (no AI agents). 
Teams with <1K events/day (batch ETL is fine). Pure ML inference platforms.
```

**Section: Three Core User Journeys**

Journey 1: "Support agent answers order status" (time to first answer: 15 min)  
Journey 2: "Ops agent monitors pipeline health" (time to alert: 30 sec)  
Journey 3: "Merch agent queries revenue metrics" (time to insight: <1 min)

Each journey: Before state → After state → Step-by-step with code.

**Section: Success Metrics**

| Metric | Target |
|--------|--------|
| Time to first agent response using live data | < 15 min from `make demo` |
| Data freshness | < 30 sec end-to-end |
| API p95 latency | < 100ms (entity), < 200ms (metric) |
| Data quality gate rejection rate | > 0% in any realistic demo |
| Developer onboarding time | < 5 min to first SDK call |

**Section: MVP Scope vs Roadmap**

Clearly table what IS in v1 vs what's roadmap (multi-tenancy RBAC, Iceberg sink, agent SDK v2, etc.)

### Acceptance criteria

- [ ] ICP section: specific, not generic
- [ ] 3 user journeys with code examples using the SDK
- [ ] Success metrics table with measurable targets
- [ ] MVP scope table: honest about what's local-demo vs production-grade
- [ ] `docs/product.md` ≤ 600 lines total (ruthlessly cut existing fluff)

---

## TASK 10 — Integration Test: Failure Scenarios

**Priority**: P2 — market products prove resilience, not just happy path  
**Time estimate**: 1h  

### What to build

Add failure-scenario integration tests that currently don't exist.

### Files to create/modify

```
tests/integration/
  test_failure_scenarios.py   # NEW
  test_pipeline.py            # add @pytest.mark.integration to any unmarked tests
```

### Failure scenarios to cover

```python
@pytest.mark.integration
class TestAuthFailures:
    def test_missing_api_key_returns_401(self): ...
    def test_invalid_api_key_returns_401(self): ...
    def test_rate_limit_triggers_429(self): ...  # send 200 req/min with limit=120

@pytest.mark.integration
class TestEntityNotFound:
    def test_unknown_order_id_returns_404(self): ...
    def test_unknown_user_id_returns_404_not_500(self): ...
    def test_404_body_has_entity_type_and_id(self): ...  # not just generic 404

@pytest.mark.integration
class TestInvalidQueries:
    def test_nl_query_with_injection_attempt_is_safe(self): ...  # SQL injection via NL
    def test_metric_unknown_name_returns_404(self): ...
    def test_metric_invalid_window_returns_422(self): ...

@pytest.mark.integration
class TestDataQuality:
    def test_invalid_event_goes_to_deadletter(self): ...
    def test_health_shows_degraded_when_no_recent_events(self): ...
```

### Acceptance criteria

- [ ] Min 15 failure-scenario tests, all `@pytest.mark.integration`
- [ ] `pytest tests/integration/test_failure_scenarios.py` → all pass
- [ ] SQL injection test confirms no raw SQL leakage in response
- [ ] Rate limit test is deterministic (not flaky)
- [ ] All tests run in < 30 seconds total

---

## Execution Order

```
TASK 1  (SDK)            ← foundation for Tasks 7
TASK 2  (OpenAPI tools)  ← independent
TASK 3  (SSE stream)     ← independent  
TASK 4  (Multi-tenant)   ← builds on existing auth in main.py
TASK 5  (DevContainer)   ← independent, do last (needs full feature set)
TASK 6  (Benchmark)      ← independent, run after Tasks 1-4 done
TASK 7  (Notebook)       ← depends on TASK 1 (SDK)
TASK 8  (Lineage)        ← independent
TASK 9  (Product docs)   ← independent
TASK 10 (Failure tests)  ← independent
```

**Parallelizable**: Tasks 2, 3, 4, 8, 9, 10 can run in parallel.  
**Sequential**: Task 7 waits for Task 1.  
**Final**: Task 5 and Task 6 after everything else.

---

## Definition of Done

The project is market-grade when:

1. `pip install -e sdk/` → `client.get_order("ORD-1")` works in < 5 min from clone
2. `docs/benchmark.md` shows real numbers matching README claims (±20%)
3. `docs/agent-tools/claude-tools.json` loads directly into a Claude agent without modification
4. `pytest tests/` → 70+ tests, 0 failures
5. `GET /v1/lineage/order/ORD-1` returns a 3-layer provenance chain
6. `GET /v1/stream/events` streams live SSE events
7. Two tenants with different rate limits behave independently
8. `notebooks/01-agent-demo.ipynb` runs top-to-bottom, no errors
