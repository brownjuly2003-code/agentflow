# AgentFlow — Commercial Quality v5
**Date**: 2026-04-11  
**Source**: Deep test report (rep.md) + research gap analysis (остатки)  
**Executor**: Codex

## Откуда задачи

**Фиксы из rep.md:**
- 6 старых `# type: ignore` (не тронуты в прошлом прогоне)
- Rate limit in-memory (сбрасывается при рестарте — отмечено в 2.8)
- Outbox pattern для exactly-once replay (архитектурное замечание в п.7)

**Новое из research gap analysis (незакрытые пункты):**
- TypeScript SDK — экосистема (frontend/Node.js агенты)
- Metric alert subscriptions — завершает alerting story
- Query result pagination — нужна для больших датасетов
- DuckDB connection pool — производительность под нагрузкой
- PyPI + npm publish setup — дистрибуция
- Grafana: дашборды для 3 user journeys из product.md

---

## Граф зависимостей

```
TASK 1 (type: ignore cleanup)     ← фиксы, с них начинаем
TASK 2 (Rate limit Redis)         ← после Task 1, использует Redis (уже в compose)
TASK 3 (Outbox pattern)           ← после Task 1, строится на event_replayer
TASK 4 (DuckDB connection pool)   ← независим, инфраструктурный
TASK 5 (TypeScript SDK)           ← независим
TASK 6 (Metric alert subs)        ← после Task 1, строится на webhook infra
TASK 7 (Query pagination)         ← независим
TASK 8 (Grafana dashboards)       ← после Task 2+4 (метрики стабильны)
TASK 9 (PyPI + npm setup)         ← после Task 5 (TS SDK готов)
TASK 10 (README overhaul)         ← последним, когда всё стабильно
```

---

## TASK 1 — Закрыть 6 старых `# type: ignore`

**Первой** — чистая типизация = фундамент для всего остального.

**Что исправить** (из rep.md):

```
src/serving/api/analytics.py      — no-untyped-def, attr-defined
src/serving/api/auth.py           — no-untyped-def
src/serving/api/security.py       — no-untyped-def
src/serving/api/versioning.py     — no-untyped-def
src/serving/semantic_layer/nl_engine.py    — union-attr
src/serving/semantic_layer/schema_evolution.py — import-untyped
```

**Подход к каждому типу:**

`no-untyped-def` — добавь аннотации возврата:
```python
# БЫЛО
def build_security_headers_middleware(app):

# СТАЛО
def build_security_headers_middleware(app: FastAPI) -> None:
```

`attr-defined` в analytics.py — mypy не видит атрибут.
Проверь: либо добавь `cast()`, либо используй `hasattr`, либо аннотируй поле явно.

`union-attr` в nl_engine.py — доступ к атрибуту на `X | None`:
```python
# БЫЛО
result = engine.translate(q)
return result.sql   # result может быть None

# СТАЛО
result = engine.translate(q)
if result is None:
    raise ValueError("Translation failed")
return result.sql
```

`import-untyped` в schema_evolution.py — добавь `# type: ignore[import-untyped]`
только если у библиотеки действительно нет stubs. Иначе найди типизированный импорт.

**Критерии приёмки:**
- [ ] `mypy src/ sdk/ --ignore-missing-imports` → 0 errors, ноль `# type: ignore` кроме PyYAML
- [ ] `pytest tests/ -q` → 306 passed, 3 skipped, 0 failed (тесты не сломаны)

---

## TASK 2 — Rate Limit Persistence (Redis-backed counters)

**После Task 1.** Строится на Redis, который уже есть в `docker-compose.prod.yml`.

**Проблема из rep.md (2.8):** rate limit counters in-memory — сбрасываются при рестарте API.
При rolling update в K8s новая реплика начинает с нулём — клиент может обойти лимит.

**Что построить:**

```
src/serving/api/
  rate_limiter.py           # NEW: Redis-backed sliding window
  auth.py                   # MODIFY: использовать RateLimiter вместо in-memory dict
tests/unit/
  test_rate_limiter.py      # NEW
```

