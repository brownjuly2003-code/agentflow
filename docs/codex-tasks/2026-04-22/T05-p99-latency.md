# T05 — P99 entity latency optimization

**Priority:** P2 · **Estimate:** 1-2 дня

## Goal

Снизить p99 `/v1/entity/{type}/{id}` с 290-320мс до **<200мс** (цель в SLO).

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- Endpoint: `src/serving/api/routers/entity.py` (или аналогичный — `grep -rn "entity" src/serving/api/routers/`)
- Зависит от: DuckDB query, sqlglot AST validation, JSON serialization, middleware stack
- Load-test harness: `tests/load/` (локально локаль locust или k6 — проверить)
- Lab baseline был 170мс, production p99 деградировал до 290-320мс — где-то накопилась overhead

## Deliverables

Строить как серию отдельных коммитов, каждая гипотеза — отдельный коммит. Если гипотеза даёт <5% — не мержить, искать другую.

### Step 1 — Профайлинг (commit: `chore: profile entity endpoint hot path`)

- `scripts/profile_entity.py`:
  - Запуск py-spy или cProfile во время load test (50 RPS × 60s против local demo)
  - Dump top-20 функций по cumulative time
  - Flamegraph → `docs/perf/flamegraph-before.svg`
- `docs/perf/entity-profile-before.md`:
  - Top-20 таблица
  - Гипотезы оптимизации (кэш sqlglot, pool DuckDB, orjson, etc.)
  - Baseline метрики: p50/p95/p99/throughput с точностью до ms

### Step 2 — Оптимизации (отдельные коммиты)

Проверить гипотезы в порядке ожидаемого эффекта. Каждая — отдельный PR-chunk (один commit):

1. `perf: cache sqlglot parsed query templates via LRU` —
   - `functools.lru_cache(maxsize=256)` на функцию парсинга
   - Ключ — canonical query template, не конкретные values
   - Verify: profiling до/после, p99 падает на X мс

2. `perf: reuse DuckDB connection pool in FastAPI app state` —
   - Если сейчас connection создаётся per-request — перевести на pool
   - `app.state.duckdb_pool` инициализируется на startup, инжектится через `Depends`
   - Verify: количество open file descriptors не растёт линейно с RPS

3. `perf: switch to orjson for response serialization` —
   - `orjson` добавить в `[project.dependencies]` в `pyproject.toml`
   - Заменить default JSON encoder в FastAPI на `ORJSONResponse`
   - Benchmark: один endpoint, микробенчмарк — orjson vs stdlib

4. _(опционально)_ `perf: eliminate pydantic round-trip in hot path` — если pydantic serialization занимает >5%, рассмотреть `model_dump_json()` или direct dict

### Step 3 — Верификация (commit: `perf: verify p99 entity latency under target`)

- `docs/perf/entity-profile-after.md`:
  - Тот же профиль после всех оптимизаций
  - Сравнение before/after (таблица: метрика → before → after → delta %)
  - Flamegraph `docs/perf/flamegraph-after.svg`
- Обновить baseline в `perf-regression.yml` если применимо — но **не ослабить gate** (20% max-regress остаётся)

## Acceptance

- `make load-test` (или `pytest tests/load/test_entity.py --benchmark`) — **p99 <200мс** на том же железе что до изменений
- `make test` зелёный (ничего не сломалось)
- `perf-regression.yml` в CI проходит с новыми значениями
- Before/after документы в `docs/perf/` присутствуют и цитируемые

## Notes

- НЕ трогать sqlglot AST validation logic (только кэшировать парсинг) — это security gate против SQL injection
- `orjson` — в `[project.dependencies]`, НЕ в dev
- Если какая-то гипотеза даёт <5% выигрыш — дропнуть commit, не мержить, искать другую
- Если после всех оптимизаций p99 >200мс — документировать причину (bottleneck на уровне DuckDB или сети) и предложить следующий шаг (index, read replica, materialized view) отдельным issue, НЕ мержить slow change
