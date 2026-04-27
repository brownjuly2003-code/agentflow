# Docker/Integration Test Recovery Audit

Дата: 2026-04-27  
Repo: `D:\DE_project`  
HEAD: `4a13d36`

## Итоговая классификация

Свежие локальные прогоны не воспроизвели продуктовых падений в `tests/integration` или `tests/chaos`, если Docker-зависимое окружение подготовлено.

| Группа | Классификация | Вывод |
|---|---|---|
| `tests/integration` default | PASS / частично env-gated | `193 passed, 8 skipped`; failures нет. Skips связаны с CDC opt-in, `kind` opt-in и отсутствующим `helm`. |
| `tests/chaos` default | PASS | `8 passed`; прошлый chaos smoke hang локально не воспроизведен. |
| `@pytest.mark.requires_docker` | PASS при доступном Docker / ENV при выключенном Docker | 11 nodeid собраны; реально Docker-зависимые Iceberg/Kafka/Chaos проходят, CDC проходит после ручного stack setup. |
| CDC full compose | ENV / command-scope issue | Полный `docker compose -f docker-compose.yml -f docker-compose.cdc.yml up ...` тянет лишние Flink/MinIO/Prometheus/Grafana образы и упал на Docker registry TLS handshake timeout до запуска теста. |
| CDC minimal compose | PASS с caveat | Минимальный список сервисов поднялся, CDC test прошел. `docker compose --wait` вернул `1`, потому что one-shot `cdc-register-connectors` завершился с кодом `0`. |
| Helm/kind tests | ENV / может скрывать продуктовые проблемы | `helm` и `kind` отсутствуют в PATH. Эти тесты не дают продуктового сигнала локально до установки toolchain. |
| `.pytest_cache` | ENV / noise | Pytest пишет `PytestCacheWarning: Access is denied` для `.pytest_cache`; на результаты не влияет, но для чистого прогона лучше добавлять `-p no:cacheprovider`. |

## Reproducible command list

### Baseline

```powershell
git -C D:\DE_project rev-parse --short HEAD
# 4a13d36

git -C D:\DE_project status --short
# target audit file was not present/modified before this audit

docker version
# Docker Desktop server available

docker compose version
# Docker Compose version v5.1.1
```

### Collection

```powershell
.venv\Scripts\python.exe -m pytest -p no:schemathesis tests\integration tests\chaos --collect-only -q --basetemp=.tmp\pytest-audit-p6-collect
```

Result: `209 tests collected in 5.18s`.

```powershell
.venv\Scripts\python.exe -m pytest -p no:schemathesis tests\integration tests\chaos -m requires_docker --collect-only -q --basetemp=.tmp\pytest-audit-p6-collect-docker
```

Result: `11/209 tests collected (198 deselected)`.

Docker-marked nodeids:

```text
tests/integration/test_cdc_capture.py::test_cdc_compose_stack_captures_postgres_and_mysql_rows
tests/integration/test_iceberg_sink.py::test_repo_default_config_writes_to_rest_catalog
tests/integration/test_kafka_pipeline.py::TestKafkaPipeline::test_valid_order_event_reaches_validated_topic
tests/integration/test_kafka_pipeline.py::TestKafkaPipeline::test_invalid_event_goes_to_deadletter
tests/integration/test_kafka_pipeline.py::TestKafkaPipeline::test_api_serves_data_after_kafka_ingestion
tests/chaos/test_chaos_smoke.py::test_smoke_metric_endpoint_returns_503_on_duckdb_timeout
tests/chaos/test_chaos_smoke.py::test_smoke_entity_endpoint_returns_503_on_duckdb_timeout
tests/chaos/test_chaos_smoke.py::test_smoke_metrics_fall_back_when_redis_proxy_is_disabled
tests/chaos/test_kafka_latency.py::test_replay_succeeds_through_kafka_latency_proxy
tests/chaos/test_kafka_latency.py::test_replay_stays_pending_when_kafka_proxy_times_out
tests/chaos/test_redis_failure.py::test_metrics_fall_back_when_redis_proxy_is_disabled
```

