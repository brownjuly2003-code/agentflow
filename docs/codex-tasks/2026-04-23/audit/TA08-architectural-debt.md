# TA08 — Architectural debt inventory

**Priority:** P2 · **Estimate:** 1ч

## Goal

Catalog known architectural issues и technical debt которые НЕ должны fix-ить сейчас (требуют major work / breaking changes / координации). Создать или обновить tickets для каждого.

## Context

Известные debt items на текущий HEAD:

1. **`agentflow` SDK name collision**: root `pyproject.toml` и `sdk/pyproject.toml` оба `name = "agentflow" version = "1.0.1"`. `pip install -e .` после `pip install -e sdk/` — один пакет затирает другой. Workaround в тестах: `sys.path.insert(0, "sdk/")`. Real fix: переименовать SDK в `agentflow-sdk` (требует синхронизации PyPI publish + npm publish + integration partners).
2. **Mixin pattern в `src/serving/semantic_layer/query/`**: 4 файла (`sql_builder.py`, `nl_queries.py`, `metric_queries.py`, `entity_queries.py`) содержат `Mixin` классы, обращающиеся к атрибутам host class (`self._tenant_router`, `self.catalog`, `self._backend` и т.д.). T00 hardening добавил `disable_error_code = ["attr-defined"]` в mypy override. Real fix: Protocol-based typing host requirements.
3. **T05 step 2/3 perf optimizations** (из v1.1 sprint, не CI repair): требуют полный Docker stack для p99 latency benchmark. Sqlglot LRU cache не даст entity wins (entity endpoint строит SQL вручную, не через sqlglot).
4. **T09 CDC connectors** (из v1.1 sprint): `src/ingestion/connectors/postgres_cdc.py` использует Debezium. Стратегическое решение Debezium vs Python-native не принято.
5. **Helm chart staging-deploy fragility**: T02 root cause был `key_id` missing in `values-staging.yaml`. Pattern: helm values rely on schema implicit, не validated. Real fix: schema validation pre-install (helm lint + custom JSON schema).

## Deliverables

1. **Расширить список** debt items найденными в ходе аудита (TA02-TA07 могут поднять новые). Например:
   - Если TA03 found T00 regression — это new architectural concern
   - Если TA04 found extras misalignment системного характера (например, `cloud` нужен everywhere → может стоит сделать default) — architectural ticket
   - Если TA05 found large dead module — architectural cleanup ticket
   - Если TA07 found Trivy gap (например, base image outdated) — base image upgrade ticket

2. Для каждого debt item — ticket в `docs/codex-tasks/2026-04-24/` или `2026-04-Q2-architecture/` (новая папка для major architectural work) с:
   - Goal / Context / Deliverables / Acceptance / Notes
   - **Estimated effort:** в днях/неделях (если >1 неделя — flag для project planning)
   - **Risk if not fixed:** что плохого случится если оставить

3. Финальный `audit/TA08-result.md`:

   ```markdown
   ## Architectural debt inventory (HEAD <sha>)

   | # | Item | Impact | Workaround in place | Real fix | Effort | Ticket | Risk if deferred |
   ```

4. **Recommended priority** в TA10 consolidation: какие 1-2 debt items стоит fix-ить в next sprint (Q2 2026), какие отложить на 6+ месяцев.

## Acceptance

- `audit/TA08-result.md` содержит все 5 known items + новые из TA02-TA07 (если есть).
- Каждый item имеет ticket в `docs/codex-tasks/2026-04-24/` или новой папке.
- Effort estimate для каждого ≥ 1 день (если меньше — это не architectural, это quick fix, должен быть закрыт quick).
- Risk-if-deferred — конкретно (не «может быть проблема» а «pip install order может сломать SDK у user-а X в setup Y»).

## Notes

- НЕ начинать fix-ить debt items в этом таске. Только catalog + tickets.
- НЕ переоценивать риск (всё «critical») — calibrate с тем что 5 items живут уже 6+ месяцев без issue.
- Если debt item требует customer signal перед start (напр., SDK rename — нужен поговорить с consumers) — отметить `blocked on <event>` в ticket-е.
- Backstop: если за час не успеть всё — приоритет item-ам которые могут regress в следующем спринте (mixin pattern, helm fragility — обе могут пробить себе жизнь снова).
