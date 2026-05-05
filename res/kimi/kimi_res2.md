# Актуализация аудита: H3–H6, M1–M4/M7–M9, L6–L7

**Дата:** 2026-05-05
**База:** `D:\DE_project`, HEAD `10bc3c7` (673 tracked files)
**Контекст:** Уже закрыты — Docker editable install / `.dockerignore` / `HEALTHCHECK`, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.
**Ограничение:** Без deploy/apply/push/paid actions. Только фиксация текущего состояния кода и локальных рекомендаций.

---

## 🔴 High Priority (H3–H6)

### H3. DuckDB в K8s с `ReadWriteOnce` PVC при `replicaCount: 2`

**Статус:** 🔴 **Open** (не изменился с `co_res1.md`)

**Evidence:**
- `helm/agentflow/values.yaml:4` — `replicaCount: 2`
- `helm/agentflow/values.yaml:37-41` — autoscaling `enabled: true`, `minReplicas: 2`, `maxReplicas: 10`
- `helm/agentflow/values.yaml:43-49` — persistence `accessModes: [ReadWriteOnce]`, `mountPath: /data`
- `k8s/staging/values-staging.yaml` использует `replicaCount: 1` и `autoscaling.enabled: false`, но это staging-only override; chart default остаётся многорепликовым.

**Риск:** Kubernetes `ReadWriteOnce` — node-scoped, не pod-scoped. DuckDB не поддерживает concurrent writers к одному файлу. При `replicaCount: 2` оба Pod'а монтируют один PVC — write contention / split-brain.

**Локальное действие:** Добавить в chart `values.yaml` guard: если `persistence.enabled: true` и backend `duckdb` — `replicaCount` должен быть 1, HPA disabled. Или сделать DuckDB режимом только для dev/single-node, а для prod default — ClickHouse backend.

---

### H4. AWS Terraform apply отключен, OIDC не настроен

**Статус:** 🔴 **Open** (не изменился)

**Evidence:**
- `.github/workflows/terraform-apply.yml:31` — `if: false` (plan job)
- `.github/workflows/terraform-apply.yml:75` — `if: false` (apply job)
- Workflow содержит корректную OIDC-разводку (`id-token: write`, `configure-aws-credentials@v4`, `role-to-assume: ${{ vars.AWS_TERRAFORM_ROLE_ARN }}`), но disabled.
- `infrastructure/terraform/environments/` содержит только `*.tfvars.example`, нет реальных tfvars.
- `docs/operations/aws-oidc-setup.md` фиксирует отсутствие `AWS_TERRAFORM_ROLE_ARN`.

**Риск:** Нет evidence production infrastructure. Terraform state backend использует устаревший DynamoDB locking (deprecated в актуальных рекомендациях Terraform S3 backend).

**Локальное действие:** Обновить документацию о readiness criteria; рассмотреть переход на S3 native lockfile вместо DynamoDB. Но включить workflow локально невозможно без живого AWS account и role.

---

### H5. Нет external penetration test

**Статус:** 🔴 **Open** (не изменился)

**Evidence:**
- `docs/operations/external-pen-test-attestation-handoff.md` — статус "blocked on an external pen-test report or attestation"
- В репозитории нет external tester identity, scope, report artifact, severity summary, remediation mapping, retest status, attestation owner.

**Риск:** Enterprise security claims (SOC 2, HIPAA) требуют независимого pentest. Internal CI scans и static analysis — не substitute.

**Локальное действие:** Подготовить DAST baseline (OWASP ZAP) в CI для снижения риска перед external test. Обновить handoff doc с checklist ready-state.

---

### H6. DuckDB encryption at rest не доказана

**Статус:** 🔴 **Open** (не изменился)

**Evidence:**
- Поиск по `src/` — все вызовы `duckdb.connect(...)` используют plain path без `ENCRYPTION_KEY` или `ENCRYPTION_CIPHER`.
- Нет `PRAGMA encryption_status` в startup / healthcheck коде.
- Нет references на `ATTACH ... ENCRYPTION_KEY` в `src/`, `config/`, `helm/`, `scripts/`.
- DuckDB 1.4.4 поддерживает AES-256-GCM encryption (DuckDB Blog, 2025-11-19), но AgentFlow её не использует.

**Риск:** GDPR/HIPAA blocker для данных at rest. DuckDB encryption не NIST-compliant yet, но отсутствие даже текущей опции — regression.

**Локальное действие:** Добавить опциональный `DUCKDB_ENCRYPTION_KEY` env var и `ATTACH` с encryption в dev-конфиге; добавить `PRAGMA encryption_status` в startup check. Для prod рекомендуется encrypted volume (LUKS / AWS EBS encryption) как дополнительный слой.

