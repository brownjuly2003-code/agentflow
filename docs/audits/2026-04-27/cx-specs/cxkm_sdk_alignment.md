# Task: Python SDK alignment with server API contract (Codex audit p8 F1-F10)

Repo: `D:\DE_project` (AgentFlow runtime). HEAD: `1c24e58`. Branch: `main`.

## Goal

Закрыть 10 findings из Codex audit p8 (`audit_codex_27_04_26.md`) — sync/async Python SDK сейчас partial typed convenience client, нужно поднять до authoritative typed client for v1.

## Context

Полный аудит в `D:\DE_project\audit_codex_27_04_26.md` секция p8. Также релевантные файлы (читай напрямую):

- `sdk/agentflow/client.py` (sync client, 350 LOC)
- `sdk/agentflow/async_client.py` (async client, ~250 LOC)
- `sdk/agentflow/models.py` (Pydantic models)
- `sdk/agentflow/retry.py` (RetryPolicy, is_retryable_method, RETRYABLE_STATUS)
- `sdk/agentflow/circuit_breaker.py` (CircuitBreaker, CircuitOpenError)
- `sdk/agentflow/exceptions.py` (AgentFlowError + subclasses)
- `sdk/agentflow/__init__.py` (public exports)
- `sdk/pyproject.toml` (`Typing :: Typed` classifier present, но `py.typed` файл отсутствует)
- `src/serving/api/main.py:314` — `/v1/catalog` payload (entities, metrics, streaming_sources, audit_sources)
- `src/serving/api/versioning.py:236-279` — server API versioning (X-AgentFlow-Version request + response headers)
- `src/serving/api/routers/agent_query.py:247,405` — server `as_of` параметр на entity и metric
- `src/serving/api/routers/agent_query.py:368,495` — server `meta` поля в entity/metric responses
- `src/serving/semantic_layer/catalog.py:157,168` — `contract_version` в catalog entity/metric
- `src/serving/api/auth/middleware.py:102` — server возвращает 403 на entity permission denial
- `docs/api-reference.md` — narrative API ref на v1 surface
- `tests/contract/test_sdk_contract.py` — existing SDK contract tests
- `tests/unit/test_sdk_client.py`, `test_async_client.py`, `test_sdk_backwards_compat.py`

## Scope (10 findings)

### F1 — `X-AgentFlow-Version` header support (HIGH)

В `AgentFlowClient.__init__` добавить `api_version: str | None = None`. Если задан — отправлять как header `X-AgentFlow-Version` на каждом request. Читать response headers `X-AgentFlow-Version`, `X-AgentFlow-Latest-Version`, `X-AgentFlow-Deprecated`, `X-AgentFlow-Deprecation-Warning` и хранить последний результат в `client.last_server_version` / `client.last_deprecation_warning` (read-only properties).

`contract_version` оставить ТОЛЬКО для schema-contract filtering через `/v1/contracts/{entity}/{version}`, не путать с API версией.

### F2 — Async SDK contract pinning parity (HIGH)

`AsyncAgentFlowClient.__init__` добавить `contract_version: str | None = None` и `api_version: str | None = None`. Реализовать тот же `_apply_contract_version()` flow через async `_get_contract()`. Cache contracts (in-memory dict). `_get_entity` async client должен пропускать через contract filter, как sync.

### F3 — `as_of` time-travel parameter (HIGH)

Add `as_of: datetime | str | None = None` parameter to:
- `AgentFlowClient._get_entity` + all typed entity helpers (`get_order/get_user/get_product/get_session`)
- `AgentFlowClient.get_metric`
- `AsyncAgentFlowClient` соответствующие methods

Normalize to ISO UTC string in query params (`?as_of=2026-04-25T12:00:00Z`).

### F4 — `meta` field в response models (HIGH)

Добавить в models.py:
- `class EntityMeta(BaseModel)`: `as_of: str | None = None`, `is_historical: bool = False`, `freshness_seconds: float | None = None`
- `class MetricMeta(BaseModel)`: same fields
- `EntityEnvelope.meta: EntityMeta | None = None`
- `MetricResult.meta: MetricMeta | None = None`

### F5 — Full `CatalogResponse` (HIGH)

Расширить `CatalogResponse` model, чтобы включал:
- `streaming_sources: list[CatalogStreamingSource]`
- `audit_sources: list[CatalogAuditSource]`
- `CatalogEntity` + `CatalogMetric` получают `contract_version: str | None = None`

Define new schemas matching server `/v1/catalog` payload — посмотри в `src/serving/semantic_layer/catalog.py` и `src/serving/api/main.py:314`.

### F6 — Public methods для discovery/governance routes (MEDIUM)

Add typed methods на sync + async client:
- `explain_query(question: str, contract_version: str | None = None) -> QueryExplanation` (POST /v1/query/explain)
- `search(query: str, *, limit: int = 10, entity_types: list[str] | None = None) -> SearchResults`
- `list_contracts() -> list[ContractSummary]` (GET /v1/contracts)
- `get_contract(entity: str, version: str | None = None) -> EntityContract`
- `diff_contracts(entity: str, from_version: str, to_version: str) -> ContractDiff`
- `validate_contract(entity: str, payload: dict) -> ContractValidation`
- `get_lineage(entity_type: str, entity_id: str) -> Lineage`
- `get_changelog() -> Changelog`

