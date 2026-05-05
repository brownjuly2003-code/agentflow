# Task 5: Рекомендации по разделению изменений на commits / PRs

**Scope:** H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7
**Исключены (уже закрыты 2026-05-05):** H1, H2, L1, M5, M10, M12
**Constraint:** Без deploy/apply/push/paid actions.

---

## 1. Принципы группировки

| Принцип | Почему важен |
|---------|-------------|
| **Single-domain reviewer** | Один PR должен попадать в экспертизу одной команды (backend / DevOps / security / QA). Смешивание Helm-шаблонов и mypy-конфигов создаёт friction при review. |
| **Atomic rollback** | Если PR ломает CI, revert должен откатить ровно одну функцию. Не смешиваем coverage gate с новыми тестами — иначе revert тестов откатывает и gate. |
| **CI blast radius** | Изменения workflow-файлов перезапускают все проверки. Изолируем их в отдельные PR, чтобы не блокировать application-code merges. |
| **External gate boundary** | Local code и external-owner evidence разводим по разным PR. External gate PR может висеть открытым, пока owner не предоставит proof. |
| **Documentation decoupling** | Doc-only изменения (ADR, runbook) можно мержить быстро, не дожидаясь длинных CI-прогонов. Не смешиваем с кодом, если нет жёсткой зависимости. |

---

## 2. Рекомендуемые PR

### PR-1: `lint: narrow Ruff S608 and Bandit B608 to sqlglot-guarded paths`
**Items:** M1 + M2
**Why together:** Оба — SAST-tool narrowing, один reviewer (security/code-quality), трогают только конфиг + inline-annotations.

**Commits:**
1. `lint: remove S608 from global Ruff ignore, add per-file ignores`
   - `pyproject.toml`
2. `lint: remove B608 from global Bandit skips, add inline nosec with justification`
   - `.bandit`
   - `src/serving/semantic_layer/query_engine.py` и другие sqlglot-пути
3. `ci: regenerate Bandit baseline`
   - `scripts/bandit_diff.py` baseline artifact

**Verification:** `ruff check src/ tests/`, `bandit -r src/ sdk/ --ini .bandit`
**Rollback:** `git checkout -- pyproject.toml .bandit` + revert inline comments
**Risk:** Low. Нет runtime-изменений.

---

### PR-2: `types: enable disallow_untyped_defs for serving and quality`
**Item:** M3
**Why separate:** Может затронуть 10–30 файлов; mypy errors часто требуют итераций. Не блокировать PR-1 и PR-3.

**Commits:**
1. `config: add mypy overrides for src.serving.* and src.quality.*`
   - `pyproject.toml`
2. `types: add missing type hints in serving package`
   - `src/serving/**/*.py`
3. `types: add missing type hints in quality package`
   - `src/quality/**/*.py`

**Verification:** `mypy src/serving/ src/quality/ --ignore-missing-imports`
**Rollback:** `git checkout -- pyproject.toml` + revert type-hint additions
**Risk:** Medium. Возможны false-positive mypy failures в CI.

---

### PR-3: `helm: externalize apiKey secrets and add DuckDB architecture guardrails`
**Items:** M4 + H3 (только Helm-часть)
**Why together:** Оба трогают `helm/agentflow/values.yaml` и `templates/secret.yaml`. Один reviewer (K8s/DevOps).

**Commits:**
1. `helm: move apiKey hashes out of default values, add existingSecret pattern`
   - `helm/agentflow/values.yaml`
   - `helm/agentflow/templates/secret.yaml`
   - `helm/agentflow/templates/_helpers.tpl`
   - `k8s/staging/values-staging.yaml` (demo overrides с явным waiver)
2. `helm: add duckdbMode guardrail — enforce single-replica for DuckDB backend`
   - `helm/agentflow/values.yaml`
   - `helm/agentflow/templates/NOTES.txt`
3. `docs: add ADR for DuckDB K8s architecture decision`
   - `docs/adr/00X-duckdb-k8s-architecture.md`

**Verification:** `helm lint helm/agentflow`, `helm template` с разными `duckdbMode`, `helm template -f k8s/staging/values-staging.yaml`
**Rollback:** `git checkout -- helm/agentflow/ k8s/staging/values-staging.yaml` + удалить ADR
**Risk:** Medium. Helm guardrail может сломать staging, если там DuckDB с `replicaCount > 1`.

**Dependency:** PR-3 должен идти **до** PR-9, если PR-9 добавляет `secret.yaml` reference для encryption key.

---

### PR-4: `ci: add rollback workflow, SBOM generation, and cosign signing skeleton`
**Items:** M7 + L6 + L7
**Why together:** Все — GitHub Actions workflow changes. Один reviewer (DevOps), один CI blast radius.

**Commits:**
1. `ci: add manual helm rollback workflow`
   - `.github/workflows/rollback.yml`
   - `scripts/helm_rollback.sh`
2. `ci: add Syft SBOM generation to security workflow`
   - `.github/workflows/security.yml`
   - `scripts/generate_sbom.py`
