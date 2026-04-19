# AgentFlow — Commercial Quality v4
**Date**: 2026-04-11  
**Source**: Research — "AgentFlow Market Landscape and Path to Commercial Product"  
**Scope**: Technical quality only (business/pricing/compliance скipped)  
**Goal**: Закрыть gap между working prototype и commercial-grade product  
**Executor**: Codex

---

## Граф зависимостей

```
TASK 1 (Security/bcrypt)
  └─► TASK 2 (Tenant isolation)
        └─► TASK 7 (API versioning)    — нужна tenant модель для pinning
        └─► TASK 8 (Helm chart)        — нужна tenant config + secrets в values.yaml

TASK 3 (Iceberg sink)                  — независим, можно сразу после Task 1

TASK 4 (Contract registry)
  └─► TASK 9 (Schema evolution)        — evolution checker нужен registry

TASK 5 (DR / backup)                   — независим
TASK 6 (SDK versioning)                — независим

TASK 10 (DORA / CI gates)             — последним, когда весь код стабилен
```

**Правило**: каждая задача начинается только когда все её зависимости завершены.

---

## TASK 1 — Security Hardening (bcrypt ключи, security headers)

**Выполняется первой** — меняет формат хранения API ключей в `config/api_keys.yaml`.  
Все последующие задачи, которые трогают auth или конфиг, должны работать с уже новым форматом.

**Gap из исследования**: Enterprise security questionnaires требуют encryption at rest, secrets management, key rotation.

### Что построить

```
src/serving/api/
  security.py               # NEW: security utilities + headers middleware
  auth.py                   # MODIFY: хранить bcrypt hash вместо plaintext
src/serving/api/main.py     # MODIFY: подключить security headers middleware
scripts/
  rotate_keys.py            # NEW: генерация ключей + запись hash
config/
  security.yaml             # NEW: security policy
tests/unit/
  test_security.py          # NEW
```

### API key hashing

```python
# БЫЛО: config/api_keys.yaml хранит ключи plaintext → риск при утечке конфига
# СТАЛО: хранятся только bcrypt хэши. Plaintext показывается один раз при создании.

# config/api_keys.yaml (новый формат)
keys:
  - key_hash: "$2b$12$..."    # bcrypt hash
    name: "Support Agent"
    tenant: "acme-corp"
    rate_limit_rpm: 60
    allowed_entity_types: null

# scripts/rotate_keys.py
def generate_key() -> tuple[str, str]:
    """Returns (plaintext_key, bcrypt_hash). Plaintext shown once, never stored."""
    key = f"af-{secrets.token_urlsafe(32)}"
    hash_ = bcrypt.hashpw(key.encode(), bcrypt.gensalt(rounds=12)).decode()
    return key, hash_
```

### Security headers middleware

```python
# src/serving/api/security.py
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'",
    "Referrer-Policy": "no-referrer",
}
```

### config/security.yaml

```yaml
security:
  key_hashing: bcrypt
  bcrypt_rounds: 12
  min_key_length: 32
  max_failed_auth_per_ip_per_hour: 10
  sensitive_headers_to_redact: [Authorization, X-API-Key]
  request_size_limit_bytes: 1_048_576
```

### Критерии приёмки

- [ ] `config/api_keys.yaml` хранит `key_hash` (bcrypt), не plaintext
- [ ] `python scripts/rotate_keys.py` — генерирует ключ, печатает plaintext один раз, сохраняет hash
- [ ] Каждый response содержит security headers
- [ ] IP throttling после 10 неудачных auth за час → 429
- [ ] API ключи не попадают в логи (structlog redaction)
- [ ] `tests/unit/test_security.py` — 8+ тестов

---

## TASK 2 — Multi-Tenant Data Isolation на уровне DuckDB

**После Task 1** — использует обновлённый `auth.py` для извлечения `tenant_id`.

**Gap из исследования**: "Enterprise procurement asks: how are tenants isolated at compute and data layers?"

### Что построить

