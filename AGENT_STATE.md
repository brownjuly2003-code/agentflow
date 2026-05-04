# Agent State

Updated: 2026-05-04

## Current Project State

- Project: AgentFlow, a Python 3.11 real-time data platform with FastAPI serving, ingestion/processing pipelines, Python SDK, TypeScript SDK, Docker, Helm, Kubernetes, and Terraform support.
- Branch: `main`
- HEAD: `527678b`
- Git status at review: dirty. Tracked change: `.gitignore`. Untracked handoff/runtime files: `AGENT_STATE.md`, `AUTOPILOT.md`, `BACKLOG.md`, `scripts/autopilot.ps1`, and `scripts/install-autopilot-task.ps1`.
- File baseline: 622 files from `rg --files`; frontend bundle size and i18n key count are not applicable to this repo. Several old pytest/temp directories still return access-denied warnings during file scans.

## Available Runtime

- pi CLI: available at `C:\Users\uedom\AppData\Roaming\npm\pi.ps1`
- codex CLI: available at `C:\Users\uedom\AppData\Roaming\npm\codex.ps1`
- Runner: `scripts/autopilot.ps1`
- Scheduler: not installed; opt-in only through `scripts/install-autopilot-task.ps1`

## Operating Mode

Status: READY_WITH_GUARDRAILS

The autopilot handoff files are project artifacts. `.autopilot/` is local runtime state and remains ignored. Do not run deploys, Terraform apply, production scripts, secret rotation, package publishing, paid external API calls, or live account operations.

## Last Verified Gates

- `git status --short -uno`: was clean during the earlier audit, but is not current.
- `Get-Command pi`: available.
- `Get-Command codex`: available.
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`: passed.
- `powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1`: preview passed; scheduler was not installed.
- `git diff --check`: passed.
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

Backlog tasks 0 through 3 are complete in the current working tree. Keep `.autopilot/` as local runtime state, and run `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun` before any guarded non-dry run.
