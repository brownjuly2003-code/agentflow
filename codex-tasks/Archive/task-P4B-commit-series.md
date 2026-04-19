# Task P4B — Логические коммиты Phase 4 работы

## Context
После P4A `.gitignore` расширен, мусор удалён. Осталось ~130-150
реальных файлов: новая работа (~120 untracked) + правки (~24 M).

Цель: разбить на **6-8 семантических коммитов по слоям архитектуры**,
чтобы история читалась. Каждый коммит — после `pytest` + `ruff` для
затронутых модулей.

## Стратегия разбиения
Порядок важен: сначала **инфраструктура и контракты**, потом **фичи**,
потом **тесты/доки**. Так пайплайн не ломается на промежуточных коммитах.

```
1. CI & ops:        .github/workflows/, deploy/, k8s/, infrastructure/,
                    Dockerfile.api, docker-compose.*.yml, scripts/,
                    monitoring/ (новые dashboards)
2. API core:        src/serving/api/{auth/, middleware/, alerts/,
                    security.py, rate_limiter.py, masking.py, versioning.py,
                    telemetry.py, analytics.py, webhook_dispatcher.py,
                    templates/}
3. API routers:     src/serving/api/routers/{admin, admin_ui, alerts, batch,
                    contracts, deadletter, lineage, search, slo, stream,
                    webhooks}.py
4. Serving layer:   src/serving/backends/, cache.py, db_pool.py,
                    semantic_layer/{contract_registry, schema_evolution,
                    search_index, sql_guard, query/}
5. Modified M:      24 M файлов (src/ + monitoring/ + Makefile +
                    pyproject.toml + docker-compose.yml + README.md +
                    docs/* и т.д.) — один коммит "enhance core pipeline"
6. SDKs:            sdk/, sdk-ts/
7. Tests:           tests/ (новые + property/ + chaos/ + e2e/ + sdk/ +
                    contract/ + integration/ + unit/)
8. Docs:            docs/* (новые .md)
```

## Preconditions
- P4A завершён, `.gitignore` закоммичен
- `git status --short` — ожидание ~130-150 файлов
- Рабочий pytest baseline: `pytest tests/unit/test_event_schemas.py
  tests/unit/test_query_engine_injection.py tests/unit/test_sql_guard.py
  tests/unit/test_masking.py tests/unit/test_security.py
  tests/integration/test_rotation.py tests/integration/test_batch.py -q`
  → 79 passed

## Правила staging для каждого коммита
- Использовать **только поштучный `git add <path>`** или `git add <dir>/`
  с явным путём
- **НИКОГДА** `git add .` / `-A` без явного path (в P4B, не в P4A)
- Перед каждым commit — `git status --short | head -20` для ревью

---

## Commit 1 — CI, deploy, ops

**Files:**
```bash
git add .github/workflows/
git add deploy/
git add k8s/ 2>/dev/null || true
git add infrastructure/
git add Dockerfile.api
git add docker-compose.chaos.yml docker-compose.flink.yml \
        docker-compose.iceberg.yml docker-compose.prod.yml
git add scripts/
git add monitoring/
git add .bandit
```

**Sanity:** `yamllint .github/workflows/*.yml` если установлен, иначе
парсить через `python -c "import yaml, glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]"`

```bash
git commit -m "Add Phase 4 infrastructure: CI workflows, deploy configs, k8s, monitoring"
```

---

## Commit 2 — API core (auth, middleware, security utilities)

**Files:**
```bash
git add src/serving/api/auth/
git add src/serving/api/middleware/
git add src/serving/api/alerts/
git add src/serving/api/security.py
git add src/serving/api/rate_limiter.py
git add src/serving/api/analytics.py
git add src/serving/api/telemetry.py
git add src/serving/api/versioning.py
git add src/serving/api/webhook_dispatcher.py
git add src/serving/api/templates/ 2>/dev/null || true
```

**Sanity:** `python -c "from src.serving.api import security, rate_limiter, telemetry, versioning, webhook_dispatcher"`

```bash
git commit -m "Add API core: auth, middleware, rate limiter, webhooks"
```

---

## Commit 3 — API routers

**Files:**
```bash
git add src/serving/api/routers/admin.py \
        src/serving/api/routers/admin_ui.py \
        src/serving/api/routers/alerts.py \
        src/serving/api/routers/batch.py \
        src/serving/api/routers/contracts.py \
        src/serving/api/routers/deadletter.py \
        src/serving/api/routers/lineage.py \
        src/serving/api/routers/search.py \
        src/serving/api/routers/slo.py \
        src/serving/api/routers/stream.py \
        src/serving/api/routers/webhooks.py
```