```
src/ingestion/
  tenant_router.py          # NEW: маршрутизация событий по tenant-топикам Kafka
src/serving/semantic_layer/
  query_engine.py           # MODIFY: scope всех запросов к tenant schema
src/serving/api/
  auth.py                   # MODIFY: добавить tenant_id в request context
config/
  tenants.yaml              # NEW: определения тенантов
tests/integration/
  test_tenant_isolation.py  # NEW
```

### Модель тенанта

```yaml
# config/tenants.yaml
tenants:
  - id: acme-corp
    display_name: "Acme Corp"
    kafka_topic_prefix: "acme"     # events.raw → acme.events.raw
    duckdb_schema: "acme"          # SELECT * FROM acme.orders_v2
    max_events_per_day: 1_000_000
    max_api_keys: 10
    allowed_entity_types: null     # null = все

  - id: demo
    display_name: "Demo Tenant"
    kafka_topic_prefix: "demo"
    duckdb_schema: "demo"
    max_events_per_day: 10_000
    max_api_keys: 2
    allowed_entity_types: ["order", "product"]
```

### Query scoping

```python
# БЫЛО: SELECT * FROM orders_v2 WHERE order_id = ?
# СТАЛО: SELECT * FROM {tenant_schema}.orders_v2 WHERE order_id = ?

class QueryEngine:
    def get_entity(self, entity_type: str, entity_id: str, tenant_id: str) -> dict:
        schema = self._get_tenant_schema(tenant_id)
        table = self.ENTITY_TABLES[entity_type]
        return self._conn.execute(
            f"SELECT * FROM {schema}.{table} WHERE entity_id = ?", [entity_id]
        ).fetchone()
```

### Cross-tenant isolation тест

```python
@pytest.mark.integration
def test_tenant_cannot_read_other_tenant_data(api_client_acme, api_client_demo):
    # Данные ORD-ACME засеяны в schema acme
    # Demo ключ пытается прочитать ORD-ACME
    resp = api_client_demo.get("/v1/entity/order/ORD-ACME")
    assert resp.status_code == 404  # не 200 с чужими данными
```

### Критерии приёмки

- [ ] Данные каждого тенанта в отдельной DuckDB schema (`acme.orders_v2`, `demo.orders_v2`)
- [ ] API key → tenant_id → schema, резолвится на каждом запросе
- [ ] Cross-tenant запрос → 404, никогда не 200 с чужими данными
- [ ] `config/tenants.yaml` — единственный источник правды
- [ ] `tests/integration/test_tenant_isolation.py` — 5+ тестов включая cross-tenant leakage
- [ ] Обратная совместимость: дефолтный тенант `demo` при отсутствии конфига

---

## TASK 3 — Production Iceberg Sink (PyIceberg)

**После Task 1** (bcrypt auth готов). Независим от Task 2, можно параллельно.

**Gap из исследования**: Core architectural promise — Kafka→Flink→**Iceberg**→Serving. Сейчас Iceberg no-op.

### Что построить

```
src/processing/
  iceberg_sink.py           # NEW: PyIceberg writer
  local_pipeline.py         # MODIFY: интеграция Iceberg sink
config/
  iceberg.yaml              # NEW: конфиг каталога
docker-compose.iceberg.yml  # NEW: Iceberg REST catalog
scripts/
  init_iceberg.py           # NEW: создание таблиц в каталоге
tests/integration/
  test_iceberg_sink.py      # NEW
```

### config/iceberg.yaml

```yaml
iceberg:
  catalog_type: rest
  catalog_uri: http://localhost:8181
  warehouse: /tmp/agentflow-warehouse
  namespace: agentflow
  tables:
    - name: orders
      partition_by: [days(created_at)]
    - name: payments
      partition_by: [days(created_at)]
    - name: clickstream
      partition_by: [hours(created_at)]
    - name: inventory
      partition_by: [days(created_at)]
    - name: dead_letter
      partition_by: [days(received_at)]
```

### src/processing/iceberg_sink.py

