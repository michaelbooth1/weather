# Registers the nightly single-host training window plus its dead-man restore.
#
# WeatherTrainingWindow        01:00 daily: stop capture -> nightly retrain -> restore
# WeatherTrainingWindowRestore 04:15 daily: unconditional idempotent capture restore
#
# Run from the repo root:  .\scripts\ops\register_training_window.ps1
# Re-running replaces the existing tasks.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$WindowTaskName = "WeatherTrainingWindow",
    [string]$RestoreTaskName = "WeatherTrainingWindowRestore",
    [string]$WindowAt = "01:00",
    [string]$RestoreAt = "04:15",
    [string]$PowerShellExecutable = "powershell.exe"
)

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$script = Join-Path $RepoRoot "scripts\ops\training_window.ps1"
if (-not (Test-Path -LiteralPath $script -PathType Leaf)) {
    throw "training window script not found at $script"
}
$script = (Resolve-Path -LiteralPath $script).Path
$contractScript = Join-Path $RepoRoot "scripts\ops\training_window_contract.ps1"
if (-not (Test-Path -LiteralPath $contractScript -PathType Leaf)) {
    throw "training window contract script not found at $contractScript"
}
. $contractScript

$powerShellCommand = Get-Command $PowerShellExecutable -CommandType Application -ErrorAction Stop
$PowerShellExecutable = [string]$powerShellCommand.Source
$windowActionTokens = @(Get-TrainingWindowTaskActionTokens `
    -RepoRoot $RepoRoot `
    -ScriptPath $script `
    -WindowTaskName $WindowTaskName `
    -SchedulerTaskExecutable $PowerShellExecutable)
$windowActionArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $windowActionTokens

$windowAction = New-ScheduledTaskAction `
    -Execute $PowerShellExecutable `
    -Argument $windowActionArguments `
    -WorkingDirectory $RepoRoot

$windowTrigger = New-ScheduledTaskTrigger -Daily -At $WindowAt

# Time limit must exceed the 3h child cap plus stop/restore overhead so the
# scheduler never kills the process before its finally-block restores capture.
$windowSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3 -Minutes 45) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $WindowTaskName `
    -Action $windowAction `
    -Trigger $windowTrigger `
    -Settings $windowSettings `
    -Principal $principal `
    -Description "Single-host training window: stops capture loops, runs nightly retrain (3h cap), restores capture. Skips on unhealthy commit/disk." `
    -Force | Out-Null

$restoreActionTokens = @(Get-TrainingWindowTaskActionTokens `
    -RepoRoot $RepoRoot `
    -ScriptPath $script `
    -WindowTaskName $WindowTaskName `
    -SchedulerTaskExecutable $PowerShellExecutable `
    -RestoreOnly)
$restoreActionArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $restoreActionTokens

$restoreAction = New-ScheduledTaskAction `
    -Execute $PowerShellExecutable `
    -Argument $restoreActionArguments `
    -WorkingDirectory $RepoRoot

$restoreTrigger = New-ScheduledTaskTrigger -Daily -At $RestoreAt

$restoreSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $RestoreTaskName `
    -Action $restoreAction `
    -Trigger $restoreTrigger `
    -Settings $restoreSettings `
    -Principal $principal `
    -Description "Dead-man backstop: unconditionally re-enables capture supervisors and ensures all loops after the training window." `
    -Force | Out-Null

Write-Host "Registered '$WindowTaskName' daily at $WindowAt and '$RestoreTaskName' daily at $RestoreAt."
Write-Host "The window action carries the exact delegated-child scheduler provenance contract."