### Реализация

```python
# src/serving/api/rate_limiter.py
import redis.asyncio as aioredis
import time

class RateLimiter:
    """
    Redis-backed sliding window rate limiter.
    Пережиает рестарт API и работает корректно при нескольких репликах.
    """
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis = aioredis.from_url(redis_url)

    async def is_allowed(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.time()
        window_start = now - window_seconds
        pipe = self._redis.pipeline()
        # Sliding window: удаляем старые записи, считаем текущие
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds * 2)
        results = await pipe.execute()
        count = results[2]
        return count <= limit

    async def get_remaining(self, key: str, limit: int, window_seconds: int = 60) -> int:
        now = time.time()
        window_start = now - window_seconds
        await self._redis.zremrangebyscore(key, 0, window_start)
        count = await self._redis.zcard(key)
        return max(0, limit - count)
```

Fallback: если Redis недоступен → логируй warning, пропускай запрос (fail-open).
Причина: rate limit — не security-critical функция; недоступность Redis не должна класть API.

### Rate limit headers

```
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 47
X-RateLimit-Reset: 1744372800   # Unix timestamp сброса окна
```

**Критерии приёмки:**
- [ ] После рестарта API счётчики сохраняются (проверяется: 100 запросов → рестарт → 20 запросов → 429)
- [ ] При двух репликах лимит считается суммарно (один Redis для обеих)
- [ ] Redis недоступен → 200 (fail-open), warning в логах
- [ ] `X-RateLimit-Remaining` в каждом ответе
- [ ] `tests/unit/test_rate_limiter.py` — 8+ тестов: sliding window, persist across restart, fail-open

---

## TASK 3 — Outbox Pattern для Exactly-Once Replay

**После Task 1.** Строится на `event_replayer.py`.

**Проблема из rep.md (п.7):** между Kafka publish и обновлением статуса в DuckDB нет
распределённой транзакции. `replay_pending` безопаснее `failed`, но не даёт exactly-once.

**Что построить:**

```
src/processing/
  outbox.py                 # NEW: OutboxProcessor
  event_replayer.py         # MODIFY: использовать outbox
src/serving/api/
  main.py                   # MODIFY: запускать OutboxProcessor на старте
tests/integration/
  test_outbox.py            # NEW
```

### Схема outbox в DuckDB

```sql
CREATE TABLE IF NOT EXISTS outbox (
    id          TEXT PRIMARY KEY,        -- UUID
    event_id    TEXT NOT NULL,           -- ссылка на dead_letter_events
    payload     JSON NOT NULL,
    topic       TEXT NOT NULL,           -- Kafka topic назначения
    created_at  TIMESTAMP DEFAULT NOW(),
    sent_at     TIMESTAMP,
    status      TEXT DEFAULT 'pending'   -- pending | sent | failed
);
```

### Протокол

```
Replay request:
  1. BEGIN TRANSACTION
  2. INSERT INTO outbox (id, event_id, payload, topic, status='pending')
  3. UPDATE dead_letter_events SET status='replay_pending'
  4. COMMIT
  ↓ (транзакция закрыта — данные сохранены атомарно)

OutboxProcessor (background task, каждые 2 сек):
  1. SELECT * FROM outbox WHERE status='pending' ORDER BY created_at LIMIT 100
  2. Для каждой записи:
     a. producer.send(topic, payload)
     b. producer.flush()   ← ждём подтверждения от Kafka
     c. UPDATE outbox SET status='sent', sent_at=NOW()
     d. UPDATE dead_letter_events SET status='replayed'
  3. При ошибке Kafka: UPDATE outbox SET status='failed', retry_count++
     Retry: exponential backoff, max 5 попыток
```