### Integration default

```powershell
.venv\Scripts\python.exe -m pytest -p no:schemathesis tests\integration -q -rs --tb=short --basetemp=.tmp\pytest-audit-p6-integration-rs
```

Result: `193 passed, 8 skipped, 1 warning in 197.73s`.

Skip reasons:

```text
SKIPPED [1] tests\integration\test_cdc_capture.py:143: set AGENTFLOW_RUN_CDC_DOCKER=1 and start docker-compose.cdc.yml to run
SKIPPED [3] tests\integration\test_helm_values_live_validation.py: kind tests require explicit marker selection
SKIPPED [4] tests\integration\test_kafka_connect_helm_chart.py:17: helm is not installed
```

Warning:

```text
PytestCacheWarning: could not create cache path D:\DE_project\.pytest_cache\v\cache\nodeids: [WinError 5] Access is denied
```

Classification: no product failure. Skips are environment/toolchain gates.

### Chaos default

```powershell
$env:PYTHONFAULTHANDLER='1'
.venv\Scripts\python.exe -m pytest -p no:schemathesis tests\chaos -q -rs --tb=short -o faulthandler_timeout=90 --basetemp=.tmp\pytest-audit-p6-chaos
```

Result: `8 passed, 1 warning in 89.26s`.

Classification: no product failure. Previous `test_smoke_metric_endpoint_returns_503_on_duckdb_timeout` hang was not reproduced on this HEAD/env.

### Docker-disabled control

```powershell
$env:SKIP_DOCKER_TESTS='1'
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration tests\chaos -q -rs --tb=short --basetemp=.tmp\pytest-audit-p6-skip-docker
```

Result: `191 passed, 18 skipped in 170.14s`.

Docker/env skips:

```text
SKIPPED [1] tests\integration\test_iceberg_sink.py:235: SKIP_DOCKER_TESTS=1
SKIPPED [3] tests\integration\test_kafka_pipeline.py: SKIP_DOCKER_TESTS=1
SKIPPED [3] tests\chaos\test_chaos_smoke.py: SKIP_DOCKER_TESTS=1
SKIPPED [2] tests\chaos\test_kafka_latency.py: SKIP_DOCKER_TESTS=1
SKIPPED [1] tests\chaos\test_redis_failure.py: SKIP_DOCKER_TESTS=1
```

Other env/toolchain skips remained:

```text
SKIPPED [1] tests\integration\test_cdc_capture.py:143: set AGENTFLOW_RUN_CDC_DOCKER=1 and start docker-compose.cdc.yml to run
SKIPPED [3] tests\integration\test_helm_values_live_validation.py: kind tests require explicit marker selection
SKIPPED [4] tests\integration\test_kafka_connect_helm_chart.py:17: helm is not installed
```

Classification: Docker-dependent coverage is intentionally removed; non-Docker product surface still passes.

### Chaos DuckDB timeout without Docker stack

```powershell
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\chaos\test_duckdb_timeout.py -q --tb=short --basetemp=.tmp\pytest-audit-p6-chaos-no-docker-core
```

Result: `2 passed in 16.46s`.

Classification: product-relevant timeout mapping passes without Docker. The smoke wrappers are Docker-marked, but the core DuckDB timeout behavior is independently covered.

### CDC gated test without stack

```powershell
$env:AGENTFLOW_RUN_CDC_DOCKER='1'
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration\test_cdc_capture.py::test_cdc_compose_stack_captures_postgres_and_mysql_rows -q -rs --tb=short --basetemp=.tmp\pytest-audit-p6-cdc-gated
```

Result: `1 skipped in 2.55s`.

Skip reason:

```text
Kafka Connect is not running on http://127.0.0.1:8083
```

Classification: env only; no product assertion ran.

### CDC full compose attempt

```powershell
docker compose -f docker-compose.yml -f docker-compose.cdc.yml up -d --wait --wait-timeout 180 --remove-orphans
```

