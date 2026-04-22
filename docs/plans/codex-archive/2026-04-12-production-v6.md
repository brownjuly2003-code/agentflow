# AgentFlow — Production v6
**Date**: 2026-04-12  
**Scope**: Production Hardening → Observability → Developer Experience  
**Executor**: Codex

## Откуда задачи

**Production Hardening:**
- E2E smoke tests в CI (нет сквозных проверок после деплоя)
- Chaos engineering — Toxiproxy (не проверяем поведение при network failures)
- K8s staging environment — Helm chart есть, но нет места его запускать
- Secrets rotation — нет механизма ротации API ключей без даунтайма

**Observability Deep Dive:**
- Distributed tracing E2E — OTel есть (v3), но spans не связаны сквозь Kafka
- Structured logging pipeline — structlog есть, но нет centralized correlation
- Alert noise reduction — AlertDispatcher есть (v5), но нет дедупликации и эскалации

**Developer Experience:**
- `agentflow init` wizard — CLI есть, но нет scaffolding для новых проектов
- Real-world agent examples — SDK есть, но нет готовых примеров под 3 user journeys
- DevContainer polish + docs — нужна синхронизация после v1-v5

---

## Граф зависимостей

```
TASK 1  E2E smoke tests in CI              ← фундамент hardening
TASK 2  Distributed tracing E2E (Jaeger)   ← независим, observability фундамент
TASK 3  Structured logging correlation     ← параллельно с Task 2
TASK 4  Chaos engineering (Toxiproxy)      ← после Task 1 (нужны стабильные тесты)
TASK 5  K8s staging (kind + Helm)          ← после Task 4 (chaos гоняется на staging)
TASK 6  Secrets rotation                   ← после Task 1
TASK 7  Alert noise reduction              ← после Task 2+3 (нужна observability)
TASK 8  agentflow init wizard              ← независим, DX
TASK 9  Real-world agent examples          ← после Task 8
TASK 10 DevContainer polish + docs         ← последним
```

---

## TASK 1 — E2E Smoke Tests in CI

**Первой** — без сквозных тестов нельзя безопасно включать chaos и staging.

**Что построить:**

```
tests/e2e/
  conftest.py               # NEW: поднимает docker-compose, ждёт ready
  test_smoke.py             # NEW: 10 критических сценариев
  test_agent_journeys.py    # NEW: 3 полных user journey
.github/workflows/
  e2e.yml                   # NEW: запускается на каждый push в main
```

### Критические сценарии (test_smoke.py)

```python
# 1. Pipeline health: GET /v1/health → 200, status "ok" или "degraded"
# 2. Entity lookup: GET /v1/entity/order/ORD-001 → 200, data не пустая
# 3. Metrics: GET /v1/metrics/revenue?window=24h → 200, value число
# 4. NL query: POST /v1/query {"question": "total revenue today"} → 200, sql не пустой
# 5. Auth: GET /v1/entity/order/ORD-001 без ключа → 401
# 6. Rate limit: 125 запросов подряд → последние 5 получают 429
# 7. Batch: POST /v1/batch [3 entity запроса] → 200, 3 результата
# 8. SSE: GET /v1/events → соединение открывается, первый event приходит < 5 сек
# 9. Webhook: POST /v1/webhooks, затем trigger → callback получен
# 10. Pagination: POST /v1/query limit=5 → next_cursor есть, fetch page 2 работает
```

### Agent journey tests (test_agent_journeys.py)

```python
async def test_support_agent_journey():
    """Полный цикл support агента: получить заказ → получить пользователя → проверить метрику."""
    client = AgentFlowClient(base_url=BASE_URL, api_key=API_KEY)
    order = await client.get_order("ORD-001")
    assert order["order_id"] == "ORD-001"
    user = await client.get_user(order["user_id"])
    assert "email" in user
    metric = await client.get_metric("active_sessions", window="1h")
    assert metric["value"] >= 0

async def test_ops_agent_journey():
    """Ops: проверить pipeline health → проверить dead letters → проверить SLO."""
    health = await client.health()
    assert health["status"] in ("ok", "degraded")
    # dead letter queue
    resp = await httpx.get(f"{BASE_URL}/v1/dead-letter", headers=headers)
    assert resp.status_code == 200
    # SLO
    slo = await httpx.get(f"{BASE_URL}/v1/slo", headers=headers)
    assert slo.status_code == 200
    assert "error_budget_remaining" in slo.json()

async def test_merch_agent_journey():
    """Merch: NL запрос → получить метрики → paginate результаты."""
    result = await client.query("top 10 products by revenue this week")
    assert result.sql != ""
    assert len(result.rows) > 0
    # paginate
    pages = []
    async for page in client.paginate("all orders today", page_size=5):
        pages.append(page)
    assert len(pages) >= 1
```

