#Requires -Version 5.1
<#
.SYNOPSIS
    Register the TradeBot-AutoStart Windows scheduled task.

.DESCRIPTION
    Creates a per-user logon trigger so TradeBot starts after reboot once you
    sign in. Does not require Administrator for the default (current user)
    registration. Re-running replaces any existing task with the same name.

    Equivalent schtasks registration (for reference):

        schtasks /Create /TN "TradeBot-AutoStart" /SC ONLOGON /RL LIMITED `
            /TR "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"<repo>\scripts\start_tradebot.ps1`"" `
            /F
#>
param(
    [string]$TaskName = "TradeBot-AutoStart",
    [string]$UserName = $env:USERNAME
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StartScript = Join-Path $RepoRoot "scripts\start_tradebot.ps1"

if (-not (Test-Path $StartScript)) {
    Write-Error "start script not found: $StartScript"
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Replaced existing task '$TaskName'."
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$StartScript`"" `
    -WorkingDirectory $RepoRoot

# At logon (not AtStartup): desktop machine keeps .env and repo under the user
# profile; Interactive principal runs in the signed-in session after reboot.
$trigger = New-ScheduledTaskTrigger -AtLogon -User $UserName

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId $UserName `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Auto-start TradeBot after user logon (feature 043). Singleton-aware launcher." | Out-Null

Write-Host ""
Write-Host "Registered scheduled task: $TaskName"
Write-Host "  Trigger : At logon for user $UserName"
Write-Host "  Action  : $StartScript"
Write-Host "  Restart : up to 3 times, 1 minute apart (on launcher failure)"
Write-Host ""
Write-Host "Verify:  schtasks /Query /TN `"$TaskName`" /V /FO LIST"
Write-Host "Test now: powershell -File `"$StartScript`""
