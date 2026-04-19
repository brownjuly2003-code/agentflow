# AgentFlow — Market-Grade v2: Ecosystem & Production
**Date**: 2026-04-10  
**Phase**: After v1 (SDK, SSE, multi-tenant auth, benchmark, notebook, lineage)  
**Goal**: Ecosystem integrations + production deployment story + advanced agent capabilities  
**Executor**: Codex

## Context for Codex

v1 is complete. Current state:
- SDK (`sdk/agentflow/`) — Python client with typed models
- Streaming (`/v1/stream/events`) — SSE
- Multi-tenant auth (`src/serving/api/auth.py`) — per-key rate limits, YAML config
- Lineage (`/v1/lineage/`) — 3-layer provenance chain
- Routers: agent_query, stream, admin, lineage
- Tests: 9 files (unit + integration + load)
- CI: 4 jobs (lint, unit, integration, terraform-validate)
- No LangChain/LlamaIndex/CrewAI integrations yet
- Docker Compose: single-broker Kafka (KRAFT), no Flink, no Redis

What's missing for true production-grade + ecosystem reach — ordered by impact:

---

## TASK 1 — LangChain + LlamaIndex Integrations

**Priority**: P0 — without ecosystem integrations, agents must write boilerplate  
**Time estimate**: 2-3h  

### What to build

Two framework integrations that let developers plug AgentFlow into their existing agent stacks in 3 lines of code.

### Files to create

```
integrations/
  langchain/
    __init__.py
    tool.py              # AgentFlowTool (BaseTool subclass)
    toolkit.py           # AgentFlowToolkit — bundles all tools
  llamaindex/
    __init__.py
    reader.py            # AgentFlowReader (BaseReader subclass)
    tool_spec.py         # AgentFlowToolSpec (BaseToolSpec subclass)
  pyproject.toml         # separate installable package: agentflow-integrations
tests/unit/
  test_langchain_tool.py
  test_llamaindex_reader.py
docs/
  integrations.md        # quickstart for each framework
```

### LangChain spec (`integrations/langchain/tool.py`)

```python
from langchain.tools import BaseTool
from agentflow import AgentFlowClient

class OrderLookupTool(BaseTool):
    name = "agentflow_order_lookup"
    description = "Look up real-time order status, items, and payment info by order ID."
    client: AgentFlowClient

    def _run(self, order_id: str) -> str:
        order = self.client.get_order(order_id)
        return order.model_dump_json(indent=2)

class MetricQueryTool(BaseTool):
    name = "agentflow_metric"
    description = "Query business metrics: revenue, order_count, avg_order_value, conversion_rate, active_sessions, error_rate. Specify metric name and optional time window (1h, 24h, 7d)."
    client: AgentFlowClient

    def _run(self, metric: str, window: str = "1h") -> str:
        result = self.client.get_metric(metric, window)
        return f"{metric} ({window}): {result.value} {result.unit}"

class NLQueryTool(BaseTool):
    name = "agentflow_query"
    description = "Ask a natural language question about business data. Returns SQL result as JSON."
    client: AgentFlowClient

    def _run(self, question: str) -> str:
        result = self.client.query(question)
        return result.model_dump_json()

class AgentFlowToolkit:
    """Bundle of all AgentFlow tools for LangChain agents."""
    def __init__(self, base_url: str, api_key: str):
        self.client = AgentFlowClient(base_url, api_key)

    def get_tools(self) -> list[BaseTool]:
        return [
            OrderLookupTool(client=self.client),
            MetricQueryTool(client=self.client),
            NLQueryTool(client=self.client),
        ]
```

Usage (goes in integrations.md):
```python
from agentflow_integrations.langchain import AgentFlowToolkit
from langchain.agents import initialize_agent

toolkit = AgentFlowToolkit("http://localhost:8000", api_key="af-dev-key")
agent = initialize_agent(toolkit.get_tools(), llm, agent="zero-shot-react-description")
agent.run("What's the revenue for today?")
```

### LlamaIndex spec (`integrations/llamaindex/reader.py`)

```python
from llama_index.core.readers.base import BaseReader
from llama_index.core import Document

class AgentFlowReader(BaseReader):
    """Load AgentFlow entities and metrics as LlamaIndex Documents."""
    def __init__(self, base_url: str, api_key: str): ...

    def load_data(
        self,
        entity_type: str | None = None,   # "order", "user", "product", "session"
        metric_names: list[str] | None = None,
        window: str = "24h",
    ) -> list[Document]:
        """
        Returns Documents with:
        - text: human-readable summary
        - metadata: {entity_type, entity_id, freshness_seconds, quality_score}
        """
```

