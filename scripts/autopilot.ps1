[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Commit,
    [string]$RepoRoot = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$AutopilotDir = Join-Path $RepoRoot ".autopilot"
$LogDir = Join-Path $AutopilotDir "logs"
$LockPath = Join-Path $AutopilotDir "autopilot.lock"
$PausePath = Join-Path $AutopilotDir "PAUSE"
$BlockedPath = Join-Path $AutopilotDir "BLOCKED.md"
$NextTaskPath = Join-Path $AutopilotDir "NEXT_TASK.md"
$AllowedPathsPath = Join-Path $AutopilotDir "allowed-paths.txt"
$CommitMessagePath = Join-Path $AutopilotDir "commit-message.txt"
$PlannerPromptPath = Join-Path $AutopilotDir "planner-prompt.md"
$ExecutorPromptPath = Join-Path $AutopilotDir "executor-prompt.md"

New-Item -ItemType Directory -Path $AutopilotDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$RunId = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "$RunId.log"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format "s") $Message"
    Add-Content -Path $LogPath -Value $line
    Write-Output $Message
}

function Stop-Blocked {
    param([string]$Message)
    $body = @"
# Autopilot Blocked

Time: $(Get-Date -Format "s")

Reason:
$Message

Next action:
Resolve the blocker, verify the working tree, then remove this file before retrying.
"@
    Set-Content -Path $BlockedPath -Value $body -Encoding UTF8
    Write-Log "BLOCKED: $Message"
    exit 1
}

function Require-Command {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $cmd) {
        Stop-Blocked "Required command is unavailable: $Name"
    }
    return $cmd.Source
}

function Invoke-RepoCommand {
    param([string]$CommandLine)
    Write-Log "RUN: $CommandLine"
    Push-Location $RepoRoot
    try {
        powershell -ExecutionPolicy Bypass -Command $CommandLine
        if ($LASTEXITCODE -ne 0) {
            Stop-Blocked "Command failed with exit code ${LASTEXITCODE}: $CommandLine"
        }
    } finally {
        Pop-Location
    }
}

function Get-ChangedFiles {
    Push-Location $RepoRoot
    try {
        $lines = @(git status --porcelain=v1)
    } finally {
        Pop-Location
    }

    $files = @()
    foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.Length -lt 4) {
            continue
        }
        $path = $line.Substring(3).Trim()
        if ($path -match " -> ") {
            $parts = $path -split " -> "
            $path = $parts[$parts.Length - 1]
        }
        $files += ($path -replace "\\", "/")
    }
    return $files
}

function Read-AllowedPaths {
    if (-not (Test-Path $AllowedPathsPath)) {
        Stop-Blocked "Planner did not create .autopilot/allowed-paths.txt"
    }

    $items = @()
    foreach ($line in Get-Content $AllowedPathsPath) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
            continue
        }
        $items += (($trimmed -replace "\\", "/").TrimStart([char[]]"./").TrimEnd([char[]]"/"))
    }
    if ($items.Count -eq 0) {
        Stop-Blocked "Allowed paths file is empty."
    }
    return $items
}

function Test-PathAllowed {
    param(
        [string]$ChangedPath,
        [string[]]$AllowedPaths
    )
    $normalized = ($ChangedPath -replace "\\", "/").TrimStart([char[]]"./")
    foreach ($allowed in $AllowedPaths) {
        if ($normalized -eq $allowed -or $normalized.StartsWith("$allowed/")) {
            return $true
        }
    }
    return $false
}

function Assert-AllowedChanges {
    $allowed = Read-AllowedPaths
    $changed = @(Get-ChangedFiles)
    foreach ($file in $changed) {
        if (-not (Test-PathAllowed -ChangedPath $file -AllowedPaths $allowed)) {
            Stop-Blocked "Changed file is outside allowed paths: $file"
        }
    }
    return $changed
}

function Test-PythonModuleCommand {
    param([string]$ModuleName)
    Push-Location $RepoRoot
    try {
        python -m $ModuleName --version *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        Pop-Location
    }
}