```python
from pyiceberg.catalog import load_catalog
import pyarrow as pa

class IcebergSink:
    def __init__(self, config_path: str = "config/iceberg.yaml"):
        cfg = yaml.safe_load(open(config_path))["iceberg"]
        self.catalog = load_catalog("agentflow",
            **{"uri": cfg["catalog_uri"], "warehouse": cfg["warehouse"]})
        self.namespace = cfg["namespace"]

    def write_batch(self, table_name: str, records: list[dict]) -> int:
        table = self.catalog.load_table(f"{self.namespace}.{table_name}")
        arrow_table = pa.Table.from_pylist(records, schema=table.schema().as_arrow())
        table.append(arrow_table)
        return len(records)

    def create_tables_if_not_exist(self) -> None: ...
```

### Интеграция в local_pipeline.py

```python
# После validate + enrich → пишем в DuckDB (serving) И в Iceberg (storage)
iceberg_sink = IcebergSink()
iceberg_sink.write_batch("orders", valid_order_events)
```

### docker-compose.iceberg.yml

```yaml
services:
  iceberg-rest:
    image: tabulario/iceberg-rest:0.6.0
    ports:
      - "8181:8181"
    environment:
      CATALOG_WAREHOUSE: /warehouse
      CATALOG_IO__IMPL: org.apache.iceberg.hadoop.HadoopFileIO
    volumes:
      - iceberg-warehouse:/warehouse
volumes:
  iceberg-warehouse:
```

### Критерии приёмки

- [ ] `python scripts/init_iceberg.py` создаёт 5 Iceberg таблиц
- [ ] `make demo` → события пишутся в DuckDB И в Iceberg
- [ ] `GET /v1/health` — репортит row counts из Iceberg таблиц
- [ ] `tests/integration/test_iceberg_sink.py` — 4+ теста
- [ ] `docs/architecture.md` обновлён: "Iceberg: local REST catalog in dev, AWS Glue в prod"

---

## TASK 4 — Semantic Contract Registry (версионированные схемы сущностей)

**После Task 2** (tenant isolation). Независим от Task 3.

**Gap из исследования**: "Feature stores ship explicit schema registries; agents need stable contracts to build against."

### Что построить

```
src/serving/semantic_layer/
  contract_registry.py      # NEW: SchemaContract, ContractVersion
  catalog.py                # MODIFY: embed contract version в catalog response
src/serving/api/routers/
  contracts.py              # NEW: /v1/contracts endpoints
config/
  contracts/
    order.v1.yaml
    order.v2.yaml
    metric.revenue.v1.yaml
tests/integration/
  test_contracts.py         # NEW
```

### Формат контракта

```yaml
# config/contracts/order.v1.yaml
entity: order
version: "1"
released: "2026-04-11"
status: stable              # stable | deprecated | experimental
fields:
  - name: order_id
    type: string
    required: true
    description: "Unique order identifier (ORD-{n} format)"
  - name: status
    type: enum
    values: [pending, processing, shipped, delivered, cancelled]
    required: true
  - name: total_amount
    type: float
    unit: USD
    required: true
  - name: user_id
    type: string
    required: true
  - name: created_at
    type: datetime
    required: true
breaking_changes: []
```

### API endpoints

```
GET /v1/contracts                           — список всех контрактов
GET /v1/contracts/{entity}                  — последняя stable версия
GET /v1/contracts/{entity}/{version}        — конкретная версия
GET /v1/contracts/{entity}/diff/{v1}/{v2}   — diff между версиями
```

### Diff response

```json
{
  "entity": "order",
  "from_version": "1",
  "to_version": "2",
  "breaking_changes": [
    {"type": "field_removed", "field": "legacy_id", "severity": "breaking"}
  ],
  "additive_changes": [
    {"type": "field_added", "field": "discount_amount", "severity": "non_breaking"}
  ]
}
```

### SDK pinning

```python
# Агенты могут зафиксировать версию контракта
client = AgentFlowClient(url, key, contract_version="order:v1")
# Ответы валидируются против v1; лишние поля из v2 игнорируются
```