3. `ci: add cosign container signing skeleton to publish workflow`
   - `.github/workflows/publish-pypi.yml`
   - `scripts/sign_image.sh`
4. `docs: update runbook for rollback, SBOM, and image signing`
   - `docs/runbook.md`

**Verification:** `act --dryrun` (rollback, security, publish workflows); `syft dir:. -o spdx-json` локально
**Rollback:** `git rm .github/workflows/rollback.yml scripts/helm_rollback.sh scripts/generate_sbom.py scripts/sign_image.sh` + revert workflow files
**Risk:** Low. Skeleton-only; cosign signing может быть no-op до registry target.

---

### PR-5: `ci: raise core module coverage gate to 75%`
**Item:** M8 (часть 1 — gate-изменение)
**Why separate от PR-6:** Изменение gate — policy decision. Тесты — content. Если тесты окажутся flaky, revert должен касаться только тестов, а не gate.

**Commits:**
1. `ci: split coverage gates — 75% for core modules, 60% global`
   - `.github/workflows/ci.yml`
   - `codecov.yml` / `pyproject.toml` (coverage config)

**Verification:** `pytest tests/unit/ tests/property/ --cov=src/serving --cov=src/quality --cov-fail-under=75`
**Rollback:** `git checkout -- .github/workflows/ci.yml codecov.yml`
**Risk:** High. CI может начать падать, пока не влит PR-6.

**Dependency:** PR-5 и PR-6 должны быть **ready-to-merge simultaneously** или PR-5 идёт сразу после PR-6.

---

### PR-6: `test: add unit tests for under-covered core modules`
**Item:** M8 (часть 2 — тесты)
**Why separate:** Большой diff (~новые файлы тестов). Reviewer — QA/backend, не DevOps.

**Commits:**
1. `test: add unit tests for auth module gap coverage`
2. `test: add unit tests for query_engine gap coverage`
3. `test: add unit tests for rate_limiter gap coverage`

**Verification:** `pytest tests/unit/ --cov=src/auth --cov=src/query_engine --cov=src/rate_limiter --cov-report=term-missing`
**Rollback:** `git rm tests/unit/...` (конкретные новые файлы)
**Risk:** Medium. Новые тесты могут быть flaky на Windows (WMI/pytest hangs).

**Merge order:** PR-6 → PR-5 (или оба в одном merge-train).

---

### PR-7: `feat: Kafka immutable audit topic publisher and dual-write`
**Item:** M9
**Why separate:** Streaming-изменение с middleware hook. Reviewer — streaming/backend, не DevOps.

**Commits:**
1. `feat: add audit_publisher for Kafka immutable audit topic`
   - `src/processing/audit_publisher.py`
   - `config/kafka_topics.yaml` (или helm/kafka-connect topic definition)
2. `feat: dual-write audit events from auth middleware to Kafka`
   - `src/serving/api/auth/middleware.py`
3. `test: integration test for immutable audit log`
   - `tests/integration/test_audit_immutable.py`
4. `docs: document immutable audit trail architecture`
   - `docs/security-audit.md`

**Verification:** `pytest tests/integration/test_audit_immutable.py -v`, `mypy src/processing/audit_publisher.py`
**Rollback:** `git checkout -- src/serving/api/auth/middleware.py` + удалить новые файлы
**Risk:** Medium. Kafka producer fail-open логика должна быть проверена; нельзя допустить 500-е ответы при недоступности Kafka.

---

### PR-8: `ci+terraform: enable terraform-apply workflow and document OIDC setup`
**Item:** H4
**Why separate:** Infrastructure-only PR, не трогает application code. Может висеть open до готовности AWS account owner.

**Commits:**
1. `ci: remove if: false from terraform-apply workflow, add environment gate`
   - `.github/workflows/terraform-apply.yml`
2. `terraform: update tfvars.example with all required variables`
   - `infrastructure/terraform/environments/staging.tfvars.example`
   - `infrastructure/terraform/environments/production.tfvars.example`
3. `docs: add runbook section for AWS OIDC and Terraform apply`
   - `docs/runbook.md`

**Verification:** `act --dryrun`, `terraform fmt -check`, `terraform validate -backend=false`
**Rollback:** `git checkout -- .github/workflows/terraform-apply.yml infrastructure/terraform/environments/ docs/runbook.md`
**Risk:** Low (локально). High risk при реальном apply.

**External gate:** Не считать закрытым до `AWS_TERRAFORM_ROLE_ARN` evidence + successful plan/apply output.

---

### PR-9: `feat: optional DuckDB at-rest encryption via operator-supplied key`
**Item:** H6
**Why separate:** Изолированное backend-изменение. Может потребовать обсуждения key management.

**Commits:**
1. `feat: add optional DuckDB encryption bootstrap via env var`
   - `src/serving/backends/duckdb_backend.py`
   - `config/security.yaml`
2. `helm: add optional encryption key reference in secret template`
   - `helm/agentflow/templates/secret.yaml` (опционально, если не конфликтует с PR-3)
