#Requires -Version 5.1
<#
.SYNOPSIS
    Safely start TradeBot if not already running (singleton-aware).

.DESCRIPTION
    Intended for Windows Task Scheduler and manual recovery after reboot.
    Checks tradebot.lock via scripts/is_tradebot_running.py (same PID logic as
    bot.singleton). Removes stale locks when the recorded PID is dead.
    Detaches from the terminal; stdout/stderr go to logs/bot_stdout.log and
    logs/bot_stderr.log.
#>
param(
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LockFile = Join-Path $RepoRoot "tradebot.lock"
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$MainPy = Join-Path $RepoRoot "main.py"
$RunningCheck = Join-Path $RepoRoot "scripts\is_tradebot_running.py"
$LogsDir = Join-Path $RepoRoot "logs"
$StdoutLog = Join-Path $LogsDir "bot_stdout.log"
$StderrLog = Join-Path $LogsDir "bot_stderr.log"
$WrapperLog = Join-Path $LogsDir "autostart.log"

function Write-AutostartLog {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $WrapperLog -Value "$ts $Message" -Encoding UTF8
}

function Test-TradeBotRunning {
    & $PythonExe $RunningCheck
    return ($LASTEXITCODE -eq 0)
}

function Remove-StaleLock {
    if (-not (Test-Path $LockFile)) {
        return
    }
    $raw = "(unreadable)"
    try {
        $raw = (Get-Content -Path $LockFile -Raw -ErrorAction Stop).Trim()
    } catch {
        # Keep default label for logging.
    }
    if ($WhatIf) {
        Write-AutostartLog "WHATIF: would remove stale lock (contents: $raw)"
        return
    }
    Remove-Item -Path $LockFile -Force -ErrorAction Stop
    Write-AutostartLog "Removed stale lock (contents: $raw)"
}

if (-not (Test-Path $PythonExe)) {
    Write-Error "venv python not found: $PythonExe"
    exit 2
}
if (-not (Test-Path $MainPy)) {
    Write-Error "main.py not found: $MainPy"
    exit 2
}
if (-not (Test-Path $RunningCheck)) {
    Write-Error "running check script not found: $RunningCheck"
    exit 2
}

New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null

if (Test-TradeBotRunning) {
    Write-AutostartLog "SKIP: TradeBot already running (live lock at $LockFile)"
    exit 0
}

if (Test-Path $LockFile) {
    try {
        Remove-StaleLock
    } catch {
        Write-AutostartLog "WARN: could not remove stale lock: $_"
    }
}

Write-AutostartLog "Starting TradeBot (python main.py)"

if ($WhatIf) {
    Write-AutostartLog "WHATIF: would start $PythonExe $MainPy in $RepoRoot"
    exit 0
}

try {
    $proc = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @($MainPy) `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog `
        -PassThru
    Write-AutostartLog "Started TradeBot PID $($proc.Id)"
    exit 0
} catch {
    Write-AutostartLog "ERROR: failed to start TradeBot: $_"
    exit 1
}
