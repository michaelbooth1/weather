# Registers the split daily settlement/evidence refresh as Windows Scheduled Tasks.
#
# Stage A runs settlement truth through fleet observability at 09:30.
# Stage B runs evidence recomputation and learning when Stage A triggers it,
# with 14:00 and 17:00 fallback triggers guarded by the Stage-A manifest.
#
# Run from the repo root:  .\scripts\ops\register_daily_refresh.ps1
# Re-running replaces the existing tasks.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherDailySettlementPromotionRefresh",
    [string]$EvidenceTaskName = "WeatherEveningEvidenceRefresh",
    [string]$At = "09:30",
    [string[]]$EvidenceAt = @("14:00", "17:00"),
    [Parameter(Mandatory = $true)]
    [string[]]$CapturedInputParityServed,
    [Parameter(Mandatory = $true)]
    [string[]]$CapturedInputParityReplay,
    [Parameter(Mandatory = $true)]
    [string[]]$ProductionReadinessServedArtifact,
    [Parameter(Mandatory = $true)]
    [string]$ProductionReadinessServedRoute,
    [switch]$ContinueOnError = $true
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

$baseArguments = "-m weather.operations.daily_refresh run --fail-on-variant-evidence-alert"
if ($ContinueOnError) {
    $baseArguments = "$baseArguments --continue-on-error"
}

$releasePointer = Join-Path $RepoRoot "artifacts\releases\current_release.json"
$releasesRoot = Join-Path $RepoRoot "artifacts\releases"
$releaseContract = "--active-release-pointer `"$releasePointer`" --releases-root `"$releasesRoot`" --repo-root `"$RepoRoot`""
$stageAProvenance = "--scheduler-invocation-topology direct --scheduler-task-name `"$TaskName`" --scheduler-task-executable `"$python`" --scheduler-task-working-directory `"$RepoRoot`" --producer-sla-seconds 14400"
$stageBProvenance = "--scheduler-invocation-topology direct --scheduler-task-name `"$EvidenceTaskName`" --scheduler-task-executable `"$python`" --scheduler-task-working-directory `"$RepoRoot`" --producer-sla-seconds 28800"

$stageAArguments = "$baseArguments --stage settlement --evidence-task-name `"$EvidenceTaskName`" $stageAProvenance $releaseContract $productionEvidenceContract"
$stageBArguments = "$baseArguments --stage evidence --status-out data\backtest\daily_refresh_evidence_status.json --report-out data\backtest\daily_refresh_evidence_report.md $stageBProvenance $releaseContract $productionEvidenceContract"

$stageAAction = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $stageAArguments `
    -WorkingDirectory $RepoRoot

$stageATrigger = New-ScheduledTaskTrigger -Daily -At $At

$stageASettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $stageAAction `
    -Trigger $stageATrigger `
    -Settings $stageASettings `
    -Description "Runs daily weather-market settlement truth through fleet observability (daily_refresh --stage settlement)." `
    -Force | Out-Null

$stageBAction = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $stageBArguments `
    -WorkingDirectory $RepoRoot

$stageBTriggers = @()
foreach ($time in $EvidenceAt) {
    $stageBTriggers += New-ScheduledTaskTrigger -Daily -At $time
}

$stageBSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -StartWhenAvailable `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $EvidenceTaskName `
    -Action $stageBAction `
    -Trigger $stageBTriggers `
    -Settings $stageBSettings `
    -Description "Runs daily weather-market evidence recomputation and learning when the Stage-A manifest is fresh (daily_refresh --stage evidence)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': settlement stage daily at $At."
Write-Host "Registered scheduled task '$EvidenceTaskName': evidence stage fallback at $($EvidenceAt -join ', ')."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Verify evidence with: Get-ScheduledTask -TaskName $EvidenceTaskName | Get-ScheduledTaskInfo"
