# Minimal Safe Implementation Plan — AgentFlow audit leftovers
**Scope:** H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7
**Excluded (already closed in 2026-05-05 remediation):** H1, H2, L1, M5, M10, M12
**Constraint:** No deploy/apply/push/paid actions proposed.

---

## Legend per item
- **Files touched** — expected working-tree changes.
- **Verification** — commands that prove correctness *before* merge.
- **Rollback** — one-step revert if validation fails.
- **PR scope** — suggested commit/PR grouping.

---

## 🔴 High

### H3 — DuckDB in K8s with `ReadWriteOnce` PVC at `replicaCount: 2`
**Category:** needs architecture decision + local doc/Helm guardrails now

| | Detail |
|---|---|
| **Files touched** | `helm/agentflow/values.yaml` (add `architectureNote` + conditional single-replica guard), `helm/agentflow/templates/NOTES.txt` (runtime warning), `docs/adr/00X-duckdb-k8s-architecture.md` (new ADR) |
| **Implementation** | 1) Add `docs/adr/00X-duckdb-k8s-architecture.md` documenting: ClickHouse as prod backend, DuckDB only for local/single-replica. 2) In `values.yaml` add `duckdbMode: local-dev` enum (`local-dev` / `single-replica` / `clickhouse-backend`). 3) If `duckdbMode == single-replica`, set `replicaCount: 1`, `autoscaling.enabled: false`, and emit a `NOTES.txt` warning. 4) If `duckdbMode == clickhouse-backend`, require `clickhouseUrl` and skip DuckDB PVC. |
| **Verification** | `helm template agentflow helm/agentflow --set duckdbMode=single-replica | grep -E "replicas|enabled"` shows `replicas: 1` and autoscaling absent/disabled. `helm lint helm/agentflow` passes. |
| **Rollback** | `git checkout -- helm/agentflow/values.yaml helm/agentflow/templates/NOTES.txt` and delete the ADR file. |
| **PR scope** | **Single PR:** `docs+helm: DuckDB K8s architecture guards` |

---

### H4 — AWS Terraform apply disabled; OIDC not configured
**Category:** needs external owner/evidence + local enablers now

| | Detail |
|---|---|
| **Files touched** | `.github/workflows/terraform-apply.yml` (remove `if: false`, add `environment: production`, add `permissions: id-token: write, contents: read`), `infrastructure/terraform/environments/staging.tfvars.example`, `infrastructure/terraform/environments/production.tfvars.example`, `docs/runbook.md` (section: "Enabling Terraform apply") |
| **Implementation** | 1) Un-disable the workflow by deleting `if: false`. 2) Add `environment: production` gate + required reviewer. 3) Add `permissions` block for OIDC (`id-token: write`). 4) Update `tfvars.example` files with all variables needed (region, bucket names, VPC CIDR, role ARNs as placeholders). 5) Add runbook section: exact steps to create `AWS_TERRAFORM_ROLE_ARN` and AWS OIDC provider. **Do not create real AWS resources or push secrets.** |
| **Verification** | `act -j terraform-apply -W .github/workflows/terraform-apply.yml --dryrun` or at minimum `python -m py_compile` the YAML; `terraform fmt -check -recursive infrastructure/terraform/` passes; `terraform validate` passes (still with `-backend=false`). |
| **Rollback** | `git checkout -- .github/workflows/terraform-apply.yml infrastructure/terraform/environments/ docs/runbook.md` |
| **PR scope** | **Single PR:** `ci+terraform: enable terraform-apply workflow and document AWS OIDC setup` |

---

### H5 — No external penetration test evidence
**Category:** needs external owner/evidence + local preparation now

| | Detail |
|---|---|
| **Files touched** | `docs/security-audit.md` (add pentest readiness checklist), `docs/compliance/pentest-scope-template.md` (new), `.github/ISSUE_TEMPLATE/pentest-evidence.md` (new tracking template) |
| **Implementation** | 1) Document scope template: API surface, auth flows, tenant isolation, SQL guard, file upload (if any), admin endpoints. 2) Add readiness checklist: all High/Medium audit items closed, staging environment accessible, API docs current. 3) Create an issue template that an external pentest vendor can fill to provide evidence (report hash, date, CVEs found). **No paid action proposed.** |
| **Verification** | Markdown lint passes; `make docs-lint` or manual review. |
| **Rollback** | `git rm docs/compliance/pentest-scope-template.md .github/ISSUE_TEMPLATE/pentest-evidence.md` and revert `docs/security-audit.md`. |
| **PR scope** | **Single PR:** `docs: pentest readiness templates and evidence tracking` |

---

### H6 — DuckDB encryption at rest not demonstrated
**Category:** needs architecture decision + local implementation now

