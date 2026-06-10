#Requires -Version 5.1
<#
.SYNOPSIS
    Safely start the local dashboard if not already listening.

.DESCRIPTION
    Intended for Windows Task Scheduler and manual recovery after reboot.
    Checks whether DASHBOARD_PORT (default 8765) is already bound before
    starting. Detaches from the terminal; stdout/stderr go to
    logs/dashboard_stdout.log and logs/dashboard_stderr.log.
#>
param(
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$LogsDir = Join-Path $RepoRoot "logs"
$StdoutLog = Join-Path $LogsDir "dashboard_stdout.log"
$StderrLog = Join-Path $LogsDir "dashboard_stderr.log"
$WrapperLog = Join-Path $LogsDir "dashboard_autostart.log"
$EnvFile = Join-Path $RepoRoot ".env"

function Get-DashboardPort {
    $port = 8765
    if (Test-Path $EnvFile) {
        foreach ($line in Get-Content -Path $EnvFile -ErrorAction SilentlyContinue) {
            if ($line -match '^\s*DASHBOARD_PORT\s*=\s*(\d+)\s*$') {
                $port = [int]$Matches[1]
                break
            }
        }
    }
    return $port
}

function Test-DashboardListening {
    param([int]$Port)
    $matches = netstat -ano | Select-String ":$Port\s" | Select-String "LISTENING"
    return ($null -ne $matches)
}

function Write-DashboardAutostartLog {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $WrapperLog -Value "$ts $Message" -Encoding UTF8
}

if (-not (Test-Path $PythonExe)) {
    Write-Error "venv python not found: $PythonExe"
    exit 2
}

New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

$port = Get-DashboardPort

if (Test-DashboardListening -Port $port) {
    Write-DashboardAutostartLog "SKIP: dashboard already listening on port $port"
    exit 0
}

Write-DashboardAutostartLog "Starting dashboard (python -m dashboard on port $port)"

if ($WhatIf) {
    Write-DashboardAutostartLog "WHATIF: would start $PythonExe -m dashboard in $RepoRoot"
    exit 0
}

try {
    $proc = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @("-m", "dashboard") `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru
    Write-DashboardAutostartLog "Started dashboard PID $($proc.Id)"
    exit 0
} catch {
    Write-DashboardAutostartLog "ERROR: failed to start dashboard: $_"
    exit 1
}