### Acceptance criteria

- [ ] `pip install -e integrations/` works
- [ ] LangChain: `AgentFlowToolkit(url, key).get_tools()` returns 3 tools
- [ ] LangChain tool `_run()` calls real SDK (mocked in tests)
- [ ] LlamaIndex: `AgentFlowReader(url, key).load_data(entity_type="order")` returns list of Documents
- [ ] `tests/unit/test_langchain_tool.py` — 6+ tests with mocked client
- [ ] `tests/unit/test_llamaindex_reader.py` — 4+ tests
- [ ] `docs/integrations.md` — LangChain quickstart + LlamaIndex quickstart, each under 20 lines of code

---

## TASK 2 — Webhook Subscriptions (Push-Based Agent Notifications)

**Priority**: P0 — SSE requires persistent connection; webhooks let agents react without polling  
**Time estimate**: 2h  

### What to build

Agents register a webhook URL + filter, AgentFlow calls it when matching events arrive.

### Files to create/modify

```
src/serving/api/routers/
  webhooks.py            # NEW: CRUD + delivery
src/serving/api/
  webhook_dispatcher.py  # NEW: background delivery task
  main.py                # register webhook router + start dispatcher on startup
config/
  webhooks.yaml          # persisted webhook registrations
tests/integration/
  test_webhooks.py       # NEW
```

### Data model

```python
class WebhookRegistration(BaseModel):
    id: str                          # auto-generated UUID
    url: str                         # agent's endpoint
    secret: str                      # HMAC-SHA256 signing secret
    tenant: str                      # from API key
    filters: WebhookFilters
    created_at: datetime
    active: bool = True

class WebhookFilters(BaseModel):
    event_types: list[str] | None = None   # ["order", "payment"]
    entity_ids: list[str] | None = None    # ["ORD-1", "USR-42"]
    min_amount: float | None = None        # only if order.total_amount >= X
```

### API endpoints (`/v1/webhooks`)

```
POST   /v1/webhooks              — register webhook
GET    /v1/webhooks              — list my webhooks (filtered by tenant)
DELETE /v1/webhooks/{id}         — unregister
POST   /v1/webhooks/{id}/test    — send a test payload to verify endpoint
GET    /v1/webhooks/{id}/logs    — last 20 delivery attempts with status
```

### Delivery spec (`webhook_dispatcher.py`)

- Background `asyncio.Task` polls `pipeline_events` for new events every 2 seconds
- For each new event, matches against registered webhooks
- Delivers via `httpx.AsyncClient.post()` with:
  - `X-AgentFlow-Event: {event_type}`
  - `X-AgentFlow-Signature: sha256={HMAC}`
  - `X-AgentFlow-Delivery: {uuid}`
  - Body: full event JSON
- Retry: 3 attempts with exponential backoff (1s, 5s, 25s)
- Logs delivery result to DuckDB `webhook_deliveries` table

### Acceptance criteria

- [ ] `POST /v1/webhooks` registers and returns `id` + `secret`
- [ ] HMAC signature on every delivery (`X-AgentFlow-Signature` header)
- [ ] 3-attempt retry with backoff on 5xx / timeout
- [ ] `POST /v1/webhooks/{id}/test` delivers test payload immediately
- [ ] `GET /v1/webhooks/{id}/logs` shows delivery history
- [ ] `tests/integration/test_webhooks.py` — uses `httpx_mock` to capture delivery, 8+ tests
- [ ] Webhook registrations survive API restart (persisted to `config/webhooks.yaml`)

---

## TASK 3 — Async SDK Client

**Priority**: P1 — modern agents are async; sync client blocks event loops  
**Time estimate**: 1.5h  

### What to build

Add `AsyncAgentFlowClient` to the SDK with identical interface to sync client.

### Files to create/modify

```
sdk/agentflow/
  async_client.py        # NEW: AsyncAgentFlowClient
  __init__.py            # export AsyncAgentFlowClient
tests/unit/
  test_sdk_async_client.py  # NEW: async unit tests with respx or pytest-httpx
```

### Implementation spec