| | Detail |
|---|---|
| **Files touched** | `src/serving/backends/duckdb_backend.py` (add `PRAGMA` setup helper), `config/security.yaml` (add `duckdb_encryption_key_env_var`), `helm/agentflow/templates/secret.yaml` (optional encrypted-key reference), `docs/security-audit.md` (encryption evidence section), `tests/unit/serving/test_duckdb_encryption.py` (new) |
| **Implementation** | 1) Add optional encryption bootstrap in DuckDB backend: if env var `AGENTFLOW_DUCKDB_ENCRYPTION_KEY` is present, execute `PRAGMA add_parquet_key('key_id', '${key}')` and/or `SET encryption='AES'` on new DB creation. 2) Document: encryption is *opt-in* and requires operator to supply key via K8s secret / env. 3) Add unit test that verifies PRAGMA is issued when env var present, and skipped when absent (backward compatible). 4) Update security-audit.md with: "At-rest encryption is enabled via operator-supplied key; see `docs/runbook.md#duckdb-encryption`." |
| **Verification** | `python -m pytest tests/unit/serving/test_duckdb_encryption.py -v` passes. `mypy src/serving/backends/duckdb_backend.py` passes. |
| **Rollback** | `git checkout -- src/serving/backends/duckdb_backend.py config/security.yaml` and delete new test + doc additions. |
| **PR scope** | **Single PR:** `feat+test: optional DuckDB at-rest encryption via env key` |

---

## 🟡 Medium

### M1 — Ruff ignores `S608` globally
**Category:** can fix locally now

| | Detail |
|---|---|
| **Files touched** | `pyproject.toml` |
| **Implementation** | 1) Remove `S608` from global `[tool.ruff.lint] ignore`. 2) Add `per-file-ignores` only for files covered by `sqlglot` guard: `src/serving/semantic_layer/query_engine.py` and any other validated NL-to-SQL paths. 3) Add inline `# noqa: S608` with justification comment for the specific lines that use dynamic SQL after AST validation. |
| **Verification** | `ruff check src/ tests/` passes without new S608 findings elsewhere. `ruff check --select S608 src/` shows only expected per-file/line ignores. |
| **Rollback** | `git checkout -- pyproject.toml` |
| **PR scope** | **Single PR:** `lint: narrow Ruff S608 ignore to sqlglot-guarded paths` |

---

### M2 — Bandit skips `B608` globally
**Category:** can fix locally now

| | Detail |
|---|---|
| **Files touched** | `.bandit`, `pyproject.toml` (if bandit config is moved there), affected source files |
| **Implementation** | 1) Remove `B608` from `.bandit` global `skips`. 2) Use inline `# nosec B608` with justification on the exact sqlglot-validated lines. 3) Update `scripts/bandit_diff.py` baseline generation if needed (regenerate baseline after change). |
| **Verification** | `bandit -r src sdk --ini .bandit --severity-level medium` exits 0 on baseline, and `bandit -r src sdk --ini .bandit` shows only `# nosec` annotated lines for B608. |
| **Rollback** | `git checkout -- .bandit` and remove inline `# nosec` comments. |
| **PR scope** | **Same PR as M1** (both are lint-tool narrowing) or separate if CI gating requires incremental. |

---

### M3 — mypy `disallow_untyped_defs = false`
**Category:** can fix locally now

| | Detail |
|---|---|
| **Files touched** | `pyproject.toml`, possibly `src/serving/**/*.py`, `src/quality/**/*.py` |
| **Implementation** | 1) Add `[tool.mypy.overrides]` for `src.serving.*` and `src.quality.*` with `disallow_untyped_defs = true`. 2) Keep global `disallow_untyped_defs = false` for legacy paths (Flink jobs already have `ignore_errors`). 3) Fix any new mypy errors in those two packages (add `-> None`, `-> dict[str, Any]`, etc.). |
| **Verification** | `mypy src/serving/ src/quality/ --ignore-missing-imports` passes. `mypy src/` (global) still passes because overrides are scoped. |
| **Rollback** | `git checkout -- pyproject.toml` and revert type-hint additions. |
| **PR scope** | **Single PR:** `types: enable disallow_untyped_defs for serving and quality` |

---

### M4 — Helm values contain bcrypt hashes
**Category:** can fix locally now (Helm template refactor) + needs external owner for real Vault

