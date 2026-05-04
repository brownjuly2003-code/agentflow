# Autopilot

This repository is suitable for a guarded local autopilot only. The runner must keep planning, execution, verification, and commits local; it must never push, deploy, read secrets, or run paid/external production actions.

## Applicability Verdict

Status: READY_WITH_GUARDRAILS

Runtime:
- Planner: pi.dev via `pi` CLI
- Executor: Codex via `codex` CLI
- Runner: `scripts/autopilot.ps1`

## Mission Source Order

1. `AGENT_STATE.md`
2. `BACKLOG.md`
3. `.autopilot/NEXT_TASK.md`
4. `README.md`, `CONTRIBUTING.md`, and `docs/`
5. Git branch, HEAD, and working tree status

## Roles

### pi.dev Planner

The planner chooses exactly one bounded task and writes only:
- `.autopilot/NEXT_TASK.md`
- `.autopilot/allowed-paths.txt`
- `.autopilot/commit-message.txt`
- `.autopilot/BLOCKED.md`, when no safe task exists

The planner must not edit product code and must not ask the user questions.

### Codex Executor

The executor reads `.autopilot/NEXT_TASK.md`, changes only the paths listed in `.autopilot/allowed-paths.txt`, runs relevant verification, and updates `AGENT_STATE.md` and `BACKLOG.md` only when those files are explicitly allowed for the task.

The executor must not commit, push, deploy, print secrets, or use external paid services.

### Local Runner

The runner is the gatekeeper. It:
- creates a lock before work starts;
- respects `.autopilot/PAUSE`;
- stops on `.autopilot/BLOCKED.md`;
- runs `pi` to produce the next task;
- runs `codex exec` for execution;
- validates changed files against `.autopilot/allowed-paths.txt`;
- runs gates that exist locally;
- commits only with explicit pathspec when started with `-Commit`;
- never runs `git add .`, `git add -A`, `git push`, deploy commands, or destructive cleanup.

## Hard Stops

Stop and write `.autopilot/BLOCKED.md` when:
- the working tree is dirty before a non-dry run;
- `.autopilot/PAUSE` exists;
- `.autopilot/BLOCKED.md` already exists;
- `pi`, `codex`, or `git` is unavailable;
- the planner does not create `NEXT_TASK.md` and `allowed-paths.txt`;
- any changed file is outside `.autopilot/allowed-paths.txt`;
- any required gate fails;
- the task requires secrets, deploys, production data, paid APIs, external accounts, or manual credentials.

## Required Gates

The runner always runs:
- `git diff --check`

When relevant commands are available and changed paths require them, it also runs:
- `python -m pytest -p no:schemathesis`
- `python -m ruff check src/ tests/`
- `python -m ruff format --check src/ tests/`
- `python -m mypy src/`
- `npm run typecheck`
- `npm run test:unit`
- `npm run build`

Missing local tools are recorded as runtime gaps in `AGENT_STATE.md` and must become backlog work before the autopilot is trusted for those areas.

## Allowed Paths Protocol

`.autopilot/allowed-paths.txt` contains one repo-relative file or directory per line. Empty lines and lines beginning with `#` are ignored.

Examples:

```text
docs/
tests/unit/test_search_index.py
src/serving/semantic_layer/search_index.py
AGENT_STATE.md
BACKLOG.md
```

A changed file is allowed only when it exactly matches an entry or is inside a listed directory.

## PAUSE And BLOCKED Protocol

Pause:

```powershell
New-Item -ItemType File .autopilot\PAUSE -Force
```

Resume:

```powershell
Remove-Item .autopilot\PAUSE
```

Blocked runs write `.autopilot/BLOCKED.md` with the reason and next manual action. Remove the file only after the cause has been handled.

## Exit Instructions

Dry-run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

One guarded run without committing:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1
```

One guarded run with explicit-path commit:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -Commit
```

Install the opt-in scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1 -Install
```