### .github/workflows/e2e.yml

```yaml
name: E2E Tests
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - name: Start services
        run: |
          docker compose -f docker-compose.prod.yml up -d
          python scripts/wait_for_services.py --timeout 120
      - name: Seed demo data
        run: python scripts/seed_demo_data.py
      - name: Run E2E tests
        run: pytest tests/e2e/ -v --tb=short --timeout=60
      - name: Collect logs on failure
        if: failure()
        run: docker compose -f docker-compose.prod.yml logs > e2e-logs.txt
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: e2e-logs
          path: e2e-logs.txt
```

### scripts/wait_for_services.py

```python
"""Poll /v1/health until 200 or timeout."""
import httpx, time, argparse, sys

def wait(url: str, timeout: int) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{url}/v1/health", timeout=5)
            if r.status_code == 200:
                print(f"Services ready in {timeout - (deadline - time.time()):.0f}s")
                return
        except Exception:
            pass
        time.sleep(3)
    print("Timeout waiting for services", file=sys.stderr)
    sys.exit(1)
```

**Критерии приёмки:**
- [ ] `pytest tests/e2e/ -v` — 10+ passed при запущенных сервисах
- [ ] GitHub Actions E2E job проходит на каждый push в main
- [ ] При падении E2E — логи автоматически аттачатся к job
- [ ] `test_support_agent_journey`, `test_ops_agent_journey`, `test_merch_agent_journey` — все зелёные
- [ ] `scripts/wait_for_services.py` — ждёт ready, не выходит по таймауту при нормальном старте

---

## TASK 2 — Distributed Tracing E2E с Jaeger

**Независим от Task 1.** OTel инструментация есть (v3), но spans не связаны сквозь Kafka.

**Проблема:** trace рвётся на Kafka boundary. Агент видит только API span, без Flink и pipeline spans.

**Что построить:**

```
src/processing/
  tracing.py                # NEW: W3C TraceContext propagation в Kafka headers
  local_pipeline.py         # MODIFY: inject/extract trace context
src/serving/api/
  middleware/tracing.py     # MODIFY: extract trace context из HTTP headers
docker-compose.prod.yml     # MODIFY: добавить Jaeger service
monitoring/
  jaeger/
    README.md               # NEW: как смотреть traces
```

### W3C TraceContext в Kafka

```python
# src/processing/tracing.py
from opentelemetry import trace
from opentelemetry.propagate import inject, extract
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

def inject_trace_to_kafka_headers(headers: dict) -> dict:
    """Inject current span context into Kafka message headers."""
    carrier: dict[str, str] = {}
    inject(carrier)  # заполняет traceparent, tracestate
    headers.update({k: v.encode() for k, v in carrier.items()})
    return headers

def extract_trace_from_kafka_headers(headers: list[tuple]) -> object:
    """Extract span context from Kafka message headers."""
    carrier = {k: v.decode() for k, v in headers if isinstance(v, bytes)}
    return extract(carrier)
```

### Kafka producer в local_pipeline.py

```python
# При отправке события в Kafka:
with tracer.start_as_current_span("kafka.produce", attributes={"topic": topic}):
    headers = inject_trace_to_kafka_headers({})
    producer.send(topic, value=payload, headers=list(headers.items()))
```

### Jaeger в docker-compose.prod.yml

```yaml
jaeger:
  image: jaegertracing/all-in-one:1.55
  ports:
    - "16686:16686"   # Jaeger UI
    - "4317:4317"     # OTLP gRPC
  environment:
    COLLECTOR_OTLP_ENABLED: "true"
```

