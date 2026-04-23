# T_AUDIT — Полный аудит проекта после спринта CI repair

> **РАЗБИТО НА 10 ПОДТАСКОВ.** См. `audit/README.md` и `audit/TA01..TA10`. Этот файл — зонтичный context. Не выполнять как один таск; запускать TA01 первым (quick fix), TA02..TA09 параллельно, TA10 последним (consolidation).

**Priority:** P0 · **Estimate:** 4-6ч (sequential) или ~2ч calendar time с параллелизацией

## Goal

После закрытия спринта CI repair (коммиты `20a5620..739ceb4` запушены в `origin/main` 2026-04-23) выполнить полный аудит состояния проекта: catalog'нуть **что зелёное / что красное / что не проверено / что протухло**, найти missed-fixes (вроде того что `test-integration` job всё ещё ставит `[dev]` без `cloud` и падает на `pyiceberg`), проверить отсутствие регрессий после T00 hardening (ruff format ~75 файлов + targeted src/ fixes + mypy override), и зафиксировать остаточный технический долг как actionable follow-up тикеты в `docs/codex-tasks/2026-04-24/`.

## Context

- Репо: `D:\DE_project\` — AgentFlow, Python 3.11 / FastAPI / Kafka KRaft / Flink 1.19 / Iceberg+DuckDB / Dagster / Helm / OpenTelemetry
- HEAD `739ceb4` на `origin/main`, tree clean
- Прошлый спринт (2026-04-22) v1.1 закрыл 9/10 codex tasks + 6 CI infra fixes (см. `~/.claude/projects/D--/memory/project_de_project.md` если есть доступ к памяти Claude, либо `git log --oneline -30`)
- Спринт CI repair (2026-04-23) — `docs/codex-tasks/2026-04-23/T00..T05` плюс T_AUDIT (этот таск). Follow-ups в `docs/codex-tasks/2026-04-24/T06..T09` уже есть (performance baselines, mutation, publish, terraform-apply OIDC).
- Локально (на момент написания ТЗ): `ruff check src/ tests/`, `ruff format --check`, `mypy src/` — все три зелёные.
- CI на push `739ceb4` (run-ы триггернуты автоматически):
  - ✅ Contract Tests (24815235708)
  - ✅ Security Scan (24815235700)
  - ✅ DORA Metrics (24814675744 — manual prior)
  - ❌ CI (24815235697) — внутри: lint ✅, schema-check ✅, terraform-validate ✅, test-unit ❌, test-integration ❌
  - ❌ Load Test (24815235691)
  - ❌ Staging Deploy (24815235706)
  - ❌ E2E Tests (24815235690)
- **Уже опознанная регрессия**: test-integration job в `.github/workflows/ci.yml` ставит `pip install -e ".[dev]"` без `cloud` extra, поэтому `tests/integration/test_*.py` валятся на `ModuleNotFoundError: pyiceberg` на коллекции. Эта проблема была закрыта только для test-unit + chaos + perf + perf-regression в коммите `ecc137c`. Test-integration пропущен. **Этот fix — первый deliverable аудита**, а не отдельный таск.

## Deliverables

Финальный отчёт сохранить в `docs/codex-tasks/2026-04-23/T_AUDIT-result.md` со следующей структурой. Каждая секция — таблица или структурированный список. **Без воды**, только actionable findings.

### 1. CI workflow matrix

Таблица **всех 15 workflows** в `.github/workflows/`:

| Workflow | Last run on main | Conclusion | Root cause (если red) | Action |
|----------|------------------|------------|----------------------|--------|

Для red — root cause разобрать конкретно (не «упал», а «упал на ModuleNotFoundError X в строке Y потому что Z»). Action — один из:
- `quick fix in this PR` — починить тут же, отдельным коммитом
- `existing ticket TXX` — указать какой
- `new ticket needed` — создать в `docs/codex-tasks/2026-04-24/T<NN>-<name>.md`
- `acceptable until <event>` — обоснование почему сейчас можно red

**Quick fix #1 (обязательный):** добавить `,cloud` в test-integration `pip install` в `.github/workflows/ci.yml` (строка ~80, где `pip install -e ".[dev]"` для test-integration job). Один коммит `ci(test-integration): install cloud extras for pyiceberg-using src modules`.

### 2. Test pass/fail catalog

Локально с чистым venv (`python3.11 -m venv .venv-audit && source .venv-audit/bin/activate && pip install -e ".[dev,integrations,cloud,load]" && pip install -e "./integrations[mcp]"`):

```bash
python -m pytest tests/unit/ tests/property/ tests/contract/ tests/sdk/ -q --tb=line
python -m pytest tests/e2e/ -q --tb=line  # с SKIP_DOCKER_TESTS=1 если нет docker
python -m pytest tests/integration/ -q --tb=line  # требует Kafka/Redis services
```

Заполнить таблицу:

| Suite | Total | Passed | Failed | Skipped | Notes |
|-------|-------|--------|--------|---------|-------|

Для каждого failed test — одна строка с file:line + 1-фразой root cause. Если test fails без actionable root cause за 30 минут — занести в `docs/codex-tasks/2026-04-24/` с TZ.

### 3. T00 hardening review (regression check)

Просмотреть **функциональные** изменения коммита `0dde32a` (без ruff format whitespace):

```bash
git show 0dde32a -- src/serving/api/auth/__init__.py src/serving/api/routers/admin.py src/serving/api/auth/key_rotation.py src/serving/api/routers/admin_ui.py src/serving/api/rate_limiter.py src/serving/cache.py src/serving/backends/clickhouse_backend.py src/serving/semantic_layer/query/sql_builder.py src/logger.py
```

Для каждого изменения — galочка:
- **Logger move в auth/__init__.py**: `logger = structlog.get_logger()` теперь после import-ов (раньше до). Проверить что `auth_package.logger.warning(...)` в `src/serving/api/auth/{manager,middleware,key_rotation}.py` всё ещё работает на runtime (не только при import). Если падает — restore с E402 noqa.
- **B904 `raise ... from None` в admin.py**: проверить что 404 ответы для отсутствующих ключей не теряют traceback в логах (структурированные логи должны иметь exception context).
- **C416 `dict(rows)` в key_rotation.py**: проверить тип `rows` (`list[tuple[str, int]]` ожидается) — если sqlite/duckdb возвращает `list[Row]` где `Row` не tuple-compatible, тест rotation сломается.
- **`fetchone()[0] if row else 0` в admin_ui.py**: edge case когда таблица пустая → `_qps_last_minute` возвращает 0.0 (раньше падал с TypeError). Проверить что ничего downstream не ожидает None для empty case.
- **Optional redis import с `# type: ignore`**: проверить что без redis в venv (`pip uninstall redis`) импорт не валится и `RateLimiter` / `QueryCache` корректно fallback-ят на in-memory.
- **clickhouse_backend casted return**: тривиально, но проверить что test_clickhouse_backend.py покрывает оба пути (success + error).
- **mypy override `disable_error_code = ["attr-defined"]` для semantic_layer.query**: проверить что override не маскирует реальные баги в этих 4 mixin файлах. Bonus: запустить `mypy src/serving/semantic_layer/query/ --disable-error-code attr-defined --disable-error-code other` чтобы увидеть нет ли других error-кодов которые скрылись.

