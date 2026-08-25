# Registers the International exchange-economics snapshot refresh as a Windows Scheduled Task.
#
# The task fetches a content-bound snapshot from official Gamma/CLOB APIs before
# the daily settlement/report refresh. It does not accept the baseline.
#
# Run from the repo root:  .\scripts\ops\register_exchange_economics_refresh.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherExchangeEconomicsSnapshotRefresh",
    [string]$At = "09:00"
)

$schedulerBoundaryScript = Join-Path $PSScriptRoot "integration_attempt_remote_git.ps1"
if (-not (Test-Path -LiteralPath $schedulerBoundaryScript -PathType Leaf)) {
    throw "Scheduler mutation boundary helper is missing: $schedulerBoundaryScript"
}
$schedulerBoundaryPreviousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Stop"
    Remove-Item `
        -LiteralPath Function:\Assert-WeatherIntegrationSchedulerMutationAllowed `
        -Force -ErrorAction SilentlyContinue
    . $schedulerBoundaryScript
    $schedulerBoundaryCommand = Get-Command `
        Assert-WeatherIntegrationSchedulerMutationAllowed `
        -CommandType Function -ErrorAction Stop
}
catch {
    throw "Scheduler mutation boundary helper could not be loaded from its canonical file."
}
finally {
    $ErrorActionPreference = $schedulerBoundaryPreviousErrorActionPreference
}
if ([string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.ScriptBlock.File) -or
    -not [IO.Path]::GetFullPath(
        [string]$schedulerBoundaryCommand.ScriptBlock.File
    ).Equals(
        [IO.Path]::GetFullPath($schedulerBoundaryScript),
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not [string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.ModuleName) -or
    -not [string]::IsNullOrWhiteSpace([string]$schedulerBoundaryCommand.Source)) {
    throw "Scheduler mutation boundary helper did not load from its canonical file."
}
$script = Join-Path $RepoRoot "scripts\ops\refresh_exchange_economics_snapshot.ps1"
if (-not (Test-Path $script)) {
    throw "refresh script not found at $script"
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -RepoRoot `"$RepoRoot`""

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Assert-WeatherIntegrationSchedulerMutationAllowed `
    -CommandName "Register-ScheduledTask" -Phase "exchange-economics refresh registration"
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Fetches current International Polymarket per-condition exchange economics from official APIs." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