```python
# sdk/agentflow/async_client.py
import httpx
from .models import OrderEntity, MetricResult, QueryResult, HealthStatus
from .exceptions import AgentFlowError, AuthError, RateLimitError, EntityNotFoundError

class AsyncAgentFlowClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0):
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    async def get_order(self, order_id: str) -> OrderEntity: ...
    async def get_user(self, user_id: str) -> UserEntity: ...
    async def get_product(self, product_id: str) -> ProductEntity: ...
    async def get_session(self, session_id: str) -> SessionEntity: ...
    async def get_metric(self, name: str, window: str = "1h") -> MetricResult: ...
    async def query(self, question: str) -> QueryResult: ...
    async def health(self) -> HealthStatus: ...
    async def is_fresh(self, max_age_seconds: int = 60) -> bool: ...

    # Context manager support
    async def __aenter__(self) -> "AsyncAgentFlowClient": ...
    async def __aexit__(self, *args: object) -> None:
        await self._http.aclose()
```

Usage:
```python
async with AsyncAgentFlowClient("http://localhost:8000", "af-key") as client:
    order = await client.get_order("ORD-1")
    metric = await client.get_metric("revenue", "24h")
```

### Acceptance criteria

- [ ] All methods are `async def` and use `httpx.AsyncClient`
- [ ] Context manager (`async with`) closes underlying client
- [ ] Same exception hierarchy as sync client
- [ ] `tests/unit/test_sdk_async_client.py` — 10+ tests with `pytest-anyio` or `asyncio`
- [ ] `sdk/README.md` updated with async usage example
- [ ] `from agentflow import AsyncAgentFlowClient` works

---

## TASK 4 — Testcontainers Integration Tests (Real Kafka)

**Priority**: P1 — ADR-002 promises Testcontainers; CI currently uses in-memory DuckDB only  
**Time estimate**: 2h  

### What to build

At least one integration test that proves the ingestion → validation → serving path works with a real Kafka broker.

### Files to create/modify

```
tests/integration/
  test_kafka_pipeline.py     # NEW: Testcontainers-based end-to-end
  conftest.py                # add kafka_container fixture
pyproject.toml               # add testcontainers[kafka] to dev deps
```

### Implementation spec

```python
# tests/integration/conftest.py (additions)
import pytest
from testcontainers.kafka import KafkaContainer

@pytest.fixture(scope="session")
def kafka_container():
    """Real Kafka broker via Testcontainers."""
    with KafkaContainer("confluentinc/cp-kafka:7.7.0") as kafka:
        yield kafka

@pytest.fixture
def kafka_bootstrap(kafka_container):
    return kafka_container.get_bootstrap_server()
```

```python
# tests/integration/test_kafka_pipeline.py
@pytest.mark.integration
class TestKafkaPipeline:
    def test_valid_order_event_reaches_validated_topic(
        self, kafka_bootstrap, api_client
    ):
        """Produce a valid order event → assert it appears in events.validated topic."""
        producer = KafkaProducer(bootstrap_servers=kafka_bootstrap, ...)
        event = build_valid_order_event()
        producer.send("events.raw", event)
        producer.flush()

        # Poll events.validated for 10 seconds
        consumer = KafkaConsumer("events.validated", bootstrap_servers=kafka_bootstrap, ...)
        received = poll_until(consumer, timeout=10)
        assert any(e["event_id"] == event["event_id"] for e in received)

    def test_invalid_event_goes_to_deadletter(self, kafka_bootstrap):
        """Produce an invalid event → assert it appears in events.deadletter."""
        ...

    def test_api_serves_data_after_kafka_ingestion(self, kafka_bootstrap, api_client):
        """Produce event → wait for processing → API returns data."""
        ...
```

### Acceptance criteria

- [ ] `pytest tests/integration/test_kafka_pipeline.py` passes (requires Docker)
- [ ] Tests marked `@pytest.mark.integration` AND `@pytest.mark.requires_docker`
- [ ] CI job skips `requires_docker` tests when Docker is unavailable (env flag `SKIP_DOCKER_TESTS=1`)
- [ ] `pyproject.toml` — `testcontainers[kafka]` in `dev` extras
- [ ] Min 3 Testcontainers tests covering: valid path, dead-letter, API serving

---

## TASK 5 — Time-Travel Queries (`?as_of=` Parameter)

**Priority**: P1 — unique differentiator; agents can audit historical state  
**Time estimate**: 1.5h  

### What to build

Add `as_of` query parameter to entity and metric endpoints, returning data as it existed at that timestamp.

