#Requires -Version 5.1
<#
.SYNOPSIS
    Remove the TradeBot-AutoStart Windows scheduled task.
#>
param(
    [string]$TaskName = "TradeBot-AutoStart"
)

$ErrorActionPreference = "Stop"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Task '$TaskName' is not registered."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed scheduled task: $TaskName"