---

## 🟡 Medium Priority (M1–M4, M7–M9)

### M1. Ruff игнорирует `S608` (SQL injection) глобально

**Статус:** 🟡 **Open** (не изменился)

**Evidence:**
- `pyproject.toml:119` — `ignore = ["S101", "S311", "S608"]`
- `per-file-ignores` не содержит scoped исключений для S608.

**Риск:** Любой новый SQL string construction попадёт в codebase без gate failure.

**Локальное действие:** Убрать `S608` из глобального ignore; добавить `per-file-ignores` только для валидированных sqlglot-путей и тестов.

---

### M2. Bandit пропускает `B608` глобально

**Статус:** 🟡 **Open** (не изменился)

**Evidence:**
- `.bandit:3` — `skips = B101,B311,B608`
- Исходники содержат inline `# nosec B608`, но global skip делает их невидимыми для регулярного gate.

**Риск:** Global skip маскирует justified suppressions; новый непроверенный SQL interpolation не вызовет failure.

**Локальное действие:** Убрать `B608` из `skips`; оставить только inline `# nosec B608` с обоснованием.

---

### M3. mypy `disallow_untyped_defs = false`

**Статус:** 🟡 **Open** (не изменился)

**Evidence:**
- `pyproject.toml:178` — `disallow_untyped_defs = false`
- `[[tool.mypy.overrides]]` есть только для `src.processing.flink_jobs.*` (`ignore_errors = true`), нет strict overrides для `src.serving` или `src.quality`.

**Риск:** Untyped function boundaries снижают type safety в core modules.

**Локальное действие:** Добавить `[[tool.mypy.overrides]]` с `disallow_untyped_defs = true` для `src.serving.*`, `src.quality.*`, `src.auth.*`. Постепенно закрывать ошибки.

---

### M4. Helm values содержат bcrypt API-key hashes

**Статус:** 🟡 **Open** (не изменился)

**Evidence:**
- `helm/agentflow/values.yaml:218-236` — bcrypt hashes в `secrets.apiKeys.keys[].key_hash`
- `config/api_keys.yaml` содержит аналогичные hashes.
- Staging (`k8s/staging/values-staging.yaml`) тоже содержит hashes, но с inline comment о том, что это e2e fixtures.

**Риск:** ASVS 13.3 — backend secrets должны храниться вне source/build artifacts. Bcrypt hashes — reusable offline-verification material.

**Локальное действие:** В chart добавить `existingSecret` pattern; вынести hashes из `values.yaml` в `ExternalSecret` / `SealedSecret`. Для staging оставить комментарий и `REPLACE_ME` placeholders с явным waiver.

---

### M7. Нет rollback workflow

**Статус:** 🟡 **Open** (не изменился)

**Evidence:**
- `scripts/k8s_staging_up.sh:200-206` — `helm upgrade --install` без `--atomic`
- `.github/workflows/staging-deploy.yml` — deploy через `k8s_staging_up.sh`, нет rollback step
- На failure только diagnostics capture (`kubectl get logs`), нет `helm rollback`

**Риск:** Failed rollout остаётся в broken state до manual intervention.

**Локальное действие:** Добавить `--atomic` в `helm upgrade --install` и rollback job `if: failure()` в staging-deploy.yml. Для prod — отдельный workflow с `helm history` + `helm rollback`.

---

### M8. Coverage gate 60% — низкий

**Статус:** 🟡 **Open** (не изменился)

**Evidence:**
- `.github/workflows/ci.yml:67` — `--cov-fail-under=60`
- `coverage.xml:2` — `line-rate="0.623"` (62.3%)
- `codecov.yml` — patch target 80%, project target `auto` (не enforced).

**Риск:** Низкий порог не гарантирует качество core modules.

**Локальное действие:** Поднять global gate до 70% (текущий 62.3% не даст 75% без новых тестов). Для `src/auth`, `src/serving`, `src/quality` — per-module gate 80%. Для Flink paths — оставить 60% с explicit waiver.

---

### M9. Нет immutable audit log

**Статус:** 🟡 **Open** (не изменился)

**Evidence:**
- `src/serving/api/analytics.py` — все записи идут в DuckDB `api_sessions` через `INSERT OR REPLACE`
- `INSERT OR REPLACE` — mutable operation; записи могут быть перезаписаны.
- Нет Kafka topic `api_usage.audit`, нет external log sink (S3 Object Lock / SIEM).

**Риск:** ASVS 16.1/16.4 требуют protected logs, которые нельзя модифицировать, и transmission к logically separate system.

**Локальное действие:** Создать Kafka topic `api-usage.audit.v1` с `retention.ms=-1`, dual-write из analytics middleware. Для immutability — sink в S3 Object Lock (Compliance Mode) через Kafka Connect.

