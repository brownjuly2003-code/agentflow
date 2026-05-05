# Agent State

Updated: 2026-05-06

## Current Project State

- Project: AgentFlow, a Python 3.11 real-time data platform with FastAPI serving, ingestion/processing pipelines, Python SDK, TypeScript SDK, Docker, Helm, Kubernetes, and Terraform support.
- Branch: `main`
- Backlog correction base HEAD: `3080275`
- Current resume HEAD: `afbe643`
- Git status at resume: clean for tracked files on `main`, `main...origin/main [ahead 23]`; full status still reports expected access-denied warnings for old local temp directories.
- Current expected worktree changes after commit `afbe643`: none.
- File count: `git ls-files` reports 701 tracked files. Frontend bundle size, build artifact size, and i18n key count are not applicable to this backend/security/coverage task.

## Available Runtime

- pi CLI: available at `C:\Users\uedom\AppData\Roaming\npm\pi.ps1`
- codex CLI: available at `C:\Users\uedom\AppData\Roaming\npm\codex.ps1`
- Runner: `scripts/autopilot.ps1`
- Scheduler: opt-in only through `scripts/install-autopilot-task.ps1`; preview without `-Install` must not modify scheduler state.

## Operating Mode

Status: READY_WITH_GUARDRAILS

The autopilot handoff files are project artifacts. `.autopilot/` is local runtime state and remains ignored. Do not run deploys, Terraform apply, production scripts, secret rotation, package publishing, paid external API calls, or live account operations.

The 2026-05-05 closeout was interrupted by an explicit audit-remediation request. Commit `adb9c8e` records the first five locally verifiable Kimi audit fixes, Codex+Kimi synthesis under `res/codex/`, M1/M2 SQL static-analysis gate narrowing, L6 SBOM artifact generation, M7 staging rollback safety, and the first narrow M3 mypy strict slice for `src.quality.validators.*`. Commit `afbe643` records the M8 scoped validators coverage gate. Tasks 18-22 stay blocked until real owner-provided evidence is supplied.

## Last Verified Gates

- Manual release-readiness sync verification on 2026-05-04:
  - `git rev-parse --short HEAD`: `3f88d74` at sync start.
  - `git diff --check`: passed.
  - `python -m pytest tests/unit -p no:schemathesis`: passed with 456 tests in 101.39s after the live-doc consistency updates.
  - Stale live-doc search excluding `docs/plans/codex-archive/**` and dated audit snapshots: only the guarded-autopilot example pattern remains.
  - `scripts/autopilot.ps1`: intentionally not run for the manual no-autopilot continuation.
- External gate evidence intake was completed after the manual continuation note:
  - `b8d2159`: added `docs/operations/external-gate-evidence-intake.md` and linked it from release docs.
  - `001694b`: added the project-local Pi skill at `.pi/skills/external-gate-evidence-intake`.
  - The intake checklist is documentation/workflow guidance only; it does not close AWS, production CDC, PMF/pricing, production benchmark, pen-test, or npm-token gates without real owner-provided evidence.
