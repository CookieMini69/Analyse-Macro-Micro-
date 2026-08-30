param(
    [string]$At = "07:00",
    [string]$TaskName = "AI Stock Opportunity Scanner"
)

$ErrorActionPreference = "Stop"
$null = [datetime]::ParseExact($At, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
$Runner = (Resolve-Path (Join-Path $PSScriptRoot "run_daily.ps1")).Path
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Scan quotidien point-in-time et alertes locales PEA" `
    -Force

Write-Output "Tâche '$TaskName' installée chaque jour à $At."

