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

function Get-TradeBotMainPyProcesses {
    $venvPy = [regex]::Escape($RepoRoot) + "\\.venv\\Scripts\\python\.exe"
    $mainPyFull = [regex]::Escape($RepoRoot) + "\\main\.py"
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $cmd = $_.CommandLine
            ($cmd -match $mainPyFull) -or ($cmd -match $venvPy -and $cmd -match "main\.py")
        } |
        ForEach-Object {
            $cmd = $_.CommandLine
            [PSCustomObject]@{
                Pid     = $_.ProcessId
                IsVenv  = ($cmd -match $venvPy)
                Command = $cmd
            }
        }
}

function Stop-NonVenvTradeBots {
    foreach ($proc in (Get-TradeBotMainPyProcesses | Where-Object { -not $_.IsVenv })) {
        if ($WhatIf) {
            Write-AutostartLog "WHATIF: would stop non-venv TradeBot PID $($proc.Pid)"
            continue
        }
        Write-AutostartLog "Stopping non-venv TradeBot PID $($proc.Pid)"
        Stop-Process -Id $proc.Pid -Force -ErrorAction SilentlyContinue
    }
}

function Stop-DuplicateTradeBots {
    $procs = @(Get-TradeBotMainPyProcesses)
    if ($procs.Count -eq 0) {
        return
    }

    Stop-NonVenvTradeBots

    $procs = @(Get-TradeBotMainPyProcesses)
    if ($procs.Count -le 1) {
        return
    }

    foreach ($proc in $procs) {
        if ($WhatIf) {
            Write-AutostartLog "WHATIF: would stop duplicate venv TradeBot PID $($proc.Pid)"
            continue
        }
        Write-AutostartLog "Stopping duplicate venv TradeBot PID $($proc.Pid)"
        Stop-Process -Id $proc.Pid -Force -ErrorAction SilentlyContinue
    }

    if (-not $WhatIf -and (Test-Path $LockFile)) {
        Remove-StaleLock
    }
}

function Start-VenvTradeBotProcess {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $stdoutLog = Join-Path $LogsDir "bot_stdout_$stamp.log"
    $stderrLog = Join-Path $LogsDir "bot_stderr_$stamp.log"
    return Start-Process `
        -FilePath $PythonExe `
        -ArgumentList @($MainPy) `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
}

function Test-VenvTradeBotAlive {
    if (Test-TradeBotRunning) {
        return $true
    }
    return @(Get-TradeBotMainPyProcesses | Where-Object { $_.IsVenv }).Count -gt 0
}

function Confirm-VenvTradeBotAlive {
    param([System.Diagnostics.Process]$Proc)

    # Bot imports (ccxt, discord, etc.) can take 10–20s before the poll loop runs.
    Start-Sleep -Seconds 20

    if (Test-VenvTradeBotAlive) {
        $livePid = $Proc.Id
        if (-not (Get-Process -Id $livePid -ErrorAction SilentlyContinue)) {
            $venvProc = Get-TradeBotMainPyProcesses | Where-Object { $_.IsVenv } | Select-Object -First 1
            if ($venvProc) {
                $livePid = $venvProc.Pid
            }
        }
        if (-not $WhatIf) {
            try {
                [System.IO.File]::WriteAllText($LockFile, "$livePid")
            } catch {
                Write-AutostartLog "WARN: could not reaffirm lock for PID $livePid : $_"
            }
        }
        return $true
    }

    Write-AutostartLog "WARN: venv TradeBot PID $($Proc.Id) exited after start"
    return $false
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

Stop-DuplicateTradeBots

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
    $proc = Start-VenvTradeBotProcess
    Write-AutostartLog "Started TradeBot PID $($proc.Id)"

    if (Confirm-VenvTradeBotAlive -Proc $proc) {
        exit 0
    }

    if (Test-Path $LockFile) {
        Remove-StaleLock
    }
    Stop-NonVenvTradeBots
    Start-Sleep -Seconds 1

    Write-AutostartLog "Retrying TradeBot start after non-venv race"
    $proc = Start-VenvTradeBotProcess
    Write-AutostartLog "Started TradeBot PID $($proc.Id)"

    if (Confirm-VenvTradeBotAlive -Proc $proc) {
        exit 0
    }

    Write-AutostartLog "ERROR: venv TradeBot failed to stay alive after retry"
    exit 1
} catch {
    Write-AutostartLog "ERROR: failed to start TradeBot: $_"
    exit 1
}
