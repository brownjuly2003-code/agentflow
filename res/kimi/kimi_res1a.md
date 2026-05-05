# Исследование оставшихся открытых пунктов audit_kimi_04_05_26.md

**Дата:** 2026-05-05
**Контекст:** После локального remediation-пакета 2026-05-05 (закрыты H1/H2/L1/M5/M10/M12) остаются открытыми пункты H3–H6, M1–M4/M7–M9, L6–L7.
**Методология:** Проверка current best practice по первичным источникам — Kubernetes Docs, DuckDB.org, Ruff/Bandit/mypy docs, Helm Docs, OWASP/NIST/PTES, Confluent/Kafka Docs, Sigstore/SLSA/CISA.
**Ограничение:** Без deploy/apply/push/paid actions — только research и локальные рекомендации.

---

## 🔴 High Priority (H3–H6)

### H3. DuckDB в K8s с `ReadWriteOnce` PVC при `replicaCount: 2`

**Проблема:** Data divergence между репликами, split-brain — каждый Pod получает изолированный PVC, и нет механизма репликации данных между ними.

**Current best practice (первичные источники):**
- **Kubernetes Docs — StatefulSet**: StatefulSets создают *уникальный PVC на каждый Pod* через `volumeClaimTemplates` с access mode `ReadWriteOnce`. Это by design обеспечивает изолированное хранилище per-pod, а не shared storage. Для production Kubernetes project рекомендует `ReadWriteOncePod` вместо `ReadWriteOnce` ( StatefulSet persistent storage docs, 2026-03-16).
- **DuckDB Docs**: DuckDB — in-process embedded database. Она *не поддерживает concurrent writers* к одному файлу. Можно распространять encrypted database read-only (например, через CDN), но это требует явного `ATTACH ... READ_ONLY` и не решает проблему записи (DuckDB Blog, 2025-11-19).

**Рекомендация для AgentFlow:**
1. **Immediate fix**: `replicaCount: 1` для DuckDB-backed Deployment/StatefulSet + отключение HPA для writer. Читатели — через отдельный read-only механизм (ClickHouse backend, который уже есть в проекте).
2. **Стратегически**: Перейти на ClickHouse для production serving, оставив DuckDB только для local dev / CI. Это соответствует audit-рекомендации и архитектурному риску "Single-node DuckDB bottleneck".

---

### H4. AWS Terraform apply отключен, OIDC не настроен

**Проблема:** Workflow `.github/workflows/terraform-apply.yml` имеет `if: false`. Нет реального production infrastructure deploy.

**Current best practice (первичные источники):**
- **AWS + GitHub Actions OIDC**: Использование `configure-aws-credentials@v4` с `role-to-assume` и `id-token: write` — industry standard. Устраняет необходимость в long-lived AWS credentials в GitHub Secrets (AWS Docs / GitHub Actions, 2025).
- **Terraform CI/CD best practices** (Terrateam / HashiCorp):
  - `terraform plan` на каждом PR с постингом результата.
  - `terraform apply` только на merge в `main`, с manual approval gate для production.
  - S3 backend + DynamoDB locking для state.
  - Separate plan и apply permissions (plan — read-only).

**Рекомендация для AgentFlow:**
1. Создать IAM OIDC Identity Provider в AWS (`token.actions.githubusercontent.com`).
2. Создать IAM Role с trust policy, restricted до `repo:org/DE_project:ref:refs/heads/main`.
3. Убрать `if: false` из workflow, добавить `environment: production` с required reviewers.
4. Добавить `terraform plan` job на PR (без apply).
5. Зафиксировать в `docs/` ADR с описанием OIDC trust policy.

---

### H5. Нет external penetration test

**Проблема:** Отсутствие evidence независимого pentest блокирует enterprise security claims.

