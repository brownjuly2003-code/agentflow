# Task: Tenant isolation + SQL guard + entity allowlist enforcement

Repo: `D:\DE_project` (AgentFlow runtime). HEAD: `e8b1237`. Branch: `main`.

## Goal

Закрыть три связанных security finding из недавнего внешнего аудита:

1. **Tenant isolation** на агрегирующих/streaming/control-plane путях: `pipeline_events` не имеет колонки `tenant_id`, поэтому `webhook_dispatcher`, `/v1/stream/events`, `/v1/lineage`, `/v1/slo`, `/v1/deadletter` показывают глобальные данные всем тенантам.
2. **SQL guard bypass** в `engine.paginated_query()` и `engine.explain()` — оба пути обходят `validate_nl_sql()`, поэтому через `/v1/query` (paginated) и `/v1/query/explain` можно выполнить произвольный SELECT (например `information_schema.tables`).
3. **`allowed_entity_types` обходится** через NL query, batch query/metric, search и metric routes — он enforce'ится только на `/v1/entity/{type}/{id}` через regex middleware.

## Context

Полный конфликт описан в `D:\DE_project\audit_codex_27_04_26.md` секции p2_1 #1-4, p2_2 #4, p3 #1-4, p1 R3, R5. Файл локально доступен.

Релевантные точки кода:

- `src/processing/local_pipeline.py:88-96` — DDL `pipeline_events` (5 столбцов, без tenant_id)
- `src/serving/backends/duckdb_backend.py:132` — duplicate DDL `pipeline_events`
- `src/serving/backends/clickhouse_backend.py:192` — duplicate DDL `pipeline_events`
- `src/processing/event_replayer.py:44` — DDL `dead_letter_events`
- `src/processing/local_pipeline.py:108-160` — INSERT в pipeline_events (несколько мест)
- `src/serving/api/webhook_dispatcher.py:198-211, 289-304` — `dispatch_new_events()` + `_fetch_pipeline_events()`
- `src/serving/api/routers/stream.py:22, 35, 43, 57` — `/v1/stream/events` reads pipeline_events
- `src/serving/api/routers/lineage.py:68, 87` — `/v1/lineage`
- `src/serving/api/routers/slo.py:90, 135` — `/v1/slo`
- `src/serving/api/routers/deadletter.py:83-91, 94-204, 229-295` — `/v1/deadletter`
- `src/serving/semantic_layer/query/nl_queries.py:82-176` — `paginated_query`, `execute_nl_query`, `explain` + `validate_nl_sql`
- `src/serving/semantic_layer/sql_guard.py` — `validate_nl_sql` allowlist
- `src/serving/api/routers/agent_query.py:139-160, 180-220, 360-400, 480-500` — `/v1/query`, `/v1/query/explain`
- `src/serving/api/routers/batch.py:60, 147, 179` — batch entity/query/metric
- `src/serving/api/routers/search.py:51` — `/v1/search`
- `src/serving/api/auth/middleware.py:102-103` — `is_entity_allowed` enforcement (только на entity path)
- `src/serving/api/auth/manager.py` — `TenantKey.allowed_entity_types`
- `src/serving/masking.py:36-54` — regex-based table parsing → не работает для quoted SQL `"acme"."users_enriched"`
- `src/serving/semantic_layer/query/sql_builder.py:110-113` — emits quoted tenant SQL

Тесты:

- `tests/unit/test_auth.py` (для baseline)
- `tests/integration/test_webhooks.py`, `test_alerts.py`, `test_streaming.py`, `test_lineage.py`, `test_slo.py`, `test_deadletter.py`, `test_batch.py`, `test_contracts.py`
- `tests/unit/test_pii_masker.py`

## Scope

Сделать ТРИ изменения, в порядке приоритета:

### A. Tenant isolation на pipeline_events / dead_letter_events (P0)

A1. Добавить столбец `tenant_id VARCHAR` (default `'default'`) в DDL `pipeline_events` во всех трёх местах: `local_pipeline.py`, `duckdb_backend.py`, `clickhouse_backend.py`. Добавить `tenant_id` в DDL `dead_letter_events` (`event_replayer.py`).

A2. Поправить все INSERT'ы в pipeline_events / dead_letter_events так, чтобы они писали актуальный tenant. Для local_pipeline и Flink processor канонически: tenant из `event['tenant']` или `event.get('source_metadata', {}).get('tenant')`, fallback на `'default'`. Для CDC normalizer (`src/ingestion/cdc/normalizer.py`) — извлечь tenant из topic prefix через `TenantRouter`, fallback на `'default'`.

A3. Добавить миграцию в существующую таблицу через `ALTER TABLE pipeline_events ADD COLUMN IF NOT EXISTS tenant_id VARCHAR DEFAULT 'default'` в init/`ensure_*` функциях.

A4. Поправить readers:

- `webhook_dispatcher._fetch_pipeline_events()` — добавить параметр `tenant: str | None`; если задан, фильтровать `WHERE tenant_id = ?`. В `dispatch_new_events()` итерировать webhooks по tenant и подгружать events для каждого tenant отдельно (или загружать все и filter в Python — выбор по efficiency, сохранить deterministic order).
- `routers/stream.py` — добавить `WHERE tenant_id = ?` (использовать `request.state.tenant_id`).
- `routers/lineage.py` — то же + intersection с `tenant_key.allowed_entity_types`.
- `routers/slo.py` — то же.
- `routers/deadletter.py` — все 5 endpoints (stats/list/detail/replay/dismiss) фильтруют по tenant_id; `_require_deadletter_write_access` дополнительно проверяет ownership события.