### Ключевые spans

| Span name | Атрибуты |
|-----------|---------|
| `http.request` | method, route, status_code, tenant_id |
| `kafka.produce` | topic, event_type, tenant_id |
| `kafka.consume` | topic, consumer_group, lag |
| `duckdb.query` | sql (обрезан до 200 символов), tenant_id |
| `query_engine.translate` | question, model, latency_ms |
| `iceberg.write` | table, rows_written |

**Критерии приёмки:**
- [ ] Запрос `POST /v1/query` порождает trace с spans: `http.request → query_engine.translate → duckdb.query`
- [ ] Replay event через outbox — trace связывает API span с Kafka produce span
- [ ] Jaeger UI на `http://localhost:16686` — trace виден после запроса
- [ ] `tenant_id` присутствует во всех spans как атрибут
- [ ] `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317` настраивается через env var
- [ ] При `OTEL_SDK_DISABLED=true` — никаких ошибок, трейсинг просто выключается

---

## TASK 3 — Structured Logging Correlation

**Параллельно с Task 2.** Structlog уже есть, нужна correlation с trace IDs.

**Проблема:** логи и трейсы живут отдельно. При расследовании инцидента нельзя перейти от лога к trace и обратно.

**Что построить:**

```
src/
  logger.py                 # MODIFY: добавить trace_id, span_id в каждый лог
  serving/api/middleware/
    logging.py              # MODIFY: request_id → correlation_id
tests/unit/
  test_logging.py           # NEW: проверяем наличие correlation полей
```

### Structlog + OTel correlation

```python
# src/logger.py
import structlog
from opentelemetry import trace

def add_otel_context(logger, method, event_dict):
    """Structlog processor: добавляет trace_id и span_id из текущего span."""
    span = trace.get_current_span()
    if span.is_recording():
        ctx = span.get_span_context()
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        add_otel_context,            # NEW
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
```

### Request-level context

```python
# В FastAPI middleware:
@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    # Берём из заголовка или генерируем
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        correlation_id=correlation_id,
        tenant_id=request.state.tenant_id if hasattr(request.state, "tenant_id") else None,
        path=request.url.path,
    )
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response
```

### Формат лога (JSON)

```json
{
  "timestamp": "2026-04-12T10:30:00.123Z",
  "level": "info",
  "event": "entity_lookup_complete",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "correlation_id": "req-7f3a9b2c",
  "tenant_id": "acme-corp",
  "path": "/v1/entity/order/ORD-001",
  "latency_ms": 12.4
}
```

**Критерии приёмки:**
- [ ] Каждый лог в API содержит `trace_id`, `span_id`, `correlation_id`, `tenant_id`
- [ ] `X-Correlation-ID` из запроса пробрасывается в ответ и во все логи
- [ ] Логи формате JSON (structlog JSONRenderer)
- [ ] `grep trace_id logs/api.log` → видны совпадающие trace_id для цепочки запросов
- [ ] `tests/unit/test_logging.py` — 5+ тестов: correlation присутствует, tenant_id есть, JSON формат

---

## TASK 4 — Chaos Engineering с Toxiproxy

**После Task 1** (нужны стабильные E2E тесты для сравнения baseline).

**Что проверяем:** поведение системы при Kafka latency, DuckDB timeout, Redis недоступен.

**Что построить:**

```
tests/chaos/
  conftest.py               # NEW: Toxiproxy client setup
  test_kafka_latency.py     # NEW
  test_redis_failure.py     # NEW
  test_duckdb_timeout.py    # NEW
docker-compose.chaos.yml    # NEW: compose с Toxiproxy proxy-ями
scripts/
  chaos_report.py           # NEW: сводный отчёт по chaos сценариям
```

### docker-compose.chaos.yml

```yaml
version: "3.9"
services:
  toxiproxy:
    image: ghcr.io/shopify/toxiproxy:2.9.0
    ports:
      - "8474:8474"    # Toxiproxy API
      - "19092:19092"  # Kafka proxy
      - "16380:16380"  # Redis proxy
    command: ["-config", "/config/toxiproxy.json"]
    volumes:
      - ./config/toxiproxy.json:/config/toxiproxy.json
```

