# Guarded Autopilot Log And Lock Inspection

Use this note when inspecting local guarded autopilot runtime history. The
`.autopilot/` directory is ignored local runtime state and should not be
committed.

## Recent Logs

Start with read-only inspection:

```powershell
git status --short --branch
Get-ChildItem .autopilot\logs -Force
Get-ChildItem .autopilot\logs -Force | Sort-Object LastWriteTime -Descending | Select-Object -First 10 Name,Length,LastWriteTime
```

To read the newest log without editing it:

```powershell
$latest = Get-ChildItem .autopilot\logs -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) { Get-Content $latest.FullName -Tail 80 }
```

Use more specific `Get-Content` paths only after identifying the intended log.
Do not truncate, move, delete, or regenerate logs as part of routine inspection.

## Lock Inspection

Check whether a lock exists and when it was last updated:

```powershell
Get-Date
$lock = Get-Item .autopilot\autopilot.lock -ErrorAction SilentlyContinue
if ($lock) { $lock | Format-List FullName,Length,CreationTime,LastWriteTime }
if ($lock) { Get-Content $lock.FullName }
```

If the lock content records a process id, inspect that process directly:

```powershell
Get-Process -Id <pid-from-lock> -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,StartTime
```

A lock appears stale only when the evidence lines up: the lock timestamp is
older than the expected run window, recent logs show no active progress, and no
matching local process is still running. Treat this as an operator judgment, not
as proof that removal is safe.

## Manual Decision Only

Lock removal is a manual operator decision. Routine autopilot documentation
tasks must not automate lock deletion, add cleanup scripts, or remove
`.autopilot/autopilot.lock` just because it appears old. Record the evidence in
`AGENT_STATE.md` or `BACKLOG.md` and let the operator decide the next action.

## Forbidden Operations

Do not use log or lock inspection to justify cleanup, lock deletion, revert,
commit, push, deploy, publish, Terraform, secret, scheduler install, or external
account operations.
