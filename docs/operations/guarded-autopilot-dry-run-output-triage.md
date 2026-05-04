# Guarded Autopilot Dry-Run Output Triage

Use this note to interpret `scripts/autopilot.ps1 -DryRun` before a guarded
non-dry autopilot run. Dry-run output is preflight evidence only; it does not
authorize execution, cleanup, commit, push, deploy, publish, Terraform, secret,
scheduler, or external account operations.

## Run The Preflight

Start from the repo root:

```powershell
git status --short --branch
git diff --check
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

The expected healthy dry-run path reports:

```text
Dry-run: PAUSE protocol OK.
Dry-run: BLOCKED protocol OK.
Dry-run: allowed-paths protocol requires .autopilot/allowed-paths.txt before execution.
Dry-run: pi and codex commands are available.
```

The `allowed-paths` line is a reminder, not permission to run without a bounded
scope file.

## PAUSE Report

If dry-run reports `PAUSE exists; non-dry run would exit before work`, inspect
the flag without changing it:

```powershell
Test-Path .autopilot\PAUSE
Get-Item .autopilot\PAUSE -ErrorAction SilentlyContinue | Format-List FullName,Length,LastWriteTime
git status --short --branch
```

Do not remove `PAUSE` until the operator has confirmed the run should resume.

## BLOCKED Report

If dry-run reports `BLOCKED.md exists; non-dry run would stop`, inspect the
blocker:

```powershell
Test-Path .autopilot\BLOCKED.md
Get-Content .autopilot\BLOCKED.md
git status --short --branch
git diff --check
```

Resolve the stated blocker first. Do not delete `BLOCKED.md` just to make
dry-run output cleaner.

## Missing Allowed Paths

If dry-run only reports that `.autopilot/allowed-paths.txt` is required, inspect
whether the scope file exists and what task it belongs to:

```powershell
Test-Path .autopilot\allowed-paths.txt
Get-Content .autopilot\NEXT_TASK.md
Get-Content .autopilot\allowed-paths.txt
```

If the file is missing, create it only as part of a bounded backlog item using
the allowed-paths bootstrap note. Do not infer a scope from the current diff.

## Dirty Worktree

Dry-run prints `RUN: git status --short -uno`. Treat any tracked output there
as a stop signal before non-dry execution:

```powershell
git status --short --branch
git diff --name-status
git diff --stat
git diff --check
git ls-files --others --exclude-standard
```

Use the dirty-worktree preflight note to decide whether the changes belong to
the current task. Do not clean, revert, or delete files during triage.

## Missing Local Commands

If dry-run reports a missing command such as `Required command is unavailable:
pi` or `Required command is unavailable: codex`, verify availability without
installing or changing tools:

```powershell
Get-Command git -ErrorAction SilentlyContinue
Get-Command pi -ErrorAction SilentlyContinue
Get-Command codex -ErrorAction SilentlyContinue
Get-Content .autopilot\BLOCKED.md
```

Record the blocker in `AGENT_STATE.md` or `BACKLOG.md`. Installation,
authentication, npm, package ownership, or external account work requires an
explicit separate operator decision.

## Forbidden Operations

Do not use dry-run triage to justify cleanup, revert, commit, push, deploy,
publish, Terraform, secret, scheduler install, external account, paid service,
or production data operations.
