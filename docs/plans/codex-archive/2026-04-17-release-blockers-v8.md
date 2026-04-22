# AgentFlow — Release Blockers v8
**Date**: 2026-04-17
**Цель**: закрыть Phase 0 блокеры релиза из BCG аудита (2026-04-12)
**Executor**: Codex
**Reference**: `BCG_audit.md` §7 "Сводная матрица рисков", §8 "Phase 0"

## Откуда задачи

**BCG аудит, Phase 0 — блокеры релиза:**
- p50 = 26 000 мс при цели < 100 мс (отклонение 216 000%) — `docs/benchmark.md`
- SQL injection risk через `_scope_sql` regex + `_quote_literal` string interpolation в `query_engine.py`
- God-class файлы: `auth.py` (861), `alert_dispatcher.py` (738), `query_engine.py` (634)

**Root cause performance (подтверждённый чтением кода):**
- `query_engine.get_entity/get_metric` — sync, используют `self._backend.execute(sql)` без connection pool на hot path
- Роутер `src/serving/api/routers/agent_query.py:271-285` вызывает их из `async def` БЕЗ `run_in_threadpool` — блокирует event loop
- Для сравнения: `routers/batch.py` корректно использует `await run_in_threadpool(...)` для всех DB вызовов

**Root cause SQL injection:**
- `query_engine.py:135-151` — `_scope_sql` использует regex для переписывания `FROM`/`JOIN`, ломается на подзапросах, CTE, комментариях
- `query_engine.py:419-422` — `get_entity` конкатенирует `entity_id` через `_quote_literal` вместо parameterized query
- `get_metric:587+` — аналогично
- NL→SQL output (`execute_nl_query:303`) не валидируется SQL-парсером перед выполнением

---

## Граф зависимостей

```
TASK 1  Async offload для hot-path endpoints       ← независим, самый быстрый win
TASK 2  Parameterized queries в query_engine       ← независим
TASK 3  Query cache для entity lookups             ← после Task 1
TASK 4  SQL validator через sqlglot для NL→SQL     ← после Task 2
TASK 5  _scope_sql замена regex на sqlglot AST     ← после Task 4
TASK 6  Разбить auth.py на 3 модуля                ← независим
TASK 7  Разбить alert_dispatcher.py на 3 модуля    ← независим
TASK 8  Разбить query_engine.py на 3 модуля        ← после Task 2+5
TASK 9  Benchmark regression: p50 < 100ms gate     ← после Task 1+3
TASK 10 Verification: full test suite + load test  ← последним
```

---

## TASK 1 — Async offload для hot-path endpoints

**Первой** — самый быстрый выигрыш производительности (блокировка event loop вероятно даёт основную долю из 26с).

**Что построить:**

```
src/serving/api/routers/
  agent_query.py        # MODIFY: обернуть engine.get_entity/get_metric в run_in_threadpool
tests/unit/
  test_agent_query_async.py  # NEW: тест что endpoint не блокирует event loop
```

### Изменения в `src/serving/api/routers/agent_query.py`

**Файл-строки:** `get_entity` в районе 271-285, аналогично для metrics endpoint.

**Паттерн:** тот же что в `routers/batch.py:88`:

```python
from starlette.concurrency import run_in_threadpool

# БЫЛО (block event loop):
result = engine.get_entity(entity_type, entity_id, tenant_id=tenant_id)

# СТАЛО:
result = await run_in_threadpool(
    engine.get_entity, entity_type, entity_id, tenant_id=tenant_id
)
```

Применить ко ВСЕМ sync вызовам `engine.*` в `agent_query.py`:
- `engine.get_entity` (271, 281, 285)
- `engine.get_entity_at` (274, 278)
- `engine.get_metric` (и все варианты)
- `engine.execute_nl_query`

### Тест `tests/unit/test_agent_query_async.py`

```python
import asyncio
import time
import pytest
from fastapi.testclient import TestClient

def test_entity_endpoint_does_not_block_event_loop(app_with_slow_backend):
    """Параллельные запросы должны выполняться конкурентно, не последовательно."""
    # backend fixture с искусственным sleep 0.5s в execute
    client = TestClient(app_with_slow_backend)

    start = time.perf_counter()
    # 4 параллельных запроса, каждый backend-sleep=500ms
    # sync: ~2.0s, async threadpool: ~0.5-0.7s
    results = asyncio.run(_parallel_requests(client, n=4))
    elapsed = time.perf_counter() - start

    assert all(r.status_code == 200 for r in results)
    assert elapsed < 1.2, f"Event loop blocked: {elapsed:.2f}s (expected <1.2s)"
```