### Files to create/modify

```
src/serving/api/routers/
  agent_query.py         # add as_of param to entity + metric endpoints
src/serving/semantic_layer/
  query_engine.py        # add time-filtered queries
tests/integration/
  test_time_travel.py    # NEW
```

### Implementation spec

```python
# In agent_query.py
@router.get("/entity/{entity_type}/{entity_id}")
async def get_entity(
    entity_type: str,
    entity_id: str,
    as_of: datetime | None = Query(None, description="Return state as of this UTC timestamp (ISO 8601)"),
    ...
):
    if as_of:
        # Query pipeline_events WHERE entity_id = ? AND created_at <= as_of
        # Reconstruct entity state from event log
        return query_engine.get_entity_at(entity_type, entity_id, as_of)
    return query_engine.get_entity(entity_type, entity_id)

@router.get("/metrics/{metric_name}")
async def get_metric(
    metric_name: str,
    window: str = "1h",
    as_of: datetime | None = Query(None),
    ...
):
    # Shift the window anchor to as_of instead of now()
    ...
```

### Response additions

Add to every entity/metric response:
```json
{
  "data": { ... },
  "meta": {
    "as_of": "2026-04-09T12:00:00Z",   // null if current
    "is_historical": true,
    "freshness_seconds": null           // not applicable for historical
  }
}
```

### Acceptance criteria

- [ ] `GET /v1/entity/order/ORD-1?as_of=2026-04-09T12:00:00Z` returns historical state
- [ ] `GET /v1/metrics/revenue?window=1h&as_of=2026-04-09T12:00:00Z` returns metric for that window ending at as_of
- [ ] `as_of` in the future → 422 with clear error message
- [ ] Response includes `meta.is_historical: true` when as_of is set
- [ ] `tests/integration/test_time_travel.py` — 6+ tests

---

## TASK 6 — Production Docker Compose (Full Stack)

**Priority**: P1 — demo with single broker is not representative of production  
**Time estimate**: 1.5h  

### What to build

A second Docker Compose file for "production-like" local stack: 3 Kafka brokers, Schema Registry, Kafka UI, Redis, Grafana pre-configured.

### Files to create/modify

```
docker-compose.prod.yml  # NEW: full stack
docker-compose.yml       # keep as minimal dev stack (no changes)
monitoring/grafana/
  provisioning/
    datasources/prometheus.yaml   # auto-provision Prometheus datasource
    dashboards/dashboards.yaml    # auto-provision dashboard directory
Makefile.py              # add stack-prod, stack-dev targets
```

### docker-compose.prod.yml spec

Services:
- `kafka-1`, `kafka-2`, `kafka-3` — KRAFT mode, 3 brokers, replication factor 3
- `schema-registry` — Confluent Schema Registry
- `kafka-ui` — Kafka UI on port 8080
- `redis` — Redis 7 for query caching (Task 7)
- `prometheus` — scrapes FastAPI `/metrics`
- `grafana` — pre-configured with AgentFlow dashboard (auto-provisioned)
- `agentflow-api` — built from Dockerfile

### Acceptance criteria

- [ ] `docker compose -f docker-compose.prod.yml up -d` starts all 8 services
- [ ] Kafka UI visible at http://localhost:8080
- [ ] Grafana visible at http://localhost:3000 with AgentFlow dashboard pre-loaded
- [ ] 3-broker Kafka with replication factor 3 (proven by Kafka UI)
- [ ] `make stack-prod` shortcut in Makefile.py
- [ ] `README.md` updated: `make stack-dev` for quick start, `make stack-prod` for full stack

---

## TASK 7 — Redis Query Cache

**Priority**: P2 — metric queries are expensive; agents hammer the same metrics  
**Time estimate**: 1h  

### What to build

Cache metric query results in Redis with configurable TTL. Cache is invalidated when new events arrive.

### Files to create/modify

```
src/serving/
  cache.py               # NEW: RedisCache wrapper
src/serving/api/routers/
  agent_query.py         # wrap metric endpoint with cache
src/serving/api/
  main.py                # init Redis connection on startup
tests/unit/
  test_cache.py          # NEW
```

### Implementation spec

