[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Commit,
    [string]$TaskName = "AgentFlow Local Autopilot",
    [int]$FrequencyMinutes = 60,
    [string]$RepoRoot = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

$RunnerPath = Join-Path $RepoRoot "scripts\autopilot.ps1"
if (-not (Test-Path $RunnerPath)) {
    throw "Runner not found: $RunnerPath"
}

$arguments = "-ExecutionPolicy Bypass -File `"$RunnerPath`""
if ($Commit) {
    $arguments = "$arguments -Commit"
}

if (-not $Install) {
    Write-Output "Scheduler is opt-in and was not installed."
    Write-Output "Preview:"
    Write-Output "  Task name: $TaskName"
    Write-Output "  Every minutes: $FrequencyMinutes"
    Write-Output "  Command: powershell $arguments"
    Write-Output ""
    Write-Output "Install with:"
    Write-Output "  powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1 -Install"
    Write-Output ""
    Write-Output "Install with explicit-path commits enabled:"
    Write-Output "  powershell -ExecutionPolicy Bypass -File scripts/install-autopilot-task.ps1 -Install -Commit"
    exit 0
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes $FrequencyMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Guarded local AgentFlow autopilot runner. Never pushes or deploys." -Force | Out-Null

Write-Output "Installed scheduled task: $TaskName"
Write-Output "Runner: $RunnerPath"
Write-Output "Commit enabled: $Commit"
Write-Output "Disable with:"
Write-Output "  Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"