### config/toxiproxy.json

```json
[
  {
    "name": "kafka",
    "listen": "0.0.0.0:19092",
    "upstream": "kafka:9092",
    "enabled": true
  },
  {
    "name": "redis",
    "listen": "0.0.0.0:16380",
    "upstream": "redis:6379",
    "enabled": true
  }
]
```

### Chaos сценарии

```python
# test_kafka_latency.py
def test_api_survives_kafka_500ms_latency(toxiproxy_client):
    """API должен отвечать на entity запросы даже при 500ms задержке Kafka."""
    toxiproxy_client.add_toxic("kafka", "latency", {"latency": 500, "jitter": 50})
    try:
        r = httpx.get(f"{BASE_URL}/v1/entity/order/ORD-001", headers=headers, timeout=5)
        assert r.status_code == 200  # Entity из DuckDB, не зависит от Kafka
    finally:
        toxiproxy_client.remove_toxic("kafka", "latency")

def test_pipeline_degrades_gracefully_on_kafka_down(toxiproxy_client):
    """Pipeline продолжает работать на DuckDB при полном отключении Kafka."""
    toxiproxy_client.disable_proxy("kafka")
    try:
        r = httpx.get(f"{BASE_URL}/v1/health", headers=headers)
        assert r.status_code == 200
        assert r.json()["status"] in ("ok", "degraded")  # не "down"
    finally:
        toxiproxy_client.enable_proxy("kafka")

# test_redis_failure.py
def test_rate_limiter_fails_open_on_redis_down(toxiproxy_client):
    """При недоступном Redis rate limiter пропускает запросы (fail-open)."""
    toxiproxy_client.disable_proxy("redis")
    try:
        responses = [
            httpx.get(f"{BASE_URL}/v1/entity/order/ORD-001", headers=headers)
            for _ in range(5)
        ]
        assert all(r.status_code == 200 for r in responses)
    finally:
        toxiproxy_client.enable_proxy("redis")
```

### scripts/chaos_report.py

```
Chaos Engineering Report — 2026-04-12
=====================================
Scenario                        | Expected    | Actual      | Pass?
Kafka 500ms latency             | API 200     | API 200     | ✅
Kafka down                      | degraded    | degraded    | ✅
Redis down (rate limit)         | fail-open   | fail-open   | ✅
DuckDB read timeout             | 503 + retry | 503 + retry | ✅
All passed: 4/4
```

**Критерии приёмки:**
- [ ] `pytest tests/chaos/ -v` — все 8+ сценариев зелёные
- [ ] Entity lookup работает при Kafka latency 500ms (читает из DuckDB)
- [ ] Health endpoint возвращает `degraded`, не `500`, при недоступном Kafka
- [ ] Rate limiter fail-open при Redis down (запросы проходят, warning в логах)
- [ ] `scripts/chaos_report.py` генерирует читаемый отчёт

---

## TASK 5 — K8s Staging Environment (kind + Helm)

**После Task 4** (chaos тесты должны гоняться в staging-like окружении).

**Проблема:** Helm chart есть (v4), но нет места его запускать. Разработчики не могут проверить K8s деплой локально.

**Что построить:**

```
k8s/
  kind-config.yaml          # NEW: локальный K8s кластер (kind)
  staging/
    values-staging.yaml     # NEW: overrides для staging
scripts/
  k8s_staging_up.sh         # NEW: поднять staging одной командой
  k8s_staging_down.sh       # NEW
  k8s_smoke_test.sh         # NEW: smoke test против staging
.github/workflows/
  staging-deploy.yml        # NEW: деплой в staging при PR merge в main
```

### kind-config.yaml

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30080    # NodePort для API
        hostPort: 8080
      - containerPort: 30090    # NodePort для Grafana
        hostPort: 3000