Result: FAIL before test execution.

Key error:

```text
failed to copy: httpReadSeeker: failed open: failed to do request ... net/http: TLS handshake timeout
```

Classification: Docker registry/network/env failure. Also the command target is too broad for the CDC test because it pulls unrelated base-stack services.

Cleanup:

```powershell
docker compose -f docker-compose.yml -f docker-compose.cdc.yml down -v --remove-orphans
```

### CDC minimal live run

```powershell
docker compose -f docker-compose.yml -f docker-compose.cdc.yml up -d --wait --wait-timeout 180 --remove-orphans kafka cdc-kafka-init postgres-source mysql-source kafka-connect cdc-register-connectors
```

Result: command exit `1`, but services reached healthy state and `cdc-register-connectors` exited `0`.

Reason for non-zero compose exit:

```text
container de_project-cdc-register-connectors-1 exited (0)
```

Service check:

```powershell
docker compose -f docker-compose.yml -f docker-compose.cdc.yml ps
```

Observed running healthy services:

```text
de_project-kafka-1             Up (healthy)
de_project-kafka-connect-1     Up (healthy)
de_project-mysql-source-1      Up (healthy)
de_project-postgres-source-1   Up (healthy)
```

Live CDC test:

```powershell
$env:AGENTFLOW_RUN_CDC_DOCKER='1'
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration\test_cdc_capture.py::test_cdc_compose_stack_captures_postgres_and_mysql_rows -q -rs --tb=short --basetemp=.tmp\pytest-audit-p6-cdc-live
```

Result: `1 passed in 73.44s`.

Cleanup:

```powershell
docker compose -f docker-compose.yml -f docker-compose.cdc.yml down -v --remove-orphans
```

Classification: product path passes. The recoverable issue is command ergonomics around compose one-shot services, not CDC behavior.

### Helm/kind explicit checks

```powershell
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration\test_helm_values_live_validation.py -m kind -q -rs --tb=short --basetemp=.tmp\pytest-audit-p6-kind-explicit
```

Result: `3 skipped in 0.39s`.

Skip reason:

```text
helm CLI is required for kind tests
```

```powershell
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration\test_kafka_connect_helm_chart.py -q -rs --tb=short --basetemp=.tmp\pytest-audit-p6-helm-chart
```

Result: `3 passed, 4 skipped in 0.76s`.

Skip reason:

```text
helm is not installed
```

Classification: env/toolchain missing. These tests can hide Helm chart product issues until `helm` and, for live validation, `kind` are installed.

## Failure classification

| Failure or blocked signal | Affected tests | Classification | Evidence | Product risk |
|---|---|---|---|---|
| Docker unavailable / disabled | Iceberg REST, Kafka pipeline, chaos ToxiProxy/Kafka/Redis tests | Docker/env only | `SKIP_DOCKER_TESTS=1` turns these into skips; same tests pass with Docker available, except CDC needs explicit stack | Low for current HEAD; failures here should first verify Docker daemon/ports/images |
| CDC stack not running | `test_cdc_compose_stack_captures_postgres_and_mysql_rows` | Docker/env only | With `AGENTFLOW_RUN_CDC_DOCKER=1` and no stack: `Kafka Connect is not running`; with minimal stack: `1 passed` | Low after stack is prepared |
| Full CDC compose pulls unrelated images and hits registry timeout | CDC setup command, not pytest assertion | Docker/env + command-scope issue | TLS handshake timeout while pulling base services | Low product risk; medium developer-experience risk |
| `cdc-register-connectors` one-shot exits `0`, compose `--wait` exits `1` | CDC setup command | Tooling/compose behavior | `container ... exited (0)` caused non-zero command despite healthy runtime services | Low product risk; can confuse CI/local recovery scripts |
| Missing `helm` | Kafka Connect Helm render/lint tests; kind live Helm tests | Env/toolchain | `helm is not installed`; `helm CLI is required for kind tests` | Medium hidden-risk: chart rendering/lint is not locally verified |
| Default kind skip | `tests/integration/test_helm_values_live_validation.py::*` | Intentional env gate | skipped unless explicit `-m kind` | Medium hidden-risk until explicit kind job runs |
| `.pytest_cache` permission denied | All pytest commands with cacheprovider enabled | Local filesystem env/noise | `PytestCacheWarning: Access is denied` | Low; use `-p no:cacheprovider` for audit/recovery commands |

