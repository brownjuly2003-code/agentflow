# Исследование оставшихся открытых пунктов audit_kimi_04_05_26.md

**Дата:** 2026-05-05
**Контекст:** После локального remediation-пакета 2026-05-05 (закрыты H1/H2/L1, M5, M10, M12) проверены оставшиеся пункты по первичным источникам.
**Ограничение:** Только локальные правки / конфигурация. Без deploy/apply/push/paid-действий.

---

## Сводка статусов

| ID | Приоритет | Тема | Статус после remediation | Источник |
|----|-----------|------|--------------------------|----------|
| H3 | 🔴 High | DuckDB в K8s с `ReadWriteOnce` PVC при `replicaCount: 2` | **Открыт** | DuckDB docs, ClickHouse Operator docs |
| H4 | 🔴 High | AWS Terraform apply отключён, OIDC не настроен | **Открыт** | AWS docs, GitHub docs |
| H5 | 🔴 High | Нет external penetration test | **Открыт** | OWASP, NIST 800-53 |
| H6 | 🔴 High | DuckDB encryption at rest не доказана | **Открыт** | DuckDB Encryption blog/docs |
| M1 | 🟡 Medium | Ruff игнорирует `S608` глобально | **Открыт** | Ruff docs (Astral) |
| M2 | 🟡 Medium | Bandit пропускает `B608` глобально | **Открыт** | Bandit docs |
| M3 | 🟡 Medium | mypy `disallow_untyped_defs = false` | **Открыт** | mypy docs |
| M4 | 🟡 Medium | Helm values содержат bcrypt hashes | **Открыт** | External Secrets Operator docs |
| M7 | 🟡 Medium | Нет rollback workflow | **Открыт** | Helm docs, GitHub Actions docs |
| M8 | 🟡 Medium | Coverage gate 60 % — низкий | **Открыт** | pytest-cov docs, industry practice |
| M9 | 🟡 Medium | Нет immutable audit log | **Открыт** | Kafka docs, Confluent best practices |
| L6 | 🟢 Low | Нет SBOM generation | **Открыт** | Syft/Trivy docs, OpenSSF |
| L7 | 🟢 Low | Нет signed container images | **Открыт** | Sigstore/Cosign docs |

---

## H3 — DuckDB в K8s с `ReadWriteOnce` PVC при `replicaCount: 2`

### Текущее состояние
- `helm/agentflow/values.yaml`: `replicaCount: 2`, `autoscaling.enabled: true`, `persistence.accessModes: [ReadWriteOnce]`.
- Каждый Pod получает собственный PVC с локальным `agentflow.duckdb`. При записи данные расходятся между репликами (split-brain).
- ClickHouse backend существует (`src/serving/backends/clickhouse_backend.py`), но в Helm чарте DuckDB остаётся дефолтным путём для local/prod.

### Best practice по первичным источникам
**DuckDB docs** не рекомендуют shared-write архитектуру для in-process БД: DuckDB рассчитан на single-node или read-only реплики через `ATTACH`/`HTTPFS`. Для multi-replica write нагрузки документация указывает на необходимость единого writer-процесса.

**ClickHouse Operator docs** (official ClickHouse Kubernetes Operator, 2026-01):
- Production кластер должен использовать `ClickHouseCluster` + `KeeperCluster` CRDs.
- `dataVolumeClaimSpec.accessModes: ReadWriteOnce` допустимо только в связке с шардированием/репликацией на уровне ClickHouse (ReplicatedMergeTree), а не для нескольких независимых писателей.
- Best practice: StatefulSet per replica с Replicated database engine (`ENGINE = Replicated`).

### Локальная рекомендация
1. **В `values.yaml` для prod-окружений** отключить `autoscaling` и установить `replicaCount: 1` для writer-инстанса, либо
2. **Переключить prod-backend** на ClickHouse: вынести `config.backend: clickhouse` в `values-staging.yaml` / `values-prod.yaml`, а DuckDB оставить только для local/dev (`values.yaml`).
3. Добавить комментарий в `values.yaml`: `# DuckDB with RWO PVC is NOT suitable for multi-replica production serving. Use ClickHouse backend for replicaCount > 1.`

---

## H4 — AWS Terraform apply отключён, OIDC не настроен