3. `test: add unit test for DuckDB encryption PRAGMA`
   - `tests/unit/serving/test_duckdb_encryption.py`
4. `docs: document DuckDB encryption setup and evidence requirements`
   - `docs/security-audit.md`

**Verification:** `pytest tests/unit/serving/test_duckdb_encryption.py -v`, `mypy src/serving/backends/duckdb_backend.py`
**Rollback:** `git checkout -- src/serving/backends/duckdb_backend.py config/security.yaml` + удалить новые файлы
**Risk:** Low. Backward-compatible (encryption opt-in).

**Dependency:** Если PR-3 уже изменил `templates/secret.yaml`, rebase PR-9 поверх PR-3.

---

### PR-10: `docs: pentest readiness templates and external evidence tracking`
**Item:** H5
**Why separate:** Doc-only, no functional code. Может быть влит независимо от всех остальных.

**Commits:**
1. `docs: add pentest scope template for external vendors`
   - `docs/compliance/pentest-scope-template.md`
2. `docs: add pentest evidence issue template`
   - `.github/ISSUE_TEMPLATE/pentest-evidence.md`
3. `docs: update security-audit with pentest readiness checklist`
   - `docs/security-audit.md`

**Verification:** Markdown lint, `make docs-lint`
**Rollback:** `git rm docs/compliance/pentest-scope-template.md .github/ISSUE_TEMPLATE/pentest-evidence.md` + revert docs
**Risk:** None.

**External gate:** Не считать закрытым до engagement letter + report artifact.

---

## 3. Порядок merge и зависимости

```
Параллельно (нет кросс-зависимостей):
  PR-1  (lint)
  PR-2  (types)
  PR-10 (docs pentest)

После PR-1 + PR-2 (опционально, не strict):
  PR-3  (helm) ──┬──► PR-9  (encryption) — rebase на secret.yaml если нужно
                 └──► PR-7  (audit) — можно параллельно

Параллельно с PR-3:
  PR-4  (CI/CD)
  PR-8  (terraform)

Перед PR-5:
  PR-6  (tests) ──► PR-5  (gate) — merge train или одновременно
```

**Strict dependencies:**
- PR-5 (gate) **не должен мержиться раньше** PR-6 (tests), иначе CI упадёт на main.
- PR-9 (encryption) **рекомендуется rebase** на PR-3, если `templates/secret.yaml` меняется в обоих.
- PR-7 (audit) **желательно после** PR-3, чтобы Kafka topic schema был согласован с helm chart values.

---

## 4. Что НЕ стоит смешивать

| Не смешивать | Почему |
|-------------|--------|
| **M8 gate + M8 tests** | Revert тестов откатит и gate. Gate — policy, тесты — content. |
| **H4 (Terraform) + H3 (DuckDB Helm)** | Разные домены (cloud IAM vs K8s storage). Terraform PR может ждать AWS owner месяцами; Helm PR можно мержить сейчас. |
| **M1/M2 (lint) + M3 (types)** | Ruff/Bandit — security reviewer. mypy — backend reviewer. Разные blast radius. |
| **M9 (audit Kafka) + L6/L7 (CI)** | Streaming logic и workflow YAML не связаны. Reviewer expertise различается. |
| **Любой external gate + local fix** | External gate PR (H4, H5, H6 full) может висеть open; local fix должен мержиться быстро. |

---

## 5. Commit-message convention

Использовать [Conventional Commits](https://www.conventionalcommits.org/):

```
<scope>: <description>

<optional body>

Refs: <audit-item-id>
```

Примеры:
```
lint: remove S608 from global Ruff ignore, add per-file ignores

Ruff now flags unvalidated SQL string construction everywhere except
src/serving/semantic_layer/query_engine.py (sqlglot-guarded path).

Refs: M1
```

---

## 6. Rollback strategy per PR group

| PR # | One-liner rollback | Время восстановления |
|------|-------------------|----------------------|
| PR-1 | `git revert <merge-commit>` конфиг + inline comments | < 5 мин |
| PR-2 | `git revert <merge-commit>` type hints + pyproject.toml | < 5 мин |
| PR-3 | `git revert <merge-commit>` helm/ + ADR | < 5 мин |
| PR-4 | `git revert <merge-commit>` workflow + scripts | < 5 мин |
| PR-5 | `git revert <merge-commit>` ci.yml gate | < 5 мин |
| PR-6 | `git revert <merge-commit>` test files | < 5 мин |
| PR-7 | `git revert <merge-commit>` middleware + publisher | < 5 мин |
| PR-8 | `git revert <merge-commit>` workflow + tfvars.example | < 5 мин |
| PR-9 | `git revert <merge-commit>` backend + test | < 5 мин |
| PR-10 | `git revert <merge-commit>` docs | < 5 мин |

**Важно:** Каждый PR — squash merge в `main`. Это делает revert атомарным на уровне merge-commit.

---

*Generated for Task 5 — Commit/PR decomposition.*
*Date: 2026-05-05*