### Критерии приёмки

- [ ] `GET /v1/contracts/order` возвращает схему с полями и типами
- [ ] `GET /v1/contracts/order/diff/1/2` — breaking vs additive изменения
- [ ] YAML файлы — единственный источник правды, загружаются при старте
- [ ] `AgentFlowClient(contract_version="order:v1")` валидирует ответы
- [ ] `tests/integration/test_contracts.py` — 6+ тестов

---

## TASK 5 — DR: Backup, Restore, RPO/RTO

**После Task 2** (tenant isolation — данные теперь по схемам, backup должен это учитывать). Независим от Task 4.

**Gap из исследования**: Well-Architected reliability pillar; enterprise procurement asks "what happens when it crashes?"

### Что построить

```
scripts/
  backup.py                 # NEW: backup DuckDB + config → timestamped .tar.gz
  restore.py                # NEW: restore из архива
  verify_backup.py          # NEW: проверка SHA-256 manifest
docs/
  disaster-recovery.md      # NEW: DR runbook с RPO/RTO
.github/workflows/
  backup.yml                # NEW: ночной автобэкап
```

### scripts/backup.py

```python
"""
Процедура:
1. DuckDB checkpoint (flush WAL)
2. Копирование DuckDB файла с timestamp
3. Экспорт config/ (tenants, api_keys, contracts, slo, pii_fields)
4. SHA-256 manifest по всем файлам
5. Сжатие в .tar.gz
6. (Опционально) upload в S3/GCS если BACKUP_S3_BUCKET задан

Использование:
  python scripts/backup.py --output /backups/
  python scripts/backup.py --output s3://my-bucket/agentflow-backups/
"""
def backup(output_dir: str) -> BackupManifest:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    # ... implementation
    return BackupManifest(
        timestamp=timestamp,
        duckdb_size_bytes=...,
        config_files=[...],
        sha256=...,
        rpo_achieved_seconds=...,
    )
```

### docs/disaster-recovery.md — обязательные разделы

- **RPO**: максимальная потеря данных = время с последнего бэкапа (дефолт 24ч; при часовом cron — 1ч)
- **RTO**: < 15 мин с локального диска; < 30 мин из remote storage
- **Failure scenarios**: DuckDB corruption / config loss / full server loss — путь восстановления для каждого
- **Процедура**: пошагово `python scripts/restore.py`
- **Тестирование**: `python scripts/verify_backup.py backup.tar.gz`

### Критерии приёмки

- [ ] `python scripts/backup.py --output /tmp/` → `.tar.gz` с DuckDB (все tenant схемы) + config
- [ ] `python scripts/verify_backup.py backup.tar.gz` → проверяет SHA-256
- [ ] `python scripts/restore.py --backup backup.tar.gz` → восстанавливает + smoke test
- [ ] `docs/disaster-recovery.md` — RPO=24ч, RTO=15мин, все сценарии
- [ ] `.github/workflows/backup.yml` — nightly cron 02:00 UTC
- [ ] Idempotent: повторный запуск не ломает предыдущие бэкапы

---

## TASK 6 — SDK Versioning + Backwards Compatibility Tests

**Независим** от серверных задач. Можно параллельно с Task 5.

**Gap из исследования**: "SDK versions must not break existing agent code silently."

### Что построить

```
sdk/
  CHANGELOG.md              # NEW: история версий
  agentflow/
    __init__.py             # MODIFY: expose __version__
    _compat.py              # NEW: deprecation warning pattern
  pyproject.toml            # MODIFY: bump version → 1.0.0
tests/unit/
  test_sdk_backwards_compat.py  # NEW: lock public API surface
```

### Правила semver (в CHANGELOG.md)

```
MAJOR: breaking changes (метод удалён, тип параметра изменён)
MINOR: новые методы, опциональные параметры, новые поля в моделях
PATCH: bug fixes, внутренние изменения

Deprecation policy:
- Метод/поле депрецируется с warning на 1 MAJOR версию до удаления
- Warning содержит: что депрецировано, что использовать, в какой версии удалят
```

