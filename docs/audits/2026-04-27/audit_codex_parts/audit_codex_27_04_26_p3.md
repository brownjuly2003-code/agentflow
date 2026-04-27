# SQL/Query Generation Audit - Codex 2026-04-27 P3

Scope: `src/serving/semantic_layer`, DuckDB/ClickHouse serving backends, Postgres CDC config surface, query/filter routes, escaping, tenant/auth boundaries, user-controlled inputs.

Baseline: HEAD `4a13d36`, branch `main`, tracked files `597`. В workspace уже были чужие modified/untracked files; этот отчет добавляет только `audit_codex_27_04_26_p3.md`.

## Findings

### 1. HIGH - `/v1/query` pagination обходит SQL guard и может читать non-catalog tables

- Статус: VERIFIED
- Уверенность: 9/10
- Категория: injection / data leakage
- Файлы:
  - `src/serving/api/routers/agent_query.py:160` выбирает `engine.paginated_query` для основного `/v1/query`.
  - `src/serving/semantic_layer/query/nl_queries.py:82` строит paginated SQL.
  - `src/serving/semantic_layer/query/nl_queries.py:108` оборачивает translated SQL в `SELECT * FROM ({sql})`.
  - `src/serving/semantic_layer/query/nl_queries.py:133` выполняет этот SQL.
  - `src/serving/semantic_layer/query/nl_queries.py:176` вызывает `validate_nl_sql` только в `execute_nl_query`, но не в `paginated_query`.
  - `src/serving/semantic_layer/sql_guard.py:29` содержит intended allowlist validator.
  - `src/serving/backends/clickhouse_backend.py:100` отправляет SQL в ClickHouse без parameter binding и без guard enforcement.

Сценарий эксплуатации:
1. У атакующего есть любой ключ, который может вызвать `/v1/query`, либо auth отключен из-за отсутствующей API key config.
2. В LLM mode (`ANTHROPIC_API_KEY` set) атакующий через prompt injection добивается, чтобы NL translator вернул single `SELECT` по non-catalog object, например `information_schema.tables`, DuckDB table functions или ClickHouse `system.*`.
3. Route вызывает `paginated_query`, который не вызывает `validate_nl_sql`.
4. Backend получает и выполняет `SELECT * FROM (<attacker-shaped SELECT>) AS paginated_query ...`.

Проверка:
- Monkeypatch `_translate_question_to_sql` вернул `SELECT * FROM information_schema.tables`.
- `paginated_query()` отправил в backend `SELECT * FROM (SELECT * FROM information_schema.tables) AS paginated_query LIMIT 2 OFFSET 0`.
- `execute_nl_query()` тот же SQL отклонил с `Unknown tables: ['tables']`.

Влияние: через обычный query endpoint можно раскрыть catalog/table metadata или другие backend-readable objects. Для ClickHouse это также относится к `system.*` tables, если configured ClickHouse user может их читать.

Рекомендация: вызывать `validate_nl_sql(translated_sql, allowed_tables)` до `_scope_sql()` в `paginated_query` и `explain`; добавить regression tests для `/v1/query` pagination и `/v1/query/explain` с `SELECT * FROM information_schema.tables`, multi-statement SQL и ClickHouse `system.tables`.

### 2. HIGH - `allowed_entity_types` обходится через NL query и batch query

- Статус: VERIFIED
- Уверенность: 8/10
- Категория: authorization / data leakage
- Файлы:
  - `src/serving/api/auth/middleware.py:102` достает entity type только из `/v1/entity/{type}/...`.
  - `src/serving/api/auth/middleware.py:103` применяет `allowed_entity_types` только для этой route shape.
  - `src/serving/api/routers/batch.py:60` проверяет `allowed_entity_types` для batch entity items.
  - `src/serving/api/routers/batch.py:147` выполняет batch query items без эквивалентной entity/table authorization check.
  - `src/serving/api/routers/agent_query.py:140` обрабатывает `/v1/query` без проверки, какие entity tables читает generated SQL.
  - `src/serving/semantic_layer/query/nl_queries.py:172` строит `allowed_tables` из всех catalog entities, а не из caller key.