- Manual no-autopilot resume verification on 2026-05-04:
  - `git rev-parse --short HEAD`: `001694b`.
  - `git diff --check`: passed.
  - `git status --short --untracked-files=no`: expected manual docs/state changes only.
  - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-manual-continue-basetemp -o cache_dir=.tmp\codex-manual-continue-cache`: passed with 755 passed, 4 skipped, and 104 warnings.
  - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
  - `cd sdk-ts; npm run typecheck`: passed.
  - `powershell -ExecutionPolicy Bypass -File scripts\autopilot.ps1 -DryRun`: passed before the explicit no-autopilot continuation request; do not use autopilot for the current manual continuation.
- Manual access triage for backlog tasks 18-22 on 2026-05-04:
  - Task 18 AWS OIDC: GitHub CLI is authenticated for repository inspection; AWS CLI and Terraform CLI are not available in `PATH`; `AWS_REGION` is the only repo variable; Terraform workflow jobs remain `if: false`; real tfvars are absent.
  - Task 19 production CDC: no source owner, secret owner, source endpoint, table scope, private network path, Kubernetes Secret owner, monitoring owner, or rollback owner was available; no production connector was touched.
  - Task 20 PMF/pricing: no approved outbound account/session, warm intro thread, CRM/calendar artifact, interview evidence, pricing/WTP artifact, LOI, invoice, or first-paying-customer signal was available.
  - Task 21 production benchmark: only historical local `.artifacts/benchmark/` files were found; no approved production-class host, budget, operator-run artifacts, fixture-safety confirmation, or publication approval was available.
  - Task 22 external pen-test: no third-party report, signed attestation, scope, severity summary, remediation map, retest status, or attestation owner was available; no external scanning or paid security service was run.
  - Each task handoff now includes a concise next operator packet describing the exact redacted owner-provided artifacts needed to unblock review.
  - Next-session task file written at `next-session-external-gates-operator-evidence-plan.md`.
- Manual no-autopilot evidence recheck on 2026-05-05:
  - `git rev-parse --short HEAD`: `10bc3c7`.
  - `git ls-files`: 673 tracked files.
  - `git status --short --branch`: clean tracked tree, `main...origin/main [ahead 21]`, with the known local access-denied warnings from old temp directories.
  - Task 18 AWS OIDC remains blocked: `gh variable list` reports only `AWS_REGION`; AWS CLI and Terraform CLI are not available; real staging/prod tfvars are absent.
  - Task 19 production CDC remains blocked: no approved production source owner packet or first-run evidence was available.
  - Task 20 PMF/pricing remains blocked: no real CRM/email/calendar/interview/pricing/LOI/invoice/procurement evidence was available.
  - Task 21 production benchmark remains blocked: no production-hardware artifacts or publication approval were available.
  - Task 22 external pen-test remains blocked: no third-party report or attestation packet was available.
  - Follow-up verification:
    - `git diff --check`: passed.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-continue-basetemp -o cache_dir=.tmp\codex-continue-cache`: passed with 755 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
- Kimi audit five-point local remediation on 2026-05-05:
  - Closed local audit items: Docker production install no longer uses editable root install; `.dockerignore` exists; MinIO images are pinned; Helm API image tag is `1.1.0`; request body size limit is enforced from the security policy.
  - Red/green verification: `tests/unit/test_security.py::test_request_size_limit_blocks_oversized_bodies` failed before the middleware change with `404`, then passed after implementation with `1 passed`.
  - Targeted verification:
    - `python -m pytest tests/unit/test_security.py tests/unit/test_helm_values_contract.py -p no:schemathesis --basetemp .tmp\codex-audit-targeted-basetemp -o cache_dir=.tmp\codex-audit-targeted-cache`: passed with 19 tests.
    - `docker compose config --quiet`: passed.
    - `docker build -f Dockerfile.api -t agentflow-api:audit-check .`: passed after preserving the built wheel filename for extras install.
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed.
    - `git diff --check`: passed.
  - Full verification:
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-audit-five-full-basetemp -o cache_dir=.tmp\codex-audit-five-full-cache`: passed with 756 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
- Codex+Kimi research synthesis and M1/M2 local remediation on 2026-05-05:
  - Integrated Codex artifacts under `res/codex/` with Kimi artifacts under `res/kimi/`; synthesis saved at `res/codex/codex_kimi_audit_synthesis_05_05_26.md`.
  - Closed local audit items: Ruff `S608` is no longer globally ignored, Bandit `B608` is no longer globally skipped, existing reviewed SQL construction is scoped through per-file Ruff ignores and inline Bandit `nosec B608` comments.
  - Red/green verification: `python -m pytest tests/unit/test_security_tooling_policy.py -p no:schemathesis --basetemp .tmp\codex-m1m2-policy-red-basetemp -o cache_dir=.tmp\codex-m1m2-policy-red-cache` failed before the config change, then passed after removing the global suppressions.
  - Focused verification:
    - `python -m ruff check src sdk integrations --select S608 --output-format concise`: passed.
    - `python -m ruff check src/ tests/`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-current.json`: passed with no new findings.
    - `python -m pytest tests/unit/test_bandit_diff.py tests/unit/test_security_tooling_policy.py -p no:schemathesis --basetemp .tmp\codex-m1m2-bandit-basetemp -o cache_dir=.tmp\codex-m1m2-bandit-cache`: passed with 6 tests.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 213 files already formatted.
    - `git diff --check`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`: passed with no new findings.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m1m2-final-full-basetemp -o cache_dir=.tmp\codex-m1m2-final-full-cache`: passed with 757 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