```python
# src/serving/cache.py
import redis.asyncio as redis
import hashlib, json
from datetime import timedelta

class QueryCache:
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis = redis.from_url(redis_url)

    async def get(self, key: str) -> dict | None:
        data = await self._redis.get(key)
        return json.loads(data) if data else None

    async def set(self, key: str, value: dict, ttl: int = 30) -> None:
        await self._redis.setex(key, timedelta(seconds=ttl), json.dumps(value))

    async def invalidate_metrics(self) -> None:
        """Called when new events arrive — clear metric cache."""
        keys = await self._redis.keys("metric:*")
        if keys:
            await self._redis.delete(*keys)

    @staticmethod
    def metric_key(name: str, window: str, as_of: str | None = None) -> str:
        return f"metric:{name}:{window}:{as_of or 'now'}"
```

Fallback: if Redis is unavailable, log warning and serve uncached. Never fail the request due to cache unavailability.

### Acceptance criteria

- [ ] Metric endpoints cache results for 30s by default (configurable via `CACHE_TTL_SECONDS` env)
- [ ] Cache hit is logged at DEBUG level with key
- [ ] Cache miss goes to DuckDB as before
- [ ] New event arrival triggers `invalidate_metrics()` (called from SSE dispatcher)
- [ ] Redis unavailability → warn + serve uncached (no 500)
- [ ] Response header: `X-Cache: HIT` or `X-Cache: MISS`
- [ ] `tests/unit/test_cache.py` — 6+ tests with mocked Redis

---

## TASK 8 — Semantic Entity Search

**Priority**: P2 — agents don't always know IDs; they need discovery by description  
**Time estimate**: 1.5h  

### What to build

`GET /v1/search?q=...` — full-text search across entities and metrics by name/description.

### Files to create/modify

```
src/serving/api/routers/
  search.py              # NEW: search router
src/serving/semantic_layer/
  search_index.py        # NEW: in-memory inverted index
src/serving/api/
  main.py                # register search router
tests/integration/
  test_search.py         # NEW
```

### Implementation spec

```python
# GET /v1/search
class SearchResult(BaseModel):
    type: Literal["entity", "metric", "catalog_field"]
    id: str                   # entity ID or metric name
    entity_type: str | None   # "order", "user", etc.
    score: float              # relevance 0-1
    snippet: str              # human-readable summary
    endpoint: str             # e.g. "/v1/entity/order/ORD-1"

@router.get("/search")
async def search(
    q: str = Query(..., min_length=2, description="Natural language search query"),
    limit: int = Query(10, le=50),
    entity_types: list[str] | None = Query(None),
):
    """
    Search across all indexed entities and metrics.
    Useful when agents don't know the exact ID.
    
    Examples:
      ?q=large orders       → orders with high total_amount
      ?q=revenue metric     → metric definition + current value
      ?q=user julia         → users with name matching 'julia'
    """
```

Index strategy: On startup, index all entity data from DuckDB into an in-memory inverted index (TF-IDF over string fields). Rebuild every 60 seconds via background task.

### Acceptance criteria

- [ ] `GET /v1/search?q=large+orders` returns ranked order entities
- [ ] `GET /v1/search?q=revenue` returns `MetricResult` for revenue metric
- [ ] `?entity_types=order,user` filters results
- [ ] Results include `endpoint` field (directly callable)
- [ ] Auth required
- [ ] `tests/integration/test_search.py` — 8+ tests including empty results, type filtering

---

## TASK 9 — SLO Definitions + Error Budget Endpoint

**Priority**: P2 — operational maturity signal; agents can self-regulate  
**Time estimate**: 1h  

### What to build

Formal SLO definitions + `GET /v1/slo` endpoint reporting current compliance.

### Files to create/modify

```
config/
  slo.yaml               # NEW: SLO definitions
src/serving/api/routers/
  slo.py                 # NEW: SLO endpoint
src/serving/api/
  main.py                # register SLO router
tests/integration/
  test_slo.py            # NEW
```

### config/slo.yaml

```yaml
slos:
  - name: api_latency_p95
    description: "95th percentile API latency < 100ms for entity queries"
    target: 0.99           # 99% of rolling 30-day window
    measurement: p95_latency_ms
    threshold: 100
    window_days: 30

  - name: data_freshness
    description: "Pipeline data freshness < 30 seconds"
    target: 0.999          # 99.9%
    measurement: freshness_seconds
    threshold: 30
    window_days: 7

  - name: error_rate
    description: "API error rate (5xx) < 0.1%"
    target: 0.999
    measurement: error_rate_percent
    threshold: 0.1
    window_days: 30
```

### Response model