**Current best practice (первичные источники):**
- **OWASP Testing Guide v5**: Gold standard для web application security assessments. 286 test cases, покрывающие XSS, SQL injection, broken authentication и др.
- **NIST SP 800-115**: Технический гид для government/enterprise security testing. Определяет три категории: review, target identification, vulnerability validation.
- **PTES (Penetration Testing Execution Standard)**: 7 фаз — от pre-engagement до reporting.
- **Frequency**: PCI DSS и HIPAA требуют annual pentest. High-risk environments — quarterly. Major releases требуют targeted retest (NetSPI / ClearFuze, 2025–2026).

**Рекомендация для AgentFlow:**
1. **Краткосрочно (1–3 мес.)**: Заказать external pentest у CREST/OSCP-certified провайдера с OWASP Testing Guide + PTES methodology. Обязательные scope: API (FastAPI), K8s ingress, tenant isolation, SQL guard.
2. **До pentestа**: Запустить автоматизированный DAST (OWASP ZAP) в CI для baseline.
3. **Результат**: Получить формальный отчет с CVSS scoring, compliance mapping (GDPR/SOC 2/HIPAA) и evidence of remediation.

---

### H6. DuckDB encryption at rest не доказана

**Проблема:** Локальные `.duckdb` файлы не показывают evidence of encryption. Для GDPR/HIPAA — blocker.

**Current best practice (первичные источники):**
- **DuckDB 1.4.0+**: Поддерживает transparent data encryption с AES-GCM-256 (рекомендуется) и AES-CTR-256. Шифруются: основной файл БД, WAL, temporary files (автоматически). Ключ derivation через KDF, secure key cache с locked memory (DuckDB Blog, 2025-11-19).
- **ВАЖНО**: DuckDB encryption *does not yet meet official NIST requirements* — отслеживать issue #20162 "Store and verify tag for canary encryption".
- **NIST / HIPAA**: Требуется AES-256 для data at rest. DuckDB AES-GCM-256 соответствует алгоритмически, но без NIST compliance — риск для регулятора.

**Рекомендация для AgentFlow:**
1. **Immediate**: Включить encryption для всех `.duckdb` файлов:
   ```sql
   ATTACH 'data.duckdb' AS db (
       ENCRYPTION_KEY '${DUCKDB_ENCRYPTION_KEY}',
       ENCRYPTION_CIPHER 'GCM'
   );
   ```
2. Ключ должен быть 32-byte base64, поставляться из KMS (AWS KMS / Vault), никогда не храниться в plaintext.
3. Добавить в CI проверку: `PRAGMA encryption_status` после открытия БД.
4. Для HIPAA-ready deployments: рассмотреть encrypted volumes (LUKS / AWS EBS encryption) как дополнительный слой до достижения NIST compliance DuckDB.

---

## 🟡 Medium Priority (M1–M4, M7–M9)

### M1. Ruff игнорирует `S608` (SQL injection) глобально

**Проблема:**
```toml
[tool.ruff.lint]
ignore = ["S101", "S311", "S608"]
```

**Current best practice (первичные источники):**
- **Ruff Docs**: `per-file-ignores` — recommended way для targeted exclusions. Примеры из production codebases (ibis-project, freqtrade) показывают, что `S608` должен игнорироваться только для test files и валидированных sqlglot-путей (Ruff Docs / GitHub raw configs).

**Рекомендация для AgentFlow:**
```toml
[tool.ruff.lint]
# Убрать S608 из глобального ignore
ignore = ["S101", "S311"]

[tool.ruff.lint.per-file-ignores]
# Только для файлов, где sqlglot гарантирует безопасность
"src/processing/sqlglot_*.py" = ["S608"]
"tests/**/*.py" = ["S101", "S311", "S608"]
```
Это предотвращает пропуск реальных SQL injection при росте codebase.

---

### M2. Bandit пропускает `B608` глобально

**Проблема:**
```ini
[bandit]
skips = B101,B311,B608
```

**Current best practice (первичные источники):**
- **Bandit Docs**: Bandit поддерживает `skips` globally и `# nosec B608` inline с обоснованием. Нет native per-file skips в INI, но можно использовать YAML/TOML config с `exclude_dirs` или запускать bandit с разными config файлами для разных директорий. Inline suppression — предпочтительный подход для обоснованных исключений (Bandit ReadTheDocs).