- L6 SBOM artifact generation on 2026-05-05:
  - Closed local audit item: `.github/workflows/security.yml` now generates `agentflow-api.cdx.json` in CycloneDX format from `agentflow-api:security-scan` and uploads it as `agentflow-api-sbom-cyclonedx`.
  - Red/green verification: `python -m pytest tests/unit/test_security_workflow.py -p no:schemathesis --basetemp .tmp\codex-l6-sbom-red-basetemp -o cache_dir=.tmp\codex-l6-sbom-red-cache` failed before the workflow change, then the targeted test passed after implementation.
  - Targeted verification:
    - `python -m pytest tests/unit/test_security_workflow.py -p no:schemathesis --basetemp .tmp\codex-l6-sbom-targeted-basetemp -o cache_dir=.tmp\codex-l6-sbom-targeted-cache`: passed with 1 test.
    - `python -m ruff check tests/unit/test_security_workflow.py`: passed.
    - `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/security.yml').read_text(encoding='utf-8')); print('security workflow yaml ok')"`: passed.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 214 files already formatted.
    - `python -m pytest tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-l6-final-targeted-basetemp -o cache_dir=.tmp\codex-l6-final-targeted-cache`: passed with 7 tests.
    - `python -c "import pathlib, yaml; [yaml.safe_load(path.read_text(encoding='utf-8')) for path in pathlib.Path('.github/workflows').glob('*.yml')]; print('workflow yaml ok')"`: passed.
    - `git diff --check`: passed.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-l6-final-full-basetemp -o cache_dir=.tmp\codex-l6-final-full-cache`: passed with 758 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`: passed with no new findings.
- M8 scoped validators coverage gate on 2026-05-06:
  - Closed local audit item partially: `.github/workflows/ci.yml` now runs `tests/unit/test_validators.py` with `--cov=src.quality.validators --cov-fail-under=90`; broader global coverage remains at 60% until additional modules have enough evidence.
  - Tests-first verification:
    - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-validators-cov-basetemp -o cache_dir=.tmp\codex-m8-validators-cov-cache`: failed before new tests with total coverage 84.35%.
    - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-validators-cov-green-basetemp -o cache_dir=.tmp\codex-m8-validators-cov-green-cache`: passed after new tests with total coverage 100.00%.
  - CI-gate red/green verification:
    - `python -m pytest tests/unit/test_coverage_policy.py -p no:schemathesis --basetemp .tmp\codex-m8-ci-gate-red-basetemp -o cache_dir=.tmp\codex-m8-ci-gate-red-cache`: failed before the CI gate existed.
    - `python -m pytest tests/unit/test_coverage_policy.py -p no:schemathesis --basetemp .tmp\codex-m8-ci-gate-green-basetemp -o cache_dir=.tmp\codex-m8-ci-gate-green-cache`: passed after adding the CI gate.
  - Targeted verification:
    - `python -m ruff check tests\unit\test_coverage_policy.py tests\unit\test_validators.py`: passed.
    - `python -m pytest tests/unit/test_coverage_policy.py tests/unit/test_validators.py -p no:schemathesis --basetemp .tmp\codex-m8-final-targeted-basetemp -o cache_dir=.tmp\codex-m8-final-targeted-cache`: passed with 19 tests.
    - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-final-cov-basetemp -o cache_dir=.tmp\codex-m8-final-cov-cache`: passed with total coverage 100.00%.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 217 files already formatted.
    - `python -m pytest tests/unit/test_coverage_policy.py tests/unit/test_validators.py tests/unit/test_typing_policy.py -p no:schemathesis --basetemp .tmp\codex-m8-final-combined-basetemp -o cache_dir=.tmp\codex-m8-final-combined-cache`: passed with 20 tests.
    - `python -m pytest tests/unit/test_validators.py -v --tb=short --cov=src.quality.validators --cov-report=term-missing --cov-fail-under=90 --basetemp .tmp\codex-m8-final-cov2-basetemp -o cache_dir=.tmp\codex-m8-final-cov2-cache`: passed with total coverage 100.00%.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m8-final-full-basetemp -o cache_dir=.tmp\codex-m8-final-full-cache`: passed with 767 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
