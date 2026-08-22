# Registers nightly retrain -> validate -> inactive immutable candidate build.
#
# Run from the repo root:  .\scripts\ops\register_nightly_retrain.ps1
# Re-running replaces the existing task with one reviewed run-specific occurrence.

param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [ValidateSet("WeatherNightlyRetrainValidatePromote")]
    [string]$TaskName = "WeatherNightlyRetrainValidatePromote",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')]
    [string]$RunAtLocal,
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

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
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

function Require-NonEmpty([string]$Value, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Label is required."
    }
    if ($Value.Contains('"')) {
        throw "$Label may not contain a double quote."
    }
    return $Value.Trim()
}

$runAt = [datetime]::MinValue
if (-not [datetime]::TryParseExact(
        $RunAtLocal,
        "yyyy-MM-ddTHH:mm:ss",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeLocal,
        [ref]$runAt
    )) {
    throw "RunAtLocal must use exact local yyyy-MM-ddTHH:mm:ss form."
}
if ($runAt -le (Get-Date).AddMinutes(2)) {
    throw "RunAtLocal must be more than two minutes in the future."
}
$RunAtLocal = $runAt.ToString("yyyy-MM-ddTHH:mm:ss")
$scheduleLocalTime = $runAt.ToString("HH:mm")
$parsedTargetDate = [datetime]::MinValue
if (-not [datetime]::TryParseExact(
        $BaseRetrainTargetDate,
        "yyyy-MM-dd",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsedTargetDate
    )) {
    throw "BaseRetrainTargetDate must be a real yyyy-MM-dd date."
}
$BaseRetrainTargetDate = $parsedTargetDate.ToString("yyyy-MM-dd")
$parsedTrainingAsOf = [DateTimeOffset]::MinValue
if ($BaseRetrainTrainingAsOf -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$' -or
    -not [DateTimeOffset]::TryParse(
        $BaseRetrainTrainingAsOf,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsedTrainingAsOf
    )) {
    throw "BaseRetrainTrainingAsOf must be ISO-8601 with an explicit timezone."
}
$BaseRetrainTrainingAsOf = $BaseRetrainTrainingAsOf.Trim()
$BaseRetrainParentReleaseId = Require-NonEmpty $BaseRetrainParentReleaseId "BaseRetrainParentReleaseId"
$BaseRetrainFeatureContractId = Require-NonEmpty $BaseRetrainFeatureContractId "BaseRetrainFeatureContractId"
$BaseRetrainRuntimeId = Require-NonEmpty $BaseRetrainRuntimeId "BaseRetrainRuntimeId"
$BaseRetrainCorpusManifest = Resolve-RequiredFile $BaseRetrainCorpusManifest "Base-retrain corpus manifest"
$BaseRetrainPitForecastCorpusManifest = Resolve-RequiredFile `
    $BaseRetrainPitForecastCorpusManifest "Base-retrain PIT forecast corpus manifest"
$BaseRetrainCandidateDir = [IO.Path]::GetFullPath(
    (Require-NonEmpty $BaseRetrainCandidateDir "BaseRetrainCandidateDir")
)
if (Test-Path -LiteralPath $BaseRetrainCandidateDir) {
    throw "BaseRetrainCandidateDir must not already exist: $BaseRetrainCandidateDir"
}
$repoPrefix = $RepoRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
if ($BaseRetrainCandidateDir -ieq $RepoRoot -or
    $BaseRetrainCandidateDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "BaseRetrainCandidateDir must be outside the repository: $BaseRetrainCandidateDir"
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
    if ($role -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$' -or
        $role.Contains('"')) {
        throw "Production readiness served artifact role is empty or unsafe: $role"
    }
    $resolved = Resolve-RequiredFile $path "Served artifact '$role'"
    $productionEvidenceContract += " --production-readiness-served-artifact `"$role=$resolved`""
}
$servedRoute = Resolve-RequiredFile $ProductionReadinessServedRoute "Production readiness served route"
$productionEvidenceContract += " --production-readiness-served-route `"$servedRoute`""

# A direct Python task cannot own the repository heavy-work lease and cannot
# prove that the three capture supervisors/workers are absent before claiming
# offline_host. Keep the reviewed one-shot construction below as the intended
# future contract, but refuse registration until a repository-owned
# lease/proof wrapper is implemented and reviewed.
throw (
    "Direct nightly registration is unsupported: no repository-owned " +
    "lease-owning offline-host proof wrapper exists. Use the bounded " +
    "WeatherTrainingWindow topology or implement that wrapper first."
)

$arguments = "-m weather.operations.nightly_retrain run"
if ($FailOnBlock) {
    $arguments = "$arguments --fail-on-block"
}
if ($FailOnDailyLearningBlocker) {
    $arguments = "$arguments --fail-on-daily-learning-blocker"
}
else {
    # Python defaults this gate on. Omitting the positive flag would not honor
    # an explicit PowerShell false binding.
    $arguments = "$arguments --no-fail-on-daily-learning-blocker"
}

$releasePointer = Join-Path $RepoRoot "artifacts\releases\current_release.json"
$releasesRoot = Join-Path $RepoRoot "artifacts\releases"
$arguments = (
    "$arguments --scheduler-invocation-topology direct" +
    " --scheduler-task-name `"$TaskName`"" +
    " --scheduler-task-executable `"$python`"" +
    " --scheduler-task-working-directory `"$RepoRoot`"" +
    " --schedule-local-time `"$scheduleLocalTime`" --schedule-timezone America/Toronto" +
    " --producer-sla-seconds 28800" +
    " --capture-resource-mode offline_host" +
    " --base-retrain-target-date `"$BaseRetrainTargetDate`"" +
    " --base-retrain-parent-release-id `"$BaseRetrainParentReleaseId`"" +
    " --base-retrain-training-as-of `"$BaseRetrainTrainingAsOf`"" +
    " --base-retrain-feature-contract-id `"$BaseRetrainFeatureContractId`"" +
    " --base-retrain-corpus-manifest `"$BaseRetrainCorpusManifest`"" +
    " --base-retrain-pit-forecast-corpus-manifest `"$BaseRetrainPitForecastCorpusManifest`"" +
    " --base-retrain-candidate-dir `"$BaseRetrainCandidateDir`"" +
    " --base-retrain-runtime-id `"$BaseRetrainRuntimeId`"" +
    " --release-pointer `"$releasePointer`" --releases-root `"$releasesRoot`"" +
    " --repo-root `"$RepoRoot`" $productionEvidenceContract"
)

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Once -At $runAt

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8 -Minutes 15) `
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