### Verify
```bash
pytest tests/unit/test_agent_query_async.py -v
# Ожидаемо: PASSED, elapsed < 1.2s
```

---

## TASK 2 — Parameterized queries в query_engine

**Независима от Task 1.** Убирает string interpolation в hot path — одновременно safety fix и perf win (DuckDB переиспользует prepared plan).

**Что построить:**

```
src/serving/semantic_layer/
  query_engine.py              # MODIFY: get_entity, get_metric, get_entity_at — через params
  backends/
    duckdb_backend.py          # MODIFY: execute(sql, params=None)
    base.py                    # MODIFY: protocol с params
tests/unit/
  test_query_engine_injection.py  # NEW: 8+ injection-атак
```

### Изменения в `backends/base.py`

```python
class QueryBackend(Protocol):
    def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> list[dict]: ...
```

### Изменения в `backends/duckdb_backend.py`

DuckDB нативно поддерживает `?` placeholders через `connection.execute(sql, params)`.

```python
def execute(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
    with self._pool.acquire() as conn:
        if params:
            cursor = conn.execute(sql, params)
        else:
            cursor = conn.execute(sql)
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
```

### Изменения в `query_engine.py:419-422` (`get_entity`)

```python
# БЫЛО:
sql = (
    f"SELECT * FROM {table_name} "
    f"WHERE {entity_def.primary_key} = {self._quote_literal(entity_id)} "
    "LIMIT 1"
)
result = self._backend.execute(sql)

# СТАЛО:
# table_name и primary_key — из catalog (доверенный источник), не user input
# entity_id — user input → через параметр
sql = (
    f"SELECT * FROM {table_name} "
    f"WHERE {self._quote_identifier(entity_def.primary_key)} = ? "
    "LIMIT 1"
)
result = self._backend.execute(sql, (entity_id,))
```

Аналогично для:
- `get_entity_at` (as_of как параметр)
- `get_metric` (name, window как параметры где применимо)
- любые другие методы использующие `_quote_literal`

**Оставить `_quote_literal` ТОЛЬКО** для cases где значение приходит из catalog/schema (не user input) — с комментарием почему.

### Тест `tests/unit/test_query_engine_injection.py`

```python
import pytest
from src.serving.semantic_layer.query_engine import QueryEngine

ATTACK_VECTORS = [
    "'; DROP TABLE orders; --",
    "' OR '1'='1",
    "'; DELETE FROM users WHERE '1'='1",
    "\\'; DROP TABLE orders; --",
    "ORD' UNION SELECT * FROM api_keys --",
    "'); ATTACH 'evil.db' AS evil; --",
    "ORD\x00'; DROP TABLE --",
    "ORD' AND (SELECT COUNT(*) FROM api_keys) > 0 --",
]

@pytest.mark.parametrize("payload", ATTACK_VECTORS)
def test_get_entity_rejects_injection(engine_with_seed_data, payload):
    """Attack payloads не должны выполнять побочные SQL операции."""
    result = engine_with_seed_data.get_entity("order", payload)
    assert result is None  # payload не найден как valid entity_id
    # И таблицы должны быть нетронуты:
    assert engine_with_seed_data.get_entity("order", "ORD-20260401-0001") is not None
```

### Verify
```bash
pytest tests/unit/test_query_engine_injection.py -v
bandit -r src/serving/semantic_layer/ --severity-level medium
# Ожидаемо: 8/8 PASSED, bandit B608 не должен триггериться
```

---

## TASK 3 — Query cache для entity lookups

**После Task 1.** Большинство entity lookups — горячие ключи. Redis cache уже существует (`src/serving/cache.py`), но используется только для metrics.

**Что построить:**

```
src/serving/api/routers/
  agent_query.py           # MODIFY: cache wrap вокруг get_entity
src/serving/
  cache.py                 # MODIFY: добавить entity namespace + TTL policy
tests/unit/
  test_entity_cache.py     # NEW: hit/miss/invalidation
```

### Политика кеширования

- **Key:** `entity:{tenant_id}:{entity_type}:{entity_id}`
- **TTL:** 5 секунд (baseline; < freshness SLA 30s)
- **Invalidation:** через `WebhookDispatcher` OR `OutboxProcessor` при write event → `DEL entity:*:{entity_type}:{entity_id}`
- **Negative cache:** не кешируем `None` (404) — опасно при eventual consistency
- **`as_of` запросы (historical):** не кешируем

