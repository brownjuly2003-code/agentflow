# TA02 — Test suite pass/fail catalog

**Priority:** P1 · **Estimate:** 1-2ч

## Goal

Прогнать все test suites локально в чистом venv с полным набором extras и зафиксировать matrix passed/failed/skipped по directories. Для каждого failed/error — root cause в одной фразе.

## Context

- Локальная проверка нужна потому что CI test jobs зависят от extras (`,cloud`, `[mcp]`) которые могут быть пропущены в каком-то workflow (см. TA01).
- Test directories: `tests/unit/`, `tests/property/`, `tests/contract/`, `tests/sdk/`, `tests/e2e/`, `tests/integration/`, `tests/chaos/`, `tests/load/`
- Memory note: 552 теста зелёных по состоянию v1.1 sprint, но после T00 hardening цифра могла сдвинуться (в обе стороны)

## Deliverables

1. Setup чистого venv:
   ```bash
   python3.11 -m venv .venv-audit
   . .venv-audit/bin/activate  # или Scripts/activate.bat на Windows
   pip install --upgrade pip
   pip install -e ".[dev,integrations,cloud,load,llm,contract]"
   pip install -e "./integrations[mcp]"
   pip install -e "./sdk"
   ```
2. Прогон без Docker-зависимых suites:
   ```bash
   python -m pytest tests/unit/ -q --tb=line -o cache_dir=/tmp/.pytest_cache_unit > audit-unit.log
   python -m pytest tests/property/ -q --tb=line > audit-property.log
   python -m pytest tests/contract/ -q --tb=line > audit-contract.log
   python -m pytest tests/sdk/ -q --tb=line > audit-sdk.log
   SKIP_DOCKER_TESTS=1 python -m pytest tests/e2e/ -q --tb=line > audit-e2e-skipped.log
   ```
3. Если есть Docker — прогон Docker-зависимых:
   ```bash
   docker compose -f docker-compose.e2e.yml up -d --wait
   python -m pytest tests/e2e/ -q --tb=line > audit-e2e.log
   docker compose -f docker-compose.e2e.yml down
   # tests/integration/ требует Kafka+Redis+Postgres — поднять через docker-compose.prod.yml minimal services
   ```
   Если нет Docker — отметить в result `not run — no docker available`.
4. Результат в `audit/TA02-result.md`:
   ```markdown
   ## Test suite catalog (venv: <commit-sha>, deps: <pip freeze hash>)

   | Suite | Total | Passed | Failed | Errored | Skipped | Time | Notes |
   |-------|-------|--------|--------|---------|---------|------|-------|

   ### Failed/Errored test breakdown

   | Suite | File:Line | Test | Failure type | Root cause (1 sentence) | Action |
   ```
5. Action на каждый failed: `pre-existing` / `regression from T00` / `flaky` / `needs ticket` (с указанием TXX в `2026-04-24/` если создаётся).

## Acceptance

- `audit/TA02-result.md` содержит matrix всех 8 directories (даже если `not run` со reason).
- Для каждого failed/errored test — указан root cause + action.
- Если найдена T00-регрессия — отдельный ticket в `2026-04-24/` с минимальным репро.
- pip freeze hash зафиксирован чтобы потом можно было воспроизвести.

## Notes

- НЕ чинить failed tests в этом таске. Catalog only + tickets.
- `tests/integration/` требует Kafka/Redis/Postgres — если нет docker, явно отметить `not run` и оставить comparison с TA01 CI test-integration результатом.
- Если pytest collection падает раньше чем тест запустился (как сейчас на pyiceberg) — это **errored**, не **failed**, отдельная колонка.
- Backstop: если за 2 часа не запустить все suites — приоритет unit + property + contract + sdk (быстрые, не Docker), e2e/integration отложить с отметкой `partial — extend`.