function Run-Gates {
    param([string[]]$ChangedFiles)

    Invoke-RepoCommand "git diff --check"

    $pythonTouched = $false
    $typescriptTouched = $false
    foreach ($file in $ChangedFiles) {
        if ($file -match "^(src|tests|sdk|integrations)/" -or $file -eq "pyproject.toml" -or $file -eq "requirements.txt") {
            $pythonTouched = $true
        }
        if ($file -match "^(sdk-ts/|tests/client\.test\.ts)" -or $file -eq "package-lock.json") {
            $typescriptTouched = $true
        }
    }

    if ($pythonTouched) {
        Require-Command "python" | Out-Null
        Invoke-RepoCommand "python -m pytest -p no:schemathesis"
        if (Test-PythonModuleCommand "ruff") {
            Invoke-RepoCommand "python -m ruff check src/ tests/"
            Invoke-RepoCommand "python -m ruff format --check src/ tests/"
        } else {
            Write-Log "GAP: python -m ruff is unavailable; record this in AGENT_STATE.md."
        }
        if (Test-PythonModuleCommand "mypy") {
            Invoke-RepoCommand "python -m mypy src/"
        } else {
            Write-Log "GAP: python -m mypy is unavailable; record this in AGENT_STATE.md."
        }
    }

    if ($typescriptTouched) {
        Require-Command "npm" | Out-Null
        Invoke-RepoCommand "Push-Location sdk-ts; npm run typecheck; if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }; npm run test:unit; if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }; npm run build; exit `$LASTEXITCODE"
    }
}

function Write-PlannerPrompt {
    $prompt = @"
You are the pi.dev planner for the AgentFlow local autopilot.

Read AGENT_STATE.md, BACKLOG.md, README.md, CONTRIBUTING.md, docs, and git state.
Choose exactly one bounded safe task.

Write .autopilot/NEXT_TASK.md with:
- task title
- why this is next
- allowed files or directories
- acceptance criteria
- required verification
- commit allowed: yes/no
- suggested commit message

Also write .autopilot/allowed-paths.txt with one repo-relative allowed file or directory per line.
Also write .autopilot/commit-message.txt with one short commit message.

Hard rules:
- Do not edit product code.
- Do not ask the user anything.
- Do not read, print, or request secrets.
- Do not choose deploy, publish, Terraform apply, production DB, paid API, or external account work.
- If no safe task exists, write .autopilot/BLOCKED.md with the blocker.
"@
    Set-Content -Path $PlannerPromptPath -Value $prompt -Encoding UTF8
}

function Write-ExecutorPrompt {
    $prompt = @"
You are the Codex executor for the AgentFlow local autopilot.

Read .autopilot/NEXT_TASK.md and perform only that task.
You are not alone in the codebase; do not revert or overwrite unrelated changes.

Hard rules:
- Change only files listed in .autopilot/allowed-paths.txt.
- Write failing tests before backend behavior changes.
- Run relevant verification from NEXT_TASK.md.
- Update AGENT_STATE.md and BACKLOG.md only if those files are allowed.
- Do not commit.
- Do not push.
- Do not deploy.
- Do not read or print secrets.
- Do not run paid external services or live account operations.
- If blocked, write .autopilot/BLOCKED.md and stop.
"@
    Set-Content -Path $ExecutorPromptPath -Value $prompt -Encoding UTF8
}

function Invoke-Planner {
    Write-PlannerPrompt
    Write-Log "RUN: pi planner"
    Push-Location $RepoRoot
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & pi --mode text --print --no-session --tools read,grep,find,ls,bash,write,edit "@$PlannerPromptPath" 2>&1 | Tee-Object -FilePath $LogPath -Append
        $plannerExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
    if ($plannerExitCode -ne 0) {
        Write-Log "pi planner failed with exit code $plannerExitCode; falling back to codex planner."
        Write-Log "RUN: codex planner"
        Push-Location $RepoRoot
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            Get-Content -Raw $PlannerPromptPath | codex exec -c 'approval_policy="never"' --cd $RepoRoot --sandbox workspace-write - 2>&1 | Tee-Object -FilePath $LogPath -Append
            $plannerExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
            Pop-Location
        }
        if ($plannerExitCode -ne 0) {
            Stop-Blocked "codex planner failed with exit code $plannerExitCode"
        }
    }
    if (Test-Path $BlockedPath) {
        Write-Log "Planner wrote BLOCKED.md."
        exit 1
    }
    if (-not (Test-Path $NextTaskPath)) {
        Stop-Blocked "Planner did not create .autopilot/NEXT_TASK.md"
    }
    if (-not (Test-Path $AllowedPathsPath)) {
        Stop-Blocked "Planner did not create .autopilot/allowed-paths.txt"
    }
}

