# Test Coverage Gap Audit

Дата: 2026-04-27  
Репозиторий: `D:\DE_project`  
HEAD: `4a13d36`

## Бейзлайн и метод

- Измеренный бейзлайн до работы: 597 tracked files, `dist` = 1,055,399 bytes, 6,197 key-like JSON entries across 25 tracked JSON files.
- Тестовая поверхность: `tests/unit` = 351 тест, `tests/integration` = 200, `tests/sdk` = 17, `tests/contract` = 8, `tests/e2e` = 18, `sdk-ts/tests` = 16.
- `coverage.xml` от 2026-04-25 показывает общий line-rate `62.3%` (`4298/6899` lines). Его использовал как индикатор пробелов, не как единственный критерий.
- Сопоставление делалось по runtime entrypoints в `src`, Python SDK в `sdk/agentflow`, TS SDK в `sdk-ts/src` и тестам в `tests/unit`, `tests/integration`, `tests/sdk`, `tests/contract`, `tests/e2e`.

## Карта покрытия runtime paths

| Runtime path | Текущие тесты | Риск |
| --- | --- | --- |
| `src/serving/api/routers/agent_query.py` | unit/integration/e2e покрывают entity, metrics, query, pagination, time-travel, PII, cache, tenant routing | Средний: базовый путь покрыт, но SDK/contract покрывают только малую часть |
| `src/serving/api/routers/batch.py` | `tests/integration/test_batch.py`, базовый e2e smoke | Высокий: нет tenant/permission/PII сценариев для batch как единой операции |
| `src/serving/api/routers/stream.py` | integration helper-level SSE, e2e first event, TS unit stream | Средний: мало edge cases вокруг keepalive, legacy schema, duplicate suppression |
| `src/serving/api/routers/lineage.py` | basic integration happy path/404/auth/catalog | Высокий: нет tenant isolation и malformed historical data |
| `src/serving/api/routers/slo.py` | integration по трем measurements | Средний: нет missing/empty/unsupported config paths |
| `src/serving/api/routers/webhooks.py`, `src/serving/api/webhook_dispatcher.py` | integration CRUD/test/retry/filter/persistence | Высокий: outbound side effects не проверены на tenant leakage и timeout/4xx semantics |
| `src/serving/api/routers/alerts.py`, `src/serving/api/alerts/*` | integration create/update/delete/test/escalation/flapping/history | Высокий: evaluator/deliver edge cases почти не имеют unit-level покрытия |
| `src/processing/outbox.py`, `src/processing/event_replayer.py` | integration replay/outbox happy path, retry, restart, trace headers | Высокий: max-retries/final failure and invalid payload paths не закрыты |
| `src/processing/local_pipeline.py`, `src/ingestion/producers/event_producer.py` | несколько integration через `_process_event`; producer фактически не покрыт | Высокий: ingest/runtime generator и CLI burst path могут сломаться без сигнала |
| `src/serving/backends/clickhouse_backend.py` | только bandit filename fixtures | Критичный: альтернативный serving backend имеет `0%` line coverage |
| `src/quality/monitors/freshness_monitor.py` | нет прямых тестов | Высокий: мониторинг SLA может молча сломаться |
| `tests/contract/test_openapi_compliance.py` + `docs/openapi.json` | contract проверяет только 6 documented paths | Критичный: большая часть публичных API не входит в contract/e2e matrix |
| `sdk/agentflow/*`, `sdk-ts/src/*` | Python unit/contract частично; TS только mocked unit | Высокий: нет live TS contract, Python contract не покрывает batch/health/catalog/errors полностью |

## Критичные непокрытые сценарии и тесты, которые надо добавить

### 1. Extended API routes не входят в contract suite

Сейчас `docs/openapi.json` содержит только `/v1/catalog`, `/v1/entity/{entity_type}/{entity_id}`, `/v1/health`, `/v1/metrics/{metric_name}`, `/v1/query`, `/v1/stream/events`. Runtime при этом включает `/v1/batch`, `/v1/webhooks`, `/v1/alerts`, `/v1/deadletter`, `/v1/lineage`, `/v1/slo`, `/v1/contracts`, `/v1/admin/*`, `/v1/search`, `/v1/changelog`.

Добавить:
- `tests/contract/test_openapi_compliance.py::test_documented_openapi_includes_all_public_v1_routes`
- `tests/contract/test_extended_openapi_compliance.py::test_extended_routes_validate_against_live_api`
- `tests/e2e/test_ops_extended_surfaces.py::test_ops_journey_covers_deadletter_slo_lineage_webhooks_alerts_batch`

### 2. Tenant isolation не проверена для batch, lineage, webhooks и alerts

