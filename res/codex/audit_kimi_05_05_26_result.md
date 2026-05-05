# AgentFlow audit_kimi 2026-05-05 local remediation result

Date: 2026-05-05
Repo: `D:\DE_project`
Baseline: HEAD `10bc3c7`, branch `main` ahead of `origin/main` by 21 commits.

## Closed locally

1. Docker runtime no longer uses editable install:
   - `Dockerfile.api` now builds a wheel in a builder stage and installs that wheel in runtime.
   - `Dockerfile.api` now has a `/v1/health` container healthcheck.
2. Docker build context is reduced:
   - `.dockerignore` was added.
3. MinIO images are pinned:
   - `minio/minio:RELEASE.2025-09-07T16-13-09Z`
   - `minio/mc:RELEASE.2025-08-13T08-35-41Z`
4. Helm default image tag is aligned with the package version:
   - `helm/agentflow/values.yaml` uses `image.tag: "1.1.0"`.
5. Oversized request bodies are blocked:
   - `src/serving/api/security.py` returns HTTP 413 when `Content-Length` exceeds `request_size_limit_bytes`.
   - `tests/unit/test_security.py` includes the red-green regression test.
6. M1/M2 SQL static-analysis gates are narrowed:
   - Ruff no longer globally ignores `S608`.
   - Bandit no longer globally skips `B608`.
   - Existing reviewed SQL construction is covered by scoped Ruff suppressions and inline Bandit `nosec B608` comments.
   - `tests/unit/test_security_tooling_policy.py` prevents reintroducing global `S608/B608` suppressions.
7. L6 SBOM generation is added:
   - `.github/workflows/security.yml` generates `agentflow-api.cdx.json` in CycloneDX format from the already-built scan image.
   - The workflow uploads the SBOM as the `agentflow-api-sbom-cyclonedx` artifact.
   - `tests/unit/test_security_workflow.py` prevents removing the SBOM generation/upload steps.
8. M7 staging rollback safety is added:
   - `scripts/k8s_staging_up.sh` uses `helm upgrade --install --atomic --wait`.
   - Failure diagnostics now include `helm history` for the staging release.
   - `tests/unit/test_staging_rollback.py` prevents removing the atomic rollout and Helm history diagnostics.
9. M3 first strict mypy slice is added:
   - `src.quality.validators.*` now has `disallow_untyped_defs = true` in `pyproject.toml`.
   - `src/quality/validators/schema_validator.py` has the missing model-map and return annotations required by the strict slice.
   - `tests/unit/test_typing_policy.py` prevents removing the strict validators slice while keeping the global mypy gate narrow.
10. M8 scoped coverage gate is added:
   - `tests/unit/test_validators.py` now covers all `src.quality.validators` lines.
   - `.github/workflows/ci.yml` adds a scoped `src.quality.validators` coverage gate at `--cov-fail-under=90`.
   - `tests/unit/test_coverage_policy.py` prevents removing the scoped validators coverage gate.

## Updated files

- `.dockerignore`
- `Dockerfile.api`
- `docker-compose.yml`
- `helm/agentflow/values.yaml`
- `src/serving/api/security.py`
- `tests/unit/test_contract_dependencies.py`
- `tests/unit/test_security.py`
- `.bandit`
- `pyproject.toml`
- `tests/unit/test_security_tooling_policy.py`
- `.github/workflows/security.yml`
- `tests/unit/test_security_workflow.py`
- `scripts/k8s_staging_up.sh`
- `tests/unit/test_staging_rollback.py`
- `src/quality/validators/schema_validator.py`
- `tests/unit/test_typing_policy.py`
- `.github/workflows/ci.yml`
- `tests/unit/test_validators.py`
- `tests/unit/test_coverage_policy.py`
- `AGENT_STATE.md`
- `next-session-external-gates-operator-evidence-plan.md`
- `res/codex/codex_kimi_audit_synthesis_05_05_26.md`

## Verification

- Red test before implementation:
  - `python -m pytest tests/unit/test_security.py::test_request_size_limit_blocks_oversized_bodies -p no:schemathesis --basetemp .tmp\codex-audit-size-red-basetemp -o cache_dir=.tmp\codex-audit-size-red-cache`
  - Failed as expected with `404 != 413`.
- Full Python suite:
  - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-audit-five-final-basetemp -o cache_dir=.tmp\codex-audit-five-final-cache`
  - `756 passed, 4 skipped`.
- Python lint/format:
  - `python -m ruff check src/ tests/`
  - `python -m ruff format --check src/ tests/`
- SDK:
  - `cd sdk-ts; npm run test:unit` -> `46 passed`.
  - `cd sdk-ts; npm run typecheck`.
- Docker:
  - `docker build -f Dockerfile.api -t agentflow-api:audit-check .`
  - `docker compose config --quiet`.
- Diff hygiene:
  - `git diff --check`.
- M1/M2 red/green:
  - `python -m pytest tests/unit/test_security_tooling_policy.py -p no:schemathesis --basetemp .tmp\codex-m1m2-policy-red-basetemp -o cache_dir=.tmp\codex-m1m2-policy-red-cache`
  - Failed as expected while `S608` and `B608` were globally suppressed.
  - The same test passed after removing the global suppressions.
- M1/M2 focused checks:
  - `python -m ruff check src sdk integrations --select S608 --output-format concise`
  - `python -m ruff check src/ tests/`
  - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-current.json`
  - `python -m pytest tests/unit/test_bandit_diff.py tests/unit/test_security_tooling_policy.py -p no:schemathesis --basetemp .tmp\codex-m1m2-bandit-basetemp -o cache_dir=.tmp\codex-m1m2-bandit-cache`
