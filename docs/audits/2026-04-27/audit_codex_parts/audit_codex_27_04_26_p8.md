# Python SDK Audit - SDK/server mismatch findings

Дата: 2026-04-27  
Repo: `D:\DE_project`  
HEAD: `4a13d36`  
Scope: `sdk/agentflow`, публичный Python API, retries/timeouts, typed contracts, ошибки и совместимость с server API.

## Findings

### F1 - High - `contract_version` в Python SDK не совместим с server API versioning

Server versioning выбирается через header `X-AgentFlow-Version` или tenant pin: `src/serving/api/versioning.py:236`, `src/serving/api/versioning.py:249`, `src/serving/api/versioning.py:255`. Ответы также возвращают `X-AgentFlow-Version`, `X-AgentFlow-Latest-Version`, deprecated/warning headers: `src/serving/api/versioning.py:279`.

Python SDK вместо этого принимает `contract_version="entity:vN"` и локально фильтрует entity payload через `/v1/contracts/{entity}/{version}`: `sdk/agentflow/client.py:51`, `sdk/agentflow/client.py:171`, `sdk/agentflow/client.py:208`. HTTP client отправляет только `X-API-Key`: `sdk/agentflow/client.py:53`.

Impact: пользователь думает, что pinned SDK работает с нужной server API версией, но сервер продолжает отдавать latest или tenant-pinned date version. Это особенно опасно для `meta` transform и deprecation headers.

Fix: добавить явный параметр `api_version` или `agentflow_version`, отправлять `X-AgentFlow-Version`, читать response version headers, а `contract_version` оставить только для schema-contract filtering.

### F2 - High - Async SDK не поддерживает contract pinning вообще

Sync client имеет `contract_version` и `_apply_contract_version`: `sdk/agentflow/client.py:46`, `sdk/agentflow/client.py:171`. Async constructor принимает только `base_url`, `api_key`, `timeout`: `sdk/agentflow/async_client.py:46`, а `_get_entity` валидирует напрямую `envelope.data`: `sdk/agentflow/async_client.py:146`.

Impact: два публичных клиента дают разные typed-contract guarantees. Интеграция, которая проходит на sync SDK с `contract_version="order:v1"`, может сломаться или принять лишние поля на async SDK.

Fix: выровнять async API с sync: тот же `contract_version`, cache contracts, async `_get_contract`, единые contract tests для sync/async.

### F3 - High - Historical API (`as_of`) есть на сервере, но отсутствует в Python SDK

Server поддерживает `as_of` для entity и metric: `src/serving/api/routers/agent_query.py:247`, `src/serving/api/routers/agent_query.py:405`. Документация относит это к core API: `docs/api-reference.md:59`, `docs/api-reference.md:60`.

Python SDK методы не принимают `as_of`: `get_order/get_user/get_product/get_session` вызывают `_get_entity` без query params, а `_get_entity` строит только `/v1/entity/{type}/{id}`: `sdk/agentflow/client.py:143`, `sdk/agentflow/client.py:212`. `get_metric` передает только `window`: `sdk/agentflow/client.py:224`.

Impact: SDK не может использовать time-travel/freshness workflows, хотя сервер и docs объявляют их частью API.

Fix: добавить `as_of: datetime | str | None` в generic/entity/metric methods и нормализовать ISO UTC в query params.

### F4 - High - Серверные `meta` поля silently dropped by SDK models

Entity responses возвращают `meta.as_of`, `meta.is_historical`, `meta.freshness_seconds`: `src/serving/api/routers/agent_query.py:368`. Metric responses возвращают `meta` с historical context: `src/serving/api/routers/agent_query.py:495`.

Python models игнорируют лишние поля через `AgentFlowModel.model_config = ConfigDict(extra="ignore")`: `sdk/agentflow/models.py:7`. `EntityEnvelope` и `MetricResult` не имеют `meta`: `sdk/agentflow/models.py:11`, `sdk/agentflow/models.py:70`.

Impact: даже если добавить `as_of`, SDK потеряет серверный признак historical response. Пользователь не сможет отличить live value от historical value через typed model.

Fix: добавить `meta: dict[str, Any] = Field(default_factory=dict)` в entity envelope и metric/query response contracts, либо typed `EntityMeta`/`MetricMeta`.

### F5 - High - Catalog SDK model не соответствует server catalog

Server `/v1/catalog` возвращает `entities`, `metrics`, `streaming_sources`, `audit_sources`: `src/serving/api/main.py:314`. Entity/metric catalog также содержит `contract_version`: `src/serving/semantic_layer/catalog.py:157`, `src/serving/semantic_layer/catalog.py:168`.

Python SDK `CatalogResponse` моделирует только `entities` и `metrics`; `CatalogEntity`/`CatalogMetric` не включают `contract_version`: `sdk/agentflow/models.py:111`, `sdk/agentflow/models.py:123`.

Impact: SDK скрывает discovery/governance surface, который сервер рекламирует для agents. Через typed SDK нельзя обнаружить SSE stream, lineage/audit route и актуальные schema contract versions.

Fix: расширить `CatalogResponse` до полного server payload: `streaming_sources`, `audit_sources`, `contract_version` в entity/metric.

### F6 - Medium - Python SDK public API покрывает только часть public v1 server API