**Sanity:** `python -c "from src.serving.api.routers import admin, alerts, batch, contracts, deadletter, lineage, search, slo, stream, webhooks; print('all imported')"`

```bash
git commit -m "Add API routers: admin/alerts/batch/contracts/deadletter/lineage/search/slo/stream/webhooks"
```

---

## Commit 4 — Serving layer backends + semantic

**Files:**
```bash
git add src/serving/backends/
git add src/serving/cache.py
git add src/serving/db_pool.py
git add src/serving/masking.py
git add src/serving/semantic_layer/contract_registry.py \
        src/serving/semantic_layer/schema_evolution.py \
        src/serving/semantic_layer/search_index.py \
        src/serving/semantic_layer/sql_guard.py \
        src/serving/semantic_layer/query/
```

**Sanity:** full app import:
```bash
python -c "from src.serving.api.main import app; print(len([r for r in app.routes]))"
# Должен показать все зарегистрированные routes без ImportError
```

```bash
git commit -m "Add serving backends, cache pool, masking, semantic layer guards"
```

---

## Commit 5 — Enhance existing core (24 M files)

**Files:** все modified:
```bash
git add -u  # -u стейджит только tracked M/D, не untracked (безопасно)
```

**Sanity:** запустить baseline suite:
```bash
pytest tests/unit/test_event_schemas.py tests/unit/test_query_engine_injection.py \
       tests/unit/test_sql_guard.py tests/unit/test_masking.py \
       tests/unit/test_security.py tests/integration/test_rotation.py \
       tests/integration/test_batch.py -q
# → 79 passed (минимум)
```

```bash
git commit -m "Enhance core pipeline: semantic engine, Flink jobs, quality monitors, docs"
```

---

## Commit 6 — SDKs

```bash
git add sdk/
git add sdk-ts/
```

```bash
git commit -m "Add Python + TypeScript SDKs"
```

---

## Commit 7 — Tests

```bash
git add tests/chaos/ tests/contract/ tests/e2e/ tests/property/ tests/sdk/ \
        tests/client.test.ts tests/test_examples.py \
        tests/integration/ tests/unit/ tests/load/
```

**Sanity (selective — полный прогон может быть долгим):**
```bash
pytest tests/unit/ -q --ignore=tests/unit/test_llamaindex_reader.py 2>&1 | tail -5
# Хотя бы unit тесты должны пройти целиком
```

Если какие-то тесты падают на уровне import'а — **СТОП**, разбираться
отдельно; это значит commits 2-4 что-то не докинули.

```bash
git commit -m "Add test coverage: chaos, contract, e2e, property, integration, unit, SDK"
```

---

## Commit 8 — Docs

```bash
git add docs/ config/ warehouse/ notebooks/ \
        requirements.txt
# Проверить: res_co.md / rep.md / codex_res.md НЕ попадают — они удалены в P4A
```

```bash
git commit -m "Add Phase 4 documentation: competitive analysis, security audit, API reference, benchmarks"
```

---

## Post-commits verification

```bash
git status
# Должно быть: working tree clean (или только файлы, явно не вошедшие
# в план — тогда ревью их вручную)

git log --oneline -10
# Должно показать 8 новых коммитов + P4A + предыдущие

pytest tests/unit/test_event_schemas.py tests/unit/test_query_engine_injection.py \
       tests/unit/test_sql_guard.py tests/unit/test_masking.py \
       tests/unit/test_security.py tests/integration/test_rotation.py \
       tests/integration/test_batch.py -q
# → 79 passed

ruff check . 2>&1 | tail -3
# Желательно: 0 errors. Если много — отдельная задача.
```

## CONSTRAINTS
- Каждый commit: **явные пути** в `git add`, никаких `-A` / `.`
- После каждого commit — `git status` ревью (просто посмотреть что
  осталось, не коммитить дубли)
- Если между коммитами что-то забыли — делать **новый** commit, не amend
- Никаких `--no-verify`, `push`, `reset --hard`

## DONE WHEN
- [ ] 8 коммитов с понятными сообщениями, в порядке выше
- [ ] `git status` → clean (или явно остаточные файлы с пометкой)
- [ ] 79-тестовая baseline suite проходит
- [ ] `git log --oneline -12` читается как связная история Phase 4

## STOP conditions
- Любой commit — ImportError при sanity check → откатить, разобрать
  зависимость; скорее всего пропущен файл из предыдущего коммита
- pytest в commit 5 ломается → откатить commit 5, diff'ать с предыдущим
  состоянием, фикс отдельным commit'ом
- Неожиданные untracked после всех 8 коммитов → ревью вручную, НЕ
  коммитить bulk'ом