**Рекомендация для AgentFlow:**
1. Убрать `B608` из глобального `skips`.
2. Для валидированных sqlglot-путей использовать inline suppression:
   ```python
   query = sqlglot.parse(raw_query)  # nosec B608 — AST-validated, parameterized
   ```
3. Для test files: добавить `tests/` в `exclude_dirs` (там `B101` и `B311` допустимы), но не `B608`.
4. Альтернатива: создать `bandit-core.yaml` для `src/` (со strict набором) и `bandit-tests.yaml` для `tests/`.

---

### M3. mypy `disallow_untyped_defs = false`

**Проблема:** Отсутствие обязательной типизации снижает value type checking. Flink paths полностью игнорируются.

**Current best practice (первичные источники):**
- **mypy Docs**: `disallow_untyped_defs` можно задавать per-module через `[[tool.mypy.overrides]]`. Это позволяет strict mode для core и lenient mode для legacy (mypy ReadTheDocs).
- **Eightfold AI Engineering Blog (2026-04-01)**: Two-tier system — strict mode (100% typed, CI blocks any untyped function) для новых модулей, lenient mode для legacy с AddedTypesTest, гарантирующим типизацию только нового кода.

**Рекомендация для AgentFlow:**
```toml
[tool.mypy]
disallow_untyped_defs = false  # global default для legacy

[[tool.mypy.overrides]]
module = ["src.serving.*", "src.quality.*", "src.auth.*"]
disallow_untyped_defs = true

[[tool.mypy.overrides]]
module = ["src.processing.flink_jobs.*"]
ignore_errors = true  # временно, до типизации Flink
```
- Постепенно добавлять модули в strict mode по мере достижения 100% coverage типами.

---

### M4. Helm values содержат bcrypt hashes

**Проблема:** Хеши в plaintext в `values.yaml` создают риск rainbow-table атаки.

**Current best practice (первичные источники):**
- **Kubernetes + Helm**: Хранение secrets в values.yaml — антипаттерн. Рекомендуемые решения (по приоритету):
  1. **External Secrets Operator (ESO)** — синхронизация из AWS Secrets Manager / Vault / Azure Key Vault в K8s Secret (External Secrets Operator Docs, 2023-03-17).
  2. **Sealed Secrets** — asymmetric encryption, только target cluster может расшифровать.
  3. **Vault Agent Injector** — sidecar-инжекция секретов в Pod без хранения в K8s etcd.
- **ESO Security Best Practices**: namespace isolation, scoped RBAC, network policies, disable cluster-wide resources если не нужны.

**Рекомендация для AgentFlow:**
1. Убрать `key_hash` из `values.yaml`.
2. Создать `ExternalSecret` resource, ссылающийся на AWS Secrets Manager или Vault.
3. В Helm chart использовать `existingSecret` pattern:
   ```yaml
   secrets:
     apiKey:
       existingSecret: "agentflow-api-keys"
       existingSecretKey: "key_hash"
   ```

---

### M7. Нет rollback workflow

**Проблема:** Нет автоматизированного rollback при failed deployment.

**Current best practice (первичные источники):**
- **Helm Docs**: `helm rollback <release> <revision>` — встроенная команда. `helm upgrade --install --atomic` автоматически откатывает при failed rollout (Helm best practices, 2023 / Flavius Dinu blog, 2025-06-19).
- **GitHub Actions**: `if: failure()` job для rollback. `helm history` + `helm rollback` в отдельном job с `needs: deploy`.

**Рекомендация для AgentFlow:**
```yaml
# В staging-deploy.yml или новом deploy workflow
- name: Deploy
  run: helm upgrade --install agentflow ./helm/agentflow --atomic --wait --timeout 10m

- name: Rollback on failure
  if: failure()
  run: |
    helm rollback agentflow 0  # 0 = previous revision
    kubectl get pods -n $NAMESPACE
```
Добавить `--atomic` во все `helm upgrade` вызовы.

