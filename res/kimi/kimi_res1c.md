# Исследование оставшихся открытых пунктов audit_kimi_04_05_26.md

**Проект:** AgentFlow (DE_project)
**Дата:** 2026-05-05
**Контекст:** После локального remediation-пакета 2026-05-05 закрыты H1/H2/L1 (Docker), M5 (MinIO pinned tags), M10 (Helm image tag 1.1.0), M12 (request body size middleware).
**Источники:** Первичные — GitHub Actions OIDC docs, Terraform docs, AWS IAM docs, Kubernetes docs, DuckDB docs, pytest/coverage docs, Sigstore/cosign docs, CISA/ENISA SBOM guidance.

---

## 🔴 High Priority (оставшиеся)

### H3. DuckDB в K8s с `ReadWriteOnce` PVC при `replicaCount: 2`

**Текущее состояние:**
- `helm/agentflow/values.yaml`: `replicaCount: 2`, `persistence.accessModes: [ReadWriteOnce]`, `autoscaling.enabled: true` (min 2, max 10).
- DuckDB — in-process, embedded БД. Каждый pod получает собственный PVC с RWO. При `replicaCount > 1` данные расходятся между репликами (split-brain на уровне приложения).

**Best practice (первичные источники):**
- Kubernetes docs: `ReadWriteOnce` означает монтирование на один node, но на нём может быть несколько pod'ов. Однако DuckDB не поддерживает shared-write даже на одном node (file-level locking отсутствует).
- DuckDB docs / community: DuckDB не предназначена для multi-writer. StatefulSet с `replicaCount: 1` — единственный supported pattern для persistent storage в K8s.
- Рекомендуемый production pattern: единственный writer pod (StatefulSet, `replicaCount: 1`, HPA disabled) + отдельный read-only replicas через `attach` (только если экспериментальная фича) **или** замена на ClickHouse/PostgreSQL для serving layer.

**Рекомендация:**
1. Для prod: перевести `agentflow-api` на `StatefulSet` с `replicaCount: 1` и отключить HPA для writer.
2. Альтернатива: использовать ClickHouse backend (`src/serving/backends/clickhouse_backend.py` уже реализован) — это production-grade решение для multi-replica serving.
3. Если DuckDB остаётся: использовать `ReadWriteOncePod` (K8s 1.27+) для гарантии single-pod access.

---

### H4. AWS Terraform apply отключен, OIDC не настроен

**Текущее состояние:**
- `.github/workflows/terraform-apply.yml`: `if: false` на обоих jobs (plan + apply).
- Комментарий в workflow требует: `AWS_TERRAFORM_ROLE_ARN`, `AWS_REGION` (repo-level vars), staging/prod tfvars, GitHub Environments.
- `infrastructure/terraform/modules/github-oidc/main.tf`: модуль создан, thumbprint hardcoded (`dd55b4520291e276588f0dd02fafd83a7368e0fa`), `StringLike` condition на `sub` claim.
- `oidc.tf`: вызывает модуль с `allowed_branches = ["main"]`, `allowed_environments = ["production", "staging"]`.

**Best practice (первичные источники):**

1. **GitHub Actions OIDC docs** (`aws-actions/configure-aws-credentials` v4, 2026-04-06):
   - Thumbprint больше не требуется при создании OIDC provider через AWS Console/CLI: *"Prior versions of this documentation gave instructions for specifying the certificate fingerprint, but this is no longer necessary. The thumbprint, if specified, will be ignored."*
   - Audience (`client_id_list`) должен содержать `sts.amazonaws.com`.
   - Trust policy **должен** содержать `StringEquals` condition на `aud` и `StringLike`/`StringEquals` на `sub`. Без `sub` condition любой GitHub repo может assum'нуть роль.

2. **Terraform AWS Provider docs / IAM best practices:**
   - Рекомендуется **разделение ролей plan и apply** (least privilege): plan-роль — read-only + state access; apply-роль — full write access.
   - IAM policy в модуле содержит широкие права (`iam:*OpenIDConnectProvider*`, `ec2:*`, `kafka:*Cluster*`, `kinesisanalytics:*Application*`) с `resources = ["*"]` — это рискованно для CI-роли.
   - `role-session-name` должен быть уникальным для аудита (уже есть `gha-terraform-${{ github.run_id }}`).

