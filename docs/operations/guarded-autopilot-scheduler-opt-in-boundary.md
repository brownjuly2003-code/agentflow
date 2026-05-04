# Guarded Autopilot Scheduler Opt-In Boundary

Use this note when deciding whether guarded autopilot should run
continuously without an operator starting each local run. Continuous unattended
execution requires an explicit scheduler opt-in; it is not part of the default
local backlog loop.

## Local Boundary

The default guarded loop is manual and local. `scripts/autopilot.ps1 -Commit`
may create a local commit only after `.autopilot/NEXT_TASK.md` contains the
exact gate `commit allowed: yes`, required verification passes, and the runner
validates all changed files against `.autopilot/allowed-paths.txt`.

That gate does not authorize scheduler installation, credentials, secrets,
external accounts, deploy, publish, Terraform apply, cleanup, revert, push, or
product-code work. Each of those requires a separate explicit operator task.

## Read-Only Scheduler Inspection

Run these commands from the repo root to inspect whether the default scheduled
task is present without changing scheduler state:

```powershell
Get-ScheduledTask -TaskName "AgentFlow Local Autopilot" -ErrorAction SilentlyContinue | Select-Object TaskName,State,TaskPath
schtasks.exe /Query /TN "AgentFlow Local Autopilot"
```

If neither command reports an installed task, treat the scheduler as absent.
Do not create, modify, enable, disable, unregister, or repair a scheduled task
from a routine guarded-autopilot documentation task.

## Preview Only

Preview the scheduler command without installing it:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1
```

The preview omits `-Install`, so it must not install, register, update, or
modify the scheduler. It prints the task name, cadence, runner command, and
the separate install commands an operator could choose in a future explicit
task.

## Stop Before Scheduler Changes

Stop and ask for a separate explicit operator task before any action that
would change scheduler or remote state, including:

- Running `scripts/install-autopilot-task.ps1 -Install` or
  `scripts/install-autopilot-task.ps1 -Install -Commit`.
- Registering, unregistering, enabling, disabling, editing, or deleting a
  scheduled task.
- Reading, printing, rotating, or repairing credentials, secrets, tokens,
  cookies, recovery codes, account settings, or external account sessions.
- Deploying, publishing, applying Terraform, pushing, cleaning up, reverting,
  editing product code, touching production data, or calling paid services.

Preserve local evidence and keep the scheduler opt-in decision separate from
the guarded local backlog loop.