### Текущее состояние
- `.github/workflows/terraform-apply.yml` содержит `if: false` (workflow disabled).
- В `infrastructure/` модули Terraform валидны, но реальный `apply` не выполнялся.
- Нет `AWS_TERRAFORM_ROLE_ARN` в GitHub Environment secrets.

### Best practice
- AWS + GitHub OIDC: использование `id-token: write` + `aws-actions/configure-aws-credentials` с `role-to-assume` — рекомендованный AWS паттерн для eliminate long-lived keys (AWS Security Blog, GitHub docs).
- `terraform-apply.yml` должен иметь `environment: production` + `required reviewers`, а не быть полностью отключён.

### Локальная рекомендация
1. Убрать `if: false` из `terraform-apply.yml` и заменить на `if: github.ref == 'refs/heads/main'` + `workflow_dispatch`.
2. Добавить `needs: [security-scan, e2e]` перед apply.
3. Оставить placeholder для `AWS_TERRAFORM_ROLE_ARN` в `.env.example` с комментарием `Required for production Terraform apply via OIDC`.
4. **Не применять** Terraform в реальное облако без явного согласования (ограничение задачи).

---

## H5 — Нет external penetration test

### Текущее состояние
- В репозитории нет отчётов о внешнем pentest (Bishop Fox, Cobalt, etc.).
- Есть внутренние security scans (Bandit, Safety, Trivy), но нет external attestation.

### Best practice
- OWASP Testing Guide v4.2 / NIST SP 800-53 Rev. 5: для enterprise production требуется независимый penetration test не реже 1 раза в год или при significant architecture change.
- SOC 2 Type II / ISO 27001 также требуют сторонней оценки.

### Локальная рекомендация
1. Создать `docs/security/pentest-plan.md` с scope, target dates, exclusion list и emergency contact.
2. Добавить checklist в `release-readiness.md`: `□ External pentest report (critical/high remediated)`.
3. **Не заказывать** пентест в рамках локального remediation (ограничение задачи).

---

## H6 — DuckDB encryption at rest не доказана

### Текущее состояние
- `src/serving/backends/duckdb_backend.py` открывает БД через `duckdb.connect(self.db_path)` без `ENCRYPTION_KEY`.
- Нет `PRAGMA` или `ATTACH ... (ENCRYPTION_KEY '...', ENCRYPTION_CIPHER 'GCM')`.
- `.duckdb` файлы в репозитории и `docker-compose` volumes не зашифрованы.

### Best practice по первичным источникам
**DuckDB Data-at-Rest Encryption (blog 2025-11-19, DuckDB v1.4+):**
- Поддерживает AES-GCM-256 (рекомендуется) и AES-CTR-256.
- Шифруются все блоки и WAL; main header остаётся plaintext (не содержит sensitive data).
- Для записи требуется загрузка `httpfs` extension (OpenSSL backend) — Mbed TLS режим write отключён в v1.4.1+ из-за RNG issues.
- Ключ рекомендуется 32-byte base64. Пользователь несёт ответственность за key management.

### Локальная рекомендация
1. **Для local/dev**: добавить в `duckdb_backend.py` опциональный `encryption_key` параметр:
   ```python
   if encryption_key:
       conn.execute(f"ATTACH '{db_path}' AS af (ENCRYPTION_KEY '{encryption_key}', ENCRYPTION_CIPHER 'GCM')")
   else:
       conn = duckdb.connect(db_path)
   ```
2. **Для production**: не полагаться на DuckDB encryption как единственный контроль; использовать encrypted PVC (LUKS/Ledger) или мигрировать на ClickHouse (TLS + at-rest encryption через провайдер хранилища).
3. Добавить в `docs/security-audit.md` раздел: "DuckDB at-rest encryption is enabled for local files via AES-GCM-256 when `DUCKDB_ENCRYPTION_KEY` is set; for production, ClickHouse backend is recommended."

---

## M1 — Ruff игнорирует `S608` глобально

### Текущее состояние
- `pyproject.toml`:
  ```toml
  [tool.ruff.lint]
  ignore = ["S101", "S311", "S608"]
  ```
- Есть `per-file-ignores` для тестов и backend файлов, но `S608` (SQL injection) глобально отключён.