3. **GitHub Environments docs:**
   - Для production apply **обязателен** required reviewer + deployment protection rules.
   - `terraform-apply.yml` уже использует `environment: ${{ inputs.environment }}` в apply job — это correct.

4. **Terraform state security:**
   - S3 backend: `encrypt = true` уже есть. Best practice — включить `kms_key_id` для server-side encryption with CMK.
   - DynamoDB locking table должна иметь point-in-time recovery enabled.

**Выявленные gaps:**
- Hardcoded thumbprint — не критично, но лишнее. AWS теперь auto-fetches thumbprints.
- Один IAM role для plan и apply — нарушение least privilege.
- `iam:*OpenIDConnectProvider*` с `resources = ["*"]` позволяет CI удалить/изменить **любой** OIDC provider в аккаунте.
- Отсутствие `AWS_TERRAFORM_ROLE_ARN` variable в repo settings — блокер.

**Рекомендация:**
1. Создать **две** IAM роли: `agentflow-plan` (read-only + state) и `agentflow-apply` (write + state).
2. Убрать hardcoded thumbprint из Terraform (оставить `thumbprint_list = []` или доверить AWS).
3. Сузить IAM policy: убрать `resources = ["*"]` для `OidcProviderLifecycle`, `SecurityGroups`, `MSKClusters`, `ManagedFlinkApplications`.
4. Добавить repo-level vars: `AWS_TERRAFORM_ROLE_ARN` / `AWS_TERRAFORM_APPLY_ROLE_ARN`, `AWS_REGION`.
5. Создать `environments/staging.tfvars` из `.tfvars.example`, убрать production option до готовности.
6. Включить workflow: убрать `if: false`, добавить `if: inputs.confirm == 'APPLY'`.
7. Добавить CloudWatch alarm на failed OIDC auth attempts (как в best practice).

---

### H5. Нет external penetration test

**Текущее состояние:**
- В репозитории нет отчётов о внешнем пентесте.
- `docs/security-audit.md` содержит threat model и controls, но не содержит independent validation.

**Best practice:**
- SOC 2 Type II / ISO 27001 требуют ежегодный external penetration test.
- Для enterprise sales (B2B SaaS) — **must have** независимый отчёт (например, от Bishop Fox, Cobalt, Cure53) за последние 12 месяцев.
- Best practice: black-box + grey-box тестирование API (OWASP API Security Top 10), tenant isolation bypass, SQL injection (sqlglot bypass), rate limit bypass.

**Рекомендация:**
- Заказать external pen-test до начала enterprise sales. Scope: API endpoints (`/v1/query`, `/v1/entity/*`, `/v1/admin/*`), tenant isolation, auth bypass, CDC webhook injection.
- Результат разместить в `docs/audits/YYYY-MM-DD/` (restricted access, executive summary public).

---

### H6. DuckDB encryption at rest не доказана

**Текущее состояние:**
- `.duckdb` файлы создаются в `/data/agentflow.duckdb` (PVC). Нет evidence of encryption.
- DuckDB поддерживает `PRAGMA encryption='AES'` (через `sqlcipher` build), но это нестандартная сборка.

**Best practice:**
- DuckDB docs: encryption — experimental, требует специальную сборку. Для production не рекомендуется полагаться на неё.
- Kubernetes + cloud: использовать **encrypted volumes** (AWS EBS encryption с KMS, GCP PD CMEK, Azure Disk Encryption) — прозрачно для приложения.
- Для GDPR/HIPAA: encryption at rest — mandatory control. Достаточно storage-level encryption (PVC на encrypted StorageClass).

**Рекомендация:**
1. Для K8s: создать `StorageClass` с `encrypted: true` (cloud-specific) и использовать его для DuckDB PVC.
2. Добавить комментарий в `values.yaml` и документацию: "DuckDB files rely on storage-level encryption (EBS/KMS); application-level encryption not supported by DuckDB runtime build."
3. Для ClickHouse backend (prod): включить `encryption_at_rest` в ClickHouse Cloud или disk encryption для self-hosted.

---

## 🟡 Medium Priority (оставшиеся)

### M1. Ruff игнорирует `S608` (SQL injection) глобально