Список найденных issue + recommended action.

### 4. Dependency / extras matrix

Таблица: какой job в `.github/workflows/*.yml` ставит какие extras, какие src-модули они импортируют через тесты, и нужны ли все extras.

| Job | Workflow | pip install | Imports needed (transitive) | Gap |
|-----|----------|-------------|-----------------------------|-----|

Для каждого Gap (jоб ставит меньше чем нужно или больше) — одна строка action: `add ,X` или `drop ,Y` или `OK`.

Особое внимание:
- `test-integration` (нужен `,cloud` — quick fix #1)
- `chaos`, `performance`, `perf-regression` — уже исправлены в `ecc137c`, проверить что ничего больше не нужно
- `staging-deploy` — что устанавливает, нужен ли pyiceberg для E2E запускаемых после deploy

### 5. Stale code scan

Найти dead code:

```bash
# Unused .py files (нет импортов)
python -c "import ast, pathlib; ..."  # или vulture / unimport

# Orphan test files (тестируют удалённые модули)
grep -rL "^from\|^import" tests/  # тесты без импортов из src

# .gitignored runtime artifacts которые попали в дерево
git ls-files | grep -E "\.(duckdb|wal|tmp|cache)$"
```

Также проверить `docs/plans/`, `docs/codex-tasks/2026-04-22/` и `2026-04-23/` — нет ли markdown-ов которые ссылаются на closed work (можно архивировать в `docs/plans/archive/` если ≥30 дней).

Список + предложение (delete / archive / keep).

### 6. Documentation alignment

Проверить что в синке:
- `README.md` — отражает current state (v1.0.1, 30+ commits, CI status)
- `CHANGELOG.md` — `[Unreleased]` секция содержит CI repair sprint changes (T00-T05). Если нет — добавить.
- `docs/codex-tasks/2026-04-23/README.md` — порядок T00-T05 + T_AUDIT, статус «closed»/«in_progress»/«open»
- `docs/codex-tasks/2026-04-24/README.md` — если ещё нет, создать индекс T06-T09
- Архитектурные docs (`docs/architecture/`, `docs/deployment/`, `docs/runbook.md` если есть) — нет ли упоминания `docker-compose.prod.yml` для E2E (теперь `docker-compose.e2e.yml`)

Список расхождений + один doc-PR fix-ит все сразу.

### 7. Security posture

```bash
# Trivy на текущем prod image — список actionable HIGH/CRITICAL после T04 setuptools+wheel pin
docker compose -f docker-compose.prod.yml build agentflow-api
trivy image --severity HIGH,CRITICAL --ignore-unfixed agentflow_de_project-agentflow-api:latest

# Bandit / Safety — current findings vs baseline
bandit -r src sdk --ini .bandit --severity-level medium -f json -o /tmp/bandit-now.json
python scripts/bandit_diff.py .bandit-baseline.json /tmp/bandit-now.json

# .trivyignore audit (если он появился) — каждая запись имеет обоснование?
test -f .trivyignore && cat .trivyignore
```

Найти:
- HIGH/CRITICAL CVE с available fix → action `bump <pkg> to <ver>` коммитом
- HIGH/CRITICAL без fix → `.trivyignore` запись с обоснованием + target date
- Bandit findings новые с baseline → review case-by-case

### 8. Architectural debt inventory

Зафиксировать known issues которые стоят в очереди отдельным таском (НЕ чинить тут, только catalog):

- **`agentflow` SDK name collision**: root `pyproject.toml` и `sdk/pyproject.toml` оба `name = "agentflow" version = "1.0.1"`. Ломает `pip install -e .` после `pip install -e sdk/`. Workaround — `sys.path.insert` в тестах. Real fix — переименовать (issue: PyPI publish coordination).
- **Mixin pattern в `semantic_layer/query/`**: 4 mixin файла обращаются к атрибутам host class. T00 disabled mypy attr-defined. Real fix — Protocol-based typing.
- **T05 step 2/3 perf optimizations** (из v1.1 sprint) — требуют Docker stack для честного p99 замера; sqlglot LRU cache не даст entity p99 wins (entity endpoint строит SQL вручную, не через sqlglot)
- **T09 CDC connectors** (из v1.1 sprint) — `src/ingestion/connectors/postgres_cdc.py` использует Debezium, нужно стратегическое решение Debezium vs Python-native
- Любые новые architectural smells найденные в ходе аудита

Каждый item — заметка + ссылка на ticket если есть, или `needs ticket` если нужно создать.

## Acceptance

- `docs/codex-tasks/2026-04-23/T_AUDIT-result.md` существует и содержит все 8 секций заполненными.
- Quick fix #1 (test-integration `,cloud`) закоммичен и запушен; CI workflow `CI` job `test-integration` идёт дальше collection (либо зелёный, либо падает на test failure а не collection error).
- Все open follow-ups (то, что не quick fix) — есть тикет в `docs/codex-tasks/2026-04-24/` с понятным `Goal/Context/Deliverables/Acceptance/Notes`.
- `docs/codex-tasks/2026-04-24/README.md` содержит индекс всех тикетов 24-го.
- Memory note (если CX имеет доступ): `~/.claude/projects/D--/memory/project_de_project.md` State секция отражает реальный CI matrix после quick fixes.
- На GitHub Actions страница `main`-branch не должна иметь red runs за последние 24 часа **кроме** workflows которые задокументированы как `acceptable until <event>` (со ссылкой на тикет).

## Notes

- НЕ делать research перед написанием отчёта — собирать факты из `gh run view`, `pytest`, `git log`, `git diff` и т.д. Если факта нет — написать `unknown — see TXX`.
- НЕ переписывать код в этом таске кроме quick fix #1 (test-integration extras). Любая другая правка — отдельный ticket.
- НЕ удалять/архивировать docs или code без явного `acceptable to delete: yes` в отчёте + одобрения юзера в финале.
- НЕ trigger-ить ручные workflow runs кроме абсолютно необходимых для аудита (DORA, mutation, perf — манульный запуск дорогой по minutes). Если `Last run on main` пустое для workflow — отметить `never run on main, manual trigger needed for audit` и предложить тикет.
- Backstop: если за 6 часов не успеть всё — приоритезировать секции 1-4 (CI matrix + tests + T00 review + extras matrix), 5-8 закрыть в сжатой форме с пометкой `partial — extend in follow-up ticket`.
- Использовать `gh api rate_limit --jq .resources.core` чтобы не упереться в GitHub API лимит на массовых `gh run view` вызовах. На каждый workflow — один `gh run view --json jobs` достаточно.
- Если найден сломанный workflow с явным root cause (не deps, не env) и фикс <30 строк — допускается quick fix вторым коммитом (после #1) с явной отметкой в отчёте, но **не больше 2 quick fix-ов в одном PR**, остальное в тикеты.