### Best practice
- Ruff docs (Astral): `ignore` в глобальной секции применяется ко всем файлам. Для узких исключений рекомендуется `per-file-ignores` с обоснованием.
- SQL-инъекции должны быть разрешены только в файлах с проверенными guard-ами (например, `sqlglot` AST validation + parameterized queries).

### Локальная рекомендация
1. Убрать `"S608"` из глобального `ignore`.
2. Добавить в `per-file-ignores` только для валидированных путей:
   ```toml
   [tool.ruff.lint.per-file-ignores]
   "src/serving/backends/duckdb_backend.py" = ["S608"]
   "src/serving/backends/clickhouse_backend.py" = ["S608"]
   "src/serving/semantic_layer/query_engine.py" = ["S608"]
   ```
3. Добавить комментарий над каждым `S608` игнором: `# S608 allowed: queries built via sqlglot AST validation + parameterized execution; no user-controlled string concatenation.`

---

## M2 — Bandit пропускает `B608` глобально

### Текущее состояние
- `.bandit`:
  ```ini
  [bandit]
  skips = B101,B311,B608
  ```
- Аналогично M1: B608 (hardcoded SQL expressions) пропускается во всей кодовой базе.

### Best practice
- Bandit docs: `skips` в `.bandit` — глобальный список. Рекомендуется использовать `nosec` комментарии на конкретных строках или per-file baseline с обоснованием.
- Для baseline-approach: использовать `.bandit-baseline.json` и `bandit_diff.py`, но не отключать плагин глобально.

### Локальная рекомендация
1. Убрать `B608` из `skips` в `.bandit`.
2. В файлах, где `B608` срабатывает ложно (например, `duckdb_backend.py` строка с `SELECT * FROM {table_name}`), добавить `# nosec B608` с пояснением:
   ```python
   conn.execute(f"SELECT * FROM {table_name} LIMIT 0")  # nosec B608 - table_name from internal catalog, not user input
   ```
3. Обновить `scripts/bandit_diff.py`, чтобы он игнорировал `nosec`-аннотации при сравнении (Bandit по умолчанию это делает).

---

## M3 — mypy `disallow_untyped_defs = false`

### Текущее состояние
- `pyproject.toml`:
  ```toml
  [tool.mypy]
  disallow_untyped_defs = false
  ```
- Полностью отключено требование типизации для всех функций. Flink paths игнорируются (`ignore_errors = true`).

### Best practice
- mypy docs: `disallow_untyped_defs = true` — ключевой флаг для strict mode. Рекомендуется включать поэтапно: сначала для критичных модулей (`src/serving/`, `src/quality/`), затем для всего `src/`.
- Per-module override в `pyproject.toml` позволяет мигрировать постепенно без блокировки CI.

### Локальная рекомендация
1. Установить `disallow_untyped_defs = true` глобально.
2. Добавить override для модулей, которые ещё не готовы:
   ```toml
   [[tool.mypy.overrides]]
   module = ["src.processing.flink_jobs.*", "tests.*"]
   disallow_untyped_defs = false
   ```
3. Запустить `mypy src/` локально, исправить ошибки в `src/serving/` и `src/quality/` (это core модули).

---

## M4 — Helm values содержат bcrypt hashes

### Текущее состояние
- `helm/agentflow/values.yaml` содержит:
  ```yaml
  secrets:
    apiKeys:
      keys:
        - key_hash: "$2b$12$UNE9Vh.YivKR7Zt7xIZweebebjkcVaQv240rqabzG/H3dWoljplcO"
  ```
- Хотя это hash, наличие его в values.yaml создаёт риск rainbow-table атаки при известном salt/rounds.

### Best practice
- External Secrets Operator docs: secrets должны храниться в external vault (AWS Secrets Manager, Azure Key Vault, HashiCorp Vault) и синхронизироваться в K8s через `ExternalSecret`/`SecretStore` CRDs.
- Helm best practice: `values.yaml` не должен содержать credentials или hashes; использовать `lookup` или external secret manager.

### Локальная рекомендация
1. **В `values.yaml`**: заменить хеш на placeholder:
   ```yaml
   secrets:
     apiKeys:
       keys: []  # populated via ExternalSecret in production; see docs/deployment/secrets.md
   ```