- Final verification after Codex+Kimi synthesis and M1/M2:
  - `python -m ruff check src/ tests/`
  - `python -m ruff format --check src/ tests/`
  - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`
  - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m1m2-final-full-basetemp -o cache_dir=.tmp\codex-m1m2-final-full-cache`
  - `757 passed, 4 skipped`.
  - `cd sdk-ts; npm run test:unit` -> `46 passed`.
  - `cd sdk-ts; npm run typecheck`.
- L6 red/green:
  - `python -m pytest tests/unit/test_security_workflow.py -p no:schemathesis --basetemp .tmp\codex-l6-sbom-red-basetemp -o cache_dir=.tmp\codex-l6-sbom-red-cache`
  - Failed as expected because the Trivy job did not contain SBOM generation.
  - `python -m pytest tests/unit/test_security_workflow.py -p no:schemathesis --basetemp .tmp\codex-l6-sbom-targeted-basetemp -o cache_dir=.tmp\codex-l6-sbom-targeted-cache`
  - Passed after adding the CycloneDX SBOM and artifact steps.
- Final verification after L6:
  - `python -m ruff check src/ tests/`
  - `python -m ruff format --check src/ tests/`
  - `python -m pytest tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-l6-final-targeted-basetemp -o cache_dir=.tmp\codex-l6-final-targeted-cache`
  - `python -c "import pathlib, yaml; [yaml.safe_load(path.read_text(encoding='utf-8')) for path in pathlib.Path('.github/workflows').glob('*.yml')]; print('workflow yaml ok')"`
  - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-l6-final-full-basetemp -o cache_dir=.tmp\codex-l6-final-full-cache`
  - `758 passed, 4 skipped`.
  - `cd sdk-ts; npm run test:unit` -> `46 passed`.
  - `cd sdk-ts; npm run typecheck`.
  - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`
- M7 red/green:
  - `python -m pytest tests/unit/test_staging_rollback.py -p no:schemathesis --basetemp .tmp\codex-m7-rollback-red-basetemp -o cache_dir=.tmp\codex-m7-rollback-red-cache`
  - Failed as expected because `helm upgrade --install` did not include `--atomic`.
  - `python -m pytest tests/unit/test_staging_rollback.py -p no:schemathesis --basetemp .tmp\codex-m7-rollback-targeted-basetemp -o cache_dir=.tmp\codex-m7-rollback-targeted-cache`
  - Passed after adding `--atomic` and `helm history`.
  - `bash -n scripts/k8s_staging_up.sh`
- Final verification after M7:
  - `python -m ruff check src/ tests/`
  - `python -m ruff format --check src/ tests/`
  - `python -m pytest tests/unit/test_staging_rollback.py tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-m7-final-targeted-basetemp -o cache_dir=.tmp\codex-m7-final-targeted-cache`
  - `bash -n scripts/k8s_staging_up.sh`
  - `python -c "import pathlib, yaml; [yaml.safe_load(path.read_text(encoding='utf-8')) for path in pathlib.Path('.github/workflows').glob('*.yml')]; print('workflow yaml ok')"`
  - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m7-final-full-basetemp -o cache_dir=.tmp\codex-m7-final-full-cache`
  - `759 passed, 4 skipped`.
  - `cd sdk-ts; npm run test:unit` -> `46 passed`.
  - `cd sdk-ts; npm run typecheck`.
  - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`
- M3 red/green:
  - `python -m pytest tests/unit/test_typing_policy.py -p no:schemathesis --basetemp .tmp\codex-m3-typing-red-basetemp -o cache_dir=.tmp\codex-m3-typing-red-cache`
  - Failed as expected because `src.quality.validators.*` was not yet a strict mypy slice.
  - `python -m mypy src\quality\validators\schema_validator.py --config-file pyproject.toml --disallow-untyped-defs --follow-imports=skip --no-incremental --show-error-codes`
  - Failed before implementation with one missing return type annotation.
  - `python -m mypy src\quality\validators --config-file pyproject.toml --follow-imports=skip --no-incremental --show-error-codes`
  - Passed after adding the scoped override and annotations.
  - `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_validators.py -p no:schemathesis --basetemp .tmp\codex-m3-final-targeted-basetemp -o cache_dir=.tmp\codex-m3-final-targeted-cache`
  - Passed with 13 tests.
