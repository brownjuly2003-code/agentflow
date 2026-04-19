#!/usr/bin/env pwsh
$originalErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

$composeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.flink.yml")

try {
    Write-Host "Starting AgentFlow Flink locally via Docker..."
    docker compose @composeArgs up --build -d flink-job-runner
    Write-Host "Flink Web UI: http://localhost:8081"
    Write-Host "Following flink-job-runner logs. Press Ctrl+C to stop and tear down the stack."
    docker compose @composeArgs logs -f flink-job-runner
} finally {
    docker compose @composeArgs down
    Pop-Location
    $ErrorActionPreference = $originalErrorActionPreference
}