- M3 first strict mypy slice on 2026-05-05:
  - Closed local audit item partially: `src.quality.validators.*` now has scoped `disallow_untyped_defs = true`; global mypy `disallow_untyped_defs` remains `false`.
  - Red/green verification: `python -m pytest tests/unit/test_typing_policy.py -p no:schemathesis --basetemp .tmp\codex-m3-typing-red-basetemp -o cache_dir=.tmp\codex-m3-typing-red-cache` failed before the scoped override, then passed after implementation.
  - Mypy verification:
    - `python -m mypy src\quality\validators\schema_validator.py --config-file pyproject.toml --disallow-untyped-defs --follow-imports=skip --no-incremental --show-error-codes`: failed before implementation with one missing return type annotation.
    - `python -m mypy src\quality\validators --config-file pyproject.toml --follow-imports=skip --no-incremental --show-error-codes`: passed after adding the scoped override and annotations. The targeted run still prints the existing unused `src.processing.flink_jobs.*` override warning because that module is outside the checked slice.
  - Targeted verification:
    - `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_validators.py -p no:schemathesis --basetemp .tmp\codex-m3-final-targeted-basetemp -o cache_dir=.tmp\codex-m3-final-targeted-cache`: passed with 13 tests.
    - `python -m ruff check src\quality\validators\schema_validator.py tests\unit\test_typing_policy.py`: passed.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 216 files already formatted.
    - `python -m mypy src\quality\validators --config-file pyproject.toml --follow-imports=skip --no-incremental --show-error-codes`: passed. The targeted run still prints the existing unused `src.processing.flink_jobs.*` override warning because that module is outside the checked slice.
    - `python -m pytest tests/unit/test_typing_policy.py tests/unit/test_validators.py tests/unit/test_staging_rollback.py tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-m3-final-combined-basetemp -o cache_dir=.tmp\codex-m3-final-combined-cache`: passed with 21 tests.
    - `git diff --check`: passed.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m3-final-full-basetemp -o cache_dir=.tmp\codex-m3-final-full-cache`: passed with 760 passed, 4 skipped, and 104 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`: passed with no new findings.
- M7 staging rollback safety on 2026-05-05:
  - Closed local audit item: `scripts/k8s_staging_up.sh` now runs `helm upgrade --install` with `--atomic` and includes `helm history "$RELEASE_NAME" --namespace "$NAMESPACE"` in failure diagnostics.
  - Red/green verification: `python -m pytest tests/unit/test_staging_rollback.py -p no:schemathesis --basetemp .tmp\codex-m7-rollback-red-basetemp -o cache_dir=.tmp\codex-m7-rollback-red-cache` failed before the script change, then the targeted test passed after implementation.
  - Targeted verification:
    - `python -m pytest tests/unit/test_staging_rollback.py -p no:schemathesis --basetemp .tmp\codex-m7-rollback-targeted-basetemp -o cache_dir=.tmp\codex-m7-rollback-targeted-cache`: passed with 1 test.
    - `python -m ruff check tests/unit/test_staging_rollback.py`: passed.
    - `bash -n scripts/k8s_staging_up.sh`: passed.
  - Final verification:
    - `python -m ruff check src/ tests/`: passed.
    - `python -m ruff format --check src/ tests/`: passed with 215 files already formatted.
    - `python -m pytest tests/unit/test_staging_rollback.py tests/unit/test_security_workflow.py tests/unit/test_security_tooling_policy.py tests/unit/test_bandit_diff.py -p no:schemathesis --basetemp .tmp\codex-m7-final-targeted-basetemp -o cache_dir=.tmp\codex-m7-final-targeted-cache`: passed with 8 tests.
    - `bash -n scripts/k8s_staging_up.sh`: passed.
    - `python -c "import pathlib, yaml; [yaml.safe_load(path.read_text(encoding='utf-8')) for path in pathlib.Path('.github/workflows').glob('*.yml')]; print('workflow yaml ok')"`: passed.
    - `git diff --check`: passed.
    - `python -m pytest -p no:schemathesis --basetemp .tmp\codex-m7-final-full-basetemp -o cache_dir=.tmp\codex-m7-final-full-cache`: passed with 759 passed, 4 skipped, and 105 warnings.
    - `cd sdk-ts; npm run test:unit`: passed with 46 tests.
    - `cd sdk-ts; npm run typecheck`: passed.
    - `python scripts\bandit_diff.py .bandit-baseline.json .tmp-security\bandit-m1m2-final.json`: passed with no new findings.
