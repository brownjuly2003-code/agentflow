# AgentFlow (DE_project) — Исследование открытых пунктов audit_kimi_04_05_26.md

**Дата:** 2026-05-05
**Контекст:** Локальный remediation-пакет 2026-05-05 уже закрыл H1/H2/L1 (Docker), M5 (MinIO pin), M10 (Helm tag 1.1.0), M12 (request body size middleware).
**Цель:** Для оставшихся открытых пунктов H3–H6, M1–M4/M7–M9, L6–L7 проверить current best practice по первичным источникам (OWASP/ASVS, SLSA/Sigstore, Syft/Trivy, Bandit/Ruff/mypy docs) и зафиксировать результат.

---

## Реестр открытых пунктов и выводы по best practice

### 🔴 High Priority

#### H3. DuckDB в K8s с `ReadWriteOnce` PVC при `replicaCount: 2`

**Текущее состояние:** `helm/agentflow/values.yaml` содержит `replicaCount: 2`, HPA `minReplicas: 2`, `persistence.accessModes: [ReadWriteOnce]`. Каждый pod получает свой PVC с изолированным `.duckdb`-файлом. Данные между репликами расходятся (split-brain при записи).

**Первичные источники / best practice:**
- **OWASP ASVS 4.0.3 V1.1.2 / V1.6** — архитектурные контроли требуют документирования trust boundaries и stateful/stateless разделения. Stateful сервис с неконсистентным storage нарушает принцип единого источника истины.
- **Kubernetes best practice (CNCF / SIG-Storage)** — `ReadWriteOnce` + multi-replica Deployment = антипаттерн для read-write нагрузки. Для shared state требуется `ReadWriteMany` (если СХД поддерживает) или отказ от shared writable storage в пользу внешней БД.
- **DuckDB официальная документация** — DuckDB спроектирована как in-process, single-node аналитическая БД. Нет встроенной multi-master replication. Для concurrent write из нескольких pod она не предназначена.

**Вывод:** Для production serving в K8s с `replicaCount > 1` DuckDB на `ReadWriteOnce` PVC является архитектурным mismatch. Best practice — либо ClickHouse backend (уже реализован как опция), либо single-replica StatefulSet с отключённым HPA для writer + read-only реплики через другой механизм.

---

#### H4. AWS Terraform apply отключен, OIDC не настроен

**Текущее состояние:** `.github/workflows/terraform-apply.yml` имеет `if: false` для обоих jobs (plan/apply). В репозитории отсутствуют `AWS_TERRAFORM_ROLE_ARN` и реальные `.tfvars`. Terraform validate проходит, но apply не автоматизирован.

**Первичные источники / best practice:**
- **OWASP ASVS V14.1.2 / V14.1.6** — build pipeline должен содержать шаги автоматической сборки и верификации безопасного деплоя, включая IaC.
- **SLSA v1.0 Build L2+** — требует versioned build service (CI/CD) с tamper-resistant provenance. Disabled workflow = отсутствие воспроизводимого infrastructure deployment.
- **GitHub Security hardening** — OIDC (`id-token: write`) + `aws-actions/configure-aws-credentials` с `role-to-assume` является рекомендованным паттерном вместо long-lived AWS credentials. AWS и GitHub документируют это как best practice для всех production Terraform pipeline.

**Вывод:** Без включённого Terraform apply и настроенного OIDC инфраструктура не может считаться production-hardened. Рекомендуется: (1) создать IAM role с trust policy на GitHub OIDC, (2) добавить repo-level variable `AWS_TERRAFORM_ROLE_ARN`, (3) создать `staging.tfvars` из example, (4) включить workflow поэтапно (staging → prod) с `environment` protection rules.

---

#### H5. Нет external penetration test

**Текущее состояние:** В репозитории нет отчётов о внешнем пентесте.

**Первичные источники / best practice:**
- **OWASP ASVS 4.0.3** — пентест (manual/automated) является стандартным методом верификации для L2+. ASVS прямо рекомендует penetration testing для проверки controls, которые невозможно полностью покрыть SAST/DAST.
- **OWASP WSTG (Web Security Testing Guide)** — определяет методологию black/grey box тестирования.
- **SOC 2 Type II / ISO 27001** — external penetration test обычно требуется ежегодно (или при существенных изменениях) для enterprise compliance.