**Текущее состояние:**
```toml
[tool.ruff.lint]
ignore = ["S101", "S311", "S608"]
```
- `S608` — hardcoded SQL expressions (SQL injection через string formatting).
- SQL-инъекции покрыты `sqlglot` guard, но глобальный ignore рискован при росте codebase.

**Best practice (Ruff docs / Bandit docs):**
- Использовать `per-file-ignores` с **explicit justification comment**.
- Только файлы, прошедшие sqlglot-валидацию, могут игнорировать `S608`.

**Рекомендация:**
```toml
[tool.ruff.lint]
ignore = ["S101", "S311"]  # S101: asserts in tests; S311: random non-crypto

[tool.ruff.lint.per-file-ignores]
# sqlglot-validated dynamic SQL — explicit exception justified in ADR-003
"src/serving/semantic_layer/query_engine.py" = ["S608"]
"src/processing/flink_jobs/*.py" = ["S608"]
```

---

### M2. Bandit пропускает `B608` глобально

**Текущее состояние:**
```ini
[bandit]
skips = B101,B311,B608
```
- `B608` — hardcoded SQL expressions (аналог Ruff S608).
- Bandit используется с diff-gate (`bandit_diff.py`), но baseline может скрывать новые находки в не-sqlglot путях.

**Best practice (Bandit docs):**
- Bandit поддерживает `skips` только глобально. Для per-file control рекомендуется использовать inline `# nosec` с **explicit justification** (`# nosec B608` + комментарий).
- Или перейти на Ruff `S608` как primary linter (Bandit постепенно deprecated в пользу Ruff).

**Рекомендация:**
1. Убрать `B608` из глобальных skips.
2. Добавить `# nosec B608` с комментарием в каждую функцию с sqlglot-валидированным SQL.
3. Долгосрочно: полностью мигрировать SQL-инъекцию контроль на Ruff S608 (per-file ignores).

---

### M3. mypy `disallow_untyped_defs = false`

**Текущее состояние:**
```toml
[tool.mypy]
disallow_untyped_defs = false
check_untyped_defs = true
```
- Flink paths полностью игнорируются (`ignore_errors = true` для `src.processing.flink_jobs.*`).

**Best practice (mypy docs):**
- `disallow_untyped_defs = true` — **strict** режим для core модулей (auth, query engine, rate limiter).
- `check_untyped_defs = true` — good baseline, но не гарантирует полноту type annotations.
- Рекомендуется **gradual typing**: разделить на typed/untyped модули.

**Рекомендация:**
```toml
[tool.mypy]
disallow_untyped_defs = true  # global strict

[[tool.mypy.overrides]]
module = "src.processing.flink_jobs.*"
disallow_untyped_defs = false
ignore_errors = true

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
```
- Добавить type annotations для `src/serving/` и `src/quality/` (уже частично покрыто), затем включить strict.

---

### M4. Helm values содержат bcrypt hashes

**Текущее состояние:**
```yaml
secrets:
  apiKeys:
    keys:
      - key_hash: "$2b$12$UNE9Vh.YivKR7Zt7xIZweebebjkcVaQv240rqabzG/H3dWoljplcO"
```
- Хеши в `values.yaml` — не plaintext, но раскрывают salt + алгоритм. Rainbow-table возможна при утечке словаря.

**Best practice (Kubernetes + Helm docs):**
- **Never commit secrets to Git**, даже хеши (risk of offline brute-force).
- Использовать `existingSecret` pattern + External Secrets Operator (ESO) / Vault Agent Injector / Sealed Secrets.
- ESO: синхронизация из AWS Secrets Manager / Azure Key Vault / GCP Secret Manager в K8s Secret.

**Рекомендация:**
1. В `values.yaml` оставить только `existingSecret: "agentflow-api-keys"`.
2. Создать `ExternalSecret` manifest для синхронизации из AWS Secrets Manager.
3. Локальные dev-values (`values-dev.yaml`) могут содержать dummy-хеши, но не production.

---

### M7. Нет rollback workflow

**Текущее состояние:**
- `staging-deploy.yml` делает `helm lint` + `helm upgrade` через `scripts/k8s_staging_up.sh`.
- Нет automated rollback при failed deployment.
- `terraform-apply.yml` disabled, поэтому infra rollback неактуален сейчас.