Entity/metric/query tenant scoping покрыт, но агрегирующие и side-effect пути обходят те же данные иначе. Особо рискованно: `lineage` читает `pipeline_events` напрямую, webhook dispatcher выбирает все pipeline events, alerts оценивают rule tenant через dispatcher.

Добавить:
- `tests/integration/test_batch.py::test_batch_entity_enforces_allowed_entity_types`
- `tests/integration/test_batch.py::test_batch_entity_metric_and_query_are_scoped_to_api_key_tenant`
- `tests/integration/test_batch.py::test_batch_masks_pii_for_tenant_scoped_entity_results`
- `tests/integration/test_lineage.py::test_lineage_does_not_return_other_tenant_events_for_shared_entity_id`
- `tests/integration/test_webhooks.py::test_dispatcher_does_not_deliver_cross_tenant_pipeline_events`
- `tests/integration/test_alerts.py::test_dispatcher_evaluates_alert_rules_with_rule_tenant_only`

### 3. ClickHouse serving backend имеет нулевое runtime coverage

`src/serving/backends/clickhouse_backend.py` покрыт на `0%`, хотя `SERVING_BACKEND=clickhouse` является runtime-путем через `create_backend` и `QueryEngine`. Без тестов можно сломать SQL translation, Basic Auth, HTTP error mapping, `UNKNOWN_TABLE`, demo seeding и health.

Добавить:
- `tests/unit/test_clickhouse_backend.py::test_translate_sql_covers_filters_casts_booleans_and_intervals`
- `tests/unit/test_clickhouse_backend.py::test_request_sends_basic_auth_database_and_json_format`
- `tests/unit/test_clickhouse_backend.py::test_unknown_table_http_error_maps_to_backend_missing_table`
- `tests/unit/test_clickhouse_backend.py::test_health_reports_error_on_transport_failure`
- `tests/integration/test_query_engine_clickhouse_backend.py::test_query_engine_uses_clickhouse_backend_when_configured`

### 4. Ingestion producer и local pipeline success paths почти не защищены

`src/ingestion/producers/event_producer.py` и `src/processing/local_pipeline.py` являются первичным source/runtime path. Текущие тесты проверяют часть `_process_event` через failure/kafka scenarios, но не защищают генераторы, Decimal serialization, product/click/payment branches, Iceberg fallback и CLI burst mode.

Добавить:
- `tests/unit/test_event_producer.py::test_generated_order_payment_click_and_product_events_validate_against_schemas`
- `tests/unit/test_event_producer.py::test_decimal_encoder_preserves_json_serializable_amounts`
- `tests/unit/test_event_producer.py::test_run_producer_flushes_on_keyboard_interrupt`
- `tests/unit/test_local_pipeline.py::test_process_event_commits_order_product_click_and_payment_success_paths`
- `tests/unit/test_local_pipeline.py::test_process_event_rolls_back_when_storage_write_fails`
- `tests/integration/test_local_pipeline_cli.py::test_local_pipeline_burst_writes_validated_and_deadletter_counts`

### 5. Freshness monitor is a blind spot

`src/quality/monitors/freshness_monitor.py` имеет `0%` line coverage. Это отдельный long-running runtime process, который отвечает за SLA metrics и alert signal. Сейчас нет защиты от invalid JSON, missing timestamp, bad timestamp, Kafka EOF/error веток, rolling SLA window и consumer shutdown.

Добавить:
- `tests/unit/test_freshness_monitor.py::test_process_message_observes_latency_and_updates_sla_compliance`
- `tests/unit/test_freshness_monitor.py::test_process_message_skips_invalid_json_missing_timestamp_and_bad_timestamp`
- `tests/unit/test_freshness_monitor.py::test_sla_window_is_capped_to_configured_size`
- `tests/unit/test_freshness_monitor.py::test_start_ignores_partition_eof_logs_real_kafka_errors_and_closes_consumer`

### 6. SDK contract coverage недостаточен для live runtime compatibility

Python SDK contract покрывает typed entity/query/paginate/auth/not-found. Не покрыты live batch, health/catalog model compatibility, rate-limit mapping, contract version filtering и async SDK contract. TS SDK покрыт только mocked unit tests; live API compatibility отсутствует.

Добавить:
- `tests/contract/test_sdk_contract.py::test_batch_returns_partial_errors_with_sdk_builders`
- `tests/contract/test_sdk_contract.py::test_health_and_catalog_models_match_live_api`
- `tests/contract/test_sdk_contract.py::test_rate_limit_response_maps_to_rate_limit_error`
- `tests/contract/test_async_sdk_contract.py::test_async_client_entity_query_pagination_and_errors_against_live_api`
- `tests/unit/test_sdk_client.py::test_contract_version_filters_allowed_fields_and_caches_contract`
- `sdk-ts/tests/contract-live.test.ts::uses_live_api_for_entity_query_batch_stream_and_errors`
- `sdk-ts/tests/client.test.ts::applies_contract_version_and_rejects_missing_required_fields`

