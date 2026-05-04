# Agent State

Updated: 2026-05-04

## Current Project State

- Project: AgentFlow, a Python 3.11 real-time data platform with FastAPI serving, ingestion/processing pipelines, Python SDK, TypeScript SDK, Docker, Helm, Kubernetes, and Terraform support.
- Branch: `main`
- Task 12 base HEAD: `36e715b`
- Git status at task 12 start: clean for the allowed task paths on `main`; full-repo status still reports access-denied warnings for old pytest/temp directories and `C:\Users\uedom\.config\git\ignore`.
- Current expected worktree changes: `docs/operations/guarded-autopilot-handoff-refresh-checklist.md`, `AGENT_STATE.md`, and `BACKLOG.md` only, to complete backlog task 12 and seed task 13.
- File count: `rg --files` reported 634 files at task 12 start with access-denied warnings for old pytest/temp directories; `docs/operations/` contained 13 files before adding the handoff refresh checklist note. Frontend bundle size and i18n key count are not applicable to this repo.

## Available Runtime

- pi CLI: available at `C:\Users\uedom\AppData\Roaming\npm\pi.ps1`
- codex CLI: available at `C:\Users\uedom\AppData\Roaming\npm\codex.ps1`
- Runner: `scripts/autopilot.ps1`
- Scheduler: not installed; opt-in only through `scripts/install-autopilot-task.ps1`

## Operating Mode

Status: READY_WITH_GUARDRAILS

The autopilot handoff files are project artifacts. `.autopilot/` is local runtime state and remains ignored. Do not run deploys, Terraform apply, production scripts, secret rotation, package publishing, paid external API calls, or live account operations.

## Last Verified Gates

- `git status --short --branch -- docs/operations AGENT_STATE.md BACKLOG.md`: during task 12 final check, expected changes are `AGENT_STATE.md`, `BACKLOG.md`, and `docs/operations/guarded-autopilot-handoff-refresh-checklist.md`.
- `git rev-parse --short HEAD`: `36e715b`.
- `Get-Command pi`: available.
- `Get-Command codex`: available.
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`: passed during task 12 verification; dry-run reported the PAUSE and BLOCKED protocols OK, noted `.autopilot/allowed-paths.txt` is required before execution, confirmed `pi` and `codex` are available, and ran `git diff --check`.
- `powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1`: preview passed; scheduler was not installed.
- `git diff --check`: passed during task 12 verification.
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

Backlog tasks 0 through 12 are complete. Task 13 is the next bounded safe item: document guarded autopilot stop conditions. Keep `.autopilot/` as local runtime state, and run `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun` before any guarded non-dry run.