```python
# src/processing/outbox.py
class OutboxProcessor:
    def __init__(self, duckdb_path: str, kafka_bootstrap: str):
        self._conn = duckdb.connect(duckdb_path)
        self._producer = KafkaProducer(bootstrap_servers=kafka_bootstrap)

    async def process_pending(self) -> int:
        """Process pending outbox entries. Returns count processed."""
        rows = self._conn.execute(
            "SELECT id, event_id, payload, topic FROM outbox "
            "WHERE status = 'pending' ORDER BY created_at LIMIT 100"
        ).fetchall()
        processed = 0
        for row in rows:
            try:
                self._producer.send(row["topic"], row["payload"].encode())
                self._producer.flush()
                self._conn.execute(
                    "UPDATE outbox SET status='sent', sent_at=NOW() WHERE id=?",
                    [row["id"]]
                )
                self._conn.execute(
                    "UPDATE dead_letter_events SET status='replayed' WHERE event_id=?",
                    [row["event_id"]]
                )
                processed += 1
            except Exception as e:
                self._conn.execute(
                    "UPDATE outbox SET status='failed' WHERE id=?", [row["id"]]
                )
        return processed
```

**Критерии приёмки:**
- [ ] Replay: INSERT в outbox и UPDATE dead_letter атомарны (один TRANSACTION)
- [ ] OutboxProcessor запускается как background task при старте API
- [ ] API рестарт посередине replay → запись в outbox подхватывается после старта
- [ ] Kafka недоступен → outbox запись остаётся `pending`, ретраится позже
- [ ] `tests/integration/test_outbox.py` — 5+ тестов: atomicity, crash recovery, kafka failure

---

## TASK 4 — DuckDB Connection Pool

**Независим.** Параллельно с Task 2-3.

**Проблема:** каждый запрос открывает/закрывает DuckDB соединение или конкурирует за одно.
Под нагрузкой (50+ concurrent агентов из load test) это bottleneck.

**Что построить:**

```
src/serving/
  db_pool.py                # NEW: DuckDBPool
src/serving/semantic_layer/
  query_engine.py           # MODIFY: брать соединение из пула
src/serving/api/
  main.py                   # MODIFY: инициализировать пул на старте
tests/unit/
  test_db_pool.py           # NEW
```

### Реализация

```python
# src/serving/db_pool.py
import duckdb
import asyncio
from contextlib import asynccontextmanager

class DuckDBPool:
    """
    Простой пул DuckDB соединений.
    DuckDB поддерживает несколько read-only соединений одновременно
    и одно read-write. Пул управляет этим разделением.
    """
    def __init__(self, db_path: str, pool_size: int = 5):
        self._path = db_path
        self._pool_size = pool_size
        self._read_pool: asyncio.Queue[duckdb.DuckDBPyConnection] = asyncio.Queue()
        self._write_conn: duckdb.DuckDBPyConnection | None = None

    async def initialize(self) -> None:
        # Read-only соединения (параллельные запросы)
        for _ in range(self._pool_size):
            conn = duckdb.connect(self._path, read_only=True)
            await self._read_pool.put(conn)
        # Одно write соединение
        self._write_conn = duckdb.connect(self._path, read_only=False)

    @asynccontextmanager
    async def read_conn(self):
        conn = await self._read_pool.get()
        try:
            yield conn
        finally:
            await self._read_pool.put(conn)

    @asynccontextmanager
    async def write_conn(self):
        # Write serialized через asyncio.Lock
        async with self._write_lock:
            yield self._write_conn
```

**Критерии приёмки:**
- [ ] `pool_size=5` read connections, 1 write connection
- [ ] Concurrent read запросы не блокируют друг друга
- [ ] Write операции сериализованы (Lock)
- [ ] `GET /v1/health` репортит pool utilization
- [ ] Locust load test: p95 entity query ≤ 50ms при 50 concurrent users (было: измерь baseline)
- [ ] `tests/unit/test_db_pool.py` — 6+ тестов: concurrent reads, write lock, pool exhaustion

---

## TASK 5 — TypeScript / JavaScript SDK

**Независим.** Параллельно с Task 2-4.

