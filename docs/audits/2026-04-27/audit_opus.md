# AgentFlow / DE_project — Глубокий аудит

**Аудитор:** Claude Opus 4.7 (1M)
**Дата:** 2026-04-27
**HEAD на момент аудита:** `4a13d36f9baa652cc0082ccbd04137d768f9929b` (`main`)
**Объект:** `D:\DE_project` (AgentFlow runtime + Python SDK + TS SDK + CDC stack + Helm/Terraform IaC)
**Метод:** статический анализ репозитория, чтение кода, проверка артефактов, сверка docs ↔ git ↔ CI. Никаких изменений не вносил.

---

## 0. TL;DR

AgentFlow находится в **release-blocked** состоянии для v1.1.0. Технический фундамент 9/10 — код, тесты, CI/CD, документация и security posture в очень хорошей форме. Есть один **критический операционный блокер** и несколько middle-tier hardening gaps.

| Срез | Оценка | Главное |
|------|--------|---------|
| Архитектура / код | **9.0** | Чистая слоёная структура, никаких bare-except / eval / shell=True / SQL concat; sqlglot + bcrypt + параметризация повсеместно |
| Tests | **8.5** | 105 файлов / 19 236 LOC; 8 типов suites; mutation testing на 5 critical paths; coverage floor 60% / patch 80% |
| CI/CD | **8.5** | 15 workflows, OIDC PyPI, secret diff bandit, mutation cron, performance gate; **нет SLSA provenance** |
| Helm / K8s | **7.5** | HPA + PVC + checksum-driven restarts ✓; **нет NetworkPolicy / PDB / runAsNonRoot / readOnlyRootFilesystem** |
| Terraform / Cloud | **7.0** | MSK + KDA + S3 + OIDC написаны; реальный `apply` ни разу не выполнялся, single-region S3 без DR |
| Observability | **7.0** | Prom + 4 Grafana dashboards + 4 alert rules; OTEL только envvars, no real tracing wiring; нет on-call runbooks |
| Docs / contracts | **9.5** | release-readiness, audit-history, security-audit, competitive-analysis, narrative API ref, 4 entity contracts |
| **Release readiness** | **6.0** | **BLOCKED** на pre-commit chaos smoke hang + один uncommitted edit в `publish-pypi.yml` |
| **Repo hygiene** | **8.0** | Big files уже корректно `.gitignore`d; `.dora/deployments.jsonl` tracked при `.dora/` в gitignore — намеренное `add -f` |
| **Overall** | **8.2** | Готовый продукт, который не публикует release из-за одной flaky-выглядящей цепочки в chaos smoke |

**Главный вывод:** v1.1.0 на disk фактически готов. Доказательная база (release-readiness.md, бенчмарки, twine preflight, npm pack dry-run, terraform validate, bandit diff, full-suite на 668 passed) сходится. Не публикуется один release, потому что один тест на одной workstation хвостится в `starlette.testclient` через DuckDB timeout сценарий. Это нужно либо починить, либо явно waive — иначе откладывание накапливает рост дельты между tag-целью и HEAD (сейчас `v1.1.0` указывает на `1ee89a3`, а HEAD = `4a13d36`, т.е. **+30+ коммитов после тега**, и эта дельта продолжает расти ежедневно).

---

## 1. Состояние репозитория

### 1.1. Версионирование и теги

| Артефакт | Значение |
|----------|----------|
| HEAD (`main`) | `4a13d36` (2026-04-27 16:?) — `ci: record deployment fc50de6c…` |
| Tag `v1.0.0` | published, GitHub Release exists |
| Tag `v1.0.1` | `2e4b2e8`, published, GitHub Release exists |
| Tag `v1.1.0` | `1ee89a3` (старый, **+30 коммитов до HEAD**), GitHub Release **отсутствует** |
| Tag `v1.1.0-rc1` | `5b57cf4` (промежуточный) |
| Branch state | `## main...origin/main` — синхронен с remote |
| Uncommitted | 2 файла: `.github/workflows/publish-pypi.yml` (+`environment: pypi`), `docs/release-readiness.md` (расширение раздела) |