**Вывод:** Для enterprise sales и compliance (SOC 2, ISO 27001) external penetration test — must-have. Рекомендуется заказать тестирование от аккредитованного vendor (Bishop Fox, Cobalt, Synack) с охватом API, tenant isolation, SQL guard, auth flow.

---

#### H6. DuckDB encryption at rest не доказана

**Текущее состояние:** Локальные `.duckdb`-файлы на PVC не показывают evidence of encryption. В конфигурации нет `PRAGMA encryption` или параметров `ENCRYPTION_KEY`.

**Первичные источники / best practice:**
- **OWASP ASVS 4.0.3 V6.1.1 / V6.1.2** — regulated private/health data must be stored encrypted at rest (L2/L3). GDPR Article 32 требует «appropriate technical measures, such as encryption».
- **DuckDB официальный блог (ноябрь 2025)** — начиная с DuckDB v1.4.0 поддерживается transparent data encryption (AES-GCM-256 / AES-CTR-256). Для включения используется:
  ```sql
  ATTACH 'encrypted.duckdb' AS enc (ENCRYPTION_KEY 'key', ENCRYPTION_CIPHER 'GCM');
  ```
  - Важное ограничение: encryption в DuckDB 1.4.x **ещё не имеет NIST compliance** (issue `#20162` — отслеживается). Для HIPAA/GDPR strict interpretation это может быть blocker.
- **NIST SP 800-57 / SP 800-171** — key management должен быть centralized, с separation of duties и регулярной ротацией.

**Вывод:** Для GDPR/HIPAA compliance необходимо либо (1) включить DuckDB encryption at rest (AES-GCM) с внешним key management (KMS), либо (2) мигрировать sensitive data на backend с проверенным at-rest encryption (ClickHouse с encrypted volumes / AWS RDS / etc.). Учитывать ограничение NIST-compliance в текущей версии DuckDB.

---

### 🟡 Medium Priority

#### M1. Ruff игнорирует `S608` (SQL injection) глобально

**Текущее состояние:** `pyproject.toml`:
```toml
[tool.ruff.lint]
ignore = ["S101", "S311", "S608"]
```

**Первичные источники / best practice:**
- **Ruff docs (astral.sh)** — рекомендует использовать `per-file-ignores` вместо глобального `ignore` для security-правил. Глобальное игнорирование `S608` скрывает потенциальные SQL injection во всех модулях, включая новый код.
- **Bandit / flake8-bandit upstream** — `S608` отмечает string-based query construction. Ложные срабатывания возможны, но подавлять их следует inline (`# noqa: S608`) или `per-file-ignores` с обоснованием, а не глобально.
- **OWASP ASVS V5.3** — все параметризованные queries должны использовать prepared statements / parameterized queries. Static analysis gate должен блокировать string formatting в SQL.

**Вывод:** Лучшая практика — убрать `S608` из глобального `ignore`, оставить только в `per-file-ignores` для файлов с валидированными `sqlglot`-путями, с комментарием-обоснованием. Для `src/serving/semantic_layer/query_engine.py` (где sqlglot guard активен) допустимо исключение через `per-file-ignores`, для остальных модулей — нет.

---

#### M2. Bandit пропускает `B608` глобально

**Текущее состояние:** `.bandit`:
```ini
[bandit]
skips = B101,B311,B608
```

**Первичные источники / best practice:**
- **Bandit docs (PyCQA)** — `skips` в `.bandit` применяется глобально. Рекомендуется использовать inline `# nosec B608` с justification для конкретных строк, либо exclude_dirs для test files.
- **Bandit baseline diff gate** — текущий CI использует `bandit_diff.py` для сравнения с `.bandit-baseline.json`. Глобальный skip означает, что новый код с B608 вообще не попадёт в baseline diff.
- **OWASP ASVS V5.3 / V14.2** — SAST tools должны быть сконфигурированы для минимизации false negatives на injection-уязвимостях.