Доплнительно — generic `get_entity(entity_type: str, entity_id: str, *, as_of=None) -> EntityEnvelope` для F7.

Admin/operational routes (`/v1/admin/*`, `/v1/webhooks`, `/v1/alerts`, `/v1/deadletter`, `/v1/slo`, `/v1/stream/events`, `/v1/batch`) — НЕ добавлять public typed methods, явно задокументировать в SDK README. (Batch уже есть.)

### F7 — Public `get_entity()` (MEDIUM)

`AgentFlowClient.get_entity(entity_type: str, entity_id: str, *, as_of=None) -> EntityEnvelope` — public method без typed unwrap. Существующие `get_order/get_user/get_product/get_session` остаются как thin convenience wrappers, делегируют `get_entity()` + cast в типизованную модель.

### F8 — Idempotent POST retry support (MEDIUM)

Расширить `_request()` (и async equivalent) чтобы принимать `headers: dict[str, str] | None = None`. Public POST methods (`query()`, `batch()`, `validate_contract()`) принимают `idempotency_key: str | None = None`; если задан — добавляют `Idempotency-Key` header и retry становится possible через `is_retryable_method(method, headers={"Idempotency-Key": ...})`.

Проверить что `is_retryable_method` принимает и использует headers — если нет, расширить signature и логику.

### F9 — Stable error taxonomy (MEDIUM)

- Add `PermissionDeniedError(AgentFlowError)` для 403 responses. Map в `_handle_response` / async equivalent.
- `CircuitOpenError` сейчас наследуется от `RuntimeError`. Изменить на `CircuitOpenError(AgentFlowError)`. Добавить в `agentflow/__init__.py:__all__` re-export.

### F10 — `py.typed` marker (MEDIUM)

- Создать пустой `sdk/agentflow/py.typed`.
- Убедиться что Hatch wheel/sdist включают marker (`include` rule в `sdk/pyproject.toml` под `[tool.hatch.build.targets.wheel]`).
- Add unit test `tests/unit/test_sdk_packaging.py::test_sdk_wheel_contains_py_typed_marker` — открывает `sdk/dist/agentflow_client-*.whl` (если присутствует) или вызывает `python -m build sdk` и проверяет contents.

## Tests (обязательно)

В `tests/`:
- `tests/contract/test_sdk_contract.py::test_sync_client_sends_x_agentflow_version_header` (F1)
- `tests/contract/test_sdk_contract.py::test_async_client_sends_x_agentflow_version_header` (F1+F2)
- `tests/contract/test_sdk_contract.py::test_async_client_filters_by_contract_version` (F2)
- `tests/contract/test_sdk_contract.py::test_get_entity_with_as_of_sends_query_param` (F3)
- `tests/contract/test_sdk_contract.py::test_metric_response_exposes_meta_fields` (F4)
- `tests/contract/test_sdk_contract.py::test_catalog_exposes_streaming_and_audit_sources` (F5)
- `tests/contract/test_sdk_contract.py::test_explain_query_returns_typed_result` (F6)
- `tests/contract/test_sdk_contract.py::test_search_returns_typed_results` (F6)
- `tests/contract/test_sdk_contract.py::test_get_lineage_returns_typed_result` (F6)
- `tests/unit/test_sdk_client.py::test_get_entity_generic_method` (F7)
- `tests/unit/test_sdk_client.py::test_post_with_idempotency_key_is_retried` (F8)
- `tests/unit/test_sdk_client.py::test_403_maps_to_permission_denied_error` (F9)
- `tests/unit/test_sdk_client.py::test_circuit_open_inherits_from_agentflow_error` (F9)
- `tests/unit/test_sdk_packaging.py::test_sdk_wheel_contains_py_typed_marker` (F10)

## Acceptance

1. `python -m pytest tests/unit tests/integration tests/contract tests/sdk -p no:cacheprovider -p no:schemathesis -q` — 0 failures, 0 errors. Skipped — env-gated OK.
2. Все новые tests реально fail на parent commit `1c24e58` и pass на твоём commit.
3. `sdk/agentflow/__init__.py:__all__` экспортирует новые public errors (PermissionDeniedError) и не убирает существующие.
4. Backward compat: existing `from agentflow import AgentFlowClient` + старые typed methods продолжают работать без изменений в callsite сценариях из `tests/unit/test_sdk_backwards_compat.py`.
5. `sdk/pyproject.toml` версия НЕ меняется (остаётся 1.1.0).

## Notes / Constraints

- НЕ трогать `helm/`, `k8s/`, `.github/workflows/`, `docs/api-reference.md` (последний — отдельный doc update follow-up).
- НЕ трогать TS SDK (`sdk-ts/`).
- НЕ менять server API. Все changes только в `sdk/`, `tests/`.
- Если `is_retryable_method` сигнатура несовместима — расширь её, но сохрани backward compat (default args).
- Если scope F6 (8 новых typed methods) окажется крупнее — реализуй F1-F5 + F7 + F8 + F9 + F10 полностью + F6 ТОЛЬКО для `explain_query` и `search`. Остальные F6 routes (contracts/lineage/changelog) — отметь TODO с pointer на этот finding.
- Use `httpx.Client.headers` for static headers like `X-API-Key`; per-request headers через `headers=` argument в `request()`.

## Deliverables

- Diff применимый через `git apply` (или прямые file edits).
- Краткий summary changes + список новых tests.
- Acceptance run output.