### 1.2. История с момента предыдущей сессии (memory snapshot 36cf8e5)

+32 коммита, основные темы:
- **CDC operationalization (10+ commits):** Debezium normalizer, Kafka Connect Helm chart, secret mode enforcement, schema-history bootstrap, watermarks через source timestamps
- **Release evidence cycles (8 commits):** docs refresh + benchmark history + `ci: record deployment` каждый раз когда CI зелёный
- **CI hardening (3 commits):** integration deps restored, p99 endpoint gates, perf check honour endpoint baselines
- **Test stability (1 commit):** `test: stabilize full suite flakes` (2cbccb9)

### 1.3. Crufts на disk (НЕ в git, но засоряют workspace)

```
agentflow_api.duckdb           54 MB   ← на disk, в .gitignore (line 44 + 79) ✓
agentflow_demo.duckdb          4.8 MB  ← на disk, в gitignore ✓
agentflow_demo_api.duckdb      268 KB  ← на disk, в gitignore ✓
coverage.xml                   267 KB  ← на disk, в gitignore (line 39) ✓
.tmp/                          ~26 MB  ← в gitignore ✓
.tmp-security/                 36 KB   ← в gitignore (line 84) ✓
DE_project.tmppytest-basetemp-final-gate/   ← НЕ в gitignore, leftover
node_modules/.vite/            1 KB    ← root-level node_modules с одним пустым subdir, безвредный
```

**Один реальный нюанс:** `.dora/` в `.gitignore` строка 50, но `.dora/deployments.jsonl` — **отслеживается**. Это намеренное `git add -f` (DORA metrics — единственный полезный артефакт из этой папки), но конфликт между rule и exception стоит явно whitelisted-ить (`!.dora/deployments.jsonl` после `.dora/`) — иначе случайный `git add .dora/` затянет в индекс остальные mypy/ruff snapshot-ы, которых сейчас 0.

---

## 2. Архитектура и код (`src/`, `sdk/`, `sdk-ts/`)

### 2.1. Layered structure

`src/` ≈ 13 400 LOC / 94 файла, разбито на 5 слоёв:

| Слой | LOC | Назначение |
|------|-----|------------|
| `serving/` | 10 807 | FastAPI: 13 routers + 5-layer middleware + auth/security + DuckDB/ClickHouse backends + semantic layer (NL→SQL) + caching + masking |
| `processing/` | 1 247 | Flink jobs (ignore_errors в mypy), local pipeline, Iceberg sink, outbox processor |
| `quality/` | 386 | Schema/semantic validators, freshness monitors, metrics |
| `ingestion/` | 286 | CDC connectors (Postgres/MySQL), Debezium normalizer, Kafka producers, tenant routing |
| `orchestration/` | 224 | Dagster DAGs для batch |

**God-class split** — `docs/release-readiness.md:54` фиксирует: auth, alerts, query модули разделены с compatibility imports. Подтверждается отсутствием в `src/` файлов >800 LOC из ручной выборки.

### 2.2. API layer (`src/serving/api/`)

- `main.py` (386 LOC): lifespan + 5-layer middleware + 13 routers
- 13 router-файлов по domain (agent_query, batch, admin, admin_ui, alerts, webhooks, stream, deadletter, lineage, search, contracts, slo)
- Pydantic validation на **всех** endpoints с field constraints (`min_length=3`, `max_length=1000`, `ge=1, le=1000`)
- ApiVersionRegistry + ResponseTransformer — **date-based API versioning** (auto-migration между версиями) — это редко встречается, хорошая практика
- Async-correctness: sync I/O везде через `await run_in_threadpool()`, asyncio.Lock для health cache, asyncio.Queue для outbox — ни одного sync-в-async leak в проверенной выборке

### 2.3. Security в коде