**Вывод:** Аналогично M1 — перейти на per-file / per-line suppression. Убрать `B608` из глобального `skips`. Для `sqlglot`-путей использовать `# nosec B608` с комментарием, либо настроить `exclude_dirs` только для директорий с известными safe patterns.

---

#### M3. mypy `disallow_untyped_defs = false`

**Текущее состояние:** `pyproject.toml`:
```toml
[tool.mypy]
disallow_untyped_defs = false
```
Flink paths полностью игнорируются (`ignore_errors = true` для `src.processing.flink_jobs.*`).

**Первичные источники / best practice:**
- **mypy docs** — `disallow_untyped_defs = true` является core флагом strict mode. Без него mypy пропускает не типизированные функции, что снижает value type checking.
- **Eightfold.ai / mypy best practices (2026)** — рекомендуется two-tier system: strict mode (`disallow_untyped_defs = true`) для новых/критичных модулей, lenient mode для legacy. Для постепенной миграции используется per-module override, а не глобальное `false`.
- **Python typing community best practice** — `check_untyped_defs = true` (уже включён в проекте) частично компенсирует, но не заменяет `disallow_untyped_defs` для нового кода.

**Вывод:** Рекомендуется установить `disallow_untyped_defs = true` для `src/serving/`, `src/quality/`, `src/ingestion/` (core runtime). Для Flink jobs и legacy модулей оставить override `false` или `ignore_errors = true` до миграции. Это соответствует постепенному (gradual) подходу без глобальной потери strictness.

---

#### M4. Helm values содержат bcrypt hashes

**Текущее состояние:** `helm/agentflow/values.yaml` содержит plaintext bcrypt hashes:
```yaml
secrets:
  apiKeys:
    keys:
      - key_hash: "$2b$12$UNE9Vh.YivKR7Zt7xIZweebebjkcVaQv240rqabzG/H3dWoljplcO"
```

**Первичные источники / best practice:**
- **OWASP ASVS V6.4.1** — cryptographic keys must not be stored in application code / config. Secrets should be managed via dedicated secret management system.
- **Kubernetes docs / Helm best practices** — sensitive data в `values.yaml` создаёт риск утечки через Git history, CI logs, helm chart museum. Рекомендуется External Secrets Operator, Vault Agent Injector, Sealed Secrets или `helm-secrets` + SOPS.
- **NIST SP 800-57** — key storage требует access controls, encryption at rest, audit logging.

**Вывод:** Bcrypt hashes, хотя и не являются plaintext keys, всё равно чувствительны к rainbow-table атакам при известном salt. Best practice — вынести их из `values.yaml` в external secret store (AWS Secrets Manager / Vault / External Secrets Operator) и монтировать в pod как `env` или `volume` из Kubernetes Secret.

---

#### M7. Нет rollback workflow

**Текущее состояние:** Нет GitHub Action для автоматизированного `helm rollback` при failed deploy. `staging-deploy.yml` делает deploy в kind, но rollback не реализован.

**Первичные источники / best practice:**
- **Helm docs (helm.sh)** — `helm rollback <release> [revision]` с `--cleanup-on-fail`, `--wait`, `--timeout`. Best practice: автоматический rollback при fail smoke tests.
- **CNCF / Helm best practices** — `--atomic` flag в `helm upgrade --install` автоматически откатывает при failure. Это native guard.
- **GitHub Actions best practice** — pattern: deploy → smoke test → rollback on failure. Сохранение `previous_revision` через `helm history` + `jq` для точного отката.

**Вывод:** Рекомендуется добавить `--atomic` к `helm upgrade` в CI/CD pipeline. Для production — отдельный workflow с шагами: (1) capture current revision, (2) deploy, (3) smoke test, (4) `helm rollback` on failure. Это минимизирует downtime при битых релизах.

---

#### M8. Coverage gate 60% — низкий

**Текущее состояние:** CI (`ci.yml`) использует `--cov-fail-under=60` для unit/property тестов. Codecov patch gate — 80% для changed code.

