# T28 — Diagnose and fix chaos test order-dependency flakiness

**Priority:** P2 · **Estimate:** 2-4 часа · **Track:** Test infra hygiene

## Goal

`tests/chaos/test_redis_failure.py::test_metrics_fall_back_when_redis_proxy_is_disabled` падает в full-suite run (`python -m pytest`) но проходит в isolation (`python -m pytest tests/chaos/test_redis_failure.py::test_metrics_fall_back_when_redis_proxy_is_disabled`). Классический test pollution / order dependency. Найти leak, починить, защитить от повторения.

## Context

- Замечено во время T27 sprint (commit `cd4a11a`, 2026-04-25). Codex's full-suite run (`python -m pytest -p no:schemathesis`) → 645 passed, 3 skipped, **2 failed**. Один из них — этот chaos test.
- Тест **не запускается на CI workflow `Chaos`** регулярно (workflow trigger — schedule, не push). Поэтому проблема не блокировала CI зелёный, но на dev machine при `pytest` (no args) — ловится.
- T27 changes только trogали `tests/load/`, `docs/perf/`, `.github/workflows/load-test.yml`. С chaos тестом физически не пересекаются — это pre-existing flakiness, всплывшая под наблюдение.

Что проверить (в порядке ROI):

1. **Mocked Redis state leak.** Если предыдущий chaos test patches `src.serving.cache.redis_client` (или connection pool) и не снимает patch — следующий тест получает мёртвую заглушку, `metrics_fall_back` получает unexpected behaviour.
2. **Asyncio event loop leak.** Если предыдущий тест запускает `asyncio.create_task(...)` без cleanup — task жив через границу теста, пишет в глобальные структуры. См. `pytest-asyncio` mode (`asyncio_mode = "auto"` в `pyproject.toml`) — все async tests шарят loop по default.
3. **Module-level state in `src/serving/api/`** — counter, gauge, или registry, который не resets между тестами. Prometheus metrics часто страдают этим (registry singleton).
4. **DuckDB connection pool** — если test pollution влияет на pool state.

## Deliverables

1. **Reproduce и locate**:
   - Запустить `python -m pytest tests/chaos/ -v -p no:schemathesis` — посмотреть, в каком ordering test падает.
   - Запустить `pytest --collect-only tests/chaos/` чтобы увидеть, какие тесты идут до проблемного.
   - Применить `pytest-randomly` или manual reorder: запустить `pytest tests/chaos/test_redis_failure.py tests/chaos/<other_file>.py::<other_test> tests/chaos/test_redis_failure.py::test_metrics_fall_back_when_redis_proxy_is_disabled` чтобы найти **минимальный pair** triggering fail.
2. **Root cause** — задокументировать в commit message одним абзацем. Что именно leak'ит, между какими тестами.
3. **Fix** — выбрать минимальный из:
   - Autouse fixture с teardown (например, reset Prometheus registry, drain asyncio tasks, `monkeypatch.undo()`).
   - Move к function-scoped fixture где сейчас module/session-scoped.
   - Dispose-pattern в самом тесте, если leak — внутренний.
4. **Regression guard** — добавить аналогичный fixture глобально в `tests/chaos/conftest.py` (или общий `tests/conftest.py` если applicable), чтобы не воспроизводилось.
5. **Verify** — full suite зелёная без skip/xfail на этот тест:
   - `python -m pytest -p no:schemathesis` → 0 failed.
   - `python -m pytest tests/chaos/ -p no:schemathesis` → 0 failed.
   - `python -m pytest tests/chaos/test_redis_failure.py::test_metrics_fall_back_when_redis_proxy_is_disabled -p no:schemathesis` → passed.
   - 3 пуска подряд full suite — всё зелёное (исключаем flakiness).
6. Один коммит `fix(chaos): <root cause> — drop test pollution into test_metrics_fall_back_when_redis_proxy_is_disabled`. Push.

## Acceptance

- Full suite зелёная 3 раза подряд локально (Python 3.13 + Windows + Redis Docker).
- Сам test не помечен skip/xfail.
- `tests/chaos/conftest.py` (или другая autouse область) обновлен с regression-guard fixture.
- В commit message — четкий root-cause statement (не общая фраза "fixed pollution").

## Notes

- **Не** маскировать через `@pytest.mark.flaky(reruns=N)` — это broken-window. Найти и устранить причину.
- Если выяснится, что причина — **bug в production code** (а не test infra), это важная находка — задокументируй и реши: фиксить production code (отдельный коммит) или test setup. Production fix имеет приоритет.
- Не путай с `tests/contract/test_openapi_compliance.py` — отдельный fail в той же full-suite run, отдельная задача T29.
- Test НЕ runs в CI на push (только schedule). Значит CI green не гарантирует test green после твоего фикса — verify локально 3×.
- Помни: project имеет `python_version = "3.11"` mypy + `requires-python = ">=3.11"`. Локально может быть 3.13, behaviour может отличаться (особенно asyncio). Если корень — Python 3.13-specific — задокументируй и предложи pin Python version в pre-commit hook.
