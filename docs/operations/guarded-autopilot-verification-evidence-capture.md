# Guarded Autopilot Verification Evidence Capture

Use this note after a bounded guarded autopilot task to capture local evidence
without deleting, regenerating, committing, pushing, publishing, deploying, or
reading secrets. Capture only evidence for the current task and its allowed
paths.

## Evidence Classes

| Class | What To Capture | Status |
| --- | --- | --- |
| Required gate output | Commands listed in the task's `Required Verification` section, their exit codes, and relevant failure lines | Required before handoff |
| Advisory dry-run output | `scripts/autopilot.ps1 -DryRun` output and exit code | Required preflight evidence, not approval for non-dry execution |
| Generated logs | Runner log filenames, sizes, and timestamps under `.autopilot/logs/` | Diagnostic local runtime evidence |
| State updates | `AGENT_STATE.md` and `BACKLOG.md` edits that record completed gates and seed the next safe item | Project documentation evidence |

Dry-run output and generated logs are evidence about local readiness. They do
not authorize cleanup, revert, commit, push, deploy, publish, Terraform,
secret, scheduler install, external account, paid service, or production data
operations.

## Capture Required Gate Output

Run required gates from the repo root and keep the full console output with the
handoff. For the default guarded documentation tasks:

```powershell
git diff --check
$diffCheckExit = $LASTEXITCODE
Write-Output "git diff --check exit code: $diffCheckExit"

powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
$dryRunExit = $LASTEXITCODE
Write-Output "autopilot dry-run exit code: $dryRunExit"
```

If either exit code is nonzero, stop and record the blocker instead of
continuing to state updates or any non-dry run.

For tasks with additional local gates, run exactly the commands listed in the
task or the local verification matrix. Do not substitute broader commands that
touch deployments, package publishing, Terraform, live accounts, paid APIs, or
secret material.

## Capture Advisory Dry-Run Output

Dry-run output should be treated as advisory preflight evidence. Record the
specific lines that identify the guarded protocols:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun
Write-Output "autopilot dry-run exit code: $LASTEXITCODE"
```

Healthy dry-run evidence usually includes PAUSE and BLOCKED protocol results,
allowed-paths status, local command availability, and `git diff --check`
execution. If dry-run reports a blocker, inspect only the relevant local
runtime file named in the output.

## Capture Generated Log Metadata

Use metadata-first inspection for generated logs. This confirms that evidence
exists without printing log contents that might include sensitive command
output from a different task:

```powershell
Get-ChildItem .autopilot\logs -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 Name,Length,CreationTime,LastWriteTime
```

Read a log body only when it belongs to the current run and the task did not
execute secret-sensitive commands. Prefer the required gate console output when
the log origin is ambiguous.

## Capture State Updates

After required gates pass, record the completed task and next safe item in the
allowed project state files:

```powershell
git status --short -- docs/operations AGENT_STATE.md BACKLOG.md
git diff -- AGENT_STATE.md BACKLOG.md docs/operations
git diff --check
```

The state diff should show only the current task's documentation note and the
minimal state/backlog updates. Do not stage, commit, push, clean, or revert as
part of evidence capture unless a separate bounded operator task explicitly
allows that operation.
