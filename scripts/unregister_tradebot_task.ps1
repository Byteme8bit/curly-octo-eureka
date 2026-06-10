#Requires -Version 5.1
<#
.SYNOPSIS
    Remove the TradeBot-AutoStart Windows scheduled task.

.DESCRIPTION
    Use -IncludeDashboard to also remove TradeBot-Dashboard-AutoStart.
#>
param(
    [string]$TaskName = "TradeBot-AutoStart",
    [string]$DashboardTaskName = "TradeBot-Dashboard-AutoStart",
    [switch]$IncludeDashboard
)

$ErrorActionPreference = "Stop"

function Remove-LogonTask {
    param([string]$Name)

    $existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "Task '$Name' is not registered."
        return
    }

    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    Write-Host "Removed scheduled task: $Name"
}

Remove-LogonTask -Name $TaskName

if ($IncludeDashboard) {
    Remove-LogonTask -Name $DashboardTaskName
}