- `git status --short --branch -- docs/operations/guarded-autopilot-scheduler-opt-in-boundary.md AGENT_STATE.md BACKLOG.md`: during task 17 final check, expected changes are `AGENT_STATE.md`, `BACKLOG.md`, and `docs/operations/guarded-autopilot-scheduler-opt-in-boundary.md`.
- `git rev-parse --short HEAD`: `7900754`.
- `Get-Command pi`: available.
- `Get-Command codex`: available.
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`: passed during task 17 verification; dry-run reported the PAUSE and BLOCKED protocols OK, noted `.autopilot/allowed-paths.txt` is required before execution, confirmed `pi` and `codex` are available, and ran `git status --short -uno` plus `git diff --check`.
- `powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1`: preview passed during task 16; scheduler was not installed.
- `git diff --check`: passed during task 17 verification.
- `python -m pytest tests/unit -p no:schemathesis`: passed with 454 tests.
- `python -m ruff check src/ tests/`: passed.
- `python -m ruff format --check src/ tests/`: passed.
- `python -m pytest -p no:schemathesis`: passed with 753 passed, 4 skipped, and 104 warnings after Docker Desktop was started.
- `$env:SKIP_DOCKER_TESTS='1'; python -m pytest -p no:schemathesis`: passed with 729 passed, 28 skipped, and 104 warnings before Docker was available.
- Standalone lint/typecheck/build gates: not run separately; no frontend source was changed.
- Local verification matrix: documented in `docs/operations/local-verification-matrix.md`.
- `cd sdk-ts; npm run typecheck`: passed.
- `cd sdk-ts; npm run test:unit`: passed with 46 tests.
- `cd sdk-ts; npm run build`: passed.

## Runtime Gaps

- Integration, staging, load, publish, and Terraform workflows depend on Docker, Kubernetes, cloud credentials, external services, or GitHub secrets and are forbidden for autopilot by default.
- The runner cannot sandbox `pi` or `codex` to path-level writes before execution; it enforces allowed paths after execution and blocks commits on violations.
- Scheduler is intentionally not enabled by setup.

## Safe Scope

- Documentation under `docs/` and root markdown files.
- Unit/property tests that do not require Docker, cloud credentials, or live services.
- Local-only scripts that do not deploy, publish, rotate secrets, or delete project data.
- Small source changes when the required verification can run locally.

## Forbidden Scope

- `.github/workflows/*publish*`, `.github/workflows/terraform-apply.yml`, deployment workflows, and release publishing.
- `deploy/`, production `docker-compose` flows, `helm/`, `k8s/`, and `infrastructure/terraform/` unless the user explicitly assigns a bounded non-deploy documentation task.
- Secret files, `.env*`, API keys, tokens, recovery codes, cloud accounts, npm/PyPI publishing, and paid external API calls.
- Runtime databases, warehouses, logs, and generated artifacts.

## Next Step

Backlog tasks 0 through 17 are complete. Tasks 18 through 22 have now had a manual no-autopilot access triage. Task 18 remains blocked on external AWS account inputs after updating `docs/operations/aws-oidc-setup.md`. Task 19 remains blocked on external production CDC source decisions after updating `docs/operations/cdc-production-onboarding.md`. Task 20 remains blocked on absent real PMF outreach, interview, pricing/WTP, and first-paying-customer evidence after updating `docs/customer-discovery-tracker.md` and `docs/pricing-validation-plan.md`. Task 21 remains blocked on absent approved production-hardware access, budget, operator-run results, fixture-safety confirmation, and publication approval after updating `docs/perf/public-production-hardware-benchmark-plan.md`. Task 22 remains blocked on absent external pen-test report or attestation after updating `docs/operations/external-pen-test-attestation-handoff.md`.

The external gate evidence intake checklist is now checked in at `docs/operations/external-gate-evidence-intake.md`, with a project-local Pi skill at `.pi/skills/external-gate-evidence-intake`. No next bounded safe backlog item is currently queued. Continue only when an operator supplies real external evidence for one blocked gate or explicitly assigns another bounded local documentation/task-maintenance item. Keep work outside external systems, and do not convert blocked external gates into completed work without real operator-provided evidence.
