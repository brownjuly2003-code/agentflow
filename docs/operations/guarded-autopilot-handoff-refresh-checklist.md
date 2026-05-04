# Guarded Autopilot Handoff Refresh Checklist

Use this checklist after a bounded guarded autopilot run has completed and its
required gates have passed. The goal is to align durable project handoff files
with ignored local runtime inputs without deleting, regenerating, committing,
pushing, publishing, deploying, or reading secrets.

## Compare Current Handoff Inputs

Run from the repo root. These commands read the current runtime handoff,
allowed paths, git status, and matching backlog item without changing them:

```powershell
$BacklogTaskNumber = 12

git status --short --branch
git diff --check

Get-Content .autopilot\NEXT_TASK.md
Get-Content .autopilot\allowed-paths.txt

Get-Content .autopilot\allowed-paths.txt | ForEach-Object {
    git status --short -- $_
}

Select-String -Path BACKLOG.md -Pattern "^## $BacklogTaskNumber\. " -Context 0,40
```

The task title, status, allowed paths, acceptance criteria, and required
verification in `.autopilot/NEXT_TASK.md` should match the selected backlog
item. The path list in `.autopilot/allowed-paths.txt` should match the task's
allowed files or directories, and `git status` should show only expected files
inside that scope.

To find the next ready backlog item before setting a new runtime handoff, use:

```powershell
Select-String -Path BACKLOG.md -Pattern "^## [0-9]+\.|^Status: Ready\." -Context 0,8
```

Do not edit `.autopilot/NEXT_TASK.md` or `.autopilot/allowed-paths.txt` from a
documentation-only completion task unless those paths are explicitly allowed by
the active task.

## Refresh Project State

Project state files are durable handoff artifacts:

| File | Belongs There |
| --- | --- |
| `AGENT_STATE.md` | Current operating mode, base HEAD, expected worktree changes, last verified gates, known runtime gaps, and the next safe item |
| `BACKLOG.md` | Durable task statuses, allowed paths, acceptance criteria, required verification, forbidden scope, and the next seeded backlog item |
| `docs/operations/` | Reusable local operations notes that future agents and operators can cite |

After updating project state, inspect only the intended state files and docs:

```powershell
git status --short -- AGENT_STATE.md BACKLOG.md docs/operations
git diff -- AGENT_STATE.md BACKLOG.md docs/operations
git diff --check
```

The state diff should record the completed run, required verification evidence,
and the next bounded safe task. It should not introduce product-code work,
cleanup, revert, deployment, publishing, Terraform, scheduler installation,
external account setup, paid API use, or secret handling.

## Keep Runtime State Local

`.autopilot/` is ignored runtime state. It is used by the runner and local
operators, but it is not the durable project handoff source:

| Runtime Path | Role |
| --- | --- |
| `.autopilot/NEXT_TASK.md` | Local executor task input for the current or next run |
| `.autopilot/allowed-paths.txt` | Local write-scope input for the current or next run |
| `.autopilot/commit-message.txt` | Local commit message input only when `-Commit` is explicitly allowed |
| `.autopilot/PAUSE` | Local operator stop flag |
| `.autopilot/BLOCKED.md` | Local blocker report generated when execution cannot continue |
| `.autopilot/logs/*.log` | Local runner logs and diagnostic evidence |
| `.autopilot/autopilot.lock` | Local in-progress run guard |

Treat runtime files as inputs or evidence for a local run. Do not commit them,
rewrite them to make state look clean, or delete them during a documentation
handoff refresh.

## Final Local Gates

Before handing off, run the gates required by the active task:

```powershell
git diff --check
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

If either gate fails, stop and record the blocker instead of continuing to a
non-dry run, commit, push, deploy, publish, Terraform, cleanup, revert,
scheduler install, external account, paid API, or secret operation.