$matches = @(Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
if ($matches.Count -ne 1) {
    throw "direct nightly registration readback expected one task, found $($matches.Count)"
}
$registered = $matches[0]
$registeredActions = @($registered.Actions)
$registeredTriggers = @($registered.Triggers)
if ([string]$registered.TaskPath -ne "\" -or
    [string]$registered.State -ne "Ready" -or
    $registeredActions.Count -ne 1 -or
    [string]$registeredActions[0].Execute -ine $python -or
    [string]$registeredActions[0].Arguments -cne $arguments -or
    [string]$registeredActions[0].WorkingDirectory -ine $RepoRoot -or
    $registeredTriggers.Count -ne 1 -or
    [string]$registeredTriggers[0].CimClass.CimClassName -ne "MSFT_TaskTimeTrigger" -or
    ([datetime]$registeredTriggers[0].StartBoundary) -ne $runAt -or
    -not [bool]$registeredTriggers[0].Enabled -or
    -not [string]::IsNullOrWhiteSpace([string]$registeredTriggers[0].Repetition.Interval) -or
    [bool]$registered.Settings.StartWhenAvailable -or
    -not [bool]$registered.Settings.WakeToRun -or
    [string]$registered.Settings.ExecutionTimeLimit -ne "PT8H15M" -or
    [string]$registered.Settings.MultipleInstances -ne "IgnoreNew" -or
    [bool]$registered.Settings.DisallowStartIfOnBatteries -or
    [bool]$registered.Settings.StopIfGoingOnBatteries -or
    [string]$registered.Principal.UserId -ine $env:USERNAME -or
    [string]$registered.Principal.LogonType -ne "S4U" -or
    [string]$registered.Principal.RunLevel -ne "Limited") {
    throw "direct nightly readback does not match the exact run-specific one-shot contract"
}

Write-Host "Registered one-shot scheduled task '$TaskName' at $RunAtLocal local."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