**Первичные источники / best practice:**
- **OWASP ASVS V14.1** — build pipeline должен включать automated testing с adequate coverage. Для core security modules (auth, access control, crypto) требуется более высокое покрытие.
- **Industry best practice (Google SRE, Martin Fowler)** — 60% — минимальный порог для legacy; для critical paths рекомендуется 80%+. Mutation testing (mutmut, уже используется) компенсирует низкое line coverage, но не заменяет его для нового кода.
- **NIST SSDF / secure SDLC** — security-critical modules должны иметь максимально возможное покрытие тестами.

**Вывод:** Рекомендуется tiered coverage gate: 75–80% для `src/serving/`, `src/quality/`, `src/ingestion/` (core), 60% для Flink jobs и интеграционных тестов. Текущий 60% — acceptable для общего gate, но недостаточен для security-critical модулей без дополнительных compensating controls (mutation testing + chaos + property-based tests уже частично компенсируют).

---

#### M9. Нет immutable audit log

**Текущее состояние:** `api_usage` пишется в DuckDB — mutable storage. Нет dedicated Kafka topic или WORM storage для compliance audit trail.

**Первичные источники / best practice:**
- **OWASP ASVS 4.0.3 V7.3.3** — «Verify that security logs are protected from unauthorized access and modification» (L2/L3).
- **OWASP ASVS V7.1.3 / V7.1.4** — security relevant events (auth, access control failures) must be logged with detailed metadata.
- **NIST SP 800-53 AU-6 / AU-11** — audit records must be retained and protected from modification. WORM (Write Once Read Many) storage recommended.
- **Telekom Security CP 5.4.4 / 5.4.6** — log data SHALL be collected in separate tamper-proof system; entries can only be added but not deleted during retention period.

**Вывод:** DuckDB как mutable storage для audit log не соответствует L2/L3 требованиям. Best practice — создать dedicated Kafka topic (`api_usage.audit`) с `cleanup.policy=compact,retention.ms=-1` (или log retention по compliance требованиям) + консьюмер, записывающий в WORM storage (S3 Object Lock, AWS QLDB, или append-only ClickHouse). Альтернатива: hash chain (Merkle tree) для integrity verification.

---

### 🟢 Low Priority

#### L6. Нет SBOM generation

**Текущее состояние:** В CI отсутствует генерация Software Bill of Materials. Trivy используется только для vulnerability scanning container image.

**Первичные источники / best practice:**
- **OWASP SCVS (Software Component Verification Standard)** — SBOM generation является обязательным начиная с Level 2 (Inventory + BOM maturity).
- **CISA Minimum Elements for SBOM (2025)** — требует machine-readable SBOM (SPDX или CycloneDX) для каждого релиза.
- **NIST SP 800-161r1 SR-4** — SBOMs should be digitally signed using a verifiable and trusted key.
- **Syft / Trivy docs** — Syft (Anchore) — de facto стандарт для container SBOM: `syft <image> -o cyclonedx-json`. Trivy: `trivy image --format cyclonedx`. Обе утилиты поддерживают SPDX и CycloneDX.
- **EU Cyber Resilience Act (CRA)** — с декабря 2027 machine-readable SBOMs станут обязательными для ПО на рынке ЕС.

**Вывод:** Рекомендуется добавить SBOM generation в CI (security.yml или publish-pypi.yml). Минимальный viable flow: `syft dir:. -o cyclonedx-json > sbom.cdx.json` для source + `syft agentflow-api:latest -o spdx-json > sbom.spdx.json` для image. Артефакты прикреплять к release. Это закрывает требования NIST/CISA и готовит к CRA.

---

#### L7. Нет signed container images

**Текущее состояние:** Container image `agentflow-api` собирается в CI, но не подписывается. Нет cosign / Sigstore интеграции.

**Первичные источники / best practice:**
- **SLSA v1.0** — Level 2 требует signed provenance, generated by build service. Level 3 — non-falsifiable provenance + build isolation.
- **Sigstore / Cosign** — keyless signing через GitHub OIDC (`id-token: write`) является стандартом де-факто: `cosign sign --yes ghcr.io/...@${{ steps.build.outputs.digest }}`. Не требует управления ключами.
- **OWASP ASVS V14.1 / SCVS V6** — software provenance must be documented; build artifacts should be signed.
- **GitHub docs (2026)** — `actions/attest-build-provenance@v2` предоставляет native SLSA Level 3 provenance без дополнительных инструментов.

