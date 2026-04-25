# T29 — Diagnose and fix test_openapi_compliance local-only failure

**Priority:** P2 · **Estimate:** 3-5 часов · **Track:** Test infra hygiene

## Goal

`tests/contract/test_openapi_compliance.py::test_documented_openapi_snapshot_matches_live_api` стабильно падает на локальной dev machine (Python 3.13 + Windows + Redis в Docker), но **проходит на CI** (Contract Tests workflow зелёный на 5+ последних SHAs main). Найти причину divergence, исправить — либо local repro работающий, либо тест честно помечен как CI-only с обоснованием.

## Context

- Замечено в T27 sprint (commit `cd4a11a`, 2026-04-25) под `python -m pytest -p no:schemathesis`. 645 passed, 3 skipped, 2 failed.
- Симптом (из Codex output): "live OpenAPI ValidationError schema отличается от documented snapshot". Точный diff — нужно собрать (см. Deliverables).
- CI workflow `contract.yml` запускает `pytest tests/contract -v --tb=short` после `pip install -e ".[dev,cloud,contract]" && pip install -e "./sdk"`. **Зелёный.** Значит проблема не в самом snapshot или live API generally — а в **environment delta** между local и CI runner.

Likely causes (в порядке вероятности):

1. **Python 3.13 vs 3.11 pydantic schema generation.** Codex локально на 3.13 (см. `tests` output: `Python 3.13.7`). CI на 3.11. Pydantic 2.9 (per pyproject) генерит OpenAPI schema differently between Python versions (особенно `Annotated`, `Literal`, `Union` representation).
2. **DuckDB seed state difference.** Local `agentflow_demo.duckdb` seeded ранее (другой запуск `local_pipeline.py`); CI всегда fresh. Live `/openapi.json` может включать examples из live data → snapshot mismatch.
3. **Local API serves different version.** Локально может быть запущен другой `uvicorn` instance (например, оставшийся от A03 profiling) — тест берёт оттуда, а snapshot был сгенерирован на чистой instance.
4. **Locale / encoding.** Windows cp1252 vs Linux UTF-8 в JSON dump — порядок ключей или escape sequences. Скорее всего нет — JSON canonical, но проверить.

## Deliverables

1. **Capture exact diff** — запустить тест с verbose output, сохранить:
   - `live_openapi_local.json` — то, что live API возвращает локально
   - `live_openapi_ci.json` — то, что CI runner получает (нужно вытянуть из CI artifact или запустить тест в Docker container с Python 3.11 локально)
   - `diff -u` между ними → задокументировать в `docs/perf/test_openapi_compliance-divergence-2026-04-25.md` (или другом diagnostic doc)
2. **Identify root cause** — один из 4 above или другой. Доказать с evidence (не угадать).
3. **Fix** — один из:
   - **Если pydantic/Python diff:** обновить snapshot до version-agnostic representation, либо нормализовать diff в test (sort keys, strip version-specific fields).
   - **Если DuckDB seed:** изолировать тест от live DuckDB state (use clean tmpdir DB fixture).
   - **Если stale uvicorn:** документировать в `docs/perf/entity-benchmark-contract.md` (или новом testing guide) — "kill stray uvicorn before running contract tests".
   - **Если Python 3.13 unsupported:** документировать в README "use Python 3.11 for local dev" + add `.python-version` или CI check.
4. **Verify** — после фикса:
   - Локально на Python 3.13 + Windows: тест зелёный.
   - Локально через Docker Python 3.11: тест зелёный.
   - CI Contract Tests workflow: остаётся зелёный (не сломали то, что работало).
5. Один коммит. Если diff document создан — отдельный коммит до фикса (`docs(perf): test_openapi_compliance local divergence captured`).

## Acceptance

- Local Python 3.13 → тест проходит (3 раза подряд).
- CI Contract Tests workflow → проходит (один пуш).
- В commit message — root cause + fix approach в одном абзаце.
- Если решение — "не поддерживаем Python 3.13 локально" — это требует **визибл документации** (README + .python-version + CI guard), а не молчаливый skip.

## Notes

- **Не** обновлять snapshot до того, что live API возвращает локально, без анализа. Это будет round-trip green но скрытно сломает CI.
- **Не** добавлять `@pytest.mark.skipif(sys.version_info >= (3, 13))` без явного документирования в README. Если так — это flag для юзера: "проект больше не работает на 3.13 локально, требуется 3.11".
- Если фикс — schema normalization (sort keys, strip dynamic fields) — будь осторожен: пройти не всё, а только namespaced sub-paths где divergence реальная (избегай "compare nothing").
- Codex's full-suite hardgate (`python -m pytest` 0 failed) — этот тест блокирует commit/push любых других CX задач, пока не починен. Высокий ROI на скорость sprint.
- Не путай с T28 (chaos test order-dependency) — параллельный fail в той же full-suite, отдельная задача.
- A06 enforcement: contract.yml workflow profile = `contract`. Если меняешь install line — обновить `[tool.agentflow.dependency-profiles.profiles.contract]` в pyproject.toml. См. `feedback_a06_enforcement.md`.