**Почему:** frontend агенты (Vercel AI SDK, browser-based) и Node.js агенты не могут использовать Python SDK.
Это огромная часть экосистемы.

**Что построить:**

```
sdk-ts/
  src/
    client.ts               # AgentFlowClient
    models.ts               # TypeScript типы из OpenAPI
    exceptions.ts           # AgentFlowError, AuthError, RateLimitError
    stream.ts               # SSE streaming helper
  index.ts                  # exports
  package.json
  tsconfig.json
  README.md
tests/
  client.test.ts            # Vitest тесты
```

### client.ts spec

```typescript
export class AgentFlowClient {
  constructor(
    private readonly baseUrl: string,
    private readonly apiKey: string,
    private readonly options: ClientOptions = {}
  ) {}

  // Entity lookups
  async getOrder(orderId: string): Promise<OrderEntity>
  async getUser(userId: string): Promise<UserEntity>
  async getProduct(productId: string): Promise<ProductEntity>
  async getSession(sessionId: string): Promise<SessionEntity>

  // Metrics
  async getMetric(name: MetricName, window?: TimeWindow): Promise<MetricResult>

  // NL query
  async query(question: string): Promise<QueryResult>

  // Health
  async health(): Promise<HealthStatus>
  async isFresh(maxAgeSeconds?: number): Promise<boolean>

  // Streaming (SSE)
  streamEvents(filters?: EventFilters): AsyncGenerator<PipelineEvent>

  // Batch
  async batch(requests: BatchItem[]): Promise<BatchResponse>
}
```

### Vercel AI SDK integration (bonus, если успеет)

```typescript
// sdk-ts/src/vercel-ai.ts
import { tool } from "ai";
import { AgentFlowClient } from "./client";

export function createAgentFlowTools(client: AgentFlowClient) {
  return {
    getOrder: tool({
      description: "Look up real-time order status by order ID",
      parameters: z.object({ orderId: z.string() }),
      execute: async ({ orderId }) => client.getOrder(orderId),
    }),
    getMetric: tool({
      description: "Query business metrics: revenue, conversion_rate, etc.",
      parameters: z.object({
        name: z.enum(["revenue", "order_count", "avg_order_value",
                       "conversion_rate", "active_sessions", "error_rate"]),
        window: z.enum(["1h", "24h", "7d"]).optional(),
      }),
      execute: async ({ name, window }) => client.getMetric(name, window),
    }),
  };
}
```

**Критерии приёмки:**
- [ ] `npm install` в `sdk-ts/` без ошибок
- [ ] `npx tsc --noEmit` → 0 ошибок
- [ ] `AgentFlowClient` покрывает те же методы что Python SDK
- [ ] `streamEvents()` возвращает `AsyncGenerator` с SSE событиями
- [ ] Vitest тесты: 10+ с mocked fetch
- [ ] `sdk-ts/README.md` — quickstart (5 строк → первый результат)
- [ ] Бонус: `createAgentFlowTools()` для Vercel AI SDK

---

## TASK 6 — Metric Alert Subscriptions

**После Task 1.** Строится на webhook infra из v2.

**Проблема:** webhook'и работают на события (order created, payment failed).
Но агентам нужно получать алерты когда **метрика пересекает порог**
(revenue упал на 20%, error_rate > 1%).

**Что построить:**

```
src/serving/api/routers/
  alerts.py                 # NEW: CRUD для alert rules
src/serving/api/
  alert_dispatcher.py       # NEW: фоновая проверка метрик, dispatch via webhook
config/
  alerts.yaml               # NEW: persisted alert rules
tests/integration/
  test_alerts.py            # NEW
```

### Alert rule model

```python
class AlertRule(BaseModel):
    id: str
    name: str
    tenant: str
    metric: str                          # "revenue", "error_rate", etc.
    window: str                          # "1h", "24h"
    condition: Literal["above", "below", "change_pct"]
    threshold: float
    webhook_url: str
    cooldown_minutes: int = 30           # не алертить повторно в течение N минут
    active: bool = True
    last_triggered_at: datetime | None = None
```

