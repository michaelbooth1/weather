# Registers the nightly single-host training window plus its dead-man restore.
#
# WeatherTrainingWindow        reviewed 01:00 one-shot: opt-in stop -> retrain -> proved restore
# WeatherTrainingWindowRestore 04:15 daily: unconditional idempotent capture restore
#
# Run from the repo root:  .\scripts\ops\register_training_window.ps1
# Re-running replaces the existing tasks.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [ValidateSet("WeatherTrainingWindow")]
    [string]$WindowTaskName = "WeatherTrainingWindow",
    [ValidateSet("WeatherTrainingWindowRestore")]
    [string]$RestoreTaskName = "WeatherTrainingWindowRestore",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')]
    [string]$RunAtLocal,
    [ValidateSet("04:15")][string]$RestoreAt = "04:15",
    [string]$PowerShellExecutable = "powershell.exe",
    [Parameter(Mandatory = $true)]
    [string]$BaseRetrainTargetDate,
    [Parameter(Mandatory = $true)]
    [string]$BaseRetrainParentReleaseId,
    [Parameter(Mandatory = $true)]
    [string]$BaseRetrainTrainingAsOf,
    [Parameter(Mandatory = $true)]
    [string]$BaseRetrainFeatureContractId,
    [Parameter(Mandatory = $true)]
    [string]$BaseRetrainCorpusManifest,
    [Parameter(Mandatory = $true)]
    [string]$BaseRetrainPitForecastCorpusManifest,
    [Parameter(Mandatory = $true)]
    [string]$BaseRetrainCandidateDir,
    [Parameter(Mandatory = $true)]
    [string]$BaseRetrainRuntimeId,
    [switch]$EnableWindow
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$python = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "project interpreter is missing: $python"
}
$python = (Resolve-Path -LiteralPath $python -ErrorAction Stop).Path
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
$runAt = Resolve-TrainingWindowRunAtLocal -RunAtLocal $RunAtLocal -RequireFuture
$RunAtLocal = $runAt.ToString(
    "yyyy-MM-ddTHH:mm:ss",
    [Globalization.CultureInfo]::InvariantCulture
)
$baseBindings = Resolve-TrainingWindowBaseRetrainBindings `
    -RepoRoot $RepoRoot `
    -ScheduleLocalTime "01:00" `
    -BaseRetrainTargetDate $BaseRetrainTargetDate `
    -BaseRetrainParentReleaseId $BaseRetrainParentReleaseId `
    -BaseRetrainTrainingAsOf $BaseRetrainTrainingAsOf `
    -BaseRetrainFeatureContractId $BaseRetrainFeatureContractId `
    -BaseRetrainCorpusManifest $BaseRetrainCorpusManifest `
    -BaseRetrainPitForecastCorpusManifest $BaseRetrainPitForecastCorpusManifest `
    -BaseRetrainCandidateDir $BaseRetrainCandidateDir `
    -BaseRetrainRuntimeId $BaseRetrainRuntimeId

$powerShellCommand = Get-Command $PowerShellExecutable -CommandType Application -ErrorAction Stop
$PowerShellExecutable = [string]$powerShellCommand.Source
$windowActionTokens = @(Get-TrainingWindowTaskActionTokens `
    -RepoRoot $RepoRoot `
    -ScriptPath $script `
    -WindowTaskName $WindowTaskName `
    -SchedulerTaskExecutable $PowerShellExecutable `
    -RunAtLocal $RunAtLocal `
    -BaseRetrainTargetDate $baseBindings.BaseRetrainTargetDate `
    -BaseRetrainParentReleaseId $baseBindings.BaseRetrainParentReleaseId `
    -BaseRetrainTrainingAsOf $baseBindings.BaseRetrainTrainingAsOf `
    -BaseRetrainFeatureContractId $baseBindings.BaseRetrainFeatureContractId `
    -BaseRetrainCorpusManifest $baseBindings.BaseRetrainCorpusManifest `
    -BaseRetrainPitForecastCorpusManifest $baseBindings.BaseRetrainPitForecastCorpusManifest `
    -BaseRetrainCandidateDir $baseBindings.BaseRetrainCandidateDir `
    -BaseRetrainRuntimeId $baseBindings.BaseRetrainRuntimeId)
$windowActionArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $windowActionTokens

$windowAction = New-ScheduledTaskAction `
    -Execute $PowerShellExecutable `
    -Argument $windowActionArguments `
    -WorkingDirectory $RepoRoot

$windowTrigger = New-ScheduledTaskTrigger -Once -At $runAt

# Time limit must exceed the 170m child cap plus stop/restore overhead so the
# scheduler never kills the process before its finally-block restores capture.
$windowSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3 -Minutes 45) `
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
    -Description "Opt-in one-shot single-host training reservation: stops capture loops, runs one run-specific nightly retrain, proves capture recovery, and restores capture. Registration leaves it disabled unless -EnableWindow is explicit." `
    -Force | Out-Null