2. Создать `docs/deployment/secrets.md` с шаблоном `ExternalSecret`:
   ```yaml
   apiVersion: external-secrets.io/v1beta1
   kind: ExternalSecret
   metadata:
     name: agentflow-api-keys
   spec:
     refreshInterval: 1h
     secretStoreRef:
       name: vault-backend
       kind: SecretStore
     target:
       name: agentflow-api-keys
       template:
         data:
           api_keys.yaml: |
             keys:
               - key_hash: "{{ .api_key_hash }}"
     data:
       - secretKey: api_key_hash
         remoteRef:
           key: agentflow/api-keys
           property: hash
   ```
3. **Не применять** ExternalSecret в кластер без наличия SecretStore (ограничение задачи).

---

## M7 — Нет rollback workflow

### Текущее состояние
- `.github/workflows/staging-deploy.yml` выполняет `helm upgrade`, но нет шага `helm rollback` при failure.
- Нет отдельного workflow для emergency rollback production.

### Best practice
- Helm docs: `helm rollback <RELEASE> [REVISION]` — стандартная команда для отката к предыдущей ревизии. Best practice: автоматизировать rollback в CI при failed health-check после deploy.
- GitHub Actions: использовать `failure()` condition + `helm rollback` в том же job, либо отдельный reusable workflow.

### Локальная рекомендация
1. В `staging-deploy.yml` добавить шаг после deploy-failure:
   ```yaml
   - name: Rollback on failure
     if: failure()
     run: |
       helm history agentflow --namespace agentflow
       helm rollback agentflow 0 --namespace agentflow --wait
   ```
2. Создать `docs/runbook.md` раздел "Emergency Helm Rollback" с командами:
   ```bash
   helm history agentflow -n agentflow
   helm rollback agentflow <PREV_REVISION> -n agentflow --wait --timeout 5m
   ```
3. Для production рекомендуется `helm upgrade --atomic --cleanup-on-fail` (atomic rollback автоматически).

---

## M8 — Coverage gate 60 % — низкий

### Текущее состояние
- `.github/workflows/ci.yml`:
  ```bash
  python -m pytest tests/unit/ tests/property/ ... --cov-fail-under=60
  ```
- 60 % — ниже рекомендуемого для core-модулей (auth, query engine, rate limiter).

### Best practice
- pytest-cov docs: `--cov-fail-under` задаёт глобальный floor. Для монорепозиториев рекомендуется differential coverage (Codecov patch status) + повышенный floor для критичных пакетов.
- Industry practice: core security modules — 80-90 %, остальные — 60-75 %.

### Локальная рекомендация
1. Поднять глобальный gate до `--cov-fail-under=65` (incremental step).
2. Добавить per-package gate в `pyproject.toml` через `coverage` config:
   ```toml
   [tool.coverage.report]
   fail_under = 65

   [tool.coverage.run]
   source = ["src", "sdk"]

   [tool.coverage.report.paths]
   source = ["src"]
   ```
3. В CI добавить отдельный шаг для core modules:
   ```bash
   pytest tests/unit/test_auth.py tests/unit/test_rate_limiter.py tests/unit/test_query_engine.py --cov=src.serving.api.auth,src.serving.api.rate_limiter,src.serving.semantic_layer.query_engine --cov-fail-under=80
   ```
4. Обновить `docs/CONTRIBUTING.md`: указать target coverage для новых модулей.

---

## M9 — Нет immutable audit log

### Текущее состояние
- `api_usage` пишется в DuckDB (`agentflow_api.duckdb`) — mutable storage.
- Нет dedicated Kafka topic для audit events с infinite retention.

### Best practice
- Kafka docs / Confluent: audit log должен быть append-only, immutable, с долгосрочным хранением (Tiered Storage или S3 Object Lock через Kafka Connect).
- Confluent Cloud использует отдельный Kafka cluster для audit logs с 7+ днями retention и WORM-хранилищем.

### Локальная рекомендация
1. Добавить в `docker-compose.yml` (local dev) топик `api_usage.audit`:
   ```bash
   kafka-topics --create --topic api_usage.audit --partitions 3 --replication-factor 1 --config retention.ms=-1 --config cleanup.policy=delete
   ```
   (для local dev `cleanup.policy=delete` с большим retention достаточно; для prod — `compact` + Tiered Storage).
