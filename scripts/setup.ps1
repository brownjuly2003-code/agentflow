#!/usr/bin/env pwsh
$originalErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    Write-Host "=== AgentFlow Setup ==="

    if ($PSVersionTable.PSVersion.Major -lt 7) {
        throw "PowerShell 7+ is required."
    }

    $pythonExe = $null

    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $candidate = (& py -3.11 -c "import sys; print(sys.executable)").Trim()
            if ($LASTEXITCODE -eq 0 -and $candidate) {
                $pythonExe = $candidate
            }
        } catch {
        }
    }

    if (-not $pythonExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
        $version = (& python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
        if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]"3.11.0") {
            $pythonExe = "python"
        }
    }

    if (-not $pythonExe) {
        throw "Python 3.11+ is required."
    }

    $version = (& $pythonExe -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    Write-Host "Using Python $version"

    & $pythonExe -m venv .venv

    $venvPath = (Resolve-Path ".\.venv").Path
    $env:VIRTUAL_ENV = $venvPath
    $env:PATH = "$venvPath\Scripts;$env:PATH"

    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"
    python -m pip install -e ./sdk

    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
    }

    python -c "from src.serving.api.main import app; print('OK')"

    if ($MyInvocation.InvocationName -eq ".") {
        Write-Host "=== Setup complete. Run: make demo ==="
    } else {
        Write-Host "=== Setup complete. Run '. .\scripts\setup.ps1' before 'make demo' to keep the virtualenv active. ==="
    }
} finally {
    $ErrorActionPreference = $originalErrorActionPreference
    Pop-Location
}
