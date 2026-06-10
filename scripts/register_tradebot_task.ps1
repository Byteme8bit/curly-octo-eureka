#Requires -Version 5.1
<#
.SYNOPSIS
    Register the TradeBot-AutoStart Windows scheduled task.

.DESCRIPTION
    Creates a per-user logon trigger so TradeBot starts after reboot once you
    sign in. Does not require Administrator for the default (current user)
    registration. Re-running replaces any existing task with the same name.

    Use -IncludeDashboard to also register TradeBot-Dashboard-AutoStart.

    Equivalent schtasks registration (for reference):

        schtasks /Create /TN "TradeBot-AutoStart" /SC ONLOGON /RL LIMITED `
            /TR "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"<repo>\scripts\start_tradebot.ps1`"" `
            /F
#>
param(
    [string]$TaskName = "TradeBot-AutoStart",
    [string]$DashboardTaskName = "TradeBot-Dashboard-AutoStart",
    [string]$UserName = $env:USERNAME,
    [switch]$IncludeDashboard
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Register-LogonTask {
    param(
        [string]$Name,
        [string]$StartScript,
        [string]$Description
    )

    if (-not (Test-Path $StartScript)) {
        Write-Error "start script not found: $StartScript"
        exit 1
    }

    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "Replaced existing task '$Name'."
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
        -TaskName $Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $Description | Out-Null

    Write-Host ""
    Write-Host "Registered scheduled task: $Name"
    Write-Host "  Trigger : At logon for user $UserName"
    Write-Host "  Action  : $StartScript"
    Write-Host "  Restart : up to 3 times, 1 minute apart (on launcher failure)"
}

$StartTradeBot = Join-Path $RepoRoot "scripts\start_tradebot.ps1"
Register-LogonTask `
    -Name $TaskName `
    -StartScript $StartTradeBot `
    -Description "Auto-start TradeBot after user logon (feature 043). Singleton-aware launcher."

Write-Host ""
Write-Host "Verify:  schtasks /Query /TN `"$TaskName`" /V /FO LIST"
Write-Host "Test now: powershell -File `"$StartTradeBot`""

if ($IncludeDashboard) {
    $StartDashboard = Join-Path $RepoRoot "scripts\start_dashboard.ps1"
    Register-LogonTask `
        -Name $DashboardTaskName `
        -StartScript $StartDashboard `
        -Description "Auto-start local dashboard after user logon (feature 043). Port-aware launcher."

    Write-Host ""
    Write-Host "Verify:  schtasks /Query /TN `"$DashboardTaskName`" /V /FO LIST"
    Write-Host "Test now: powershell -File `"$StartDashboard`""
}