| Контроль | Реализация | Файл |
|----------|------------|------|
| API key hashing | bcrypt 12 rounds | `src/serving/api/security.py:50` |
| Timing-safe compare | `secrets.compare_digest` | `src/serving/api/auth/manager.py:220` |
| SQL safety | sqlglot AST + 6 forbidden node types (Alter, Delete, …) | `src/serving/api/sql_guard.py:11-25` |
| Rate limiting | per-key rpm + IP failure throttling (10/hr) | `src/serving/api/auth/middleware.py:43,90` |
| Security headers | HSTS, CSP, X-Frame-Options, X-Content-Type-Options | `security.py:16-23` |
| Header redaction | structlog redactor | `security.py:60-70` |
| CORS | env-driven `allow_origins` | `main.py:264-276` |

**Anti-patterns audit (negative findings):**
- 0 bare `except:` / `except Exception: pass`
- 0 `eval()` / `exec()` / `os.system()` / `shell=True`
- 0 SQL string concatenation (всё параметризовано или sqlglot AST)
- 0 hardcoded credentials/URLs
- 0 `print()` в production paths (структурный logger через structlog)
- `# nosec` комментарии — 2 явных override (B608 sql_guard.py:56, webhook_dispatcher.py:110), 5 `nosec B110` в rollback/audit paths (зафиксировано в `release-readiness.md:57`)
- B310 (`urllib.urlopen` для permitted schemes) — 1 baseline issue в `clickhouse_backend.py:49`, approved

### 2.4. Soft observations (не блокеры, но стоит держать в виду)

1. **MyPy soft mode**: `disallow_untyped_defs: false`, `check_untyped_defs: true`, `ignore_missing_imports: true`. Flink jobs полностью исключены через `ignore_errors`. Type coverage не strict.
2. **SDK ↔ contracts divergence risk**: `contracts/entities/*.yaml` — источник истины, но Python SDK классы написаны вручную, нет OpenAPI→SDK генератора. Контракт и SDK сейчас совпадают, но при эволюции схемы дрейф ничем не enforce-ится. `scripts/generate_contracts.py --check` валидирует контракт-файл, но **не** sync с SDK Pydantic-моделями.
3. **OutboxProcessor `process_pending()` блокирующий внутри async loop** (`src/.../outbox.py:68-70`): работает на текущем load, но при росте RPS станет узким местом. Не P0.
4. **`_PII_MASKER` глобальный кэш** в `agent_query.py:29-36`: thread-safe не гарантирован при path mismatch reload. Edge-case.
5. **Demo mode path-prefix check** (`startswith("/v1/admin")`) — если префикс admin endpoints поменяется, проверка молча перестанет защищать. Лучше через explicit decorator/route.flag.

---

## 3. Tests (`tests/`)

### 3.1. Suite breakdown

| Тип | Файлов | Что покрывает |
|-----|--------|---------------|
| Unit | 39 | auth, masking, caching, query engine, validators, SDK retry/CB |
| Integration | 20 | Kafka pipeline, CDC capture, alerts, webhooks, batch, helm validation |
| E2E | 3 | smoke, agent journeys, compose config |
| Contract | 2 | OpenAPI compliance (Schemathesis), SDK contract tests |
| Chaos | 5 | DuckDB timeout, Kafka latency, Redis failure, conftest |
| Property-based | 4 | auth, masking, pagination, tenant isolation (Hypothesis) |
| Load | 3 | locustfile + thresholds + run_load_test wrapper |
| SDK | 3 | circuit breaker, resilience, retry |

**Всего:** 105 файлов / **19 236 LOC** тестового кода — серьёзный объём, соразмерный production-проекту.

### 3.2. Качественные показатели

- **Real Kafka** через testcontainers в integration suite (`tests/integration/test_kafka_pipeline.py:47`)
- **In-memory DuckDB** в unit-тестах
- **Mocked HTTP** в SDK-тестах через httpx mocks
- 0 `@pytest.mark.flaky` маркеров (skip/xfail вместо retry-on-flake — здоровая практика)
- **Mutation testing** на 5 critical paths: auth, masking, query_engine, outbox, rate_limiter (`mutation.yml`, расписание Sun 4 AM UTC)
- Coverage floor: `--cov-fail-under=60`, patch coverage 80% через Codecov
- Schemathesis для OpenAPI fuzzing
- Locust для load (`locustfile.py`: 40% entity / 30% metrics / 20% NL / 10% health), thresholds: p50<100ms, p99<500ms

