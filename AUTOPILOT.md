# Autopilot

This repository is suitable for a guarded local autopilot only. The runner must
keep planning, execution, verification, and commits local; it must never deploy,
read secrets, or run paid/external production actions. Human-agent autonomous
sessions have standing authorization to run ordinary `git push origin main`
after the push gates below are green.

## Applicability Verdict

Status: READY_WITH_GUARDRAILS

Runtime:
- Planner: Codex via `codex` CLI by default
- Optional planner modes: `-Planner auto` for `pi` then Codex fallback, `-Planner pi` for forced `pi`
- Executor: Codex via `codex` CLI
- Runner: `scripts/autopilot.ps1`
- Scheduled task: `AgentFlow Local Autopilot`, installed as `-Planner codex -ExitZeroOnBlocked -Commit`
- Local host policy: this Windows workstation is no-Docker; do not start Docker Desktop or Docker-backed gates here because Docker can hang local processes.

## Mission Source Order

1. `AGENT_STATE.md`
2. `BACKLOG.md`
3. `.autopilot/NEXT_TASK.md`
4. `README.md`, `CONTRIBUTING.md`, and `docs/`
5. Git branch, HEAD, and working tree status

When chat context is compacted, stale, contradictory, or incomplete, rebuild
from these durable files and current git state. Do not ask the operator for a
recap while the repository contains enough evidence to continue.

See `docs/operations/autonomous-compact-safe-process.md` for the compact-safe
autonomous process.

## Roles

### Planner

The runner defaults to the Codex planner. The optional `pi` planner remains available through `-Planner auto` or `-Planner pi`, but the scheduled task uses `-Planner codex` to avoid repeated startup failures when `pi` has no local API key.

The planner chooses exactly one bounded task and writes only:
- `.autopilot/NEXT_TASK.md`
- `.autopilot/allowed-paths.txt`
- `.autopilot/commit-message.txt`
- `.autopilot/BLOCKED.md`, when no safe task exists

The planner may choose product-code work only when the task is bounded, has explicit allowed paths, requires tests before behavior changes, and can be verified locally without external services or Docker on this host. It must not choose documentation churn only to keep the autopilot moving, and it must not choose handoff refresh solely to update HEAD, branch-ahead counts, timestamps, latest commits, or tracked-file counts after local autopilot commits.

Before choosing a task, the planner must compare the candidate with the most
recent completed or blocked item family in durable state. It must not repeat the
same family unless there is new owner-provided evidence, a fresh failed
verification with a local diagnostic path, current dirty WIP to close, or a
distinct named atomic item with different verification.

### Codex Executor

The executor reads `.autopilot/NEXT_TASK.md`, changes only the paths listed in `.autopilot/allowed-paths.txt`, runs relevant verification, and updates `AGENT_STATE.md` and `BACKLOG.md` only when those files are explicitly allowed for the task.

The executor must not commit, push, deploy, print secrets, or use external paid services.

### Local Runner

The runner is the gatekeeper. It:
- creates a lock before work starts;
- respects `.autopilot/PAUSE`;
- stops on `.autopilot/BLOCKED.md`;
- runs the selected planner to produce the next task;
- runs `codex exec` for execution;
- validates changed files against `.autopilot/allowed-paths.txt`;
- runs gates that exist locally;
- commits only with explicit pathspec when started with `-Commit`;
- never runs `git add .`, `git add -A`, `git push`, deploy commands, or destructive cleanup.

When started with `-ExitZeroOnBlocked`, the runner exits with code `0` for an existing or newly planned `.autopilot/BLOCKED.md`. This is the scheduled-task mode: "no safe local task" is recorded as runtime state instead of reported as a recurring task failure.

## Hard Stops

Stop and write `.autopilot/BLOCKED.md` when:
- the working tree is dirty before a non-dry run;
- `.autopilot/PAUSE` exists;
- `.autopilot/BLOCKED.md` already exists;
- the selected planner, `codex`, or `git` is unavailable;
- the planner does not create `NEXT_TASK.md` and `allowed-paths.txt`;
- any changed file is outside `.autopilot/allowed-paths.txt`;
- any required gate fails;
- the task requires Docker on this Windows workstation;
- the task requires secrets, deploys, production data, paid APIs, external accounts, or manual credentials.

A true external blocker is not a reason to keep planning the same task. The
runner should record the non-secret blocker evidence once, exit cleanly in
scheduled mode, and wait for new evidence or a different bounded local task.

## Autonomous No-Prompt Mode

When the latest operator instruction requests autonomous work, the local agent
owns tactical decisions and should not ask what to do next while a safe local
candidate exists.

The autonomous loop is:

1. Refresh git status and durable handoff state.
2. Close current dirty WIP first.
3. Select the highest-confidence safe atomic item.
4. Make the smallest scoped edit.
5. Run relevant no-Docker verification.
6. Create a local commit when the item is verified and the dirty set is scoped.
7. Continue to the next safe candidate.

Do not stop merely because a local commit was created, a handoff file was
updated, or a status report was written.

## Standing Push Authorization

The operator has authorized the human-agent autonomous session to run ordinary
`git push origin main` without asking again when all of these gates are true:

- `git status --short --branch --untracked-files=no` shows a clean tracked
  worktree and no unexpected branch divergence;
- `git diff --check` passes;
- the commits being pushed were created or reviewed in this autonomous session;
- no force-push, tag push, release, deploy, package publish, scheduler/env
  change, Terraform apply, secret/account operation, or destructive git command
  is involved.

This standing authorization does not allow `git push --force`, pushing other
branches or tags, deploy/release/publish actions, Terraform apply, or any
operation that needs external credentials or secrets. The scheduled autopilot
runner still does not push; this applies to the interactive autonomous agent.

## Admin And External Delegation

If an item requires repository admin rights, cloud/account access, production
evidence, customer evidence, external pen-test evidence, publishing, deploys, or
Terraform apply, delegate to an available admin-capable agent or tool with exact
scope and forbidden operations. Integrate only verified non-secret facts.

If no real external evidence exists, keep the gate blocked. Do not invent owner
inputs, enable disabled workflows, create placeholder secrets, or convert
documentation-complete gates into completed production claims.

## Required Gates

The runner always runs:
- `git diff --check`

When relevant commands are available and changed paths require them, it also runs:
- `$env:SKIP_DOCKER_TESTS='1'; python -m pytest -p no:schemathesis`
- `python -m ruff check <changed-python-files>`
- `python -m ruff format --check <changed-python-files>`
- `python -m mypy src/`
- `npm run typecheck`
- `npm run test:unit`
- `npm run build`

Full pytest without `SKIP_DOCKER_TESTS`, Docker build, Docker compose, chaos,
kind, and Helm live gates are Mac/CI evidence on this workstation. Do not start
Docker Desktop locally to satisfy an autopilot gate.

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
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -Planner codex -Commit
```

Scheduled-task equivalent, where a planner blocker is a clean no-work result:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -Planner codex -ExitZeroOnBlocked -Commit
```

Install the opt-in scheduled task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1 -Install -Commit -Planner codex
```