### Deprecation pattern

```python
# sdk/agentflow/_compat.py
def deprecated(replacement: str, removed_in: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            warnings.warn(
                f"{func.__name__} deprecated, removed in {removed_in}. "
                f"Use {replacement} instead.",
                DeprecationWarning, stacklevel=2,
            )
            return func(*args, **kwargs)
        return wrapper
    return decorator
```

### Backwards compat тесты — фиксируют public API

```python
# tests/unit/test_sdk_backwards_compat.py
"""
Падение любого теста = breaking change = нужен MAJOR bump.
"""
def test_client_constructor_signature():
    sig = inspect.signature(AgentFlowClient.__init__)
    assert "base_url" in sig.parameters
    assert "api_key" in sig.parameters

def test_order_entity_required_fields():
    required = {"order_id", "status", "total_amount", "user_id", "created_at"}
    actual = set(OrderEntity.model_fields.keys())
    assert required.issubset(actual), f"Breaking: removed {required - actual}"

def test_exceptions_importable():
    from agentflow.exceptions import (
        AgentFlowError, AuthError, RateLimitError,
        DataFreshnessError, EntityNotFoundError
    )
```

### Критерии приёмки

- [ ] `sdk/CHANGELOG.md` — записи для v0.x и v1.0.0
- [ ] `from agentflow import __version__` возвращает semver строку
- [ ] `pyproject.toml` version → `1.0.0`
- [ ] `test_sdk_backwards_compat.py` — 10+ контрактных тестов
- [ ] Любое будущее breaking изменение ломает хотя бы один тест (by design)
- [ ] `_compat.py` с `@deprecated` готов к использованию

---

## TASK 7 — API Versioning (Date-Based, Per-Tenant Pinning)

**После Task 2** (нужна tenant модель для per-tenant version pinning).

**Gap из исследования**: Stripe/Twilio pattern; "breaking API changes without versioning destroy agent reliability."

### Что построить

```
src/serving/api/
  versioning.py             # NEW: version registry + response transformer
  main.py                   # MODIFY: versioning middleware
src/serving/api/routers/
  agent_query.py            # MODIFY: version-aware responses
config/
  api_versions.yaml         # NEW: changelog версий
tests/unit/
  test_versioning.py        # NEW
```

### Version negotiation

```
Request:   X-AgentFlow-Version: 2026-01-01
           (если не указан: pinned версия тенанта, или latest)

Response:  X-AgentFlow-Version: 2026-01-01
           X-AgentFlow-Latest-Version: 2026-04-11
           X-AgentFlow-Deprecated: false
```

### Pinning в tenants.yaml

```yaml
tenants:
  - id: acme-corp
    api_version_pin: "2026-01-01"   # acme остаётся на январской версии
```

### config/api_versions.yaml

```yaml
versions:
  - date: "2026-01-01"
    status: stable
    changes: []

  - date: "2026-04-11"
    status: latest
    changes:
      - type: additive
        description: "Added meta.is_historical to entity responses"
      - type: additive
        description: "Added X-PII-Masked response header"
```

### Response transformer

```python
class ResponseTransformer:
    def transform(self, response: dict, from_version: str, to_version: str) -> dict:
        """Трансформирует ответ из текущей версии в запрошенную старую."""
        if from_version == to_version:
            return response
        for change in self._get_changes_between(to_version, from_version):
            response = self._apply_inverse(response, change)
        return response
```

### Deprecation warning

Если pinned версия тенанта старше 6 месяцев:
```
X-AgentFlow-Deprecation-Warning: Your pinned version 2026-01-01 will be
  unsupported after 2027-01-01. See /v1/changelog.
```

### Критерии приёмки