### Изменения в `cache.py`

```python
ENTITY_TTL_SECONDS = 5

def cache_entity_key(tenant_id: str, entity_type: str, entity_id: str) -> str:
    tenant = tenant_id or "default"
    return f"entity:{tenant}:{entity_type}:{entity_id}"

async def invalidate_entity(
    cache: RedisCache, tenant_id: str, entity_type: str, entity_id: str
) -> None:
    key = cache_entity_key(tenant_id, entity_type, entity_id)
    await cache.delete(key)
```

### Изменения в `agent_query.py`

```python
if as_of is None:  # only cache live lookups
    cache_key = cache_entity_key(tenant_id, entity_type, entity_id)
    cached = await cache.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        result = cached
    else:
        result = await run_in_threadpool(
            engine.get_entity, entity_type, entity_id, tenant_id=tenant_id
        )
        if result is not None:
            await cache.set(cache_key, result, ttl=ENTITY_TTL_SECONDS)
        response.headers["X-Cache"] = "MISS"
```

### Изменения в outbox/webhook path

Где применяется write к entity — добавить `invalidate_entity(...)` после коммита.

### Verify
```bash
pytest tests/unit/test_entity_cache.py -v
# Ручной: запрос 1 → MISS, запрос 2 (в пределах 5s) → HIT
curl -D - http://localhost:8000/v1/entity/order/ORD-20260401-0001 | grep X-Cache
```

---

## TASK 4 — SQL validator через sqlglot для NL→SQL

**После Task 2.** NL→SQL output (`execute_nl_query`) может содержать враждебный SQL если NL parser compromised или prompt injection в user question.

**Что построить:**

```
src/serving/semantic_layer/
  sql_guard.py              # NEW: валидация через sqlglot AST
  query_engine.py           # MODIFY: execute_nl_query → через sql_guard
tests/unit/
  test_sql_guard.py         # NEW: allowed/denied SQL patterns
```

### `src/serving/semantic_layer/sql_guard.py`

```python
"""SQL safety validator for NL→SQL output.

Parses SQL with sqlglot, rejects anything except single-statement SELECT
reading from an allowlist of tables.
"""
import sqlglot
from sqlglot import exp

ALLOWED_STATEMENT_TYPES = {exp.Select, exp.With}
FORBIDDEN_NODE_TYPES = {
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.Truncate, exp.Command,
}


class UnsafeSQLError(ValueError):
    pass


def validate_nl_sql(sql: str, allowed_tables: set[str]) -> None:
    try:
        parsed = sqlglot.parse(sql, dialect="duckdb")
    except sqlglot.errors.ParseError as e:
        raise UnsafeSQLError(f"Unparseable SQL: {e}") from e

    if len(parsed) != 1:
        raise UnsafeSQLError(
            f"Expected single statement, got {len(parsed)}"
        )

    stmt = parsed[0]
    if type(stmt) not in ALLOWED_STATEMENT_TYPES:
        raise UnsafeSQLError(
            f"Statement type {type(stmt).__name__} not allowed"
        )

    for node in stmt.walk():
        if type(node) in FORBIDDEN_NODE_TYPES:
            raise UnsafeSQLError(
                f"Forbidden node: {type(node).__name__}"
            )

    # Table allowlist (включая tenant schema qualifiers)
    tables_used = {
        t.name for t in stmt.find_all(exp.Table)
    }
    unknown = tables_used - allowed_tables
    if unknown:
        raise UnsafeSQLError(f"Unknown tables: {unknown}")
```

### Интеграция в `query_engine.py:303` (`execute_nl_query`)

```python
from .sql_guard import validate_nl_sql, UnsafeSQLError

def execute_nl_query(self, question: str, tenant_id: str | None = None):
    sql = self._translate_question_to_sql(question)
    allowed = {entity.table for entity in self.catalog.entities.values()}
    allowed.add("pipeline_events")
    try:
        validate_nl_sql(sql, allowed)
    except UnsafeSQLError as e:
        raise ValueError(f"NL→SQL produced unsafe query: {e}") from e
    scoped_sql = self._scope_sql(sql, tenant_id)
    return self._backend.execute(scoped_sql)
```

### Тест `tests/unit/test_sql_guard.py`

