# Guarded Autopilot Runtime Artifact Inventory

Use this note to inspect the local `.autopilot/` runtime inventory without
deleting, regenerating, committing, publishing, or deploying anything. The
`.autopilot/` directory is ignored local runtime state, not a project artifact.

## Project Artifacts

These files describe or implement the guarded flow and may be committed when a
bounded task explicitly allows them:

```text
AUTOPILOT.md
AGENT_STATE.md
BACKLOG.md
scripts/autopilot.ps1
scripts/install-autopilot-task.ps1
docs/operations/
```

Inspect tracked project artifacts with read-only commands:

```powershell
git status --short --branch
git ls-files AUTOPILOT.md AGENT_STATE.md BACKLOG.md scripts/autopilot.ps1 scripts/install-autopilot-task.ps1 docs/operations
```

## Local Runtime Artifacts

The runner and local operators use `.autopilot/` for handoff state, stop flags,
logs, and transient locks. These files stay local:

| Path | Role | Source |
| --- | --- | --- |
| `.autopilot/NEXT_TASK.md` | Task input for the executor | Planner or operator input |
| `.autopilot/allowed-paths.txt` | Path scope input for the runner and executor | Planner or operator input |
| `.autopilot/commit-message.txt` | Local commit message input when `-Commit` is explicitly used | Planner or operator input |
| `.autopilot/PAUSE` | Operator stop flag | Operator input |
| `.autopilot/BLOCKED.md` | Blocker report and next manual action | Generated evidence |
| `.autopilot/logs/*.log` | Runner command log and preflight evidence | Generated evidence |
| `.autopilot/autopilot.lock` | Transient in-progress run guard | Generated evidence |
| `.autopilot/planner-prompt.md` | Prompt written before planner execution | Generated runtime handoff |
| `.autopilot/executor-prompt.md` | Prompt written before executor execution | Generated runtime handoff |

Treat generated evidence as diagnostic state. Do not edit it to make a run look
clean. Resolve the underlying blocker or stale runtime condition first.

## Presence And Timestamp Inspection

Use metadata-first commands when checking runtime state:

```powershell
git status --short --branch
git check-ignore -v .autopilot
Get-ChildItem .autopilot -Force | Sort-Object Name | Select-Object Name,Mode,Length,CreationTime,LastWriteTime
```

Inspect expected handoff files without changing them:

```powershell
$runtimeFiles = @(
    ".autopilot\NEXT_TASK.md",
    ".autopilot\allowed-paths.txt",
    ".autopilot\commit-message.txt",
    ".autopilot\PAUSE",
    ".autopilot\BLOCKED.md",
    ".autopilot\autopilot.lock",
    ".autopilot\planner-prompt.md",
    ".autopilot\executor-prompt.md"
)
$runtimeFiles | ForEach-Object {
    Get-Item $_ -ErrorAction SilentlyContinue | Select-Object FullName,Length,CreationTime,LastWriteTime
}
```

Inspect recent log evidence by name and timestamp only:

```powershell
Get-ChildItem .autopilot\logs -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 Name,Length,CreationTime,LastWriteTime
```

Read file contents only after confirming the specific artifact is relevant to
the current local task. Never print secrets, tokens, credentials, recovery
codes, or live account data into these files or command output.

## Forbidden Operations

Do not use runtime inventory inspection to justify cleanup, lock deletion,
revert, commit, push, deploy, publish, Terraform, secret, scheduler install,
external account, paid service, or production data operations.
