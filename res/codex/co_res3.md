# AgentFlow audit_kimi task 3: minimal safe implementation plan

Date: 2026-05-05
Repo: `D:\DE_project`
Baseline: HEAD `10bc3c7`, `673` tracked files. Bundle size and i18n key count are not applicable to this planning artifact.

Scope: H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7 from `audit_kimi_04_05_26.md`, after the 2026-05-05 local remediation package.

Already closed/out of scope per task context: Docker editable install, `.dockerignore`, Docker healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.

Boundary: this is a local implementation plan only. It does not propose deploy, apply, push, paid procurement, live-cluster mutation, registry publication, or marking external gates complete without owner evidence.

## Global rules for every local change

- Start with a clean ownership check for the specific files in the planned change: `git status --short -- <paths>`.
- Add the failing focused test or render check before changing implementation.
- Use explicit pathspecs for any future staging/rollback; do not use broad repo reset or broad add.
- Finish each implemented local change with `git diff --check` and the smallest relevant focused gate, then run the full Python test suite if code/config changed:
  - `.venv\Scripts\python.exe -m pytest -p no:schemathesis --basetemp .tmp\codex-task3-basetemp -o cache_dir=.tmp\codex-task3-cache`
- If frontend files are touched later, also run `cd sdk-ts; npm run test:unit` and `cd sdk-ts; npm run typecheck`.

## H3 - DuckDB in K8s with RWO PVC and replicas > 1

Minimal safe implementation:
- Do not try to make DuckDB multi-writer. Make the Helm chart fail closed for unsafe DuckDB topology.
- Add an explicit serving backend chart value/env path if needed, default it to DuckDB, and reject DuckDB when `replicaCount > 1` or HPA `minReplicas > 1`.
- Keep the default DuckDB-shaped chart single-replica with HPA disabled, or require ClickHouse mode before allowing multi-replica serving.

Likely files touched:
- `helm/agentflow/values.yaml`
- `helm/agentflow/values.schema.json`
- `helm/agentflow/templates/deployment.yaml`
- `helm/agentflow/templates/hpa.yaml`
- `helm/agentflow/templates/_helpers.tpl`
- `tests/integration/test_helm_values_live_validation.py`
- `tests/integration/fixtures/helm-values-invalid.yaml`
- `k8s/staging/values-staging.yaml` only if the new schema requires an explicit backend value.