### API endpoints (`/v1/alerts`)

```
POST   /v1/alerts              — создать rule
GET    /v1/alerts              — список rules (по tenant)
PUT    /v1/alerts/{id}         — обновить
DELETE /v1/alerts/{id}         — удалить
POST   /v1/alerts/{id}/test    — trigger test webhook
GET    /v1/alerts/{id}/history — последние 20 срабатываний
```

### AlertDispatcher

Background task, каждые 60 секунд:
1. Читает все active rules из `config/alerts.yaml`
2. Для каждого rule: вызывает `QueryEngine.get_metric(rule.metric, rule.window)`
3. Проверяет condition: `above` / `below` / `change_pct` (сравнение с предыдущим значением)
4. Если triggered И cooldown прошёл → POST на `rule.webhook_url`
5. Пишет в DuckDB `alert_history` таблицу

Payload webhook'а:
```json
{
  "alert_id": "alert-123",
  "alert_name": "High Error Rate",
  "metric": "error_rate",
  "current_value": 0.023,
  "threshold": 0.01,
  "condition": "above",
  "window": "1h",
  "triggered_at": "2026-04-11T14:30:00Z",
  "tenant": "acme-corp"
}
```

**Критерии приёмки:**
- [ ] `POST /v1/alerts` создаёт rule и сохраняет в `config/alerts.yaml`
- [ ] AlertDispatcher проверяет метрики каждые 60 секунд
- [ ] Cooldown: повторный алерт не отправляется до истечения `cooldown_minutes`
- [ ] `POST /v1/alerts/{id}/test` немедленно отправляет test payload
- [ ] HMAC подпись на webhook (тот же механизм что в webhook_dispatcher.py)
- [ ] `tests/integration/test_alerts.py` — 7+ тестов: create, trigger, cooldown, test-fire

---

## TASK 7 — Query Result Pagination

**Независим.** Параллельно с Task 5-6.

**Проблема:** `POST /v1/query` возвращает все строки разом. При NL запросе
"все заказы за месяц" это может быть тысячи строк — OOM и медленный response.

**Что построить:**

```
src/serving/api/routers/
  agent_query.py            # MODIFY: add cursor pagination to /v1/query
src/serving/semantic_layer/
  query_engine.py           # MODIFY: add paginated_query()
sdk/agentflow/
  client.py                 # MODIFY: add paginate() helper
  async_client.py           # MODIFY: add async paginate()
tests/integration/
  test_pagination.py        # NEW
```

### Cursor-based pagination

```python
class QueryRequest(BaseModel):
    question: str
    limit: int = Field(100, ge=1, le=1000)   # строк на страницу
    cursor: str | None = None                 # opaque cursor из предыдущего ответа

class QueryResponse(BaseModel):
    question: str
    sql: str
    rows: list[dict]
    total_count: int | None         # None если > 10_000 (дорого считать)
    next_cursor: str | None         # None если последняя страница
    has_more: bool
    page_size: int
```

Cursor — base64-encoded offset + query hash:
```python
def encode_cursor(offset: int, query_hash: str) -> str:
    return base64.b64encode(f"{offset}:{query_hash}".encode()).decode()

def decode_cursor(cursor: str) -> tuple[int, str]:
    decoded = base64.b64decode(cursor).decode()
    offset, query_hash = decoded.split(":", 1)
    return int(offset), query_hash
```

### SDK helper

```python
# client.py
def paginate(self, question: str, page_size: int = 100) -> Iterator[list[dict]]:
    """Iterate over all pages of a query result."""
    cursor = None
    while True:
        result = self.query(question, limit=page_size, cursor=cursor)
        yield result.rows
        if not result.has_more:
            break
        cursor = result.next_cursor
```