function Invoke-Executor {
    Write-ExecutorPrompt
    Write-Log "RUN: codex executor"
    Push-Location $RepoRoot
    try {
        Get-Content -Raw $ExecutorPromptPath | codex exec -c 'approval_policy="never"' --cd $RepoRoot --sandbox workspace-write -
        if ($LASTEXITCODE -ne 0) {
            Stop-Blocked "codex executor failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
    if (Test-Path $BlockedPath) {
        Write-Log "Executor wrote BLOCKED.md."
        exit 1
    }
}

function Invoke-ExplicitCommit {
    param([string[]]$ChangedFiles)

    if (-not $Commit) {
        Write-Log "Commit disabled; leaving verified changes uncommitted."
        return
    }
    if (-not (Test-Path $CommitMessagePath)) {
        Stop-Blocked "Commit requested but .autopilot/commit-message.txt is missing."
    }

    $taskText = Get-Content -Raw $NextTaskPath
    if ($taskText -notmatch "(?im)^commit allowed:\s*yes\s*$") {
        Stop-Blocked "Commit requested but NEXT_TASK.md does not say 'commit allowed: yes'."
    }

    if ($ChangedFiles.Count -eq 0) {
        Stop-Blocked "Commit requested but there are no changed files."
    }

    Push-Location $RepoRoot
    try {
        git add -- $ChangedFiles
        if ($LASTEXITCODE -ne 0) {
            Stop-Blocked "git add with explicit pathspec failed."
        }
        git diff --cached --check
        if ($LASTEXITCODE -ne 0) {
            Stop-Blocked "git diff --cached --check failed."
        }
        git commit -F $CommitMessagePath
        if ($LASTEXITCODE -ne 0) {
            Stop-Blocked "git commit failed."
        }
        Write-Log "Committed verified autopilot changes."
    } finally {
        Pop-Location
    }
}

Require-Command "git" | Out-Null
Require-Command "pi" | Out-Null
Require-Command "codex" | Out-Null

if ($DryRun) {
    Write-Log "Dry-run: repo=$RepoRoot"
    if (Test-Path $PausePath) {
        Write-Log "Dry-run: PAUSE exists; non-dry run would exit before work."
    } else {
        Write-Log "Dry-run: PAUSE protocol OK."
    }
    if (Test-Path $BlockedPath) {
        Write-Log "Dry-run: BLOCKED.md exists; non-dry run would stop."
    } else {
        Write-Log "Dry-run: BLOCKED protocol OK."
    }
    Write-Log "Dry-run: allowed-paths protocol requires .autopilot/allowed-paths.txt before execution."
    Write-Log "Dry-run: pi and codex commands are available."
    Invoke-RepoCommand "git status --short -uno"
    Invoke-RepoCommand "git diff --check"
    exit 0
}

if (Test-Path $LockPath) {
    Stop-Blocked "Lock exists: $LockPath"
}

Set-Content -Path $LockPath -Value "pid=$PID`nstarted=$(Get-Date -Format "s")" -Encoding UTF8

try {
    if (Test-Path $PausePath) {
        Write-Log "PAUSE exists; exiting without work."
        exit 0
    }
    if (Test-Path $BlockedPath) {
        Write-Log "BLOCKED.md exists; exiting without work."
        exit 1
    }

    $initialChanges = @(Get-ChangedFiles)
    if ($initialChanges.Count -gt 0) {
        Stop-Blocked "Working tree is not clean before autopilot: $($initialChanges -join ', ')"
    }

    Invoke-Planner
    $plannerChanges = @(Get-ChangedFiles)
    if ($plannerChanges.Count -gt 0) {
        Stop-Blocked "Planner changed tracked files before execution: $($plannerChanges -join ', ')"
    }

    Invoke-Executor
    $changed = @(Assert-AllowedChanges)
    Run-Gates -ChangedFiles $changed
    Invoke-ExplicitCommit -ChangedFiles $changed
    Write-Log "Autopilot run finished."
} finally {
    if (Test-Path $LockPath) {
        Remove-Item -Path $LockPath -Force
    }
}