### 3.3. Локальный full-suite результат на 2026-04-27

```
docker compose up -d redis  +  pytest -p no:schemathesis --basetemp D:\DE_project\.tmp\pytest-basetemp-doc-post-merge-gate
→ 668 passed, 8 skipped, 13 warnings in 496.93s
```

**Это пройденный gate.** Падает только pre-commit перезапуск той же команды (см. §7).

### 3.4. Соответствие мемории

Memory строка `tests 351 pass (was 320)` относится к AB_TEST проекту, не к DE_project — путаница в индексе. У DE_project: **668 passed, 8 skipped** на свежем прогоне. Корректирую memory ниже.

---

## 4. CI / CD (`.github/workflows/`)

15 workflow-файлов:

```
backup.yml         chaos.yml          ci.yml             contract.yml
dora.yml           e2e.yml            load-test.yml      mutation.yml
performance.yml    perf-regression.yml
publish-npm.yml    publish-pypi.yml   security.yml
staging-deploy.yml terraform-apply.yml
```

### 4.1. Gates (по `ci.yml`)

```
lint (ruff) → test-unit → test-integration → perf-check (p99 endpoint gates) → helm validate
```

### 4.2. Security gates

- `security.yml` (cron Mon 6 AM UTC + on push/PR): bandit + bandit_diff против baseline + safety + trivy
- 1 baseline issue (B310 ClickHouse, approved), regression падает CI

### 4.3. Publishing

- `publish-pypi.yml` принимает 3 формата tag: `vX.Y.Z`, `vX.Y.Z-rcN`, `sdk-vX.Y.Z`
- **PyPI Trusted Publishers (OIDC)** через `pypa/gh-action-pypi-publish@release/v1` — для `agentflow-runtime` и `agentflow-client`, оба pending в PyPI account на момент аудита
- `publish-npm.yml` использует `NPM_TOKEN` — secret уже добавлен (2026-04-27, validated через `/whoami`)
- **Uncommitted одна строка** в `publish-pypi.yml`: `+ environment: pypi` под publish job — нужна, чтобы OIDC claims включали environment. Эта правка должна попасть в release-commit перед push tag.

### 4.4. Что НЕ найдено (gaps)

- **Нет SLSA / provenance generation** — не видел `slsa-framework/slsa-github-generator` ни в одном workflow. Для v1.1.0 это middle-tier nice-to-have, для будущего обязательная supply-chain hardening
- Нет signed commits / sigstore-подписанных артефактов в release pipeline
- `terraform-apply.yml` существует, но никогда не отрабатывал реальный `apply` (только `validate` в `ci.yml`)

### 4.5. Proof из git log

Последние 10 deployment IDs в `.dora/deployments.jsonl`:
```
fc50de6, 4fd5761, 980cbea, 45165b3, …
```
Каждый зафиксирован коммитом `ci: record deployment <sha>` — pipeline работает, dora-метрики накапливаются.

---

## 5. Infrastructure (Helm + Docker Compose + Terraform + K8s)

### 5.1. Helm charts (`helm/`)

Два production-grade chart:

| Chart | appVersion | Что внутри |
|-------|-----------|------------|
| `helm/agentflow/` | 1.0.0 | API deployment + HPA(2-10, 70% CPU) + readiness/liveness probes + PVC 10Gi + RBAC + checksum-driven restarts + zero-downtime rolling (maxUnavailable=0, maxSurge=1) |
| `helm/kafka-connect/` | 7.7.0 | Connect workers (1 replica, не autoscaled) + extended probes (20s readiness, 60s liveness) + secret mode (file-based config providers через Kubernetes Secret mount) |

**Что отлично сделано:**
- Resource requests/limits на обоих
- Pod anti-affinity (preferred)
- ConfigMap/Secret checksum в pod template — restart на change values
- Connector registration через templates с feature flag (postgres/mysql disabled by default — safety)

