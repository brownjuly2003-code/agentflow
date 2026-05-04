# Agent State

Updated: 2026-05-04

## Current Project State

- Project: AgentFlow, a Python 3.11 real-time data platform with FastAPI serving, ingestion/processing pipelines, Python SDK, TypeScript SDK, Docker, Helm, Kubernetes, and Terraform support.
- Branch: `main`
- Backlog correction base HEAD: `3080275`
- Current resume HEAD: `001694b`
- Git status at resume: clean for tracked files on `main`; full status still reports expected access-denied warnings for old local temp directories.
- Current expected worktree changes for this manual plan/gate triage: `AGENT_STATE.md`, `BACKLOG.md`, `next-session-pmf-outreach-plan.md`, `next-session-external-gates-operator-evidence-plan.md`, and the task 18-22 handoff docs only.
- File count: `git ls-files` reports 672 tracked files. Frontend bundle size, build artifact size, and i18n key count are not applicable to this docs-only task.

## Available Runtime

- pi CLI: available at `C:\Users\uedom\AppData\Roaming\npm\pi.ps1`
- codex CLI: available at `C:\Users\uedom\AppData\Roaming\npm\codex.ps1`
- Runner: `scripts/autopilot.ps1`
- Scheduler: opt-in only through `scripts/install-autopilot-task.ps1`; preview without `-Install` must not modify scheduler state.

## Operating Mode

Status: READY_WITH_GUARDRAILS

The autopilot handoff files are project artifacts. `.autopilot/` is local runtime state and remains ignored. Do not run deploys, Terraform apply, production scripts, secret rotation, package publishing, paid external API calls, or live account operations.

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