Verification commands:
- `helm lint helm/agentflow -f k8s/staging/values-staging.yaml`
- `helm template agentflow helm/agentflow -f k8s/staging/values-staging.yaml`
- Negative render check expected to fail after implementation: `helm template agentflow helm/agentflow --set replicaCount=2 --set autoscaling.enabled=true --set autoscaling.minReplicas=2`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_helm_values_live_validation.py -v -m integration --tb=short`

Rollback:
- Restore the previous Helm defaults/schema/templates only.
- No data rollback is needed if the change is limited to render-time safety checks and defaults.
- Do not claim H3 closed for production until the operator provides serving-backend and storage evidence.

## H4 - Terraform apply disabled / AWS OIDC evidence absent

Minimal safe implementation:
- Keep the apply jobs disabled until an AWS owner provides role, trust-policy, tfvars, reviewer, and first-run evidence.
- Locally, only tighten docs/preflight clarity and Terraform validation hygiene. Do not enable `terraform apply` as a code-only change.
- If modernizing the backend configuration, keep it limited to validation-compatible S3 backend syntax and document that runtime backend evidence is still external.

Likely files touched:
- `.github/workflows/terraform-apply.yml`
- `docs/operations/aws-oidc-setup.md`
- `docs/release-readiness.md`
- `next-session-external-gates-operator-evidence-plan.md`
- `infrastructure/terraform/main.tf`
- `infrastructure/terraform/environments/*.tfvars.example`

Verification commands:
- `terraform fmt -check -recursive infrastructure/terraform/`
- `cd infrastructure/terraform; terraform init -backend=false`
- `cd infrastructure/terraform; terraform validate`
- `rg -n "if: false|AWS_TERRAFORM_ROLE_ARN|tfvars|OIDC" .github/workflows/terraform-apply.yml docs infrastructure/terraform`

Rollback:
- Restore workflow guards and docs/preflight wording.
- No infrastructure rollback command is relevant because this plan must not run `terraform apply`.
- Keep H4 blocked unless owner-provided evidence is added.

## H5 - External penetration test evidence absent

Minimal safe implementation:
- No local code implementation can close this item.
- Keep the evidence handoff document blocked and only update it with owner-provided third-party evidence: tester identity, scope, test window, report/attestation, severity summary, remediation map, retest state, and evidence owner.

Likely files touched:
- `docs/operations/external-pen-test-attestation-handoff.md`
- `docs/security-audit.md`
- `docs/release-readiness.md`
- `BACKLOG.md` only if the backlog status is being synchronized.

Verification commands:
- `rg -n "pen.?test|penetration|attestation|third-party|retest|blocked" docs BACKLOG.md`
- `git diff --check`

Rollback:
- Remove any unverified attestation claims and restore the blocked status.
- Do not replace H5 with internal scanner output or source review.

## H6 - DuckDB encryption-at-rest not proven

Minimal safe implementation:
- Do not combine this with H3. First decide whether production DuckDB is allowed at all.
- If DuckDB remains allowed, add a small encrypted-connection path behind explicit config and tests, then update every production `duckdb.connect(...)` path that touches runtime serving or usage databases.
- Do not migrate existing `.duckdb` files in the same change. Treat migration/backfill as a separate operator-controlled task with backup evidence.

Likely files touched:
- `config/serving.yaml`
- `helm/agentflow/values.yaml`
- `helm/agentflow/values.schema.json`
- `helm/agentflow/templates/deployment.yaml`
- `src/serving/backends/duckdb_backend.py`
- `src/serving/db_pool.py`
- `src/serving/semantic_layer/query/engine.py`
- `src/serving/api/auth/manager.py`
- `src/serving/api/auth/middleware.py`
- `src/serving/api/auth/key_rotation.py`
- `src/serving/api/routers/admin_ui.py`
- `scripts/backup.py`
- `tests/unit/test_auth.py`
- `tests/unit/test_security.py`
- New focused unit test only if existing test files cannot cover encrypted connection behavior.

Verification commands:
- `rg -n "duckdb\.connect" src scripts tests`
- `.venv\Scripts\python.exe -m pytest tests/unit/test_auth.py tests/unit/test_security.py tests/unit/test_query_engine.py -v --tb=short`
- Local encrypted-DB inspection after the feature exists: `.venv\Scripts\python.exe -c "import duckdb; c=duckdb.connect('path-to-test-db.duckdb'); print(c.execute('select database_name, encrypted from duckdb_databases()').fetchall())"`

Rollback:
- Disable the new encryption config flag and restore the old connection path in the touched files.
- If any encrypted test database was created, delete only that generated test artifact.
- Do not overwrite or downgrade real DuckDB files without a separate backup/restore instruction.

## M1 - Ruff globally ignores `S608`

Minimal safe implementation:
- Remove `S608` from the global Ruff ignore.
- Keep only reviewed, narrow suppressions: per-file ignores for known internal SQL-builder modules or inline `# noqa: S608` with a reason where identifier sources are allowlisted/validated.
- Prefer tightening the existing SQL-builder tests before moving suppressions.

Likely files touched:
- `pyproject.toml`
- SQL construction files reported by the focused Ruff run, likely under `src/serving/backends/`, `src/serving/semantic_layer/`, `src/serving/api/routers/`, and possibly `sdk/` or `integrations/`.
- `tests/unit/test_sql_guard.py`
- `tests/unit/test_query_engine_injection.py`
- `tests/unit/test_query_engine.py`

Verification commands:
- `.venv\Scripts\python.exe -m ruff check src sdk integrations --select S608 --isolated`
- `.venv\Scripts\python.exe -m ruff check src/ tests/`
- `.venv\Scripts\python.exe -m pytest tests/unit/test_sql_guard.py tests/unit/test_query_engine_injection.py tests/unit/test_query_engine.py -v --tb=short`

Rollback:
- Restore the previous Ruff ignore and remove any incomplete local suppressions.
- If rollback is needed, keep any tests that reveal real injection risk only if they still pass.

## M2 - Bandit globally skips `B608`

Minimal safe implementation:
- Remove `B608` from `.bandit` global skips.
- Rely on inline `# nosec B608 - <reason>` only where the SQL construction is already validated by fixed allowlists, sqlglot, or trusted config.
- Normalize any existing `nosec` comments that Bandit does not parse cleanly.

Likely files touched:
- `.bandit`
- Python files with existing or new `# nosec B608` suppressions under `src/`.
- `tests/unit/test_bandit_diff.py`

Verification commands:
- `.venv\Scripts\python.exe -m bandit -r src sdk --ini .bandit --severity-level medium -f json -o .tmp-security\bandit-current.json`
- `.venv\Scripts\python.exe scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-current.json`
- `.venv\Scripts\python.exe -m pytest tests/unit/test_bandit_diff.py -v --tb=short`

Rollback:
- Restore `.bandit` and the touched `nosec` comments.
- Do not update `.bandit-baseline.json` unless the finding was reviewed and the baseline update is explicitly part of the task.

## M3 - mypy allows untyped defs

Minimal safe implementation:
- Do not flip global `disallow_untyped_defs = true` immediately.
- Add a narrow per-module strict gate for the smallest green slice, starting with `src.quality.*` or a smaller `src.serving.*` subset.
- Add annotations until the selected slice is green, then expand in later work.

Likely files touched:
- `pyproject.toml`
- `src/quality/**/*.py`
- Selected `src/serving/**/*.py` files only if they are inside the chosen strict slice.
- Focused tests for modules whose signatures changed.

Verification commands:
- `.venv\Scripts\python.exe -m mypy src\quality --config-file pyproject.toml --disallow-untyped-defs --follow-imports=skip --no-incremental --show-error-codes`
- `.venv\Scripts\python.exe -m mypy src\serving --config-file pyproject.toml --no-incremental --show-error-codes`
- `.venv\Scripts\python.exe -m pytest tests/unit tests/property -v --tb=short`

Rollback:
- Remove the new strict override or narrow it back to the last green slice.
- Revert only annotations that caused runtime behavior or typing regressions.

## M4 - Helm values contain bcrypt API-key hashes

Minimal safe implementation:
- Add chart support for an existing Kubernetes Secret or secret name reference, then make production-shaped defaults avoid checked-in verifier material.
- Keep the current staging/e2e hashes only in explicitly test-scoped values if those tests depend on them.
- Do not claim production closure until a secret owner and secret-source evidence exist.

Likely files touched:
- `helm/agentflow/values.yaml`
- `helm/agentflow/values.schema.json`
- `helm/agentflow/templates/secret.yaml`
- `helm/agentflow/templates/deployment.yaml`
- `k8s/staging/values-staging.yaml`
- `k8s/staging/values-staging.yaml.example`
- `tests/integration/test_helm_values_live_validation.py`
- `tests/unit/test_staging_values_contract.py`

Verification commands:
- `helm lint helm/agentflow -f k8s/staging/values-staging.yaml`
- `helm template agentflow helm/agentflow -f k8s/staging/values-staging.yaml`
- `helm template agentflow helm/agentflow --set secrets.existingSecret=agentflow-api-keys`
- `.venv\Scripts\python.exe -m pytest tests/unit/test_staging_values_contract.py tests/integration/test_helm_values_live_validation.py -v --tb=short`

Rollback:
- Restore inline Secret rendering and previous values schema.
- Keep the documented production risk if checked-in hashes remain.

## M7 - No rollback workflow

Minimal safe implementation:
- For the local staging path, add Helm rollback safety without creating a production deploy path.
- Prefer `helm upgrade --install --atomic --wait --timeout 5m` for the existing staging install and add failure diagnostics for `helm history`.
- If a manual rollback script is added later, keep it target-namespace scoped and dry-run documented; do not wire it to production without owner evidence.

Likely files touched:
- `scripts/k8s_staging_up.sh`
- `.github/workflows/staging-deploy.yml`
- `scripts/k8s_staging_down.sh` only if cleanup behavior must be aligned.
- A focused unit/static test file if the repo already has workflow/script contract tests for this area.

Verification commands:
- `bash -n scripts/k8s_staging_up.sh`
- `rg -n -- "--atomic|helm history|helm rollback" scripts .github/workflows`
- `helm lint helm/agentflow -f k8s/staging/values-staging.yaml`
- Optional when Docker/kind are available: `bash scripts/k8s_staging_up.sh` followed by `bash scripts/k8s_staging_down.sh`

Rollback:
- Remove the added Helm rollback flags/diagnostic steps.
- No cluster rollback command belongs in this local plan unless a test kind cluster was created by the same local verification.

## M8 - Coverage gate remains 60%

Minimal safe implementation:
- Do not raise the global floor to 75% immediately while current `coverage.xml` line-rate is about `0.623`.
- Add a scoped gate for core modules or raise the global threshold only after tests make the new threshold green.
- Keep Codecov patch coverage at 80% and document the difference between patch and total coverage gates.

Likely files touched:
- `.github/workflows/ci.yml`
- `codecov.yml`
- `pyproject.toml` only if pytest coverage options move into config.
- Test files for whichever modules are selected to lift coverage.

Verification commands:
- `.venv\Scripts\python.exe -m pytest tests/unit/ tests/property/ -v --tb=short --cov=src --cov=sdk --cov-report=xml --cov-report=term-missing --cov-fail-under=60`
- New scoped gate after implementation, for example: `.venv\Scripts\python.exe -m pytest tests/unit/ -v --tb=short --cov=src.serving --cov-report=term-missing --cov-fail-under=<green-threshold>`
- `Select-String -Path coverage.xml -Pattern 'line-rate='`

Rollback:
- Restore the previous CI coverage command and `codecov.yml`.
- Keep newly added tests if they pass and do not depend on the failed threshold change.

## M9 - No immutable audit log

Minimal safe implementation:
- Do not relabel current DuckDB `api_usage` / `api_sessions` as immutable.
- Add a separate append-only audit sink interface and keep DuckDB usage tables as operational analytics.
- Start with a disabled-by-default sink plus tests using an in-memory or mocked producer; only add Kafka topic bootstrap after the audit schema and retention decision are explicit.

Likely files touched:
- `src/serving/api/auth/middleware.py`
- `src/serving/api/auth/manager.py`
- New small audit sink module only if the existing auth module cannot stay readable.
- `config/security.yaml` or a narrow audit config file.
- `helm/agentflow/values.yaml`
- `helm/agentflow/values.schema.json`
- Kafka topic bootstrap files only after the architecture decision: likely `helm/kafka-connect/values.yaml`, `helm/kafka-connect/templates/topic-bootstrap.yaml`, and `docker-compose*.yml`.
- `tests/unit/test_auth.py`
- `tests/unit/test_security.py`

Verification commands:
- `.venv\Scripts\python.exe -m pytest tests/unit/test_auth.py tests/unit/test_security.py -v --tb=short`
- `rg -n "api_usage.audit|audit sink|api_usage|api_sessions" src config helm docker-compose*.yml tests`
- If Kafka bootstrap is added later: `helm template kafka-connect helm/kafka-connect`

Rollback:
- Disable the audit sink config first.
- Revert only the sink emission and bootstrap files; leave existing DuckDB usage logging intact.
- Do not delete audit events from any external sink as a rollback step.

## L6 - No SBOM generation

Minimal safe implementation:
- Add SBOM artifact generation to the existing security workflow, next to the current Trivy image scan.
- Generate one machine-readable artifact first, preferably CycloneDX or SPDX JSON, and upload it as a workflow artifact.
- Keep vulnerability scanning separate from SBOM generation so one does not silently replace the other.

Likely files touched:
- `.github/workflows/security.yml`
- `docs/release-readiness.md` or `docs/publication-checklist.md` only if the workflow artifact needs to be documented.
- Possibly `scripts/check_release_artifacts.py` only if SBOM artifacts are included in release artifact validation.

Verification commands:
- Local equivalent after building the scan image: `trivy image --format cyclonedx --output .tmp-security\agentflow-api.cdx.json agentflow-api:security-scan`
- `Test-Path .tmp-security\agentflow-api.cdx.json`
- `.venv\Scripts\python.exe -m json.tool .tmp-security\agentflow-api.cdx.json > $null`
- `git diff --check`

Rollback:
- Remove the SBOM generation/upload steps.
- Keep the existing Trivy SARIF scan unchanged.

## L7 - No signed container images

Minimal safe implementation:
- Do not add signing until the project decides that container images are released artifacts and names the registry/digest owner.
- If container images become release artifacts, add signing and provenance to that future publish workflow, not to the current local security scan job.
- Until then, document L7 as conditional/not-applicable-by-scope rather than closed.

Likely files touched after an owner decision:
- Future container publish workflow, likely `.github/workflows/publish-container.yml`.
- `docs/publication-checklist.md`
- `docs/release-readiness.md`
- Optional verification docs for consumers.

Verification commands after an owner decision:
- `rg -n "cosign|sigstore|attest|provenance|image digest|container" .github docs`
- Local syntax/static checks for the new workflow.
- Signature verification must be against an owner-provided image digest; without that digest, this item remains blocked.

Rollback:
- Remove the signing/provenance steps from the future container publish workflow.
- Do not remove or rewrite already-published signatures without explicit release-owner instruction.

## Minimal execution order

1. M1 and M2 together: tighten SQL static-analysis gates.
2. L6: add SBOM artifact generation to the security workflow.
3. M7: add local staging rollback safety.
4. M3 and M8: stage typing and coverage gates only at green thresholds.
5. H3, H6, M4, M9: implement only after the relevant architecture choices are explicit.
6. H4, H5, L7: keep blocked unless owner-provided external evidence or release-scope decisions arrive.