## Product-problem candidates

None reproduced.

Fresh product-signaling assertions passed:

- Integration API/semantic/storage flows: `193 passed`.
- Chaos ToxiProxy/Kafka/Redis/DuckDB flows: `8 passed`.
- Direct DuckDB timeout behavior without Docker: `2 passed`.
- CDC Postgres/MySQL capture through Kafka Connect: `1 passed` with minimal live stack.

Remaining not-product-cleared surface:

- 4 Kafka Connect Helm CLI tests are skipped until `helm` is installed.
- 3 Helm live validation tests are skipped until explicit `-m kind` plus `helm`/`kind` toolchain are available.

## Recommended recovery commands

Use these for repeatable local recovery instead of the broad full-stack command:

```powershell
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration -q -rs --tb=short --basetemp=.tmp\pytest-integration
```

```powershell
$env:PYTHONFAULTHANDLER='1'
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\chaos -q -rs --tb=short -o faulthandler_timeout=90 --basetemp=.tmp\pytest-chaos
```

```powershell
docker compose -f docker-compose.yml -f docker-compose.cdc.yml up -d --remove-orphans kafka cdc-kafka-init postgres-source mysql-source kafka-connect cdc-register-connectors
$env:AGENTFLOW_RUN_CDC_DOCKER='1'
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration\test_cdc_capture.py::test_cdc_compose_stack_captures_postgres_and_mysql_rows -q -rs --tb=short --basetemp=.tmp\pytest-cdc-live
docker compose -f docker-compose.yml -f docker-compose.cdc.yml down -v --remove-orphans
```

For full Helm coverage, install `helm` and `kind`, then run:

```powershell
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration\test_kafka_connect_helm_chart.py -q -rs --tb=short --basetemp=.tmp\pytest-helm-chart
.venv\Scripts\python.exe -m pytest -p no:schemathesis -p no:cacheprovider tests\integration\test_helm_values_live_validation.py -m kind -q -rs --tb=short --basetemp=.tmp\pytest-kind-live
```

---

# Docs / Release Readiness / SDK Docs Audit

Note: this section was appended because `audit_codex_27_04_26_p6.md` already contained a parallel Docker/integration audit when the docs audit write was verified. The existing content above was preserved.

Date: 2026-04-27
Repo: `D:\DE_project`
HEAD: `4a13d36f9baa652cc0082ccbd04137d768f9929b`
Branch: `main`

## Baseline And Evidence

- Tracked files: `597`
- Markdown files in audit scope: `177`
- Package metadata:
  - root runtime: `agentflow-runtime` `1.1.0`
  - Python SDK: `agentflow-client` `1.1.0`
  - TypeScript SDK: `@agentflow/client` `1.1.0`
  - integrations: `agentflow-integrations` `1.0.1`
- Registry checks:
  - `npm view @agentflow/client version --json` -> `E404 Not Found`
  - `python -m pip index versions agentflow-client` -> no matching distribution
  - `python -m pip index versions agentflow-runtime` -> no matching distribution
  - `python -m pip index versions agentflow-integrations` -> no matching distribution
- Release checks:
  - `gh release view v1.1.0` -> release not found
  - `gh release view v1.0.0` and `v1.0.1` -> releases exist
  - `git ls-remote --tags origin` -> `v1.1.0` annotated tag peels to `1ee89a3`
  - `gh secret list` -> `NPM_TOKEN` exists, updated `2026-04-27T12:07:32Z`
  - GitHub environments: `production`, `pypi`, `staging`