| | Detail |
|---|---|
| **Files touched** | `helm/agentflow/values.yaml` (remove `secrets.apiKeys`), `helm/agentflow/templates/secret.yaml` (add `apiKeys` field with `b64enc` of `default ""`), `helm/agentflow/templates/_helpers.tpl` (optional validation helper), `k8s/staging/values-staging.yaml` (inject demo keys via staging override), `docs/runbook.md` (external secret manager migration guide) |
| **Implementation** | 1) Move `secrets.apiKeys.keys` out of default `values.yaml`; replace with `secrets.apiKeys.existingSecretName: ""`. 2) In `templates/secret.yaml`, if `existingSecretName` is empty and `apiKeys` is provided via Helm `--set-file` or staging values, create the Secret; otherwise require operator to provide an external secret. 3) Add a `helm lint` friendly validation: if neither is set, `fail "apiKeys must be provided via existingSecret or values override"`. 4) Keep demo hashes only in `values-staging.yaml` (non-production by definition). |
| **Verification** | `helm lint helm/agentflow` passes. `helm template helm/agentflow` fails with expected error when no apiKeys source is given. `helm template helm/agentflow -f k8s/staging/values-staging.yaml` renders Secret correctly. |
| **Rollback** | `git checkout -- helm/agentflow/values.yaml helm/agentflow/templates/secret.yaml k8s/staging/values-staging.yaml` |
| **PR scope** | **Single PR:** `helm: externalize apiKey secrets, keep staging overrides` |

---

### M7 — No rollback workflow
**Category:** can fix locally now

| | Detail |
|---|---|
| **Files touched** | `.github/workflows/rollback.yml` (new), `scripts/helm_rollback.sh` (new), `docs/runbook.md` |
| **Implementation** | 1) Create `rollback.yml` triggered by `workflow_dispatch` with inputs: `environment` (staging/production), `release_name`, `revision` (optional). 2) Job runs `helm rollback <release> <revision>` against the target cluster. 3) Add `environment` gate for production with required reviewer. 4) Add smoke step: `helm test` or `pytest tests/e2e/test_smoke.py` against rolled-back endpoint. 5) Document in runbook. **No automatic triggers** (only manual dispatch to avoid accidental rollbacks). |
| **Verification** | `act workflow_dispatch -W .github/workflows/rollback.yml --dryrun` or YAML syntax check. `helm lint` unaffected. |
| **Rollback** | `git rm .github/workflows/rollback.yml scripts/helm_rollback.sh` and revert docs. |
| **PR scope** | **Single PR:** `ci: add manual helm rollback workflow` |

---

### M8 — Coverage gate 60% too low for core modules
**Category:** can fix locally now

| | Detail |
|---|---|
| **Files touched** | `.github/workflows/ci.yml`, `pyproject.toml` or `codecov.yml`, `tests/unit/` (new or improved tests for core modules) |
| **Implementation** | 1) In `ci.yml` split coverage command: core modules (`src/serving/`, `src/quality/`, `src/processing/outbox.py`, `src/serving/api/auth/`) with `--cov-fail-under=75`; full suite (`src/`, `sdk/`) keeps `--cov-fail-under=60`. 2) Use `pytest -m "not integration"` for the 75% gate to keep it fast. 3) Identify lowest-coverage core files via `pytest --cov-report=term-missing` and add targeted unit tests. |
| **Verification** | `pytest tests/unit/ tests/property/ --cov=src/serving --cov=src/quality --cov-fail-under=75` passes locally. `pytest tests/unit/ tests/property/ --cov=src --cov=sdk --cov-fail-under=60` still passes. |
| **Rollback** | `git checkout -- .github/workflows/ci.yml codecov.yml` and delete added tests. |
| **PR scope** | **Split into 2 PRs:** (a) `ci: raise core module coverage gate to 75%`; (b) `test: add unit tests for under-covered core modules` — so CI gating changes are isolated from test additions. |

---

### M9 — No immutable audit log
**Category:** needs architecture decision + local implementation now

| | Detail |
|---|---|
| **Files touched** | `src/serving/api/auth/middleware.py` (dual-write hook), `src/processing/outbox.py` or new `src/processing/audit_publisher.py`, `config/kafka_topics.yaml` or `helm/kafka-connect/` (topic definition), `tests/integration/test_audit_immutable.py` (new), `docs/security-audit.md` |
| **Implementation** | 1) Add an async non-blocking Kafka producer call in the auth middleware after logging to DuckDB: publish to topic `api-usage.audit.v1` with schema `{tenant_id, api_key_id, endpoint, timestamp, correlation_id, ip_hash}`. 2) If Kafka is unavailable, log a warning but do **not** fail the request (fail-open for observability). 3) Define topic in Helm/kafka-connect with `retention.bytes=-1`, `retention.ms=-1`, `cleanup.policy=compact` (or `delete` with very long retention depending on compliance target). 4) Add integration test with Testcontainers Kafka verifying message lands in topic. 5) Document: "Immutable audit trail is Kafka-backed; DuckDB `api_usage` remains operational cache." |
| **Verification** | `pytest tests/integration/test_audit_immutable.py -v` passes. `pytest tests/unit/` still passes (mock Kafka producer in unit tests). `mypy src/processing/audit_publisher.py` passes. |
| **Rollback** | `git checkout -- src/serving/api/auth/middleware.py` and delete new files. Revert docs. |
| **PR scope** | **Split into 2 PRs:** (a) `feat: Kafka immutable audit topic + publisher`; (b) `test: integration test for audit immutability` |