```

### scripts/k8s_staging_up.sh

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "==> Creating kind cluster..."
kind create cluster --config k8s/kind-config.yaml --name agentflow-staging

echo "==> Loading images..."
kind load docker-image agentflow-api:latest --name agentflow-staging
kind load docker-image agentflow-pipeline:latest --name agentflow-staging

echo "==> Installing Helm chart..."
helm upgrade --install agentflow helm/agentflow \
  -f k8s/staging/values-staging.yaml \
  --namespace agentflow --create-namespace \
  --wait --timeout 3m

echo "==> Running smoke tests..."
bash scripts/k8s_smoke_test.sh

echo "==> Staging ready at http://localhost:8080"
```

### values-staging.yaml

```yaml
replicaCount: 1          # staging — 1 реплика вместо 3
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
ingress:
  enabled: false          # используем NodePort в kind
service:
  type: NodePort
  nodePort: 30080
autoscaling:
  enabled: false          # нет HPA в staging
```

### .github/workflows/staging-deploy.yml

```yaml
name: Staging Deploy
on:
  push:
    branches: [main]

jobs:
  staging:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup kind
        uses: helm/kind-action@v1.9.0
      - name: Build images
        run: |
          docker build -t agentflow-api:latest -f Dockerfile.api .
          docker build -t agentflow-pipeline:latest -f Dockerfile.pipeline .
      - name: Deploy to staging
        run: bash scripts/k8s_staging_up.sh
      - name: E2E against staging
        run: BASE_URL=http://localhost:8080 pytest tests/e2e/ -v --tb=short
```

**Критерии приёмки:**
- [ ] `bash scripts/k8s_staging_up.sh` — кластер поднимается < 3 минут
- [ ] `curl http://localhost:8080/v1/health` → 200 после запуска
- [ ] E2E тесты из Task 1 проходят против staging
- [ ] GitHub Actions staging job проходит на push в main
- [ ] `bash scripts/k8s_staging_down.sh` — полная очистка кластера

---

## TASK 6 — Secrets Rotation

**После Task 1.** Сейчас нет способа ротировать API ключи без даунтайма.

**Что построить:**

```
src/serving/api/routers/
  admin.py                  # MODIFY: добавить rotation endpoints
src/serving/api/
  auth.py                   # MODIFY: поддержка двух активных ключей при ротации
scripts/
  rotate_key.py             # NEW: CLI для ротации ключей
tests/integration/
  test_rotation.py          # NEW
```

### Схема ротации (zero-downtime)

```
Шаг 1: POST /v1/admin/keys/{key_id}/rotate
  → генерирует new_key
  → сохраняет old_key_hash + new_key_hash (оба активны)
  → возвращает new_key (показывается один раз)
  → grace_period: 24 часа (old_key продолжает работать)

Шаг 2: Клиент переключается на new_key

Шаг 3: POST /v1/admin/keys/{key_id}/revoke-old
  → удаляет old_key_hash
  → или автоматически после grace_period
```

### API

```
POST /v1/admin/keys/{key_id}/rotate
  → { new_key: "af_live_...", expires_at: "2026-04-13T10:00:00Z" }

GET  /v1/admin/keys/{key_id}/rotation-status
  → { phase: "grace_period", old_key_active_until: "...", requests_on_old_key_last_hour: 12 }

POST /v1/admin/keys/{key_id}/revoke-old
  → { revoked: true }
```

### scripts/rotate_key.py

```python
"""
Rotate API key with zero downtime.

Usage:
  python scripts/rotate_key.py --key-id KEY_ID --admin-key ADMIN_KEY
  python scripts/rotate_key.py --key-id KEY_ID --revoke-old

Flow:
  1. Call /v1/admin/keys/{id}/rotate → new key
  2. Print new key (save it now, shown once)
  3. Old key active for 24 hours
  4. Run --revoke-old when ready
"""
```

**Критерии приёмки:**
- [ ] Во время ротации оба ключа (старый и новый) принимаются API
- [ ] После `--revoke-old` старый ключ даёт 401
- [ ] `rotation-status` показывает количество запросов на старый ключ (мониторинг миграции)
- [ ] Grace period истекает → old_key_hash удаляется автоматически (background task)
- [ ] `tests/integration/test_rotation.py` — 6+ тестов: оба ключа активны, revoke, grace period

---

## TASK 7 — Alert Noise Reduction