- [ ] `X-AgentFlow-Version: 2026-01-01` → response в старой схеме (новые поля удалены)
- [ ] Pinned версия тенанта из `tenants.yaml` применяется ко всем его запросам
- [ ] Deprecated версии → `X-AgentFlow-Deprecation-Warning` header
- [ ] `GET /v1/changelog` — human-readable история версий
- [ ] `tests/unit/test_versioning.py` — 8+ тестов

---

## TASK 8 — Helm Chart (Enterprise Kubernetes Deployment)

**После Task 2** (tenant config) и **Task 1** (secrets format).

**Gap из исследования**: "Enterprise teams deploy on Kubernetes; docker-compose is not enough."

### Что построить

```
helm/agentflow/
  Chart.yaml
  values.yaml
  templates/
    deployment.yaml          # API deployment с readiness/liveness probes
    service.yaml
    configmap.yaml           # api_keys, tenants, slo, pii_fields
    secret.yaml              # admin key, bcrypt-hashed API keys
    ingress.yaml             # optional, с TLS
    hpa.yaml                 # HorizontalPodAutoscaler
    pvc.yaml                 # PersistentVolumeClaim для DuckDB
    serviceaccount.yaml
    _helpers.tpl
docs/
  helm-deployment.md         # install, upgrade, uninstall guide
```

### values.yaml (ключевые поля)

```yaml
replicaCount: 2

image:
  repository: agentflow/api
  tag: "1.0.0"

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70

persistence:
  enabled: true
  size: 10Gi

resources:
  requests: { cpu: 250m, memory: 512Mi }
  limits:   { cpu: 1000m, memory: 2Gi }

config:
  duckdbPath: /data/agentflow.duckdb
  rateLimitRpm: 120

secrets:
  adminKey: ""        # --set secrets.adminKey=...
  apiKeys: ""         # bcrypt hashes из config/api_keys.yaml
```

### deployment.yaml — обязательно

```yaml
readinessProbe:
  httpGet: { path: /v1/health, port: 8000 }
  initialDelaySeconds: 10
  periodSeconds: 5

livenessProbe:
  httpGet: { path: /v1/health, port: 8000 }
  initialDelaySeconds: 30
  periodSeconds: 10

affinity:
  podAntiAffinity:          # spread pods по нодам для HA
    preferredDuringSchedulingIgnoredDuringExecution: [...]
```

### Критерии приёмки

- [ ] `helm install agentflow ./helm/agentflow` деплоится на minikube без ошибок
- [ ] `GET /v1/health` возвращает healthy из кластера
- [ ] HPA скейлит реплики по CPU
- [ ] PVC сохраняет DuckDB данные при перезапуске пода
- [ ] `helm upgrade` → rolling update без даунтайма
- [ ] `docs/helm-deployment.md` — install, configure, upgrade, uninstall

---

## TASK 9 — Schema Evolution + Breaking Change Detection в CI

**После Task 4** (contract registry — evolution checker нужен реестр контрактов).

**Gap из исследования**: "Prevent training-serving skew; agents get wrong data silently after schema changes."

### Что построить

```
src/serving/semantic_layer/
  schema_evolution.py       # NEW: EvolutionChecker
src/serving/api/routers/
  contracts.py              # MODIFY: add /v1/contracts/{entity}/validate
scripts/
  check_schema_evolution.py # NEW: CI скрипт, падает на breaking changes
.github/workflows/
  ci.yml                    # MODIFY: добавить schema-check job
tests/unit/
  test_schema_evolution.py  # NEW
```

### Классификация изменений

```python
BREAKING_CHANGES = [
    "field_removed",
    "field_type_changed",
    "field_required_added",
    "enum_value_removed",
]

SAFE_CHANGES = [
    "field_added_optional",
    "description_changed",
    "enum_value_added",
    "field_default_added",
]

class EvolutionChecker:
    def check(self, old_schema: dict, new_schema: dict) -> EvolutionReport:
        """
        Returns:
          - breaking_changes: list[Change]
          - safe_changes: list[Change]
          - is_breaking: bool
        """
```

### CI интеграция

