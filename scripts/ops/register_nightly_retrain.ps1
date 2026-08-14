# Registers nightly retrain -> validate -> inactive immutable candidate build.
#
# Run from the repo root:  .\scripts\ops\register_nightly_retrain.ps1
# Re-running replaces the existing task.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherNightlyRetrainValidatePromote",
    [string]$At = "03:30",
    [Parameter(Mandatory = $true)]
    [string[]]$CapturedInputParityServed,
    [Parameter(Mandatory = $true)]
    [string[]]$CapturedInputParityReplay,
    [Parameter(Mandatory = $true)]
    [string[]]$ProductionReadinessServedArtifact,
    [Parameter(Mandatory = $true)]
    [string]$ProductionReadinessServedRoute,
    [switch]$FailOnBlock = $false,
    [switch]$FailOnDailyLearningBlocker = $true
)

$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}

function Resolve-RequiredFile([string]$Path, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label must name an existing regular file: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

if (-not $CapturedInputParityServed -or $CapturedInputParityServed.Count -eq 0) {
    throw "At least one -CapturedInputParityServed file is required."
}
if (-not $CapturedInputParityReplay -or $CapturedInputParityReplay.Count -eq 0) {
    throw "At least one -CapturedInputParityReplay file is required."
}
if (-not $ProductionReadinessServedArtifact -or $ProductionReadinessServedArtifact.Count -eq 0) {
    throw "At least one -ProductionReadinessServedArtifact ROLE=PATH binding is required."
}

$productionEvidenceContract = "--fail-on-production-readiness-block"
foreach ($path in $CapturedInputParityServed) {
    $resolved = Resolve-RequiredFile $path "Captured-input served parity input"
    $productionEvidenceContract += " --captured-input-parity-served `"$resolved`""
}
foreach ($path in $CapturedInputParityReplay) {
    $resolved = Resolve-RequiredFile $path "Captured-input replay parity input"
    $productionEvidenceContract += " --captured-input-parity-replay `"$resolved`""
}
foreach ($binding in $ProductionReadinessServedArtifact) {
    $separator = $binding.IndexOf("=")
    if ($separator -le 0) {
        throw "Production readiness served artifacts must use ROLE=PATH: $binding"
    }
    $role = $binding.Substring(0, $separator).Trim()
    $path = $binding.Substring($separator + 1).Trim()
    $resolved = Resolve-RequiredFile $path "Served artifact '$role'"
    $productionEvidenceContract += " --production-readiness-served-artifact `"$role=$resolved`""
}
$servedRoute = Resolve-RequiredFile $ProductionReadinessServedRoute "Production readiness served route"
$productionEvidenceContract += " --production-readiness-served-route `"$servedRoute`""

$arguments = "-m weather.operations.nightly_retrain run"
if ($FailOnBlock) {
    $arguments = "$arguments --fail-on-block"
}
if ($FailOnDailyLearningBlocker) {
    $arguments = "$arguments --fail-on-daily-learning-blocker"
}

$releasePointer = Join-Path $RepoRoot "artifacts\releases\current_release.json"
$releasesRoot = Join-Path $RepoRoot "artifacts\releases"
$arguments = "$arguments --scheduler-invocation-topology direct --scheduler-task-name `"$TaskName`" --scheduler-task-executable `"$python`" --scheduler-task-working-directory `"$RepoRoot`" --producer-sla-seconds 28800 --release-pointer `"$releasePointer`" --releases-root `"$releasesRoot`" --repo-root `"$RepoRoot`" $productionEvidenceContract"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Runs candidate-only weather-market retraining, validation, and inactive release construction." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': daily at $At."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
