# Backlog

## 0. Reconcile The Autopilot Handoff State

Status: Done.

Allowed files/directories:
- `.gitignore`
- `AGENT_STATE.md`
- `AUTOPILOT.md`
- `BACKLOG.md`
- `scripts/autopilot.ps1`
- `scripts/install-autopilot-task.ps1`
- `.autopilot/`

Acceptance criteria:
- Decide whether the autopilot handoff files are project artifacts or local-only runtime state.
- If project artifacts, add only the intended files with explicit pathspecs and keep `.autopilot/` ignored as local runtime state.
- If local-only, move or remove them deliberately so `git status --short` no longer blocks guarded runs.
- Remove `.autopilot/BLOCKED.md` only after the dirty-worktree cause is resolved.

Required verification:
- `git status --short`
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No deploy, publish, secret, external account, or scheduler install commands.

## 1. Document The Local Verification Matrix

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Document which local gates are safe by default and which require Docker, cloud credentials, or external services.
- Include exact commands for unit, integration, TypeScript SDK, benchmark, and security checks.
- Keep deploy, publish, and Terraform apply flows out of the default autopilot path.

Required verification:
- `git diff --check`

Forbidden scope:
- No source code changes.
- No deploy, publish, secret, or external account commands.

## 2. Add Unit Coverage For Search Index Token Edge Cases

Status: Done.

Allowed files/directories:
- `tests/unit/`
- `src/serving/semantic_layer/search_index.py`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a failing unit test before any behavior change.
- Cover at least one edge case around token normalization or matching.
- Keep public query behavior backward compatible unless the test documents an existing bug.

Required verification:
- `python -m pytest tests/unit -p no:schemathesis`
- `python -m ruff check src/ tests/`
- `python -m ruff format --check src/ tests/`

Forbidden scope:
- No API route changes.
- No database, Docker, deploy, or benchmark changes.

## 3. Tighten TypeScript SDK Example Verification

Status: Done.

Allowed files/directories:
- `sdk-ts/`
- `tests/client.test.ts`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Improve or add a small SDK example/test that runs locally without network access.
- Preserve the published package surface.
- Do not touch npm publishing workflow or package ownership metadata.

Required verification:
- `cd sdk-ts; npm run typecheck`
- `cd sdk-ts; npm run test:unit`
- `cd sdk-ts; npm run build`

Forbidden scope:
- No `npm publish`, `npm login`, `npm token`, or package ownership changes.
- No root backend source changes unless a later task explicitly allows them.