---

## 🟢 Low Priority (L6–L7)

### L6. Нет SBOM generation

**Статус:** 🟢 **Open** (не изменился)

**Evidence:**
- `.github/workflows/security.yml` — Trivy SARIF scan only, нет SBOM artifact generation.
- Нет `syft`, `trivy sbom`, CycloneDX/SPDX steps.

**Локальное действие:** Добавить `anchore/sbom-action@v0` или `trivy --format cyclonedx` в security/publish workflow; upload artifact.

---

### L7. Нет signed container images

**Статус:** 🟢 **Open** (не изменился)

**Evidence:**
- Нет `cosign`, `actions/attest-build-provenance`, `slsa-generator` ни в одном workflow.
- Container image builds есть (security.yml, staging-deploy.yml), но signature/provenance отсутствует.

**Локальное действие:** Добавить `sigstore/cosign-installer@v3` + `cosign sign` или GitHub Artifact Attestations в publish workflow. Но без container registry publication это скорее skeleton; если контейнеры не публикуются как артефакты — задокументировать как N/A до появления registry target.

---

## Сводная таблица статусов

| ID | Проблема | Приоритет | Статус | Enterprise blocker | Локально закрываемо |
|----|----------|-----------|--------|-------------------|---------------------|
| H3 | DuckDB в K8s с RWO PVC при `replicaCount: 2` | 🔴 High | **Open** | Да | Частично (chart guard) |
| H4 | Terraform apply disabled / OIDC не настроен | 🔴 High | **Open** | Да | Нет (требуется AWS account + role) |
| H5 | Нет external pentest evidence | 🔴 High | **Open** | Да | Нет (требуется external provider) |
| H6 | DuckDB encryption at rest не доказана | 🔴 High | **Open** | Да | Частично (dev-конфиг + PRAGMA check) |
| M1 | Ruff global ignore S608 | 🟡 Medium | **Open** | Нет | **Да** |
| M2 | Bandit global skip B608 | 🟡 Medium | **Open** | Нет | **Да** |
| M3 | mypy weak config | 🟡 Medium | **Open** | Нет | **Да** (staged) |
| M4 | Helm values bcrypt hashes | 🟡 Medium | **Open** | Да | Частично (existingSecret pattern) |
| M7 | Нет rollback workflow | 🟡 Medium | **Open** | Нет | **Да** |
| M8 | Coverage gate 60% | 🟡 Medium | **Open** | Нет | **Да** (с тестами или scoped gates) |
| M9 | Нет immutable audit log | 🟡 Medium | **Open** | Да | Частично (Kafka topic + dual-write skeleton) |
| L6 | Нет SBOM generation | 🟢 Low | **Open** | Да (supply chain) | **Да** |
| L7 | Нет signed container images | 🟢 Low | **Open** | Да (supply chain) | Частично (skeleton) |

---

## Рекомендуемый порядок закрытия (без deploy/push/paid actions)

### Немедленно (локальные изменения в коде/конфиге)
1. **M1 / M2** — убрать глобальные ignore/skip S608/B608, заменить на per-file/inline suppressions.
2. **M3** — добавить per-module `disallow_untyped_defs = true` для `src.serving`, `src.quality`, `src.auth`.
3. **M7** — добавить `--atomic` в `helm upgrade` и rollback step `if: failure()` в staging-deploy.yml.
4. **L6** — добавить SBOM generation step в security.yml.

### Краткосрочно (1–4 недели, локально + требуют внешних сервисов для полного закрытия)
5. **H3** — chart guard: reject `replicaCount > 1` для DuckDB mode; архитектурное решение по ClickHouse для prod.
6. **H6** — добавить опциональное DuckDB encryption в dev + `PRAGMA encryption_status` check.
7. **M4** — реализовать `existingSecret` pattern в Helm chart; убрать hashes из production-shaped defaults.
8. **M8** — поднять coverage gate до 70% global + 80% per core module; добавить тесты для закрытия gap.
9. **M9** — создать Kafka topic schema и dual-write interface для audit log (без prod Kafka deploy).

### Среднесрочно (внешние зависимости)
10. **H4** — настройка AWS OIDC + включение terraform-apply workflow (требует AWS account owner).
11. **H5** — заказ external pentest (требует бюджета/провайдера).
12. **L7** — skeleton signing workflow; полное закрытие требует registry target и image publication decision.

---

*Источники:* Kubernetes Docs (2026), DuckDB.org (2025), Ruff/Bandit/mypy Docs, Helm Docs, OWASP ASVS 5.0, OWASP WSTG, Sigstore/Cosign Docs, CISA SBOM Guidance (2025), Confluent Kafka Docs.
