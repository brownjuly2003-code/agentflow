# Agent State

Updated: 2026-05-04

## Current Project State

- Project: AgentFlow, a Python 3.11 real-time data platform with FastAPI serving, ingestion/processing pipelines, Python SDK, TypeScript SDK, Docker, Helm, Kubernetes, and Terraform support.
- Branch: `main`
- Post-release backlog seeding base HEAD: `99ec9c4`
- Git status at backlog seeding start: clean for tracked files on `main`; full status still reports expected access-denied warnings for old local temp directories.
- Current expected worktree changes for this backlog-seeding task: `AGENT_STATE.md` and `BACKLOG.md` only.
- File count: `git ls-files` reports 667 tracked files. Frontend bundle size, build artifact size, and i18n key count are not applicable to this docs-only task.

## Available Runtime

- pi CLI: available at `C:\Users\uedom\AppData\Roaming\npm\pi.ps1`
- codex CLI: available at `C:\Users\uedom\AppData\Roaming\npm\codex.ps1`
- Runner: `scripts/autopilot.ps1`
- Scheduler: opt-in only through `scripts/install-autopilot-task.ps1`; preview without `-Install` must not modify scheduler state.

## Operating Mode

Status: READY_WITH_GUARDRAILS

The autopilot handoff files are project artifacts. `.autopilot/` is local runtime state and remains ignored. Do not run deploys, Terraform apply, production scripts, secret rotation, package publishing, paid external API calls, or live account operations.

## Last Verified Gates

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

Backlog tasks 0 through 17 are complete. Tasks 18 through 22 now seed the remaining project-level post-release external gates. The next bounded safe backlog item is task 18, "Prepare AWS OIDC Terraform Apply Readiness Handoff."

For task 18, guarded autopilot may only prepare documentation/backlog/state handoff updates under the task's allowed paths. If the external AWS role ARN, real environment tfvars, and explicit operator approval are still absent, mark task 18 blocked instead of enabling or running Terraform. Keep `.autopilot/` as local runtime state, and run `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun` before any guarded non-dry run.