```python
SAFE = [
    "SELECT * FROM orders",
    "SELECT COUNT(*) FROM orders WHERE status = 'delivered'",
    "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
]

UNSAFE = [
    ("DROP TABLE orders", "Forbidden"),
    ("INSERT INTO orders VALUES (1)", "Forbidden"),
    ("SELECT * FROM orders; DROP TABLE orders", "single statement"),
    ("SELECT * FROM pg_users", "Unknown tables"),
    ("UPDATE orders SET status = 'cancelled'", "Forbidden"),
    ("SELECT * FROM api_keys", "Unknown tables"),
    ("ATTACH 'evil.db' AS evil", "not allowed"),
]
```

### Verify
```bash
pytest tests/unit/test_sql_guard.py -v
# И property-based (Hypothesis): случайный SQL mutator → либо parse error, либо validator ловит
```

---

## TASK 5 — `_scope_sql` замена regex на sqlglot AST

**После Task 4** (reuse sqlglot infra). Текущий regex-based `_scope_sql` ломается на:
- CTE (`WITH x AS (SELECT FROM orders) ...`)
- Subqueries (`SELECT ... FROM (SELECT FROM orders) ...`)
- Comments (`-- FROM orders`)
- Multi-line queries с неожиданным whitespace

### Изменения в `query_engine.py:135-151`

```python
def _scope_sql(self, sql: str, tenant_id: str | None) -> str:
    known_tables = {entity.table for entity in self.catalog.entities.values()}
    known_tables.add("pipeline_events")

    schema = self._get_tenant_schema(tenant_id)
    if schema is None:
        return sql

    parsed = sqlglot.parse_one(sql, dialect="duckdb")
    for table in parsed.find_all(exp.Table):
        if table.name in known_tables and not table.db:
            table.set("db", exp.to_identifier(schema))
    return parsed.sql(dialect="duckdb")
```

### Тест (добавить в `test_query_engine.py`)

```python
def test_scope_sql_with_cte(engine):
    sql = "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent"
    scoped = engine._scope_sql(sql, tenant_id="tenant_a")
    assert '"tenant_a"."orders"' in scoped

def test_scope_sql_with_subquery(engine):
    sql = "SELECT * FROM (SELECT id FROM orders) x"
    scoped = engine._scope_sql(sql, tenant_id="tenant_a")
    assert '"tenant_a"."orders"' in scoped

def test_scope_sql_ignores_comment(engine):
    sql = "-- FROM evil_table\nSELECT * FROM orders"
    scoped = engine._scope_sql(sql, tenant_id="tenant_a")
    assert "evil_table" not in scoped
    assert '"tenant_a"."orders"' in scoped
```

### Verify
```bash
pytest tests/unit/test_query_engine.py::test_scope_sql -v
```

---

## TASK 6 — Разбить `auth.py` (861 LOC) на 3 модуля

**Независима.** Чистый structural refactor.

**Разделение по ответственностям:**

```
src/serving/api/auth/
  __init__.py               # re-export public API (backwards compat)
  manager.py                # AuthManager: load keys, verify, rate-check
  middleware.py             # AuthMiddleware: FastAPI middleware class
  key_rotation.py           # KeyRotator: rotation, expiry, audit
```

### Шаги

1. Создать директорию `src/serving/api/auth/`, переместить старый `auth.py` → `auth_legacy.py` временно
2. Выделить class `AuthManager` → `manager.py`
3. Выделить middleware class + dependency functions → `middleware.py`
4. Выделить rotation/key lifecycle → `key_rotation.py`
5. В `__init__.py` — re-export всех symbols что были в старом `auth.py`:
   ```python
   from .manager import AuthManager, verify_api_key
   from .middleware import AuthMiddleware, require_auth
   from .key_rotation import KeyRotator, rotate_all_keys
   __all__ = [...]
   ```
6. Удалить `auth_legacy.py`

### Verify
```bash
# Все imports старого вида должны работать:
python -c "from src.serving.api.auth import AuthManager, AuthMiddleware, verify_api_key"
pytest tests/unit/ tests/integration/ -k "auth" -v
# Все test_auth_* должны pass без изменений
wc -l src/serving/api/auth/*.py   # каждый файл < 350 LOC
```

---

## TASK 7 — Разбить `alert_dispatcher.py` (738 LOC)

**Независима.** По ответственностям:

```
src/serving/api/alerts/
  __init__.py               # re-export
  dispatcher.py             # AlertDispatcher: main loop, routing
  evaluator.py              # rule evaluation (threshold, anomaly)
  escalation.py             # escalation ladder, notification
  history.py                # persistence, deduplication
```

### Verify
```bash
pytest tests/ -k "alert" -v
wc -l src/serving/api/alerts/*.py   # каждый < 300 LOC
```