Сценарий эксплуатации:
1. Используется API key с ограничением `allowed_entity_types: ["order"]`.
2. Прямой `GET /v1/entity/user/USR-...` корректно блокируется.
3. Тот же caller спрашивает `/v1/query` или batch `type=query` про user/session data.
4. Если translator возвращает SQL по `users_enriched` или `sessions_aggregated`, guard разрешает его, потому что эти таблицы входят в global catalog allowlist.

Влияние: per-key entity restrictions не являются реальной policy boundary для NL query surfaces. Ограниченный support key может получить данные entity types, которые ему запрещены через direct entity endpoints.

Рекомендация: выводить allowed SQL tables из `tenant_key.allowed_entity_types` и применять этот table allowlist к `execute_nl_query`, `paginated_query`, `explain` и batch query items. Если query касается disallowed table, возвращать `403`.

### 3. HIGH - PII masking ломается на tenant-scoped quoted SQL

- Статус: VERIFIED
- Уверенность: 9/10
- Категория: data leakage
- Файлы:
  - `src/serving/semantic_layer/query/sql_builder.py:110` переписывает tenant tables с quoted schema identifiers.
  - `src/serving/semantic_layer/query/sql_builder.py:113` emits SQL вида `"acme"."users_enriched"`.
  - `src/serving/masking.py:36` маскирует query results через regex parsing table names from SQL.
  - `src/serving/masking.py:45` матчится только на unquoted `FROM/JOIN table` forms.
  - `src/serving/masking.py:54` возвращает rows unmasked, если не может resolve ровно один entity type.
  - `src/serving/api/routers/agent_query.py:210` зависит от этого masking для NL query responses.
  - `src/serving/api/routers/batch.py:179` зависит от того же masking для batch query responses.

Сценарий эксплуатации:
1. Tenant-scoped query SQL переписывается в quoted identifiers, например `SELECT email FROM "acme"."users_enriched"`.
2. Query result содержит поля из `config/pii_fields.yaml`, например `email`, `full_name`, `phone`, `ip_address`.
3. `mask_query_results()` не распознает `"acme"."users_enriched"` как `users_enriched`.
4. Он возвращает rows без изменений и не ставит `X-PII-Masked`.

Проверка:
- `mask_query_results("SELECT email, full_name FROM users_enriched", ...)` замаскировал `jane@example.com`.
- `mask_query_results("SELECT email, full_name FROM \"demo\".\"users_enriched\"", ...)` вернул `jane@example.com` без изменений.

Влияние: tenant-scoped NL или batch query responses могут раскрыть configured PII fields, хотя direct entity endpoints те же данные маскируют.

Рекомендация: не regex-parse SQL для masking. Использовать parsed AST из `sqlglot` или возвращать `tables_accessed` из query planner после normalization. Минимально: поддержать quoted identifiers и schema-qualified names в `mask_query_results`, затем добавить tests для `"tenant"."users_enriched"`.

### 4. HIGH - Pipeline event filters и webhook dispatch не tenant-scoped

- Статус: VERIFIED
- Уверенность: 8/10
- Категория: authorization / data leakage
- Файлы:
  - `src/ingestion/tenant_router.py:76` поддерживает tenant topic prefixes.
  - `src/serving/api/routers/stream.py:35` читает `pipeline_events` глобально.
  - `src/serving/api/routers/stream.py:43` фильтрует только по event type family.
  - `src/serving/api/routers/stream.py:57` фильтрует только по `entity_id`.
  - `src/serving/api/routers/lineage.py:68` fetches lineage только по `entity_id`.
  - `src/serving/api/webhook_dispatcher.py:200` загружает all active webhooks across tenants.
  - `src/serving/api/webhook_dispatcher.py:201` fetches all pipeline events.
  - `src/serving/api/webhook_dispatcher.py:209` проверяет каждый webhook against every event.
  - `src/serving/api/webhook_dispatcher.py:341` filter matching ignores webhook tenant.