**Вывод:** Рекомендуется добавить в `publish-pypi.yml` (или отдельный `container-sign.yml`) два шага: (1) `sigstore/cosign-installer` + `cosign sign` для image digest, (2) опционально `actions/attest-build-provenance` для SLSA provenance. Это достигает SLSA Level 2+ для container artifacts. Для Kubernetes admission control можно добавить Kyverno/Sigstore policy-controller позже.

---

## Сводная таблица соответствия primary sources

| ID | Проблема | Primary Source | Key Requirement | Статус в проекте |
|----|----------|---------------|-----------------|------------------|
| H3 | DuckDB RWO PVC + replicaCount:2 | K8s SIG-Storage / DuckDB docs | Stateful shared storage anti-pattern | ⚠️ Открыт |
| H4 | Terraform apply disabled | OWASP ASVS V14.1.2 / SLSA L2 | Automated secure deployment via CI | ⚠️ Открыт |
| H5 | No external pentest | OWASP ASVS / WSTG | Manual verification for L2+ | ⚠️ Открыт |
| H6 | DuckDB encryption at rest | OWASP ASVS V6.1.1 / GDPR Art.32 | At-rest encryption for regulated data | ⚠️ Открыт |
| M1 | Ruff ignores S608 globally | Ruff docs / ASVS V5.3 | Per-file security rule suppression | ⚠️ Открыт |
| M2 | Bandit skips B608 globally | Bandit docs / ASVS V14.2 | Per-line `# nosec` with justification | ⚠️ Открыт |
| M3 | mypy `disallow_untyped_defs=false` | mypy docs / typing best practices | Gradual strict mode per module | ⚠️ Открыт |
| M4 | bcrypt hashes in Helm values | OWASP ASVS V6.4.1 / NIST 800-57 | External secret management | ⚠️ Открыт |
| M7 | No rollback workflow | Helm docs / CNCF best practices | Atomic deploy + auto-rollback | ⚠️ Открыт |
| M8 | Coverage gate 60% | OWASP ASVS V14.1 / NIST SSDF | Tiered coverage for critical modules | ⚠️ Открыт |
| M9 | No immutable audit log | OWASP ASVS V7.3.3 / NIST AU-11 | Tamper-proof audit storage | ⚠️ Открыт |
| L6 | No SBOM generation | OWASP SCVS / CISA / NIST 800-161r1 | Signed machine-readable SBOM | ⚠️ Открыт |
| L7 | No signed container images | SLSA v1.0 / Sigstore | Keyless signing + provenance | ⚠️ Открыт |

---

## Уже закрытые пункты (remediation 2026-05-05)

| ID | Проблема | Действие | Подтверждение |
|----|----------|----------|---------------|
| H1 | Editable install в Dockerfile | Перешли на multi-stage build + `python -m build` + wheel install | `Dockerfile.api` использует `FROM python:3.11-slim AS builder` |
| H2 | Отсутствие `.dockerignore` | Создан `.dockerignore` | Проверено в корне репозитория |
| L1 | Нет HEALTHCHECK | Добавлен `HEALTHCHECK` в `Dockerfile.api` | Строка 38: `HEALTHCHECK --interval=30s...` |
| M5 | `minio/minio:latest` | Закреплён tag `RELEASE.2025-09-07T16-13-09Z` | `docker-compose.yml` |
| M10 | Helm image tag 1.0.0 vs runtime 1.1.0 | Обновлён на `tag: "1.1.0"` | `helm/agentflow/values.yaml` строка 8 |
| M12 | Нет request body size middleware | Добавлен middleware в `src/serving/api/security.py` | Реализована проверка `content-length` |

---

*Документ подготовлен на основе статического анализа DE_project, первичных источников OWASP ASVS 4.0.3/5.0 RC1, SLSA v1.0, NIST SP 800-161r1/800-53/800-57, документации Syft/Trivy/Bandit/Ruff/mypy, и официальных документов DuckDB / Helm / Kubernetes. Дата: 2026-05-05.*