### 7. Webhook and alert delivery failure semantics need direct tests

Webhook tests cover 5xx retry and HMAC. Alert tests cover escalation. Missing: timeout/transport retries, 4xx no-retry behavior, each attempt logged, final failure history, and cross-tenant side effects.

Добавить:
- `tests/integration/test_webhooks.py::test_deliver_retries_timeout_and_logs_each_failed_attempt`
- `tests/integration/test_webhooks.py::test_deliver_stops_after_4xx_and_records_single_failure`
- `tests/integration/test_webhooks.py::test_inactive_webhook_is_not_delivered_by_dispatcher`
- `tests/integration/test_alerts.py::test_alert_delivery_retries_timeout_and_records_failure_history`
- `tests/unit/test_alert_evaluator.py::test_change_pct_handles_zero_previous_value_and_negative_threshold`
- `tests/unit/test_alert_evaluator.py::test_window_to_timedelta_rejects_unsupported_units`

### 8. Dead-letter replay and outbox terminal states need negative coverage

Replay/outbox happy path is good, but terminal failure paths are still risky: missing replay/dismiss IDs, invalid stored payload shape, max retries marking both outbox and dead-letter failed, Kafka delivery callback failure, producer API fallback.

Добавить:
- `tests/integration/test_deadletter.py::test_replay_missing_event_returns_404`
- `tests/integration/test_deadletter.py::test_dismiss_missing_event_returns_404`
- `tests/integration/test_deadletter.py::test_deadletter_detail_non_object_payload_returns_500_without_crashing`
- `tests/integration/test_outbox.py::test_outbox_marks_entry_and_deadletter_failed_after_max_retries`
- `tests/integration/test_outbox.py::test_outbox_invalid_json_payload_does_not_mark_sent`
- `tests/unit/test_outbox.py::test_produce_to_kafka_raises_on_delivery_callback_error`

### 9. Stream, SLO and lineage edge cases need contract-like assertions

These routes are agent-facing operational context. Existing tests cover normal output, but not degraded input shapes that occur during migrations and partial deployments.

Добавить:
- `tests/integration/test_streaming.py::test_stream_events_yields_keepalive_when_no_rows_match`
- `tests/integration/test_streaming.py::test_fetch_recent_events_supports_legacy_pipeline_events_schema`
- `tests/integration/test_streaming.py::test_stream_deduplicates_events_across_poll_iterations`
- `tests/integration/test_slo.py::test_slo_missing_config_returns_503`
- `tests/integration/test_slo.py::test_slo_empty_pipeline_events_returns_breached_without_500`
- `tests/integration/test_slo.py::test_slo_unsupported_measurement_returns_explicit_error`
- `tests/integration/test_lineage.py::test_lineage_handles_rows_without_validated_event_as_unvalidated`
- `tests/integration/test_lineage.py::test_lineage_bad_processed_at_returns_404_not_500`

## Приоритет внедрения

1. Contract visibility: сначала расширить OpenAPI/contract/e2e на все public `/v1` routes.
2. Tenant isolation: batch, lineage, webhooks, alerts.
3. ClickHouse backend: unit + QueryEngine integration before declaring backend support stable.
4. Ingestion/monitoring: producer/local pipeline/freshness monitor.
5. SDK live compatibility: Python async + TS live contract.
6. Negative terminal states: outbox/deadletter and outbound delivery failures.

## Минимальный первый пакет тестов

Если делать поэтапно, самый высокий risk-reduction даст этот набор:

- `tests/contract/test_openapi_compliance.py::test_documented_openapi_includes_all_public_v1_routes`
- `tests/integration/test_batch.py::test_batch_entity_metric_and_query_are_scoped_to_api_key_tenant`
- `tests/integration/test_lineage.py::test_lineage_does_not_return_other_tenant_events_for_shared_entity_id`
- `tests/integration/test_webhooks.py::test_dispatcher_does_not_deliver_cross_tenant_pipeline_events`
- `tests/unit/test_clickhouse_backend.py::test_unknown_table_http_error_maps_to_backend_missing_table`
- `tests/unit/test_freshness_monitor.py::test_process_message_observes_latency_and_updates_sla_compliance`
- `tests/unit/test_event_producer.py::test_generated_order_payment_click_and_product_events_validate_against_schemas`
- `tests/contract/test_async_sdk_contract.py::test_async_client_entity_query_pagination_and_errors_against_live_api`