---

### M8. Coverage gate 60% — низкий

**Проблема:** Низкий порог для production core modules.

**Current best practice (первичные источники):**
- **PyPI Warehouse (Trail of Bits, 2025-05-01)**: 100% branch coverage across unit + integration suites — "non-negotiable for critical infrastructure". Использование `pytest-xdist` и `sys.monitoring` (Python 3.12+) для скорости.
- **pytest-cov / coverage.py**: Поддержка per-module `fail_under` через отдельные CI jobs или `coverage report` с `--fail-under` per package.

**Рекомендация для AgentFlow:**
1. Поднять глобальный gate до 70%.
2. Для core modules (`src/auth`, `src/serving`, `src/quality`) установить 80%:
   ```toml
   [tool.coverage.report]
   fail_under = 70
   ```
   Или отдельные CI jobs:
   ```bash
   pytest --cov=src.auth --cov-fail-under=80 tests/unit/auth/
   pytest --cov=src.serving --cov-fail-under=80 tests/unit/serving/
   pytest --cov=src --cov-fail-under=60 tests/unit/flink/
   ```
3. Для Flink paths оставить 60% с explicit waiver в `pyproject.toml`.

---

### M9. Нет immutable audit log

**Проблема:** `api_usage` пишется в DuckDB (mutable storage). Нет Kafka topic с infinite retention для compliance audit trail.

**Current best practice (первичные источники):**
- **Apache Kafka / Confluent**: Audit logs должны быть append-only, immutable, с guaranteed long-term retention. Kafka topics с `retention.ms=-1` (infinite) + tiered storage для cost efficiency. Для 7+ лет compliance — sink в S3 с Object Lock (WORM) (Confluent Blog, 2025-10-24).
- **hoop.dev / WORM**: Immutable audit log = write-once, read-many (WORM). Криптографическое подписание записей для integrity verification.

**Рекомендация для AgentFlow:**
1. Создать dedicated Kafka topic `api-usage.audit.v1`:
   ```yaml
   log.cleanup.policy: delete
   retention.ms: -1        # infinite retention
   min.insync.replicas: 2
   ```
2. Producer config: `acks=all` для durability.
3. Sink в S3 с Object Lock (Compliance Mode) через Kafka Connect для long-term retention.
4. Отдельный read-only service account для auditors (только consumer, no delete permissions).

---

## 🟢 Low Priority (L6–L7)

### L6. Нет SBOM generation

**Проблема:** Отсутствие Software Bill of Materials для release artifacts.

**Current best practice (первичные источники):**
- **CISA Minimum Elements for SBOMs (2025)**: Авторитетное руководство по обязательным элементам SBOM.
- **Syft (Anchore)**: Наиболее comprehensive container SBOM generator. Outputs: SPDX-json, CycloneDX. Рекомендуется generate at build time и хранить alongside artifact (Chainguard Edu / Safeguard.sh, 2025).
- **Trivy**: Генерирует SBOM + vulnerability scan в одном инструменте.

**Рекомендация для AgentFlow:**
```yaml
# В CI (publish-pypi.yml или отдельный workflow)
- name: Generate SBOM
  uses: anchore/sbom-action@v0
  with:
    image: "agentflow:${{ github.sha }}"
    format: spdx-json
    output-file: agentflow.spdx.json

- name: Upload SBOM
  uses: actions/upload-artifact@v4
  with:
    name: sbom
    path: agentflow.spdx.json
```
Для Python SDK (PyPI): `syft dir:. -o cyclonedx-json > sbom.json`.

---

### L7. Нет signed container images

**Проблема:** Отсутствие криптографической подписи образов.