**После Task 2+3** (нужна observability для корреляции алертов).

**Проблема:** AlertDispatcher (v5) может слать много алертов при одном инциденте (каждые 60 сек если метрика не восстановилась).

**Что построить:**

```
src/serving/api/
  alert_dispatcher.py       # MODIFY: дедупликация + эскалация
config/
  alerts.yaml               # MODIFY: escalation_policy поле
tests/integration/
  test_alert_dedup.py       # NEW
```

### Дедупликация (group_by window)

```python
class AlertDispatcher:
    """
    Улучшенная логика:
    1. Firing: первый тригер → немедленно шлём
    2. Sustained: метрика не восстановилась → шлём раз в escalation_interval
    3. Resolved: метрика вернулась в норму → шлём resolved webhook
    4. Flapping: > 3 смен состояния за 5 минут → подавляем алерты, пишем в лог
    """

    # Состояния алерта
    STATES = Literal["ok", "firing", "sustained", "resolved", "suppressed"]
```

### Escalation policy

```yaml
# config/alerts.yaml
alerts:
  - id: "high-error-rate"
    name: "High Error Rate"
    metric: error_rate
    condition: above
    threshold: 0.01
    cooldown_minutes: 30
    escalation:
      - level: 1
        after_minutes: 0         # немедленно
        webhook_url: "https://hooks.slack.com/..."
      - level: 2
        after_minutes: 15        # если не resolved через 15 мин → эскалация
        webhook_url: "https://pagerduty.com/..."
      - level: 3
        after_minutes: 60        # через час → manager
        webhook_url: "https://hooks.slack.com/managers-channel"
    flap_detection:
      enabled: true
      window_minutes: 5
      max_changes: 3             # подавить если > 3 смен за 5 мин
```

### Resolved payload

```json
{
  "alert_id": "alert-123",
  "alert_name": "High Error Rate",
  "status": "resolved",
  "metric": "error_rate",
  "resolved_value": 0.004,
  "fired_at": "2026-04-12T10:00:00Z",
  "resolved_at": "2026-04-12T10:47:00Z",
  "duration_minutes": 47
}
```

**Критерии приёмки:**
- [ ] Sustained alert не шлёт webhook каждые 60 сек — только раз в `escalation_interval`
- [ ] Resolved webhook отправляется когда метрика возвращается в норму
- [ ] Flapping: > 3 смен за 5 мин → алерт подавляется + warning в логах
- [ ] Level 2 escalation срабатывает через 15 мин если Level 1 не resolved
- [ ] `tests/integration/test_alert_dedup.py` — 7+ тестов: dedup, resolved, flapping, escalation

---

## TASK 8 — `agentflow init` Wizard

**Независим.** CLI есть (v4 SDK), но нет scaffolding команды.

**Что построить:**

```
sdk/agentflow/
  cli/
    init.py                 # NEW: agentflow init wizard
    templates/
      basic/                # NEW: шаблон для нового проекта
      langchain/            # NEW: LangChain агент шаблон
      crewai/               # NEW: CrewAI агент шаблон
      vercel-ai/            # NEW: Next.js + Vercel AI SDK шаблон
tests/unit/
  test_cli_init.py          # NEW
```

### Wizard flow

```
$ agentflow init

AgentFlow Project Setup
=======================
? Project name: my-agent
? Base URL [http://localhost:8000]:
? API key: af_live_...
? Template:
  ❯ basic        — simple Python agent
    langchain    — LangChain agent with AgentFlow tools
    crewai       — CrewAI agent with AgentFlow tools
    vercel-ai    — Next.js app with Vercel AI SDK + AgentFlow

Creating my-agent/
  ✓ Created my-agent/main.py
  ✓ Created my-agent/requirements.txt
  ✓ Created my-agent/.env.example
  ✓ Created my-agent/README.md

Next steps:
  cd my-agent
  pip install -r requirements.txt
  python main.py
```

### basic/main.py шаблон

