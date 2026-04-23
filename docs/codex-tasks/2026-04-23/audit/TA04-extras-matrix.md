# TA04 — Dependency / extras matrix audit

**Priority:** P1 · **Estimate:** 1ч

## Goal

Catalog какой CI job в `.github/workflows/*.yml` ставит какие pip extras, какие src/ модули они импортируют через тесты транзитивно, и есть ли gap (job ставит меньше чем нужно) или overhead (ставит больше чем нужно).

## Context

- Корневой `pyproject.toml` extras: `flink`, `cloud` (boto3+pyiceberg), `llm` (anthropic), `load` (locust), `integrations` (langchain+llama-index-core), `dev`
- Внутренний `integrations/pyproject.toml` extras: `mcp` (агентfлоу-mcp pakage)
- SDK `sdk/pyproject.toml` — отдельный `agentflow` package (name collision с root)
- Прецеденты missed extras: `b2f8344` load-test добавил cloud; `2cf7a7b` contract добавил cloud; `ecc137c` test-unit/chaos/perf/perf-regression добавили cloud; **TA01 quick fix** добавляет test-integration cloud

## Deliverables

1. Сканирование workflow-ов:
   ```bash
   grep -B1 -A1 "pip install" .github/workflows/*.yml
   ```
2. Для каждого `pip install` step — определить какие extras установлены и какой test directory job запускает.
3. Для каждого test directory — `grep -rn "^from\|^import" tests/<dir>/` и трассировать какие src/ модули требуются, и какие extras эти src/ требуют.
4. Matrix в `audit/TA04-result.md`:
   ```markdown
   ## Extras matrix

   | Workflow | Job | pip extras | Test dir | src/ modules transitively | Required extras (from src) | Gap | Action |
   |----------|-----|------------|----------|---------------------------|----------------------------|-----|--------|
   ```
5. Action на gap:
   - `add ,X` (с конкретным workflow:line + предложение коммита)
   - `drop ,Y` (если overhead — например, llm extra без anthropic-using тестов; но осторожно: import в src/ может быть опционален)
   - `OK` (если совпадает)
   - `needs ticket` (если сложно, например, разделение test-integration на два job-а)

## Acceptance

- `audit/TA04-result.md` содержит matrix all 15 workflows × all relevant jobs.
- Каждый Gap имеет конкретный action.
- Любой `add ,X` action **не fix-ится в этом таске** (только catalog) — добавляется в TA10 consolidation как recommended PR.
- Список missed extras сверяется с TA01 CI matrix (что красное и почему): должен быть consistent.

## Notes

- НЕ трогать `pyproject.toml` extras structure (например, не объединять `cloud` + `flink`). Любой redesign — отдельный architectural ticket в TA08.
- Для определения «нужен ли extra» — `python -c "from src.<module> import *"` в venv с/без extra. Если падает на ImportError — нужен.
- `dev` extra нужен везде где запускается pytest — это базовый.
- `[mcp]` нужен только для test-unit (test_mcp_server.py) — других тестов с mcp нет.
- Backstop: если за час не успеть всё — приоритет CI workflows (test-unit/test-integration/test-contract), остальные с пометкой `partial`.