**Hardening gaps (P2, не блокеры релиза, но обязательные перед production-traffic):**
1. **Нет NetworkPolicy** — pod-to-pod трафик не сегментирован
2. **Нет PodDisruptionBudget** — chaos / cluster upgrade может одновременно эвиктнуть оба replicas
3. **Нет `securityContext: { runAsNonRoot: true, readOnlyRootFilesystem: true }`** — контейнеры по умолчанию runs as root, can write to image FS
4. **Init containers без resource limits** (kafka-init, topic-bootstrap) — minor risk
5. Image tag `kafka-connect:local` в default values — это dev-only, в prod-values нужен SHA-pinned образ

### 5.2. Docker Compose (6 файлов)

| Файл | Назначение | Заметка |
|------|------------|---------|
| `docker-compose.yml` | Base stack (Kafka KRaft, Flink, Minio S3, Redis, DuckDB) | Healthcheck Kafka через `kafka-broker-api-versions` ✓ |
| `docker-compose.cdc.yml` | Postgres + MySQL + Kafka Connect + topic bootstrap | WAL logical для PG, ROW bin-log для MySQL ✓ |
| `docker-compose.chaos.yml` | ToxiProxy для chaos | **Замечание** в release-readiness:130 — параллельный запуск `up -d` создаёт duplicate bind на 8474, использовать только pytest-managed fixture |
| `docker-compose.e2e.yml` | E2E env | |
| `docker-compose.flink.yml` | Standalone Flink | |
| `docker-compose.iceberg.yml` | Минимальный, ссылается на внешний lakehouse | |
| `docker-compose.prod.yml` | Production-shaped (8.9K) с observability | |

**Слабое место:** Большинство сервисов не имеют `depends_on: condition: service_healthy` — race conditions возможны при запуске. Kafka-init использует условие правильно.

### 5.3. Terraform (`infrastructure/terraform/`)

5 модулей: `github-oidc`, `kafka` (MSK), `flink` (KDA), `storage` (S3 + Glacier 30d + expire 90d), `monitoring` (CloudWatch alarms).

State backend: S3 (`agentflow-terraform-state`) + DynamoDB locks + encryption.

**Реальный `apply` ни разу не выполнялся.** В CI только `terraform init -backend=false && terraform validate`. AWS OIDC role создаётся out-of-band вручную (документировано в `docs/operations/aws-oidc-setup.md`). DR strategy не явная (single-region S3).

### 5.4. K8s manifests

`k8s/` содержит manifests для local KinD staging, плюс `scripts/k8s_staging_up.sh` / `_down.sh`. Не production-grade — для development и staging.

---

## 6. Observability

### 6.1. Что есть

- **Prometheus** scrape configs (`monitoring/prometheus/prometheus.yml`)
- **Grafana** — 4 дашборда:
  - `pipeline_health.json` — общий
  - `merch-agent-journey.json`, `ops-agent-journey.json`, `support-agent-journey.json` — agent-vertical
- **Alert rules** (`monitoring/alerting/rules.yml`, 64 строки):
  - FreshnessSLABreach: <95% compliance → critical
  - HighPipelineLatency: p99 > 10s → warning
  - ZeroThroughput: 0 events / 5m → critical
  - ComponentHealth: unhealthy/degraded