```python
"""AgentFlow Basic Agent — generated by agentflow init"""
from agentflow import AgentFlowClient

client = AgentFlowClient(
    base_url="{{ base_url }}",
    api_key="{{ api_key }}"
)

def main():
    # Health check
    health = client.health()
    print(f"Pipeline status: {health['status']}")

    # Entity lookup
    order = client.get_order("ORD-001")
    print(f"Order: {order}")

    # Metric query
    revenue = client.get_metric("revenue", window="24h")
    print(f"Revenue (24h): {revenue['value']}")

    # NL query
    result = client.query("total orders today")
    print(f"SQL: {result.sql}")
    print(f"Rows: {result.rows[:3]}")

if __name__ == "__main__":
    main()
```

### langchain/main.py шаблон

```python
"""LangChain Agent с AgentFlow tools — generated by agentflow init"""
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_openai import ChatOpenAI
from agentflow.integrations.langchain import create_agentflow_tools
from agentflow import AgentFlowClient

client = AgentFlowClient(base_url="{{ base_url }}", api_key="{{ api_key }}")
tools = create_agentflow_tools(client)

llm = ChatOpenAI(model="gpt-4o", temperature=0)
agent = create_openai_functions_agent(llm, tools, prompt=...)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

result = executor.invoke({"input": "What was total revenue yesterday?"})
print(result["output"])
```

**Критерии приёмки:**
- [ ] `agentflow init` запускает интерактивный wizard
- [ ] 4 шаблона: basic, langchain, crewai, vercel-ai
- [ ] Сгенерированный проект запускается без изменений после `pip install -r requirements.txt`
- [ ] `agentflow init --template basic --name my-agent --non-interactive` — не интерактивный режим для CI
- [ ] `tests/unit/test_cli_init.py` — 6+ тестов: template selection, file generation, non-interactive mode

---

## TASK 9 — Real-World Agent Examples

**После Task 8** (wizard и шаблоны готовы).

**Что построить:**

```
examples/
  support-agent/
    main.py                 # NEW: полноценный support агент
    README.md               # NEW
  ops-agent/
    main.py                 # NEW: ops мониторинг агент
    README.md               # NEW
  merch-agent/
    main.py                 # NEW: merch analytics агент
    README.md               # NEW
  README.md                 # NEW: index примеров
tests/
  test_examples.py          # NEW: smoke test каждого примера
```

### support-agent/main.py

```python
"""
Support Agent — отвечает на вопросы о заказах и пользователях.
Использует LangChain + AgentFlow tools.

Демонстрирует:
- Entity lookup (order, user)
- Metric query (active_sessions)
- NL query для поиска заказов
- Streaming ответ
"""
import asyncio
from agentflow import AgentFlowClient
from agentflow.integrations.langchain import create_agentflow_tools
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate

async def handle_support_query(query: str) -> str:
    client = AgentFlowClient.from_env()  # читает AGENTFLOW_API_KEY из .env
    tools = create_agentflow_tools(client, tools=["get_order", "get_user", "query"])

    system_prompt = """You are a customer support assistant.
    Use the available tools to look up real-time order and user information.
    Always check actual data before answering — don't guess."""

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    agent = create_openai_functions_agent(llm, tools, ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ]))
    executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
    result = await executor.ainvoke({"input": query})
    return result["output"]

if __name__ == "__main__":
    queries = [
        "What is the status of order ORD-001?",
        "Who placed the most orders in the last 24 hours?",
        "Are there any delayed orders right now?",
    ]
    for q in queries:
        print(f"\nQ: {q}")
        print(f"A: {asyncio.run(handle_support_query(q))}")
```

### tests/test_examples.py

```python
"""Smoke test: каждый пример импортируется без ошибок и проходит dry-run."""
import importlib.util, pytest

EXAMPLES = [
    "examples/support-agent/main.py",
    "examples/ops-agent/main.py",
    "examples/merch-agent/main.py",
]

@pytest.mark.parametrize("path", EXAMPLES)
def test_example_importable(path):
    spec = importlib.util.spec_from_file_location("example", path)
    module = importlib.util.module_from_spec(spec)
    # Просто проверяем что импортируется без синтаксических ошибок
    assert module is not None
```