- Final verification after M3:
  - `python -m ruff check src/ tests/`
  - `python -m ruff format --check src/ tests/`
  - `python -m mypy src\quality\validators --config-file pyproject.toml --follow-imports=skip --no-incremental --show-error-codes`
  - `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_validators.py tests/unit/test_staging_rollback.py tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-m3-final-combined-basetemp -o cache_dir=.tmp\codex-m3-final-combined-cache`
  - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m3-final-full-basetemp -o cache_dir=.tmp\codex-m3-final-full-cache`
  - `760 passed, 4 skipped`.
  - `cd sdk-ts; npm run test:unit` -> `46 passed`.
  - `cd sdk-ts; npm run typecheck`.
  - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`
- M8 tests-first red/green:
  - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-validators-cov-basetemp -o cache_dir=.tmp\codex-m8-validators-cov-cache`
  - Failed before adding tests with total coverage `84.35%`.
  - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-validators-cov-green-basetemp -o cache_dir=.tmp\codex-m8-validators-cov-green-cache`
  - Passed after adding tests with total coverage `100.00%`.
- M8 CI-gate red/green:
  - `python -m pytest tests/unit/test_coverage_policy.py -p no:schemathesis --basetemp .tmp\codex-m8-ci-gate-red-basetemp -o cache_dir=.tmp\codex-m8-ci-gate-red-cache`
  - Failed before `.github/workflows/ci.yml` had the scoped validators coverage gate.
  - `python -m pytest tests/unit/test_coverage_policy.py -p no:schemathesis --basetemp .tmp\codex-m8-ci-gate-green-basetemp -o cache_dir=.tmp\codex-m8-ci-gate-green-cache`
  - Passed after adding the workflow gate.
  - `python -m pytest tests/unit/test_coverage_policy.py tests/unit/test_validators.py -p no:schemathesis --basetemp .tmp\codex-m8-final-targeted-basetemp -o cache_dir=.tmp\codex-m8-final-targeted-cache`
  - Passed with 19 tests.

## 2026-05-06 local gate addendum

Local code-only remediation after the original 2026-05-05 result:

- H3/M4 are closed locally for Helm render safety: default persistent DuckDB is
  single-replica, persistent multi-replica renders fail, `secrets.existingSecret`
  is supported, and default chart values no longer carry production-shaped
  API-key verifier hashes.
- H6 is closed locally as optional encryption readiness: DuckDB serving
  connections use encrypted `ATTACH` only when an operator supplies
  `AGENTFLOW_DUCKDB_ENCRYPTION_KEY` or `AGENTFLOW_DUCKDB_ENCRYPTION_KEY_FILE`.
  Defaults remain backward-compatible and unencrypted; this is not NIST,
  GDPR, HIPAA, SOC 2, or external compliance evidence.
- M9 is closed locally as append-only audit readiness: API usage can publish a
  hash-chained JSONL audit path via `AGENTFLOW_AUDIT_LOG_PATH` in addition to
  mutation-prone DuckDB analytics. External immutable retention remains
  evidence-pending.
- L7 is ready for evidence only: `.github/workflows/container-attestation.yml`
  signs and attests only an operator-supplied image digest through keyless
  GitHub/Sigstore tooling. It is not complete until a real CI run signs a
  published digest.
- H4 is improved only: `.github/workflows/terraform-apply.yml` has a manual
  `PREFLIGHT` path that checks OIDC variables, real tfvars presence, and
  `terraform init -backend=false` / `terraform validate` without apply.
- H5 is improved only: `docs/operations/security-evidence-template.md` captures
  free local scanner evidence but does not replace a third-party pen-test
  report or attestation.

Targeted red/green evidence:

- Helm H3/M4 tests failed before the chart change, then passed.
- DuckDB encryption tests failed on missing `src.serving.duckdb_connection`,
  then passed.
- Audit publisher tests failed on missing `src.serving.audit_publisher`, then
  passed.
- Container attestation and Terraform preflight workflow tests failed before
  the workflow changes, then passed.

## Still not externally closed

The remaining audit items need separate decisions or external evidence:

- H4: Terraform apply/AWS OIDC owner evidence.
- H5: external penetration test attestation.
- M8 broader global coverage raise remains intentionally deferred until more modules have enough evidence; the local validators gate is closed.
- L7: real signed published-image digest evidence.
- M9: external immutable retention evidence, if that claim is needed.

## Research prompt for the rest

```text
Исследуй оставшиеся открытые пункты audit_kimi_04_05_26.md для AgentFlow после локального remediation пакета 2026-05-05.

Контекст: уже закрыты Docker editable install/.dockerignore/healthcheck, pinned MinIO tags, Helm image tag 1.1.0, request body size middleware. Не предлагай deploy/apply/push/paid actions.

Для H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7:
1. Проверь current best practice по первичным источникам: Kubernetes/DuckDB/ClickHouse docs, GitHub Actions OIDC/Terraform docs, OWASP/ASVS, SLSA/Sigstore, Syft/Trivy, Bandit/Ruff/mypy docs.
2. Раздели каждый пункт на: can fix locally now, needs external owner/evidence, needs architecture decision, should stay documented risk.
3. Дай minimal safe implementation plan: likely files touched, verification commands, rollback.
4. Не считай external gates complete без owner-provided evidence.
5. Укажи, какие изменения стоит делать отдельными commits/PRs.
```