### B. SQL guard centralization (P0)

B1. В `src/serving/semantic_layer/query/nl_queries.py`:

- Создать helper `_prepare_nl_sql(translated_sql, allowed_tables) -> str`, который вызывает `validate_nl_sql(translated_sql, allowed_tables)`. Если invalid — поднимает HTTPException(403) с originating reason.
- `execute_nl_query`, `paginated_query`, `explain` все вызывают `_prepare_nl_sql` ДО `_scope_sql()` и pagination wrapping. Сейчас `paginated_query` пропускает этот шаг.

B2. В `src/serving/masking.py`:

- Заменить regex-based `_extract_table_names` на sqlglot-based парсинг (`sqlglot.parse_one(sql, read="duckdb")` + walking `exp.Table` nodes, нормализуя `db.schema.table` → `table`).
- Тест: `mask_query_results('SELECT email FROM "acme"."users_enriched"', ...)` должен маскировать email.

### C. allowed_entity_types enforcement на NL/batch/search/metrics (P1)

C1. Helper `tenant_key_allowed_tables(tenant_key, all_catalog_tables) -> list[str]`: если `tenant_key.allowed_entity_types is None` — вернуть all; иначе intersection.

C2. Использовать этот helper в:

- `agent_query.py::execute_nl_query` / `paginated_query` / `explain` — вместо global `allowed_tables` из catalog.
- `routers/batch.py` — для items с `type="query"` и `type="metric"` (для metric — map metric_name → entity table через catalog metadata).
- `routers/search.py` — intersect supplied `entity_types` с `tenant_key.allowed_entity_types`.

C3. В `auth/middleware.py` — оставить existing entity-path enforcement; не дублировать.

## Tests (обязательно)

- `tests/integration/test_webhooks.py::test_dispatcher_does_not_deliver_cross_tenant_pipeline_events` — два tenant, два webhook, тенант A не получает события тенанта B.
- `tests/integration/test_deadletter.py::test_deadletter_endpoints_are_tenant_scoped` — два tenant, тенант A не видит/replay/dismiss события тенанта B.
- `tests/integration/test_streaming.py::test_stream_filters_by_tenant_id` — два tenant.
- `tests/integration/test_lineage.py::test_lineage_does_not_return_other_tenant_events_for_shared_entity_id`.
- `tests/integration/test_slo.py::test_slo_only_aggregates_caller_tenant`.
- `tests/integration/test_batch.py::test_batch_query_enforces_allowed_entity_types`.
- `tests/integration/test_search.py::test_search_intersects_entity_types_with_allowlist`.
- `tests/unit/test_paginated_nl_query.py::test_paginated_query_rejects_unsafe_sql` — monkeypatch translator → `SELECT * FROM information_schema.tables`; должен 403.
- `tests/unit/test_pii_masker.py::test_mask_handles_quoted_schema_table` — `"acme"."users_enriched"`.

## Acceptance

1. `python -m pytest tests/unit tests/integration -p no:cacheprovider -p no:schemathesis -q` — 0 failures, 0 errors. Skipped (helm/kind/CDC docker) разрешены.
2. Новые tests из секции выше реально fail на parent commit `e8b1237` и pass на твоём commit (доказательство).
3. Никаких изменений в `tests/contract/` без явной необходимости (contract suite не должен сломаться).
4. Schema migration backward-compatible — старые БД без `tenant_id` колонки получают её через ALTER в init path.
5. Не вводить новую конфигурацию env var без значения по умолчанию `default`.

## Notes / Constraints

- НЕ трогать `helm/`, `k8s/`, `.github/workflows/`, `docs/` в этом diff.
- НЕ трогать SDK (`sdk/`, `sdk-ts/`).
- НЕ менять API contract (response schemas, codes) кроме добавления новых полей `tenant` в response где они уже логически принадлежат — например `/v1/lineage` payload может включать `tenant_id` в каждом lineage event для прозрачности.
- На клиенте (curl) запросы должны продолжать работать без изменений; только cross-tenant запросы должны теперь блокироваться.
- Сохрани backward compat: pipeline_events / dead_letter_events записи без tenant_id (legacy) обрабатывать как `'default'` tenant.
- Если scope C окажется крупнее ожидания (>200 строк сверх A+B), реализуй A полностью + B полностью + C только для NL query (paginated/execute/explain), и в финальном комментарии явно укажи: «C для batch/search не сделано в этом diff — нужен follow-up».
- Use `secrets.compare_digest` если будут string compares на security boundaries.
- Если найдёшь существующие tenant fields с другим именем (`tenant`, `tenant_key`, `request.state.tenant_key.tenant`, `request.state.tenant_id`) — используй их, не вводи новые.

## Deliverables

- Diff в одном patch (или ряд patch файлов) применимый через `git apply`.
- Краткий summary changes (что сделано в каждом scope A/B/C).
- Список новых тестов + результат их прогона на старом и новом HEAD.