```python
# scripts/check_schema_evolution.py
"""
Сравнивает текущие config/contracts/ с HEAD~1.
Exits 1 если обнаружено breaking change без version bump.
"""
```

```yaml
# .github/workflows/ci.yml — новый job
schema-check:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
      with: { fetch-depth: 2 }
    - name: Check schema evolution
      run: python scripts/check_schema_evolution.py
```

### Критерии приёмки

- [ ] `EvolutionChecker.check(old, new)` корректно классифицирует 8 типов изменений
- [ ] `POST /v1/contracts/{entity}/validate` — загрузить новую схему, получить отчёт
- [ ] `python scripts/check_schema_evolution.py` → exits 0 (safe), 1 (breaking)
- [ ] CI запускает schema-check на каждый PR
- [ ] `tests/unit/test_schema_evolution.py` — 10+ тестов по всем типам изменений

---

## TASK 10 — DORA Metrics + CI/CD Quality Gates

**Последней** — когда весь код стабилен.

**Gap из исследования**: "DORA metrics signal delivery maturity to enterprise buyers."

### Что построить

```
scripts/
  dora_metrics.py           # NEW: compute DORA из git + GitHub Actions
docs/
  engineering-standards.md  # NEW: наши DORA таргеты + quality gates
.github/workflows/
  dora.yml                  # NEW: еженедельный отчёт
  ci.yml                    # MODIFY: добавить deployment tracking
```

### scripts/dora_metrics.py

```python
"""
Метрики:
1. Deployment Frequency    — коммитов в main за неделю
2. Lead Time for Changes   — от первого коммита до main
3. Change Failure Rate     — % деплоев, потребовавших hotfix в течение 24ч
4. MTTR                    — от упавшего теста на main до зелёного

Использование:
  python scripts/dora_metrics.py --days 30
  python scripts/dora_metrics.py --output dora-report.json
"""
```

### docs/engineering-standards.md

```markdown
## DORA Targets

| Metric | Elite benchmark | Our target |
|--------|----------------|------------|
| Deployment frequency | Multiple/day | Daily |
| Lead time | < 1 hour | < 1 day |
| Change failure rate | < 5% | < 15% |
| MTTR | < 1 hour | < 4 hours |

## Quality Gates (enforced in CI)

- Tests pass before merge to main
- Coverage ≥ 80%
- No ruff / mypy errors
- No breaking schema changes without version bump
- p95 latency не растёт > 50% vs baseline
```

### Критерии приёмки

- [ ] `python scripts/dora_metrics.py --days 30` выводит все 4 метрики
- [ ] `.github/workflows/dora.yml` — еженедельный запуск, summary в PR comment
- [ ] `docs/engineering-standards.md` — DORA таргеты + все CI gates задокументированы
- [ ] `.dora/deployments.jsonl` — пишется при каждом merge в main
- [ ] CI enforces: tests + coverage ≥ 80% + mypy + schema-check

---

## Итоговый порядок выполнения

```
 1. TASK 1  Security hardening (bcrypt, headers)   ← меняет формат конфига — делать первым
 2. TASK 2  Tenant isolation (DuckDB schemas)      ← после Task 1
 3. TASK 3  Iceberg sink (параллельно с Task 2)    ← независим после Task 1
 4. TASK 4  Contract registry                      ← после Task 2
 5. TASK 5  DR / backup / restore                  ← после Task 2 (бэкапит tenant схемы)
 6. TASK 6  SDK versioning                         ← независим, параллельно с Task 5
 7. TASK 7  API versioning                         ← после Task 2 (per-tenant pinning)
 8. TASK 8  Helm chart                             ← после Task 1+2 (secrets + tenant config)
 9. TASK 9  Schema evolution + CI gate             ← после Task 4 (нужен contract registry)
10. TASK 10 DORA metrics + CI gates                ← последним, весь код стабилен
```

**После v4**: `pytest tests/` → 160+ тестов, cross-tenant leakage test проходит, bcrypt ключи, Iceberg реально пишет, Helm деплоит на minikube, schema-check в CI ловит breaking changes.
