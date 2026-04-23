# T06 — Performance workflows: align deps and repair benchmark gates

**Priority:** P1 · **Estimate:** 3-5ч

## Goal

Сделать зелёными три related workflow-а: `Load Test`, `Nightly Performance`, `Performance Regression`.

## Context

- `Load Test` latest failed run: `24809054280`.
  - Workflow уже доходит до benchmark gate и падает на threshold violations (`/v1/health`, `/v1/batch`, `/v1/query`, entity endpoints).
- `Nightly Performance` latest failed run: `24761959139`.
  - Падает раньше, на `ModuleNotFoundError: pyiceberg` внутри `scripts/run_benchmark.py` при seed demo data.
- `Performance Regression` historical run-ов пока нет, но workflow использует тот же benchmark path и тот же install step pattern, что и `Nightly Performance`.
- В T05 локально уже добавлен `cloud` extra в `performance.yml` и `perf-regression.yml`, но этого недостаточно, чтобы доказать зелёный статус: после import-fix workflow всё ещё должен пройти performance budget.

## Deliverables

1. Привести install steps к одному паттерну для всех performance workflow-ов:
   - `pip install -e ".[dev,load,cloud]"` там, где benchmark использует код с `pyiceberg`.
2. Разобрать текущие threshold violations из `Load Test`:
   - понять, что является реальным regression,
   - что является слишком жёстким budget для CI runner,
   - нужен ли split на smoke gate vs full nightly benchmark.
3. Принять одно решение для всей performance family:
   - либо обновить baseline/thresholds на реалистичные значения,
   - либо уменьшить workload/seed path,
   - либо разделить quick gate и long benchmark в разные workflow/job-ы.
4. Получить зелёные recent run-ы:
   - `Load Test`
   - `Nightly Performance`
   - `Performance Regression`
5. Обновить `docs/codex-tasks/2026-04-23/T05-result.md` run id-ами после зелёных прогонов.

## Acceptance

- `Load Test` green on `main`.
- `Nightly Performance` green on `workflow_dispatch` или schedule.
- `Performance Regression` green on PR against `main`.
- Ни один workflow не теряет signal:
  - benchmark реально запускается,
  - regression gate остаётся meaningful,
  - thresholds не превращены в формальность.

## Notes

- Не лечить это отключением `check_performance.py`.
- Не поднимать thresholds без объяснения, почему runner reality отличается от baseline.
- Если нужен split на smoke/full, делать явно и с сохранением release gate semantics.