**Best practice (Helm docs / GitHub Actions):**
- Helm: `helm rollback <release> <revision>` — atomic rollback.
- GitHub Actions: separate `rollback.yml` workflow с `workflow_dispatch` + environment selector.
- Best practice: использовать `helm upgrade --atomic --wait --timeout 10m` — auto-rollback на failed upgrade.

**Рекомендация:**
1. Добавить в `staging-deploy.yml` (и future prod deploy):
   ```bash
   helm upgrade --install agentflow ./helm/agentflow \
     --atomic --wait --timeout 10m \
     -f values.yaml
   ```
2. Создать `.github/workflows/rollback.yml`:
   ```yaml
   on:
     workflow_dispatch:
       inputs:
         environment: { type: choice, options: [staging, production] }
         revision: { type: number, description: "Helm revision to rollback to" }
   jobs:
     rollback:
       runs-on: ubuntu-latest
       steps:
         - uses: azure/setup-helm@v4
         - run: helm rollback agentflow ${{ inputs.revision }} --namespace agentflow
   ```
3. Хранить историю релизов: `helm history agentflow` + `helm list` в CI artifacts.

---

### M8. Coverage gate 60% — низкий

**Текущее состояние:**
- CI: `cov-fail-under=60` для unit + property tests.
- Codecov уже используется (`use_oidc: true`) с patch status.

**Best practice (pytest-cov / Codecov docs):**
- **Tiered coverage**: core modules (auth, query engine, rate limiter, tenant isolation) — 80-90%; integration tests — 60%; Flink jobs — 50% (acceptable из-за сложности инфраструктуры).
- Codecov: `project` status + `patch` status. Patch status уже есть (80% changed code), но project gate низкий.

**Рекомендация:**
```toml
# pyproject.toml
[tool.pytest.ini_options]
# Keep global floor at 60 for mixed suite, but enforce stricter per-package
```
```ini
# .codecov.yml
coverage:
  status:
    project:
      default:
        target: 60%
      core:
        paths: ["src/serving/api/", "src/serving/semantic_layer/", "src/quality/"]
        target: 80%
    patch:
      target: 80%
```
- Или разделить CI jobs: `test-unit-core` с `--cov-fail-under=80` для `src/serving/`, `src/quality/`.

---

### M9. Нет immutable audit log

**Текущее состояние:**
- `api_usage` пишется в DuckDB (`/data/agentflow_api.duckdb`) — mutable storage.
- Нет dedicated Kafka topic для audit trail.

**Best practice (Kafka docs / Compliance):**
- Audit log требует **immutable**, **append-only** storage с **non-repudiation**.
- Kafka: создать topic `api_usage.audit` с:
  - `cleanup.policy=delete` (не compact — иначе старые записи удаляются)
  - `retention.bytes=-1`, `retention.ms=-1` (infinite retention) **или** `retention.ms=31557600000` (1 year) + Tiered Storage / S3 offload.
  - `min.insync.replicas=2`, `acks=all` — durability guarantee.
  - ACL: только service account `agentflow-api` может produce; consumer group ограничен.
- Альтернатива: AWS CloudTrail (для AWS API calls) + WORM S3 bucket для application audit events.

**Рекомендация:**
1. Добавить Kafka producer в middleware для отправки audit events в `api_usage.audit`.
2. Конфигурация topic:
   ```yaml
   api_usage.audit:
     partitions: 6
     replication.factor: 3
     config:
       retention.ms: -1
       cleanup.policy: delete
       min.insync.replicas: 2
   ```
3. Для long-term storage: Kafka Connect → S3 (Parquet) с Object Lock (WORM).

---

## 🟢 Low Priority (оставшиеся)

### L6. Нет SBOM generation

**Текущее состояние:**
- Нет SBOM для Python пакетов и container image.
- Trivy сканирует image, но не генерирует SBOM artifact.

**Best practice (CISA 2025 Minimum Elements, ENISA SBOM Guide, Syft docs):**
- SBOM должен генерироваться на **каждый build**.
- Форматы: **SPDX** (ISO/IEC 5962:2021) или **CycloneDX** (OWASP).
- Инструменты: `syft` (Anchore) — gold standard для контейнеров; `trivy sbom` — как fallback.
- Хранение: как CI artifact + attach к container image (`cosign attach sbom`).