**Current best practice (первичные источники):**
- **Sigstore / Cosign**: Keyless signing через GitHub OIDC — без необходимости управления ключами. Подпись привязывается к image digest (не tag) и публикуется в Rekor transparency log (Chainguard Edu, 2025-12-26).
- **SLSA Framework**: Supply-chain Levels for Software Artifacts. Level 3 — signed provenance + hermetic builds. GitHub Artifact Attestations (2024) — нативный способ привязки provenance к build.
- **Docker Image Security Best Practices (BellSoft, 2025-11-08)**: Combine SBOM + provenance + signing. Verify at deploy time: reject unsigned images.

**Рекомендация для AgentFlow:**
```yaml
# В CI после build
- uses: sigstore/cosign-installer@v3

- name: Sign image
  run: |
    DIGEST=$(docker inspect $IMAGE | jq -r '.[0].RepoDigests[0]')
    cosign sign --yes $DIGEST
```
Или использовать GitHub Artifact Attestations:
```yaml
- uses: actions/attest-build-provenance@v1
  with:
    subject-name: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
    subject-digest: ${{ steps.build.outputs.digest }}
    push-to-registry: true
```
При deploy: `cosign verify` или `gh attestation verify` перед применением Helm chart.

---

## Сводная таблица статусов

| ID | Проблема | Приоритет | Статус | Блокер для enterprise |
|----|----------|-----------|--------|----------------------|
| H3 | DuckDB в K8s с RWO PVC при replicaCount: 2 | 🔴 High | **Open** | Да (data divergence) |
| H4 | Terraform apply disabled / OIDC не настроен | 🔴 High | **Open** | Да (no real infra) |
| H5 | Нет external pentest evidence | 🔴 High | **Open** | Да (SOC 2 / HIPAA) |
| H6 | DuckDB encryption at rest не доказана | 🔴 High | **Open** | Да (GDPR/HIPAA) |
| M1 | Ruff global ignore S608 | 🟡 Medium | **Open** | Нет (code quality) |
| M2 | Bandit global skip B608 | 🟡 Medium | **Open** | Нет (code quality) |
| M3 | mypy weak config | 🟡 Medium | **Open** | Нет (maintainability) |
| M4 | Helm values bcrypt hashes | 🟡 Medium | **Open** | Да (secrets mgmt) |
| M7 | Нет rollback workflow | 🟡 Medium | **Open** | Нет (ops maturity) |
| M8 | Coverage gate 60% | 🟡 Medium | **Open** | Нет (quality signal) |
| M9 | Нет immutable audit log | 🟡 Medium | **Open** | Да (compliance) |
| L6 | Нет SBOM generation | 🟢 Low | **Open** | Да (supply chain) |
| L7 | Нет signed container images | 🟢 Low | **Open** | Да (supply chain) |

---

## Рекомендуемый порядок закрытия (без deploy/push actions)

1. **Немедленно (локальные изменения):**
   - M1/M2/M3 — конфигурационные правки в `pyproject.toml`/`.bandit`.
   - H6 — включить DuckDB encryption в dev-конфиге, добавить `PRAGMA encryption_status` проверку в startup.
   - M7 — добавить `--atomic` и rollback step в CI workflow.

2. **Краткосрочно (1–4 недели, требуют внешних сервисов):**
   - H3 — архитектурное решение: single-replica DuckDB + ClickHouse для prod.
   - M4 — миграция на External Secrets Operator (требует Vault/AWS SM).
   - M8 — поднятие coverage gates с baseline измерением.
   - M9 — создание Kafka topic + schema для audit log.

3. **Среднесрочно (1–3 месяца):**
   - H4 — настройка AWS OIDC + включение terraform-apply workflow.
   - H5 — заказ external pentest (требует бюджета, но не требует deploy).
   - L6/L7 — добавление SBOM + signing в CI (локальные workflow changes).

---

*Источники:* Kubernetes Docs (2026), DuckDB.org (2025), Ruff Docs, Bandit ReadTheDocs, mypy Docs, External Secrets Operator Docs, Confluent Blog (2025), CISA SBOM Guidance (2025), Sigstore/Cosign Docs, OWASP Testing Guide, NIST SP 800-115, PTES.
