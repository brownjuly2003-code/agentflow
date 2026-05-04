# Guarded Autopilot Pause And Blocked Recovery

Use this note when a guarded autopilot run is paused or blocked. The
`.autopilot/` directory is ignored local runtime state and should not be
committed.

## Inspect State

Check the git state and local autopilot state before changing runtime files:

```powershell
git status --short --branch
Get-ChildItem .autopilot -Force
Get-Content .autopilot\BLOCKED.md
```

If `BLOCKED.md` does not exist, the last command will fail; that is expected.
Do not remove PAUSE or BLOCKED files until the current state is understood.

## Resume After PAUSE

`PAUSE` is an operator stop flag. A dry run reports whether a non-dry run would
exit before work:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

After confirming the run should resume, remove only the pause flag:

```powershell
Remove-Item .autopilot\PAUSE
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

## Recover After BLOCKED

`BLOCKED.md` records a blocker and the next manual action. Resolve the stated
cause first, then rerun the local preflight:

```powershell
git status --short --branch
git diff --check
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

Remove `BLOCKED.md` only after the blocker has been resolved and the preflight
is clean for the intended next action:

```powershell
Remove-Item .autopilot\BLOCKED.md
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
```

## Forbidden Operations

Do not use PAUSE or BLOCKED recovery to bypass deploy, publish, Terraform,
secret, scheduler install, or external account restrictions. If recovery needs
one of those operations, leave `BLOCKED.md` in place and record the blocker in
`AGENT_STATE.md` or `BACKLOG.md`.