**Рекомендация:**
Добавить в `security.yml` или `publish-pypi.yml`:
```yaml
- uses: anchore/syft-action@v0
  with:
    path: .
    output-format: cyclonedx-json
    output-file: sbom.cyclonedx.json

- uses: actions/upload-artifact@v4
  with:
    name: sbom
    path: sbom.cyclonedx.json
```
Для container image:
```bash
syft agentflow-api:${{ github.sha }} -o spdx-json > sbom.spdx.json
cosign attach sbom --sbom sbom.spdx.json agentflow-api:${{ github.sha }}
```

---

### L7. Нет signed container images

**Текущее состояние:**
- Container image `agentflow-api` собирается в CI (`docker-compose.prod.yml` build), но не подписывается.
- PyPI публикация использует Trusted Publishing (OIDC), но container — нет.

**Best practice (Sigstore / GitHub Artifact Attestations / SLSA):**
- **GitHub Artifact Attestations** (`actions/attest-build-provenance@v2`): native SLSA provenance, zero key management. Подписывает artifact (image) OIDC-токеном GitHub Actions.
- **Cosign** (`sigstore/cosign-installer@v3`): keyless signing через Fulcio + Rekor. Broad ecosystem support (Kyverno, OPA Gatekeeper).
- Best practice 2025-2026: **both** — GitHub attestation для SLSA provenance + cosign для registry-level verification.

**Рекомендация:**
Добавить в workflow, который build'ит image (например, `security.yml` или новый `publish-image.yml`):
```yaml
- uses: sigstore/cosign-installer@v3
- run: |
    cosign sign --yes \
      ghcr.io/${{ github.repository }}/agentflow-api@${{ steps.build.outputs.digest }}

- uses: actions/attest-build-provenance@v2
  with:
    subject-name: ghcr.io/${{ github.repository }}/agentflow-api
    subject-digest: ${{ steps.build.outputs.digest }}
    push-to-registry: true
```
Verification:
```bash
gh attestation verify oci://ghcr.io/.../agentflow-api:v1.1.0 --owner yuliaedomskikh
cosign verify ghcr.io/.../agentflow-api:v1.1.0 \
  --certificate-identity-regexp="https://github.com/yuliaedomskikh/agentflow/" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com"
```

---

## Сводная таблица: Remediation priority (пост-local-fix 2026-05-05)

| ID | Проблема | Сложность | Блокер для | Статус |
|----|----------|-----------|------------|--------|
| **H4** | Terraform apply disabled / OIDC gaps | Medium | Real AWS deploy | 🔴 Critical — требует AWS account + IAM setup |
| **H3** | DuckDB RWO + replicaCount 2 | Low-Medium | K8s prod stability | 🔴 High — architecture decision needed |
| **H6** | DuckDB encryption at rest | Low | GDPR/HIPAA | 🟡 Medium — storage-level encryption |
| **M4** | Bcrypt hashes in Helm values | Low | Secret management | 🟡 Medium — ESO setup |
| **M7** | No rollback workflow | Low | Deployment safety | 🟢 Low — helm atomic + manual rollback |
| **M1/M2** | Ruff/Bandit S608/B608 global ignore | Low | Code quality | 🟢 Low — config change |
| **M3** | mypy weak config | Medium | Type safety | 🟢 Low — gradual typing |
| **M8** | Coverage 60% | Low | Test maturity | 🟢 Low — tiered gates |
| **M9** | No immutable audit log | Medium | Compliance | 🟡 Medium — Kafka topic + producer |
| **L6** | No SBOM | Low | Supply chain | 🟢 Low — syft in CI |
| **L7** | No signed images | Low | Supply chain | 🟢 Low — cosign + attestations |
| **H5** | No pen-test | High (external) | Enterprise sales | 🔴 High — external dependency |

---

## Заключение

После remediation-пакета 2026-05-05 остаётся **11 открытых пунктов**. Наиболее критичные:
1. **H4** — требует активации AWS OIDC + разделения plan/apply ролей + tfvars. Это единственный блокер для real infrastructure deployment.
2. **H3** — архитектурный mismatch DuckDB + K8s replicas. Требует решения: либо ClickHouse для prod, либо single-replica DuckDB с StatefulSet.
3. **H5/H6** — compliance blockers (pen-test + encryption at rest), но не блокируют pilot deployment.

Остальные (M1-M4, M7-M9, L6-L7) — конфигурационные изменения, которые можно закрыть локально без external dependencies.