---

## TASK 8 — Разбить `query_engine.py` (634 LOC)

**После Task 2+5** (чтобы sqlglot refactor уже применился).

```
src/serving/semantic_layer/query/
  __init__.py               # re-export QueryEngine
  engine.py                 # QueryEngine orchestrator (< 200 LOC)
  sql_builder.py            # _scope_sql, _qualify_table, _quote_*
  entity_queries.py         # get_entity, get_entity_at
  metric_queries.py         # get_metric
  nl_queries.py             # execute_nl_query, _translate_*
  sql_guard.py              # (из Task 4)
```

### Verify
```bash
python -c "from src.serving.semantic_layer.query_engine import QueryEngine"  # backcompat
pytest tests/ -k "query_engine or semantic" -v
wc -l src/serving/semantic_layer/query/*.py
```

---

## TASK 9 — Benchmark regression: p50 < 100ms CI gate

**После Task 1+3.** Убедиться что изменения действительно решают performance problem.

### Настройки

- **Gate:** `docs/benchmark-baseline.json` обновить: `p50_ms: 100, p99_ms: 500`
- **Workflow:** `.github/workflows/perf-regression.yml` — падать если p50 > 100 ИЛИ регресс > 20% от baseline
- **Local run:** `make bench` → локально воспроизводит seed + 60s load

### Команда проверки

```bash
python scripts/run_benchmark.py --host http://127.0.0.1:8000
python scripts/check_performance.py  # exit 1 если gate fail
```

### Verify
```bash
make demo &
sleep 10
python scripts/run_benchmark.py
# Ожидаемо: p50 < 100ms для /v1/entity/*
cat docs/benchmark.md | grep -A5 "Results"
```

---

## TASK 10 — Full verification

**Последним.** Проверка что ничего не сломалось, всё что заявлено работает.

### Команды

```bash
# 1. Unit + integration + property + contract
pytest tests/ -v --cov=src --cov-report=term-missing
# Coverage >= 80%, все prev-passing тесты всё ещё pass

# 2. Security
bandit -r src/ sdk/ --severity-level medium
safety check -r requirements.txt

# 3. Mutation testing (smoke)
mutmut run --paths-to-mutate src/serving/semantic_layer/query/
mutmut results

# 4. Load test
make demo &
sleep 10
python scripts/run_benchmark.py
python scripts/check_performance.py

# 5. Чётко подтвердить:
wc -l src/serving/api/auth.py 2>/dev/null && echo "FAIL: old auth.py still exists"
wc -l src/serving/api/alert_dispatcher.py 2>/dev/null && echo "FAIL"
test -d src/serving/api/auth/ || echo "FAIL: auth/ dir missing"
test -d src/serving/api/alerts/ || echo "FAIL: alerts/ dir missing"
test -d src/serving/semantic_layer/query/ || echo "FAIL: query/ dir missing"
test -f src/serving/semantic_layer/query/sql_guard.py || echo "FAIL: sql_guard missing"
```

### Done When

- [ ] Все 379+ существующих тестов проходят
- [ ] Добавлены 40+ новых тестов (injection + async + sql_guard + scope_sql edge cases)
- [ ] `p50 < 100ms` в benchmark.md для всех /v1/entity/* endpoints
- [ ] Ни один Python-файл в `src/serving/` не превышает 400 LOC
- [ ] `bandit -r src/` не выдаёт medium/high issues
- [ ] Обновлён `BCG_audit.md` — проставить ✅ у Phase 0 чекбоксов
- [ ] Обновлён `docs/plans/2026-04-17-release-blockers-v8.md` — все TASK помечены `[x]`

---

## Notes для Codex

1. **Порядок критичен** — граф зависимостей наверху не просто документация; Task 3 не сработает без Task 1 (sync call всё равно блокирует), Task 5 не соберётся без Task 4 (общий `sqlglot` import).
2. **Не делай параллельно** — Codex получает задачи последовательно, каждая → свой PR / commit.
3. **Backwards compatibility обязательна** — все существующие import paths (`from src.serving.api.auth import ...`) должны продолжать работать через re-export в `__init__.py`.
4. **Перед каждым TASK** — `git status` clean, либо commit предыдущей работы.
5. **После каждого TASK** — запускать соответствующий `Verify`-блок И `pytest tests/` (regression check).
6. **Не трогать** в этом раунде: Flink jobs, ClickHouse migration, admin UI, landing page — это Phase 1-3 из BCG audit §8.
