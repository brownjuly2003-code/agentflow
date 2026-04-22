# T10 — Entity types contract registry

**Priority:** P3 · **Estimate:** 1-2 дня

## Goal

Вынести 4 hardcoded entity types (`order`, `user`, `product`, `session`) в YAML-реестр контрактов, чтобы можно было зарегистрировать новый тип без форка Python кода.

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- Entity types сейчас захардкожены где-то в `src/serving/semantic_layer/` (grep `grep -rn "order\|user\|product\|session" src/serving/semantic_layer/` чтобы найти точное место)
- Каждый тип имеет: schema (поля + типы), primary key, source table, relations
- Цель — data-driven definition через `contracts/entities/*.yaml` + registry loader
- API `/v1/entity/{type}/{id}` должен остаться backward-compatible

## Deliverables

1. **Директория** `contracts/entities/` с 4 YAML-файлами (по одному на legacy type):
   ```yaml
   # contracts/entities/order.yaml
   name: order
   version: 1
   primary_key: order_id
   source_table: orders
   schema:
     order_id:
       type: string
       required: true
     user_id:
       type: string
       required: true
     total:
       type: decimal
       required: true
     status:
       type: enum
       values: [pending, paid, cancelled, refunded]
     created_at:
       type: timestamp
       required: true
   relations:
     - target: user
       type: many_to_one
       foreign_key: user_id
     - target: product
       type: many_to_many
       through: order_items
   ```
   + аналогичные `user.yaml`, `product.yaml`, `session.yaml` (заполнить на основе текущих hardcoded definitions)

2. **`src/serving/semantic_layer/contract_registry.py`**:
   - Pydantic models:
     - `FieldSpec` (type, required, values, description)
     - `RelationSpec` (target, type, foreign_key, through)
     - `EntityContract` (name, version, primary_key, source_table, schema, relations)
   - `ContractRegistry` class:
     - `__init__(contracts_dir: Path)` — load all `*.yaml` из директории на startup
     - `get(name: str, version: int | None = None) -> EntityContract` — 404-style error если нет
     - `list() -> list[str]` — имена всех зарегистрированных типов
     - `reload()` — re-scan директорию (для hot-reload)
   - Валидация при load:
     - `primary_key` есть в `schema`
     - `relations[].target` указывает на existing type (после всех файлов загружены)
     - `version` — положительное integer
     - Имя файла совпадает с `name` внутри (`order.yaml` → `name: order`)
   - Fail-fast: если любой контракт невалиден — `raise ContractValidationError` на startup, сервер не поднимается

3. **Обновить** `src/serving/api/routers/entity.py`:
   - Заменить hardcoded types на `ContractRegistry`
   - Инжект через `Depends(get_registry)` или `app.state.registry`
   - Endpoint `GET /v1/catalog/entities` возвращает `registry.list()`
   - `GET /v1/entity/{type}/{id}`:
     - Если `type` не в registry → 404 `{"error": "unknown_entity_type", "available": registry.list()}`
     - Иначе — использовать `contract.source_table` + `contract.primary_key` для query

4. **Registry в app startup** (`src/serving/api/main.py` или где FastAPI app создаётся):
   ```python
   @app.on_event("startup")
   async def load_contracts():
       app.state.registry = ContractRegistry(Path("contracts/entities"))
   ```
   + SIGHUP handler для hot-reload (Unix только, Windows можно skip)

5. **Тесты**:
   - `tests/contract/test_entity_registry.py`:
     - All 4 legacy types загружаются
     - Invalid contract (primary_key не в schema) → `ContractValidationError`
     - Relation на несуществующий target → `ContractValidationError`
     - Duplicate name в двух файлах → `ContractValidationError`
   - `tests/contract/test_api_backward_compat.py`:
     - OpenAPI spec для `/v1/entity/{type}/{id}` не изменился
     - Все 4 legacy types возвращают те же response shapes что до рефакторинга (golden test с snapshot'ами)
   - `tests/contract/test_custom_entity.py`:
     - Добавить `contracts/entities/example_custom.yaml` в test fixture
     - Restart registry → new type available через `/v1/catalog/entities` и `/v1/entity/example_custom/{id}`

6. **Документация** `docs/contracts/how-to-add-entity.md`:
   - Step-by-step: написать YAML, положить в `contracts/entities/`, перезапустить (или SIGHUP)
   - Reference всех поддерживаемых `type` values (string, int, decimal, timestamp, enum, boolean)
   - Relations semantics
   - Version bumping: breaking change = новая версия, `?version=2` query param (опционально в v1, но задокументировать план)
   - Примеры + gotchas

7. **Обновить** `docs/architecture.md` (если есть) — упомянуть registry

8. Коммит: `feat(semantic-layer): extract entity types into YAML contract registry`

## Acceptance

- `make test` зелёный, включая новые `tests/contract/` tests
- `curl http://localhost:8000/v1/catalog/entities` возвращает `["order", "user", "product", "session"]`
- Snapshot tests: все 4 legacy endpoints (`/v1/entity/order/123`, etc.) возвращают те же response shapes что до рефакторинга
- Добавление нового YAML `contracts/entities/example_custom.yaml` + restart → тип доступен через API без изменения Python кода
- SIGHUP на живой процесс (Linux) → `registry.reload()` подхватывает новые YAML (Windows — skip)
- OpenAPI spec diff (`openapi.json` до и после) — no breaking changes

## Notes

- НЕ ломать SDK clients — OpenAPI spec для `/v1/entity/{type}/{id}` остаётся тем же, URL pattern тот же
- Relations — **declarative-only** в v1 (для документации и discovery), auto-join не реализовывать. Это — отдельный следующий таск
- Versioning через `version` field — breaking change = bump version. Параллельные versions поддержать через `?version=` query param — **опционально в v1**, но документировать план
- `source_table` в контракте должна быть allowlisted в sqlglot AST validator — иначе security hole. Проверить что регистрация нового контракта автоматически расширяет allowlist (или требует отдельного config change с code review)
- Hot-reload — опционально, если легко. Обязательно — reload через SIGHUP (а не автоматический inotify watcher — overkill для v1)
- Performance: registry загружается один раз на startup, далее in-memory. Нет I/O на request path