**Критерии приёмки:**
- [ ] `POST /v1/query` с `limit=10` → 10 строк + `next_cursor`
- [ ] Повторный запрос с `cursor` → следующие 10 строк
- [ ] Невалидный cursor → 400 с ясным сообщением
- [ ] `client.paginate("all orders")` → итератор по страницам
- [ ] `tests/integration/test_pagination.py` — 6+ тестов: first page, next page, last page, invalid cursor

---

## TASK 8 — Grafana: Pre-Built Dashboards для 3 User Journeys

**После Task 2+4** (метрики и pool стабильны).

**Из product.md**: три core user journeys — Support Agent, Ops Agent, Merch Agent.
Grafana уже в docker-compose.prod.yml, но дашборды generic. Нужны journey-specific.

**Что построить:**

```
monitoring/grafana/dashboards/
  pipeline_health.json           # уже есть — обновить
  support-agent-journey.json     # NEW
  ops-agent-journey.json         # NEW
  merch-agent-journey.json       # NEW
monitoring/grafana/provisioning/
  dashboards/dashboards.yaml     # MODIFY: добавить новые дашборды
```

### Support Agent Journey dashboard

Панели:
- **Order lookup latency** — p50/p95/p99 для `GET /v1/entity/order/*` (последние 1ч)
- **User lookup latency** — то же для `/v1/entity/user/*`
- **Entity cache hit rate** — `X-Cache: HIT` vs `MISS`
- **Active support agent sessions** — `active_sessions` метрика
- **Data freshness** — время с последнего события (SLA: < 30 сек)

### Ops Agent Journey dashboard

Панели:
- **Pipeline health timeline** — health status over time (green/yellow/red)
- **Dead letter rate** — события в dead letter / total (последние 24ч)
- **Kafka consumer lag** — если доступно
- **SLO compliance** — текущий error budget для api_latency_p95 и data_freshness
- **Alert history** — последние 10 alert triggers

### Merch Agent Journey dashboard

Панели:
- **Revenue (24h)** — time series
- **Conversion rate** — time series  
- **Top 5 products** — bar chart (обновляется каждые 5 мин)
- **NL query latency** — p50/p95 для `/v1/query`
- **Query engine: llm vs rule_based** — pie chart

**Критерии приёмки:**
- [ ] `docker compose -f docker-compose.prod.yml up -d` → все 4 дашборда видны в Grafana
- [ ] Каждый дашборд авто-provisioned (не нужно импортировать вручную)
- [ ] Support dashboard показывает latency из Prometheus метрик
- [ ] Ops dashboard показывает SLO compliance из `/v1/slo`
- [ ] Merch dashboard показывает revenue trend

---

## TASK 9 — PyPI + npm Publish Setup

**После Task 5** (TypeScript SDK готов).

**Что построить:**

```
.github/workflows/
  publish-pypi.yml          # NEW: publish sdk/ на PyPI при git tag
  publish-npm.yml           # NEW: publish sdk-ts/ на npm при git tag
sdk/
  pyproject.toml            # VERIFY: name, version, classifiers корректны
sdk-ts/
  package.json              # VERIFY: name, version, files, main, types корректны
scripts/
  release.py                # NEW: bump version, create tag, trigger publish
RELEASING.md                # NEW: как выпускать релиз
```

### .github/workflows/publish-pypi.yml

```yaml
on:
  push:
    tags: ["sdk-v*"]          # триггер: git tag sdk-v1.0.1

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install build twine
      - run: python -m build sdk/
      - run: twine upload sdk/dist/*
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
```

### scripts/release.py

```python
"""
Bump version, create git tag, trigger CI publish.

Usage:
  python scripts/release.py patch   # 1.0.0 → 1.0.1
  python scripts/release.py minor   # 1.0.0 → 1.1.0
  python scripts/release.py major   # 1.0.0 → 2.0.0

Actions:
  1. Bump version в sdk/pyproject.toml и sdk-ts/package.json
  2. Update sdk/CHANGELOG.md (добавить дату и версию)
  3. git commit -m "release: vX.Y.Z"
  4. git tag sdk-vX.Y.Z
  5. Печатает: git push --tags для запуска CI
"""
```