Сценарий эксплуатации:
1. Tenant A registers webhook with broad filters или вызывает `/v1/stream/events?event_type=order`.
2. Tenant B produces matching pipeline events into the shared `pipeline_events` stream/table.
3. Код фильтрует по event type/entity only, not by `request.state.tenant_id`, topic prefix or event tenant.
4. Tenant A получает или читает Tenant B pipeline metadata/payload fields.

Влияние: cross-tenant data exposure через streaming, lineage и webhook delivery paths, даже если entity/metric reads tenant-scoped.

Рекомендация: добавить canonical tenant field в pipeline events или reliably derive tenant from topic prefix, затем enforce tenant predicates in stream, lineage, SLO/deadletter reads where applicable, and webhook dispatch. Webhook matching должен требовать `event.tenant == webhook.tenant` до user filters.

### 5. MEDIUM - Query text и generated SQL сохраняются/экспортируются без redaction

- Статус: VERIFIED
- Уверенность: 8/10
- Категория: data leakage
- Файлы:
  - `src/serving/api/routers/agent_query.py:154` сохраняет full user question в span attribute `query.text`.
  - `src/serving/api/routers/agent_query.py:199` сохраняет generated SQL в span attribute `query.sql`.
  - `src/serving/semantic_layer/query/nl_queries.py:47` сохраняет первые 200 chars question в tracing.
  - `src/serving/semantic_layer/query/nl_queries.py:127` сохраняет SQL в backend query spans.
  - `src/serving/semantic_layer/nl_engine.py:98` логирует первые 80 chars question.
  - `src/serving/api/telemetry.py:29` включает OTLP export, когда configured `OTEL_EXPORTER_OTLP_ENDPOINT`.

Сценарий эксплуатации:
1. Caller включает customer identifiers, emails, secrets или incident data в natural-language question.
2. API записывает raw text и generated SQL в logs/spans.
3. В deployments with OTLP configured эти данные уходят за service boundary в telemetry backend.

Влияние: sensitive query inputs и SQL literals могут попасть в observability systems с более широким доступом/retention, чем application database.

Рекомендация: redact или hash query text by default; полный query capture держать только за explicit debug flag with short retention. Не сохранять generated SQL literals в spans или normalize literals before export.

## Проверенные поверхности без main finding

- Direct entity lookup использует DuckDB parameters для DuckDB и escaped literals для ClickHouse (`src/serving/semantic_layer/query/entity_queries.py:27-41`). Direct `entity_id` SQL injection path не найден.
- Metric `window` проходит через `WINDOW_MAP`, а не raw interpolation (`src/serving/semantic_layer/query/metric_queries.py:12-38`).
- `stream.py` использует параметры для free-form `event_type` и `entity_id`; проблема там в tenant scoping, не в SQL injection.
- В repo нет Postgres serving backend. Postgres присутствует как Debezium CDC configuration (`src/ingestion/connectors/postgres_cdc.py`) с fixed connector fields/table include list; user-controlled Postgres SQL generation в serving path не найден.

## Notes

- Самый важный single fix: сделать SQL validation обязательным единым шагом для каждого NL-generated SQL path: normal query, paginated query, explain, batch query, DuckDB и ClickHouse.
- Нельзя полагаться на comment `sql is prevalidated`; `paginated_query` сейчас противоречит этому comment.
- Independent sub-agent verification не использовался; findings self-verified через source tracing и safe local monkeypatch checks.

Disclaimer: это AI-assisted first-pass security audit, не замена профессиональному penetration test. Он может пропустить subtle authorization paths, deployment-specific risks и backend permission issues.