- DNS checks:
  - `api.agentflow.dev` -> does not resolve
  - `agentflow-demo.fly.dev` -> does not resolve from this workstation
- Test inventory, collect-only:
  - all tests: `676`
  - non-load tests: `674`
  - unit `396`, integration `202`, e2e `18`, property `15`, contract `8`, chaos `8`, sdk `17`
  - release slice `tests/unit tests/integration tests/sdk`: `615`
  - `tests/integration -m integration`: `184/202 selected`

## Stale Claims And Exact Documentation Fixes

### 1. Registry install docs read as live, but packages are not published

Files: `sdk/README.md`, `sdk-ts/README.md`, `docs/integrations.md`, `docs/product.md`, `docs/migration/v1.1.md`.

Why stale: PyPI/npm lookups for `agentflow-client`, `agentflow-runtime`, `agentflow-integrations`, and `@agentflow/client` all returned not found. `docs/release-readiness.md` correctly says registry publish is incomplete, but user-facing install docs still read as if the packages are available.

Exact fixes:

```diff
--- sdk/README.md
- > Installed from PyPI as **`agentflow-client`**. Python import remains `agentflow`.
+ > PyPI distribution name: **`agentflow-client`**. Registry publishing is not complete as of 2026-04-27; until the first green `Publish Python Packages` run, use the local editable install below. Python import remains `agentflow`.
```

```diff
--- sdk-ts/README.md
  # @agentflow/client
+
+ npm package name: **`@agentflow/client`**. Registry publishing is not complete as of 2026-04-27; until the first green `Publish TypeScript SDK` run, use the local workspace build.
```

```diff
--- docs/integrations.md
- Install the published integrations package:
+ After registry publish, install the integrations package:

- If you are working from this monorepo, use a local editable install instead:
+ In the current checked-in repo, use a local editable install:
```

```diff
--- docs/product.md
- Install the SDK with `pip install agentflow-client` (or `python -m pip install -e "./sdk"` when working from this repo).
+ Install the SDK from this repo with `python -m pip install -e "./sdk"`; after the first green registry publish, use `pip install agentflow-client`.
```

```diff
--- docs/migration/v1.1.md
- The SDK is published as **`agentflow-client`** instead.
+ The SDK distribution name is **`agentflow-client`**. As of 2026-04-27 the registry publish is still pending; use local editable installs until the first green publish workflow completes.

- The root repository now publishes as **`agentflow-runtime`** on PyPI, while the Python SDK publishes as **`agentflow-client`**
+ The root repository metadata is **`agentflow-runtime`**, while the Python SDK metadata is **`agentflow-client`**
```

Add to `docs/release-readiness.md` under `## SDK Publish Proof Path`:

```markdown
- Registry lookups on 2026-04-27 still returned not found for PyPI `agentflow-runtime`, PyPI `agentflow-client`, PyPI `agentflow-integrations`, and npm `@agentflow/client`; treat install commands as post-publish commands until the publish workflows are green.
```

### 2. TypeScript API examples import the wrong package

File: `docs/api-reference.md`

Stale lines: TypeScript examples import from `"agentflow"` at all lines matching `import { AgentFlowClient } from "agentflow";`.

Evidence: `sdk-ts/package.json` names the package `@agentflow/client`; `sdk-ts/README.md` uses `@agentflow/client`.

Exact fix, apply to all TypeScript SDK examples:

```diff
- import { AgentFlowClient } from "agentflow";
+ import { AgentFlowClient } from "@agentflow/client";
```

### 3. API reference uses a public hostname that does not resolve

File: `docs/api-reference.md`

Stale claim: examples use `https://api.agentflow.dev` while the document's base URL says `http://localhost:8000`.

Evidence: `Resolve-DnsName api.agentflow.dev` failed with DNS name does not exist.

Exact fixes:

```diff
  - Base URL: `http://localhost:8000`
