# Registers the daily paper taker-bot rollover launcher as a Windows
# Scheduled Task.
#
# The task is short-lived: it computes the local target date, starts a detached
# paper taker-bot loop for that date, records the child PID, and exits. Because
# the taker-bot run id includes the target date, each new local day gets a fresh
# run folder and budget.
#
# Run from the repo root:  .\scripts\ops\register_taker_bot_daily_roll.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherTakerBotDailyRoll",
    [string]$At = "00:05",
    [string]$Timezone = "America/Toronto",
    [string]$BudgetUsdc = "100",
    [string]$Markets = "all",
    [int]$IntervalSeconds = 60,
    [string[]]$Config = @()
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
$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

$arguments = "-m weather.operations.taker_bot_daily_roll start --timezone $Timezone --budget-usdc $BudgetUsdc --markets $Markets --interval-seconds $IntervalSeconds"
foreach ($item in $Config) {
    $arguments += " --config $item"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
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
    -CommandName "Register-ScheduledTask" -Phase "taker-bot daily-roll registration"
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Starts the active-day paper taker-bot run with a fresh daily budget (python -m weather.operations.taker_bot_daily_roll start)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At ($Timezone), $BudgetUsdc USDC, markets=$Markets."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