Maintained API reference перечисляет core/discovery routes: `/v1/search`, `/v1/contracts`, `/v1/contracts/{entity}`, `/v1/contracts/{entity}/{version}`, `/v1/contracts/{entity}/diff/...`, `/v1/contracts/{entity}/validate`, `/v1/lineage/...`, `/v1/changelog`: `docs/api-reference.md:69`.

Python SDK public methods ограничены entity/metric/query/health/catalog/batch helpers: `sdk/agentflow/client.py:212`, `sdk/agentflow/client.py:292`, `sdk/agentflow/client.py:296`. `query/explain` есть на server: `src/serving/api/routers/agent_query.py:126`, но SDK имеет только executing `query`: `sdk/agentflow/client.py:253`.

Impact: Python SDK не является full client для documented v1 API. Часть возможностей доступна только через private `_request` или CLI, что ломает typed contracts и error mapping.

Fix: добавить typed methods минимум для `explain_query`, `search`, contract list/get/diff/validate, `lineage`, `changelog`; явно задокументировать, какие admin/ops routes намеренно вне SDK.

### F7 - Medium - Dynamic entity registry на сервере конфликтует с hardcoded SDK entity API

Server грузит entity types из `contracts/entities/*.yaml`, и docs говорят, что новый тип доступен через `/v1/entity/{type}/{id}` без Python-кода: `docs/contracts/how-to-add-entity.md:3`, `src/serving/semantic_layer/entity_type_registry.py:58`.

Python SDK экспортирует только четыре hardcoded typed methods: `get_order`, `get_user`, `get_product`, `get_session`: `sdk/agentflow/client.py:212`. Generic `_get_entity` приватный: `sdk/agentflow/client.py:143`.

Impact: кастомная entity, поддержанная сервером и catalog, недоступна как публичный SDK call без обращения к private method или raw `_request`.

Fix: добавить public `get_entity(entity_type, entity_id, *, as_of=None) -> EntityEnvelope` и оставить typed convenience methods как thin wrappers.

### F8 - Medium - Retry helper умеет idempotent POST, но Python client не может его включить

`is_retryable_method` разрешает retry для `POST` только при наличии `Idempotency-Key`: `sdk/agentflow/retry.py:30`. Но `_request` не принимает custom headers и вызывает `is_retryable_method(method)` без headers: `sdk/agentflow/client.py:74`, `sdk/agentflow/client.py:83`.

Impact: SDK не может безопасно retry `POST /v1/query` или `POST /v1/batch`, хотя retry module уже содержит такой контракт. В результате временный 503 на query/batch сразу отдается пользователю.

Fix: добавить headers/idempotency_key в `_request` и public POST methods, либо убрать unreachable branch из retry contract и явно задокументировать no POST retries.

### F9 - Medium - Ошибки 403 и circuit-open не представлены как стабильные SDK errors

Auth middleware возвращает 403 при entity permission denial: `src/serving/api/auth/middleware.py:102`. Python SDK мапит только 401, 429, 404; остальные 4xx становятся generic `AgentFlowError`: `sdk/agentflow/client.py:121`, `sdk/agentflow/client.py:137`.

Circuit breaker может бросить `CircuitOpenError`, но этот класс наследуется от `RuntimeError`, не от `AgentFlowError`: `sdk/agentflow/circuit_breaker.py:13`; root package `__all__` его не экспортирует: `sdk/agentflow/__init__.py:6`.

Impact: callers не могут надежно различать auth failure, permission denied, rate limit, not found и local circuit-open через единое SDK error taxonomy.

Fix: добавить `PermissionDeniedError` для 403, экспортировать resilience errors из root или сделать `CircuitOpenError(AgentFlowError)`.

### F10 - Medium - Package claims typed, но wheel/sdist не содержат `py.typed`

`sdk/pyproject.toml` объявляет classifier `Typing :: Typed`: `sdk/pyproject.toml:16`. В `sdk/agentflow` нет `py.typed`, и wheel `sdk/dist/agentflow_client-1.1.0-py3-none-any.whl` содержит Python modules/templates, но не marker file.

Impact: type checkers не обязаны считать package PEP 561 typed package, несмотря на публичный classifier. Это делает typed SDK contracts менее полезными для downstream users.

Fix: добавить `sdk/agentflow/py.typed`, убедиться, что hatch включает marker в wheel/sdist, и добавить package artifact test.

## Cross-cutting recommendation

Сейчас Python SDK лучше считать partial convenience client, а не authoritative typed client for v1. Для release-quality SDK/server compatibility нужен один источник truth: OpenAPI или generated contract snapshot, из которого проверяются Python models, TS models, docs и live FastAPI routes.

Минимальный next step:

1. Ввести `X-AgentFlow-Version` support и `as_of` в Python SDK.
2. Выровнять sync/async contract pinning.
3. Расширить `CatalogResponse`/`EntityEnvelope`/`MetricResult` до полного server payload.
4. Добавить contract tests, которые сравнивают Python SDK public methods с maintained `docs/api-reference.md` routes.

## Verification notes

Код SDK/server не изменялся. Отчет основан на статической сверке `sdk/agentflow`, `src/serving/api`, `src/serving/semantic_layer`, `docs/api-reference.md`, `docs/contracts/how-to-add-entity.md`, `tests/unit/test_sdk_backwards_compat.py`, `tests/integration/test_contracts.py`, а также на проверке содержимого wheel/sdist для `py.typed`.