+ - Public hosted URL: not provisioned in this repository snapshot. Replace `http://localhost:8000` with your deployed base URL after deployment.
```

Replace example URLs:

```diff
- https://api.agentflow.dev
+ http://localhost:8000
```

### 4. README overstates current release/test status

File: `README.md`

Stale claims:

- badge: `tests-668_full_suite-green`
- highlight: `668 tests passing in the latest full-suite local gate`
- status: `v1.1.0 is technically release-ready`

Evidence:

- `docs/release-readiness.md` says the fresh pre-commit full-suite gate is blocked by a chaos smoke hang.
- Current collect-only sees `676` tests, so the badge looks like a stale current-count claim.
- registry packages are still unpublished.

Exact fixes:

```diff
- [![Tests](https://img.shields.io/badge/tests-668_full_suite-green)](docs/release-readiness.md)
+ [![Release gate](https://img.shields.io/badge/release_gate-blocked_on_chaos_smoke-yellow)](docs/release-readiness.md)
```

```diff
- **668 tests passing in the latest full-suite local gate**, plus the verified unit/integration/sdk release slice retained as the fast release check
+ **Last completed local full-suite gate:** 668 passed, 8 skipped on 2026-04-27. The current fresh pre-commit release gate is blocked on a chaos smoke hang; see Release Readiness for the live status.
```

```diff
- **v1.1.0** is technically release-ready for the checked-in repository.
+ **v1.1.0** is prepared in the checked-in repository, but the live release is not complete.
```

Add to the same paragraph:

```markdown
Current blockers: fresh pre-commit full-suite completion, first green npm/PyPI publish workflows, and registry package availability.
```

### 5. README clone URL still uses a placeholder

File: `README.md`

Exact fix for both Quick start blocks:

```diff
- git clone https://github.com/<your-handle>/agentflow.git
+ git clone https://github.com/brownjuly2003-code/agentflow.git
```

### 6. Quality report is stale

File: `docs/quality.md`

Stale claims:

- generated `2026-04-12T18:45:16+00:00`
- old suite counts: unit `207`, integration `174`, e2e `13`, contract `13`, chaos `5`
- old coverage/security/performance snapshot

Evidence: current collect-only counts are unit `396`, integration `202`, e2e `18`, contract `8`, chaos `8`, total `676`.

Exact fix:

```bash
python scripts/quality_report.py --output docs/quality.md
```

If not regenerating immediately, mark it as stale:

```diff
- # AgentFlow Quality Report
+ # AgentFlow Quality Report (stale local snapshot)
```

and add:

```markdown
> This report was generated on 2026-04-12 and does not reflect the current test inventory. Current collect-only on 2026-04-27 found 676 tests.
```

### 7. Glossary has stale full-suite numbers

File: `docs/glossary.md`

Stale claim: latest full local gate gives `663 passed, 7 skipped`.

Exact fix:

```diff
- на 2026-04-27 он даёт `663 passed, 7 skipped`
+ последний завершённый локальный full-suite gate на 2026-04-27 дал `668 passed, 8 skipped`; текущий fresh pre-commit gate заблокирован chaos smoke hang, см. `docs/release-readiness.md`
```

### 8. Engineering standards disagree with CI coverage threshold

File: `docs/engineering-standards.md`

Stale claims:

- `--cov-fail-under=80`
- PRs require coverage `>= 80%`

Evidence: `.github/workflows/ci.yml` uses `--cov-fail-under=60`; `docs/contributing.md` correctly says full-project floor is `60%` and changed-line coverage remains `80%` via Codecov patch status.

Exact fixes:

```diff
- pytest tests/unit/ -v --tb=short --cov=src --cov=sdk --cov-report=xml --cov-report=term-missing --cov-fail-under=80
+ python -m pytest tests/unit/ tests/property/ -v --tb=short --cov=src --cov=sdk --cov-report=xml --cov-report=term-missing --cov-fail-under=60
```

```diff
- Pull requests to `main` must pass lint, mypy, unit tests with coverage `>= 80%`, integration tests, schema evolution check, performance regression check, and Terraform validation.
+ Pull requests to `main` must pass lint, mypy, unit + property tests with a full-project coverage floor of `>= 60%`, Codecov patch coverage at `>= 80%`, integration tests, schema evolution check, performance regression check, and Terraform validation.
```

### 9. Runbook says `make demo` is "no Docker", but it starts Redis via Docker Compose

File: `docs/runbook.md`

Evidence: `Makefile` target `demo` runs `docker compose up -d redis`.

Exact fixes:

```diff
- ### Start the end-to-end demo (no Docker)
+ ### Start the local demo (Docker Redis only)

- make demo          # Seeds 500 events, starts API
+ make demo          # Seeds 500 events, starts Redis, starts API
```

### 10. E2E docs use `--timeout`, but normal dev setup does not install `pytest-timeout`

File: `docs/contributing.md`

Evidence:

- E2E workflow installs `pytest-timeout` explicitly.
- root `dev` extra does not include `pytest-timeout`.

Exact doc fix, before each E2E command using `--timeout`:

```bash
python -m pip install pytest-timeout
```

Alternative:

```diff
- pytest tests/e2e/ -v --tb=short --timeout=60
+ pytest tests/e2e/ -v --tb=short
```

Preferred: document the explicit install, because CI also uses `--timeout=60`.

### 11. Migration guide references a nonexistent runtime module

File: `docs/migration/v1.1.md`

Stale claims:

- `from agentflow.processing.pipeline import run_pipeline`
- `from src.processing.pipeline import run_pipeline`

Evidence:

- `src/processing/pipeline.py` does not exist.
- Actual local pipeline module is `src/processing/local_pipeline.py`.

Exact fixes:

```diff
- from agentflow.processing.pipeline import run_pipeline
+ from agentflow.processing.local_pipeline import run

- from src.processing.pipeline import run_pipeline
+ from src.processing.local_pipeline import run
```

Better user-facing replacement:

```bash
python -m src.processing.local_pipeline --burst 500
```

### 12. API reference says examples align with "published" clients

File: `docs/api-reference.md`

Stale claim: "published Python/TypeScript clients".

Exact fix:

```diff
- Operational, governance, and admin routes are present in the HTTP API but do not yet expose first-class helpers in the published Python/TypeScript clients.
+ Operational, governance, and admin routes are present in the HTTP API but do not yet expose first-class helpers in the current Python/TypeScript client code.
```

### 13. OpenAPI version reads `1.0.0` while package docs discuss `1.1.0`

Files: `docs/openapi.json`, `docs/api-reference.md`, `src/serving/api/main.py`

Evidence: FastAPI app version is `1.0.0`; generated OpenAPI `info.version` is `1.0.0`; package metadata is `1.1.0`.

Doc-only fix if `1.0.0` is the API contract version:

```markdown
Note: OpenAPI `info.version` currently tracks the HTTP API contract version (`1.0.0`), not the package/release version (`1.1.0`).
```

If not intentional, the source fix is code plus regeneration:

```bash
make tools
```

### 14. Screenshot section points to a directory that is absent

Files: `README.md`, `docs/publication-checklist.md`

Evidence: `docs/screenshots/` does not exist.

Exact fix:

```diff
- The repository is prepared for optional README screenshots under `docs/screenshots/`:
+ Optional README screenshots are not committed yet. When capture is complete, store them under `docs/screenshots/`:
```

Add to `docs/publication-checklist.md`:

```markdown
If screenshots are not part of the release, leave this section unchecked and do not imply that `docs/screenshots/` exists.
```

## Priority Order

1. Fix registry-publish wording in SDK/integrations/product/migration docs.
2. Fix TypeScript imports in `docs/api-reference.md`.
3. Replace or caveat `https://api.agentflow.dev`.
4. Update README release/test status to show the current blocked release gate.
5. Regenerate or mark `docs/quality.md` as stale.
6. Align `docs/engineering-standards.md` with CI coverage gates.

## Verification Notes

- Full test suite was not run for this docs audit.
- Test numbers above are collect-only.
- Source documentation was not directly edited; this section provides exact changes to apply.