**Критерии приёмки:**
- [ ] `python scripts/release.py patch` — бампит обе версии синхронно
- [ ] `git tag sdk-v1.0.1` → GitHub Actions публикует на PyPI и npm
- [ ] `pip install agentflow` после публикации → `from agentflow import AgentFlowClient` работает
- [ ] `npm install @agentflow/client` → TypeScript типы доступны
- [ ] `RELEASING.md` — пошаговая инструкция для релиза

---

## TASK 10 — README Overhaul

**Последней** — когда всё стабильно.

**Проблема:** текущий README создавался итерационно. Для коммерческого продукта нужен
единый документ: одна минута чтения → понял что это, зачем и как попробовать.

**Структура нового README.md:**

```markdown
# AgentFlow — Agent Data Serving Platform

> Real-time data layer for AI agents. Kafka → Flink → Iceberg → Semantic API.
> Fresh data in <30 seconds. Typed SDK. Zero SQL for your agents.

## Why AgentFlow

[3 строки: проблема → решение → ключевое отличие от конкурентов]

## Quick Start (< 5 минут)

[docker compose up → pip install → 3 строки кода → работающий агент]

## How It Works

[диаграмма: Kafka → Flink → Iceberg → API → Agent]

## Agent Integrations

[LangChain | CrewAI | LlamaIndex | Vercel AI SDK — по одной строке + ссылка]

## Core API

[таблица: endpoint | что делает | пример | latency]

## User Journeys

[3 конкретных сценария из product.md — Support / Ops / Merch]

## Benchmarks

[реальные числа из docs/benchmark.md]

## Architecture

[ссылка на docs/architecture.md]

## Self-Hosted vs Cloud

[таблица: что в OSS, что потребует managed]

## Contributing

[ссылка на CONTRIBUTING.md]
```

**Правила написания:**
- Максимум 200 строк
- Каждый раздел читается независимо
- Нет фраз "production-grade", "enterprise-ready" без доказательств — только цифры
- Все примеры кода — рабочие (тестируются в CI как doctest или отдельный файл)

**Критерии приёмки:**
- [ ] README ≤ 200 строк
- [ ] Quick Start: от `git clone` до первого ответа агента за < 5 минут (проверено вручную)
- [ ] Все code snippets в README — рабочие
- [ ] Нет устаревших ссылок и команд
- [ ] `docs/architecture.md` синхронизирован с текущим состоянием (v1-v5)

---

## Итоговый порядок выполнения

```
 1. TASK 1  Закрыть 6 старых type: ignore        ← чистый фундамент
 2. TASK 2  Rate limit Redis                      ← после Task 1
 3. TASK 3  Outbox pattern (exactly-once)         ← после Task 1
 4. TASK 4  DuckDB connection pool                ← параллельно с Task 2-3
 5. TASK 5  TypeScript SDK                        ← параллельно с Task 2-4
 6. TASK 6  Metric alert subscriptions            ← после Task 1
 7. TASK 7  Query pagination                      ← параллельно с Task 5-6
 8. TASK 8  Grafana dashboards (3 journeys)       ← после Task 2+4 стабильны
 9. TASK 9  PyPI + npm publish setup              ← после Task 5 (TS SDK готов)
10. TASK 10 README overhaul                       ← последним
```

**Параллельные группы:**
- Группа A (Tasks 2, 3, 4, 5, 6, 7) — все стартуют после Task 1
- Группа B (Tasks 8, 9) — стартуют после завершения соответствующих зависимостей
- Task 10 — только когда всё остальное стабильно

**После v5:**
- `mypy` — 0 errors, 0 `# type: ignore` кроме PyYAML
- Rate limits переживают рестарт API и rolling update в K8s
- Replay гарантирует exactly-once через outbox
- TypeScript SDK + Vercel AI интеграция
- `pip install agentflow` и `npm install @agentflow/client` работают
- 3 Grafana дашборда из product.md user journeys
- README читается за 1 минуту