**Критерии приёмки:**
- [ ] 3 примера: support-agent, ops-agent, merch-agent
- [ ] Каждый пример запускается командой `python main.py` с демо-данными
- [ ] `examples/README.md` — ссылки на все примеры + 1-строчное описание каждого
- [ ] `tests/test_examples.py` — smoke test проходит в CI
- [ ] Каждый `README.md` примера содержит: prerequisites, setup, run, expected output

---

## TASK 10 — DevContainer Polish + Docs Overhaul

**Последней** — когда всё стабильно.

**Что построить:**

```
.devcontainer/
  devcontainer.json         # MODIFY: обновить post-start команды
  Dockerfile                # MODIFY: добавить kind, Toxiproxy CLI
docs/
  architecture.md           # MODIFY: синхронизировать с v1-v6
  runbook.md                # NEW: как реагировать на инциденты
  contributing.md           # MODIFY: добавить chaos тесты и E2E
  api-reference.md          # MODIFY: добавить /v1/alerts, pagination, admin
```

### devcontainer.json обновления

```json
{
  "postStartCommand": "pip install -e sdk/ && cd sdk-ts && npm install && cd .. && python scripts/seed_demo_data.py",
  "features": {
    "ghcr.io/devcontainers/features/docker-in-docker:2": {},
    "ghcr.io/devcontainers/features/kubectl-helm-minikube:1": {}
  },
  "forwardPorts": [8000, 3000, 16686, 8474],
  "portsAttributes": {
    "8000": { "label": "AgentFlow API" },
    "3000": { "label": "Grafana" },
    "16686": { "label": "Jaeger UI" },
    "8474": { "label": "Toxiproxy API" }
  }
}
```

### docs/runbook.md структура

```markdown
# AgentFlow Runbook

## Incident Response

### API не отвечает
1. Проверь `GET /v1/health`
2. Проверь логи: `docker compose logs api --tail 50`
3. Проверь Jaeger: нет ли hanging traces
4. Рестарт: `docker compose restart api`

### Pipeline лаг > 60 секунд
...

### Dead letter queue растёт
...

### Alert storm (много алертов)
...

## Disaster Recovery
[ссылка на docs/dr.md]

## Key Contacts
...
```

**Критерии приёмки:**
- [ ] DevContainer открывается без ошибок, `pytest tests/ -q` зелёный сразу после старта
- [ ] `docs/architecture.md` описывает компоненты v1-v6 (outbox, Redis RL, TS SDK, chaos, K8s)
- [ ] `docs/runbook.md` покрывает 5+ инцидентных сценариев с пошаговыми инструкциями
- [ ] `docs/api-reference.md` — все endpoints включая v5-v6 additions
- [ ] Нет устаревших ссылок и команд (проверяется скриптом `scripts/check_docs_links.py`)

---

## Итоговый порядок выполнения

```
 1. TASK 1  E2E smoke tests in CI           ← фундамент для hardening
 2. TASK 2  Distributed tracing E2E         ← observability фундамент
 3. TASK 3  Structured logging correlation  ← параллельно с Task 2
 4. TASK 4  Chaos engineering (Toxiproxy)   ← после Task 1
 5. TASK 5  K8s staging (kind + Helm)       ← после Task 4
 6. TASK 6  Secrets rotation               ← после Task 1
 7. TASK 7  Alert noise reduction          ← после Task 2+3
 8. TASK 8  agentflow init wizard          ← независим, DX
 9. TASK 9  Real-world agent examples      ← после Task 8
10. TASK 10 DevContainer + docs overhaul   ← последним
```

**Параллельные группы:**
- Группа A (Tasks 2, 3): observability — параллельно после Task 1
- Группа B (Tasks 4, 6): hardening — параллельно после Task 1
- Группа C (Tasks 8): DX — независим, любое время

**После v6:**
- E2E тесты в CI на каждый push в main
- Полные traces: HTTP → Kafka → DuckDB → ответ (в Jaeger)
- Chaos engineering: 8 сценариев зелёные
- K8s staging: `bash k8s_staging_up.sh` → готов за 3 минуты
- `agentflow init` → рабочий агент за 5 минут
- 3 real-world примера (support / ops / merch)
- Нулевой даунтайм при ротации API ключей