---

## 🟢 Low

### L6 — No SBOM generation
**Category:** can fix locally now

| | Detail |
|---|---|
| **Files touched** | `.github/workflows/security.yml`, `scripts/generate_sbom.py` (new), `docs/security-audit.md` |
| **Implementation** | 1) Add job `sbom` to `security.yml` using `anchore/syft-action@v0.20.0` (or `syft` CLI install) against the built `agentflow-api:security-scan` image. 2) Output SPDX JSON as artifact (`sbom-spdx.json`). 3) Also generate CycloneDX from `requirements.txt` + `pyproject.toml` via `syft dir:.`. 4) Add `scripts/generate_sbom.py` wrapper for local runs. 5) Document artifact retention policy (e.g., 90 days). |
| **Verification** | `act -j sbom -W .github/workflows/security.yml --dryrun` or local `syft dir:. -o spdx-json=/tmp/local-sbom.json` succeeds. File is valid JSON with packages listed. |
| **Rollback** | `git checkout -- .github/workflows/security.yml` and delete `scripts/generate_sbom.py`. |
| **PR scope** | **Single PR:** `ci+sec: add Syft SBOM generation to security workflow` |

---

### L7 — No signed container images
**Category:** can fix locally now (CI job addition) + needs external owner for key/cosign setup

| | Detail |
|---|---|
| **Files touched** | `.github/workflows/publish-pypi.yml` (add image signing step), `.github/workflows/security.yml` (add verify step), `docs/runbook.md` (cosign keyless/keyed setup), `scripts/sign_image.sh` (new wrapper) |
| **Implementation** | 1) After `docker build` in `publish-pypi.yml`, add `cosign sign --yes agentflow-api:${RELEASE_VERSION}` using GitHub OIDC (keyless). 2) Save signature artifact `.sig` and certificate `.cert` to GitHub release assets. 3) In `security.yml`, add optional `cosign verify` step against public key / OIDC issuer. 4) Document: operator must enable GitHub OIDC for cosign or supply a `COSIGN_PUBLIC_KEY` secret. **No push to registry assumed; signing happens on already-built image.** |
| **Verification** | `act -j publish -W .github/workflows/publish-pypi.yml --dryrun` validates YAML. Local `cosign sign --dry-run` can test syntax if cosign CLI is installed. |
| **Rollback** | `git checkout -- .github/workflows/publish-pypi.yml .github/workflows/security.yml` and delete wrapper. |
| **PR scope** | **Single PR:** `ci: cosign container image signing and verification` |

---

## Commit / PR Grouping Recommendation

| PR # | Theme | Items | Why together |
|------|-------|-------|--------------|
| 1 | Lint-tool hardening | M1 + M2 | Same toolchain, same review domain (SAST tuning) |
| 2 | Type safety | M3 | Isolated mypy changes; easy to bisect |
| 3 | Helm security refactor | M4 + H3 (Helm part) | Both touch `helm/agentflow/` values/templates |
| 4 | CI / release hardening | M7 + L6 + L7 | All are GitHub Actions changes; DevOps reviewer |
| 5 | Coverage & tests | M8 (gate) + M8 (tests) | Split into 2 commits inside 1 PR, or 2 PRs as noted |
| 6 | Audit infrastructure | M9 | Kafka topic + middleware change; needs streaming reviewer |
| 7 | Terraform enablement | H4 | Infrastructure-only; no application code |
| 8 | DuckDB encryption | H6 | Small, isolated backend change |
| 9 | Documentation / external gates | H5 + H3 (ADR) | No functional code; compliance / PM reviewer |

---

## External Gates That Stay Open Until Owner Evidence

| Item | What is needed from owner |
|------|---------------------------|
| H4 | `AWS_TERRAFORM_ROLE_ARN` created in AWS IAM + OIDC provider added to account; `staging.tfvars` and `production.tfvars` populated and stored in GitHub Environment secrets. |
| H5 | Signed pentest report (PDF) or vendor attestation uploaded to `docs/compliance/evidence/YYYY-MM-DD-pentest.pdf` with SHA-256 in `docs/security-audit.md`. |
| H3 (full resolution) | Production ClickHouse backend provisioned and validated under load; only then remove DuckDB from prod Helm overlay. |
| H6 (full compliance) | Operator supplies `AGENTFLOW_DUCKDB_ENCRYPTION_KEY` in K8s secret and documents key rotation in KMS/Vault. |
| L7 (full trust) | Cosign public key or OIDC issuer configured in downstream consumers so `cosign verify` is actionable. |

---

*Generated for Task 3 — Minimal Safe Implementation Plan.*
*Date: 2026-05-05*