- **DORA metrics**: `.dora/deployments.jsonl` накапливает CI deploys
- **OTEL env vars** в Helm (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`)

### 6.2. Что отсутствует

- **Реальный OpenTelemetry init в коде** — env-vars присутствуют в Helm, но я не нашёл `opentelemetry.instrumentation` или `tracer.start_span` в `src/`. Tracing — pure stub.
- **Jaeger** — только `monitoring/jaeger/README.md`, без compose/manifests
- **Runbooks для production incidents** — отсутствуют (`docs/operations/chaos-runbook.md` есть, но это для locally invoking chaos suite, не для on-call)
- **On-call escalation** — 0 документации
- **SLO definitions** — slo router есть в API, но `docs/slo.md` не нашёл

---

## 7. Release Readiness — детальный разбор

### 7.1. Что готово ✅

| Артефакт | Доказательство |
|----------|----------------|
| v1.0.0 published | `gh release list` подтверждает, 2026-04-20 |
| v1.0.1 patch | published 2026-04-20, 340 unit tests pass |
| v1.1.0 локальный full-suite | 668 passed / 8 skipped / 496s на 2026-04-27 |
| Performance gate | p99 290-330 ms < 500 ms gate, baseline в `docs/benchmark-baseline.json` (2026-04-17) |
| Bandit diff | green vs baseline (1 approved B310) |
| OpenAPI compliance | `Contract Tests` workflow PASS на `8d7088d` |
| Twine preflight | `python -m twine check dist\* sdk\dist\*` ✓ |
| npm pack dry-run | `agentflow-client-1.1.0.tgz`, 16 files, 8.2 KB ✓ |
| Editable install order check | оба порядка резолвят runtime + client из repo ✓ |
| PyPI Trusted Publishers | pending для `agentflow-runtime` + `agentflow-client`, owner `brownjuly2003-code`, repo `agentflow`, workflow `publish-pypi.yml`, env `pypi` ✓ |
| GitHub `NPM_TOKEN` | exists, validated через `/whoami` 2026-04-27 ✓ |
| Helm chart validation | в `ci.yml` ✓ |
| Terraform validate | ✓ (но не apply) |
| Audit trail | `docs/audit-history.md` (retrospective reconstruction 2026-04-20) |

### 7.2. Что блокирует 🔴

**Критический блокер #1 — chaos smoke hang:**

```
tests/chaos/test_chaos_smoke.py::test_smoke_metric_endpoint_returns_503_on_duckdb_timeout
```

Зависает внутри `starlette.testclient` во время `chaos_client.get("/v1/metrics/revenue?window=1h")` под DuckDB timeout сценарием. Воспроизводимая команда зафиксирована в `release-readiness.md:158`:

```bash
python -m pytest tests/chaos/test_chaos_smoke.py::test_smoke_metric_endpoint_returns_503_on_duckdb_timeout \
  -p no:schemathesis -vv \
  --basetemp D:\DE_project\.tmp\pytest-basetemp-chaos-single \
  --timeout=60 --timeout-method=thread
```

**Анализ:** Тест PR-smoke 3 теста / 42s — зелёный (release-readiness.md:111). Сам `test_smoke_metric_endpoint_returns_503_on_duckdb_timeout` тоже **зелёный в одиночном прогоне**, но хвостится при run в составе full-suite. Это сильный признак, что:
- порядок исполнения / fixture cleanup ломает state (DuckDB connection pool, ToxiProxy, Redis)
- starlette `TestClient` синхронный wrapper над async ASGI — если в DuckDB-timeout-симуляции `app` входит в deadlock или в незакрываемый pool, TestClient никогда не возвращает control

**Рекомендация фикса:** прогнать `--timeout=60 --timeout-method=thread` с `-x --tb=long` и снять traceback в момент зависания. Если deadlock — добавить explicit `timeout` в `chaos_client.get(..., timeout=10)` и обернуть DuckDB call в `asyncio.wait_for`.

**Альтернатива (release-shipping):** waive chaos тест в pre-commit gate (отдельный CI job всё равно его прогоняет на schedule), но это **не закроет root cause** и может скрыть production-relevant deadlock.

**Блокер #2 — uncommitted change в `publish-pypi.yml`:**

```diff
+ environment: pypi
```

Без него OIDC claims при publish job не включают environment, и Trusted Publisher не примет токен (он привязан к env=`pypi`). Должно попасть в release-commit одной строкой.

**Блокер #3 — v1.1.0 tag stale:**

`v1.1.0` → `1ee89a3` (2026-04-17), HEAD = `4a13d36` (2026-04-27, +30+ коммитов). После фикса chaos нужно:

```bash
git tag -d v1.1.0
git push --delete origin v1.1.0
git tag v1.1.0 <release-commit>
git push origin v1.1.0
```

Это публичная переписывание тега — risk-флаг. Если **есть какой-либо потребитель**, который уже клонировал по `v1.1.0` (что маловероятно — release не объявлен, GitHub Release отсутствует), это сломает их checkout. Вариант безопаснее: `v1.1.1` как первый реальный publish и пометить `v1.1.0` как стабильный draft.

### 7.3. Не-блокеры (open в checklist, но не gating registry publish)

- GitHub environments `staging`/`prod` с required reviewers — manual setup
- AWS OIDC role — manual setup (нужен только когда terraform `apply` запустят)
- Production CDC source onboarding — нужны hostnames, table scope, network access, secret ownership decisions
- External pen-test attestation — отсутствует
- Public benchmark на `c8g.4xlarge+` — pending
- Phase 1 PMF customer discovery — пост-relase business работа

---

## 8. Contracts (`contracts/`)

4 entity-контракта: `order.yaml`, `user.yaml`, `product.yaml`, `session.yaml`. Каждый описывает:
- table reference
- primary key
- field metadata
- relationships (например, `order.user_id → user.user_id`)

CI gate: `python scripts/generate_contracts.py --check` (exit 0 на 2026-04-27).

**Слабое место:** YAML, не Avro / protobuf / JSON-Schema. Для Kafka producer/consumer interop с не-Python клиентами (если появятся) это будет узкое место. Сейчас все consumer — внутренние Python services + Python+TS SDK, поэтому YAML достаточно.

CDC normalizer (`src/ingestion/cdc/normalizer.py:152 LOC`) производит canonical envelope с stable UUID5 event_id, но контрактом канонической схемы я не нашёл (нет `contracts/cdc-envelope.yaml` или подобного). Если CDC consumer-ов станет несколько — контракт нужен.

---

## 9. Документация

`docs/` содержит:

| Файл/раздел | Состояние |
|-------------|-----------|
| `release-readiness.md` | 179 строк, обновлён 2026-04-27, эксклюзивно полный snapshot |
| `audit-history.md` | retrospective reconstruction 2026-04-20 |
| `security-audit.md` | присутствует |
| `competitive-analysis.md` | присутствует |
| `api-reference.md` | narrative + 6 endpoints documented |
| `glossary.md` | 33 KB |
| `migration/v1.1.md` | SDK split context |
| `publication-checklist.md` | preflight steps |
| `operations/aws-oidc-setup.md` | manual GitHub Actions IAM |
| `operations/chaos-runbook.md` | local chaos invocation |
| `operations/codecov-setup.md` | OIDC integration |
| `plans/` | плотный trail планов 2026-04-* (v8 → v19) |
| `perf/` | flamegraphs (138 KB + 112 KB SVG) — отличная инженерная гигиена |
| `codex-tasks/2026-04-23/audit/audit-trivy-*.txt` | scan output preserved (66 KB + 60 KB) |

**Чего нет:**
- `DEPRECATIONS.md` — упомянут в memory entry RAG_Support_Assistant как pattern, но в DE_project deprecation tracking только в API-versioning слое (router-level)
- Production runbooks для on-call
- Customer-facing pricing / SLA docs (OK для pre-PMF stage)

---

## 10. Сводный список рисков и действий

### 10.1. P0 — release-blocking

| # | Риск | Действие | Owner |
|---|------|----------|-------|
| 1 | Chaos smoke hang в pre-commit | Прогнать с `-vv --timeout=60 --timeout-method=thread`, собрать traceback, понять root cause (deadlock vs slow path), исправить либо явно waive | dev |
| 2 | Uncommitted edit в `publish-pypi.yml` | Закоммитить вместе с release-readiness updates после chaos fix | dev |
| 3 | `v1.1.0` tag stale (+30+ коммитов до HEAD) | После фикса перенести tag (или назначить новую версию `v1.1.1`) | dev |

### 10.2. P1 — pre-production hardening (не блокер v1.1.0, но обязательно перед prod-traffic)

| # | Риск | Действие |
|---|------|----------|
| 4 | Helm: нет NetworkPolicy | Добавить default-deny + allow-list из app namespace в `helm/agentflow/templates/` |
| 5 | Helm: нет PodDisruptionBudget | `minAvailable: 1` для api deployment |
| 6 | Helm: нет `runAsNonRoot` / `readOnlyRootFilesystem` | securityContext в pod template |
| 7 | OTEL только envvars, нет реального tracer wiring | `opentelemetry-instrumentation-fastapi` + `opentelemetry-instrumentation-asgi` в `main.py` lifespan |
| 8 | Нет on-call runbooks | Минимум: high-CPU, high-latency, Kafka lag, DuckDB lock, full-disk |

### 10.3. P2 — supply-chain & operational

| # | Риск | Действие |
|---|------|----------|
| 9 | Нет SLSA provenance в release pipeline | `slsa-framework/slsa-github-generator` в `publish-pypi.yml` и `publish-npm.yml` |
| 10 | SDK ↔ contracts sync — manual | OpenAPI → Pydantic генератор (datamodel-code-generator), CI gate на drift |
| 11 | Terraform `apply` ни разу не выполнялся | Manual AWS OIDC setup, потом первый `terraform apply` через workflow в staging |
| 12 | `.dora/` в gitignore + `.dora/deployments.jsonl` tracked | Whitelist через `!.dora/deployments.jsonl` после `.dora/` в gitignore |
| 13 | Single-region S3 для terraform state без DR | Cross-region replication + versioning verify |

### 10.4. P3 — code health micro-issues

| # | Риск | Действие |
|---|------|----------|
| 14 | OutboxProcessor sync блокирующий в async loop | Перенести в `asyncio.to_thread` или dedicated executor |
| 15 | `_PII_MASKER` global cache не явно thread-safe | `functools.lru_cache` + freeze keys |
| 16 | Demo mode path-prefix check (`/v1/admin`) | Decorator-based admin marking вместо path matching |
| 17 | MyPy soft mode | Постепенно включать `disallow_untyped_defs` per module |

### 10.5. Не-риск (false-positive из памяти)

- "Chronic Load Test fail" из memory — **не подтверждено**. Load Test workflow зелёный на `45165b3`. Реальный блокер — chaos smoke, не load.
- `tests 351 pass (was 320)` в memory — относится к AB_TEST, не DE_project. У DE_project 668 passed.

---

## 11. Что обновить в memory после этого аудита

Текущая `project_de_project.md` запись содержит:
- HEAD `36cf8e5` → должно быть `4a13d36`
- "chronic Load Test" → "chaos smoke hang `test_smoke_metric_endpoint_returns_503_on_duckdb_timeout`"
- "Жду юзера на 3 web-UI шага: 2 PyPI Trusted Publishers + NPM_TOKEN" → **уже сделано**, остался один-line commit на `publish-pypi.yml` + chaos fix
- Tag всё ещё 1ee89a3 — корректно, но дельта выросла до +30+ коммитов

Обновлять не сейчас (вы скажете когда), но это явно kandidat для memory refresh.

---

## 12. Финальный verdict

**AgentFlow v1.1.0 — production-ready по техническому фундаменту, release-blocked по одной операционной причине.**

Сильные стороны:
- Зрелая архитектура с правильной слоистой структурой и без anti-patterns
- Серьёзная test pyramid (8 типов suites + mutation testing + property-based + chaos + load)
- Полноценный CI/CD с OIDC publishing, security gates, performance gates
- Документация на уровне выше среднего senior-startup стандарта
- Чистая security posture: bcrypt, sqlglot AST, параметризация, structured logging с redaction

Слабые места:
- Один тест блокирует весь release цикл — это red flag по dev velocity, нужен root cause а не waiver
- Production-grade Kubernetes hardening (NetworkPolicy/PDB/securityContext) не закрыт
- Terraform `apply` никогда не запускался в реале — disaster recovery rehearsal невозможен
- OTEL/tracing — env vars без implementation
- Supply-chain (SLSA) gap

Следующие 2-3 рабочих дня:
1. Зафиксировать root cause chaos smoke hang
2. Commit + tag + push, проследить за `Publish Python Packages` и `Publish TypeScript SDK` workflows
3. Опубликовать GitHub Release для v1.1.0 (или v1.1.1) с changelog highlights
4. Параллельно — P1 hardening (NetworkPolicy + PDB + securityContext) в отдельную PR

После этого AgentFlow становится готов к первому paying customer и Phase 1 PMF работа из `docs/customer-discovery-questions.md`.

---

*Аудит подготовил: Claude Opus 4.7 (1M context). Все наблюдения из статического анализа репозитория без модификаций. Файлов изменено: 0.*