2. В `src/serving/api/middleware.py` (audit logging) добавить dual-write: писать одновременно в DuckDB (queryable) и в Kafka topic `api_usage.audit` (immutable trail).
3. Добавить в `config/tenants.yaml` или `config/security.yaml` флаг `audit_sink: kafka` для prod-окружений.
4. Документировать в `docs/security-audit.md`: "Local: DuckDB only. Production: DuckDB + Kafka audit topic with Tiered Storage / S3 Object Lock sink."

---

## L6 — Нет SBOM generation

### Текущее состояние
- В CI нет шагов для генерации Software Bill of Materials.
- Нет SPDX/CycloneDX артефактов в релизах.

### Best practice
- OpenSSF / Syft docs: SBOM должен генерироваться для каждого релиза (container image + Python packages). Форматы: SPDX, CycloneDX.
- Trivy может генерировать SBOM как часть security scan.

### Локальная рекомендация
1. Добавить в `.github/workflows/security.yml` шаг:
   ```yaml
   - name: Generate SBOM
     uses: anchore/sbom-action@v0
     with:
       image: agentflow/api:${{ github.sha }}
       format: spdx-json
       output-file: sbom.spdx.json
   - name: Upload SBOM
     uses: actions/upload-artifact@v4
     with:
       name: sbom
       path: sbom.spdx.json
   ```
2. Локально добавить `scripts/generate_sbom.py` (wrapper для `syft`):
   ```python
   #!/usr/bin/env python3
   import subprocess, sys
   subprocess.run(["syft", "agentflow/api:latest", "-o", "spdx-json", "=sbom.spdx.json"], check=True)
   ```
3. Обновить `Makefile`:
   ```makefile
   sbom:
       syft agentflow/api:latest -o spdx-json=sbom.spdx.json
   ```

---

## L7 — Нет signed container images

### Текущее состояние
- `.github/workflows/publish-pypi.yml` и `publish-npm.yml` не содержат подписи образов.
- Dockerfile.api собирается, но не подписывается `cosign`.

### Best practice
- Sigstore docs: Cosign — стандарт для подписи контейнеров без необходимости управления long-lived keys (keyless signing через OIDC + Fulcio/Rekor).
- GitHub Actions: `sigstore/cosign-installer` + `cosign sign` после push образа.

### Локальная рекомендация
1. Добавить в `publish-pypi.yml` (или отдельный `publish-image.yml`) шаг:
   ```yaml
   - name: Install Cosign
     uses: sigstore/cosign-installer@v3
   - name: Sign image
     run: cosign sign --yes ${{ env.IMAGE_URI_DIGEST }}
     env:
       IMAGE_URI_DIGEST: agentflow/api@${{ steps.build.outputs.digest }}
   ```
2. Для keyless signing требуется `id-token: write` permission (уже есть в publish workflows).
3. Добавить в `docs/security-audit.md`: "Container images are signed with Cosign (Sigstore). Verify with: `cosign verify --certificate-identity-regexp 'https://github.com/...' agentflow/api:TAG`"
4. **Не публиковать** образ в реестр без явного согласования (ограничение задачи).

---

## Заключение

Все перечисленные пункты остаются **открытыми** после remediation 2026-05-05. Для каждого пункта выше приведены:
- **Current state** — что найдено в коде/конфигах.
- **Primary-source best practice** — DuckDB/ClickHouse docs, Ruff/Bandit/mypy docs, External Secrets Operator, Helm, Kafka/Confluent, Sigstore.
- **Local recommendation** — конкретные правки конфигов, комментарии, скрипты, документация. **Никаких deploy/apply/push/paid actions не требуется.**

**Приоритет следующих шагов (если будет продолжение remediation):**
1. **H3 + H6** — DuckDB в K8s + encryption (архитектурные решения в values.yaml и backend code).
2. **M1 + M2 + M3** — линтеры/типизация (только конфигурационные правки `pyproject.toml`, `.bandit`, `# nosec`/`# type: ignore` комментарии).
3. **M4 + M7 + M9** — Helm secrets, rollback workflow, audit log (YAML/GitHub Actions правки).
4. **L6 + L7** — SBOM + Cosign (добавление шагов в CI workflow файлы).
5. **H4 + H5** — Terraform enablement и pentest-plan (требуют внешних ресурсов, минимум локальных правок).