```python
class SLOStatus(BaseModel):
    name: str
    target: float           # e.g. 0.99
    current: float          # actual compliance this window
    error_budget_remaining: float   # 1 - burn_rate (0-1)
    status: Literal["healthy", "at_risk", "breached"]
    window_days: int
```

### Acceptance criteria

- [ ] `GET /v1/slo` returns list of SLOStatus objects
- [ ] `status: "at_risk"` when error budget < 20% remaining
- [ ] `status: "breached"` when current compliance < target
- [ ] Auth required
- [ ] `config/slo.yaml` is the single source of truth (no hardcoding in code)
- [ ] `tests/integration/test_slo.py` — 4+ tests

---

## TASK 10 — CI: Coverage Report + Performance Regression Gate

**Priority**: P2 — professional CI catches regressions before merge  
**Time estimate**: 1h  

### What to build

Enhance `.github/workflows/ci.yml` with test coverage reporting and a latency regression gate.

### Files to create/modify

```
.github/workflows/
  ci.yml                 # modify: add coverage + perf jobs
  performance.yml        # NEW: nightly perf regression check
scripts/
  check_performance.py   # NEW: compare benchmark vs baseline, fail if regressed
docs/
  benchmark-baseline.json  # NEW: committed baseline numbers
```

### CI additions (ci.yml)

```yaml
# Add to test-unit job:
- name: Run tests with coverage
  run: |
    .venv/Scripts/python.exe -m pytest tests/unit \
      --cov=src --cov=sdk --cov-report=xml --cov-report=term-missing \
      --cov-fail-under=80

- name: Upload coverage
  uses: codecov/codecov-action@v4
  with:
    file: coverage.xml

# New job: perf-check
perf-check:
  runs-on: ubuntu-latest
  steps:
    - name: Start API and run benchmark
      run: python scripts/run_benchmark.py --quick --output /tmp/current.json
    - name: Compare to baseline
      run: python scripts/check_performance.py docs/benchmark-baseline.json /tmp/current.json
```

### scripts/check_performance.py spec

Reads baseline JSON and current JSON. Fails (exit 1) if:
- p95 latency of any endpoint increased > 50% vs baseline
- Failure rate increased > 0.1%

Prints a comparison table on success.

### Acceptance criteria

- [ ] `pytest tests/unit --cov=src` → coverage report generated
- [ ] CI fails if unit test coverage drops below 80%
- [ ] `docs/benchmark-baseline.json` — committed baseline from Task 6 numbers
- [ ] `scripts/check_performance.py baseline.json current.json` → exits 0 if within bounds, 1 if regressed
- [ ] `.github/workflows/performance.yml` — nightly schedule (`cron: "0 3 * * *"`)

---

## Execution Order

```
TASK 1  (LangChain + LlamaIndex)   ← depends on SDK (already done)
TASK 2  (Webhooks)                 ← independent
TASK 3  (Async SDK)                ← independent, extends sdk/
TASK 4  (Testcontainers)           ← independent
TASK 5  (Time-travel)              ← independent
TASK 6  (Docker Compose prod)      ← independent; Redis needed for Task 7
TASK 7  (Redis cache)              ← depends on TASK 6 (Redis service)
TASK 8  (Semantic search)          ← independent
TASK 9  (SLO endpoint)             ← independent
TASK 10 (CI improvements)          ← do last (after all code is stable)
```

**Parallelizable**: Tasks 1, 2, 3, 4, 5, 8, 9 are fully independent.  
**Sequential**: Task 7 after Task 6 (needs Redis in compose).  
**Final**: Task 10 after everything (sets coverage baseline on complete codebase).

---

## Definition of Done for v2

The project reaches "strong market product" when:

1. `from agentflow_integrations.langchain import AgentFlowToolkit` works in 3 lines
2. `POST /v1/webhooks` + verify HMAC signature on delivery
3. `AsyncAgentFlowClient` usable in any async framework
4. At least 1 Testcontainers test proving real Kafka path
5. `GET /v1/entity/order/ORD-1?as_of=2026-04-09T12:00:00Z` returns historical state
6. `docker compose -f docker-compose.prod.yml up -d` → Kafka UI + Grafana pre-configured
7. `GET /v1/search?q=large+orders` returns ranked results
8. `GET /v1/slo` reports live SLO compliance
9. CI: coverage gate (≥80%) + nightly perf regression check
10. `pytest tests/` → 100+ tests, 0 failures
