# Guarded Autopilot Stop Conditions

Use this note before edits, state updates, or a guarded non-dry autopilot run.
If any stop condition is present, pause the run and report the blocker instead
of cleaning up, reverting, committing, pushing, publishing, deploying, reading
secrets, using paid APIs, installing schedulers, running Terraform, or touching
product code.

## Read-Only Stop Checks

Run from the repo root. These commands inspect local runtime and git state
without deleting, regenerating, committing, pushing, publishing, deploying, or
reading secret files:

```powershell
git status --short --branch

Test-Path .autopilot\PAUSE
if (Test-Path .autopilot\PAUSE) {
    Get-Item .autopilot\PAUSE | Select-Object FullName, LastWriteTime
}

Test-Path .autopilot\BLOCKED.md
if (Test-Path .autopilot\BLOCKED.md) {
    Get-Content .autopilot\BLOCKED.md
}

Get-Content .autopilot\NEXT_TASK.md
Get-Content .autopilot\allowed-paths.txt

git diff --name-status
git diff --stat
git diff --name-only --cached
git ls-files --others --exclude-standard
```

Stop immediately when `PAUSE` exists, `BLOCKED.md` exists, the worktree is
dirty before the task scope is understood, `NEXT_TASK.md` and the backlog item
do not match, or `.autopilot/allowed-paths.txt` is missing.

## Allowed-Path Mismatch Check

Use this read-only comparison after reading the task and allowed-paths file. It
prints changed paths that are outside the active allowed scope:

```powershell
$Allowed = Get-Content .autopilot\allowed-paths.txt | Where-Object {
    $_.Trim() -and -not $_.TrimStart().StartsWith("#")
}

$Changed = @(
    git diff --name-only
    git diff --name-only --cached
    git ls-files --others --exclude-standard
) | Sort-Object -Unique

foreach ($Path in $Changed) {
    $PathForCompare = $Path.Replace("\", "/")
    $InScope = $false

    foreach ($Scope in $Allowed) {
        $ScopeForCompare = $Scope.Trim().Replace("\", "/").TrimEnd("/")
        if (
            $PathForCompare -eq $ScopeForCompare -or
            $PathForCompare.StartsWith($ScopeForCompare + "/")
        ) {
            $InScope = $true
        }
    }

    if (-not $InScope) {
        $Path
    }
}
```

If the command prints any path, stop before edits, state updates, or non-dry
execution. Do not expand the allowed-paths file to absorb unrelated changes.

## Unexpected Change Check

For a known documentation task, inspect expected paths and then everything
outside them:

```powershell
git status --short -- docs/operations/guarded-autopilot-stop-conditions.md AGENT_STATE.md BACKLOG.md
git status --short -- . ":(exclude)docs/operations/guarded-autopilot-stop-conditions.md" ":(exclude)AGENT_STATE.md" ":(exclude)BACKLOG.md"
```

Stop when the second command reports changed files, when a shared file is
already modified by another session, or when source, tests, SDK, deployment,
Terraform, secret, generated, or runtime data files appear in a docs-only task.

## Report The Blocker

A blocker report should preserve evidence and leave the workspace untouched.
Include:

- The stop condition that fired.
- The exact read-only command that found it.
- The relevant changed paths or runtime file names.
- The next manual decision needed from the operator.

Keep the report free of secrets and account material. If the active runner
creates `.autopilot/BLOCKED.md`, record only non-secret facts there. If the
current allowed scope does not include runtime files, report the blocker without
editing `.autopilot/`, and update only allowed project handoff files when the
task explicitly permits that.

## Forbidden Operations

Do not resolve stop conditions with cleanup, revert, product-code work, live
accounts, paid APIs, Terraform, scheduler install, deploy, publish, commit, or
push operations. Those require a separate explicit operator task.