if (-not $EnableWindow) {
    Disable-ScheduledTask -TaskName $WindowTaskName | Out-Null
}
else {
    Enable-ScheduledTask -TaskName $WindowTaskName | Out-Null
}

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

$windowMatches = @(Get-ScheduledTask -TaskName $WindowTaskName -ErrorAction SilentlyContinue)
$restoreMatches = @(Get-ScheduledTask -TaskName $RestoreTaskName -ErrorAction SilentlyContinue)
if ($windowMatches.Count -ne 1 -or $restoreMatches.Count -ne 1) {
    throw "training-window registration readback is missing or duplicated"
}
$registeredWindow = $windowMatches[0]
$registeredRestore = $restoreMatches[0]
$windowActions = @($registeredWindow.Actions)
$restoreActions = @($registeredRestore.Actions)
$windowTriggers = @($registeredWindow.Triggers)
$restoreTriggers = @($registeredRestore.Triggers)
if ([string]$registeredWindow.TaskPath -ne "\" -or
    ($EnableWindow -and [string]$registeredWindow.State -ne "Ready") -or
    (-not $EnableWindow -and [string]$registeredWindow.State -ne "Disabled") -or
    $windowActions.Count -ne 1 -or
    [string]$windowActions[0].Execute -ine $PowerShellExecutable -or
    [string]$windowActions[0].Arguments -cne $windowActionArguments -or
    [string]$windowActions[0].WorkingDirectory -ine $RepoRoot -or
    $windowTriggers.Count -ne 1 -or
    [string]$windowTriggers[0].CimClass.CimClassName -ne "MSFT_TaskTimeTrigger" -or
    ([datetime]$windowTriggers[0].StartBoundary) -ne $runAt -or
    -not [bool]$windowTriggers[0].Enabled -or
    -not [string]::IsNullOrWhiteSpace([string]$windowTriggers[0].Repetition.Interval) -or
    [bool]$registeredWindow.Settings.StartWhenAvailable -or
    -not [bool]$registeredWindow.Settings.WakeToRun -or
    [string]$registeredWindow.Settings.ExecutionTimeLimit -ne "PT3H45M" -or
    [string]$registeredWindow.Settings.MultipleInstances -ne "IgnoreNew" -or
    -not [bool]$registeredWindow.Settings.Hidden -or
    [bool]$registeredWindow.Settings.DisallowStartIfOnBatteries -or
    [bool]$registeredWindow.Settings.StopIfGoingOnBatteries -or
    [string]$registeredWindow.Principal.UserId -ine $env:USERNAME -or
    [string]$registeredWindow.Principal.LogonType -ne "S4U" -or
    [string]$registeredWindow.Principal.RunLevel -ne "Limited") {
    throw "training-window readback does not match the exact run-specific one-shot contract"
}
if ([string]$registeredRestore.TaskPath -ne "\" -or
    [string]$registeredRestore.State -ne "Ready" -or
    $restoreActions.Count -ne 1 -or
    [string]$restoreActions[0].Execute -ine $PowerShellExecutable -or
    [string]$restoreActions[0].Arguments -cne $restoreActionArguments -or
    [string]$restoreActions[0].WorkingDirectory -ine $RepoRoot -or
    $restoreTriggers.Count -ne 1 -or
    [string]$restoreTriggers[0].CimClass.CimClassName -ne "MSFT_TaskDailyTrigger" -or
    [int]$restoreTriggers[0].DaysInterval -ne 1 -or
    ([datetime]$restoreTriggers[0].StartBoundary).ToString("HH:mm") -ne "04:15" -or
    -not [bool]$restoreTriggers[0].Enabled -or
    -not [string]::IsNullOrWhiteSpace([string]$restoreTriggers[0].Repetition.Interval) -or
    -not [bool]$registeredRestore.Settings.StartWhenAvailable -or
    -not [bool]$registeredRestore.Settings.WakeToRun -or
    [string]$registeredRestore.Settings.ExecutionTimeLimit -ne "PT15M" -or
    [string]$registeredRestore.Settings.MultipleInstances -ne "IgnoreNew" -or
    -not [bool]$registeredRestore.Settings.Hidden -or
    [bool]$registeredRestore.Settings.DisallowStartIfOnBatteries -or
    [bool]$registeredRestore.Settings.StopIfGoingOnBatteries -or
    [string]$registeredRestore.Principal.UserId -ine $env:USERNAME -or
    [string]$registeredRestore.Principal.LogonType -ne "S4U" -or
    [string]$registeredRestore.Principal.RunLevel -ne "Limited") {
    throw "training-window restore readback does not match the daily 04:15 dead-man contract"
}

Write-Host "Registered one-shot '$WindowTaskName' at $RunAtLocal and daily '$RestoreTaskName' at $RestoreAt."
if ($EnableWindow) {
    Write-Host "Training reservation is ENABLED by explicit -EnableWindow authority."
}
else {
    Write-Host "Training reservation is held DISABLED; re-register with -EnableWindow only for a reviewed runnable training night."
}
Write-Host "The window action carries the exact delegated-child scheduler provenance contract."
