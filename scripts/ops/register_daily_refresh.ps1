# Registers the split daily settlement/evidence refresh as Windows Scheduled Tasks.
#
# Stage A runs settlement truth through fleet observability at 09:30.
# Stage B runs evidence recomputation and learning when Stage A triggers it,
# with 14:00 and 17:00 fallback triggers guarded by the Stage-A manifest.
#
# Full registration keeps the release-#1 production-evidence inputs mandatory.
# Before those reviewed inputs exist, the explicit -ProvenanceOnly parameter set
# registers release-aware delegated-child provenance without claiming readiness.
#
# Run from the repo root with either the complete Full parameters or:
#   .\scripts\ops\register_daily_refresh.ps1 -ProvenanceOnly
# Re-running replaces the existing tasks.

[CmdletBinding(DefaultParameterSetName = "Full")]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherDailySettlementPromotionRefresh",
    [string]$EvidenceTaskName = "WeatherEveningEvidenceRefresh",
    [string]$At = "09:30",
    [string[]]$EvidenceAt = @("14:00", "17:00"),
    [string]$PowerShellExecutable = "powershell.exe",
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string[]]$CapturedInputParityServed,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string[]]$CapturedInputParityReplay,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string[]]$ProductionReadinessServedArtifact,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$ProductionReadinessServedRoute,
    [Parameter(Mandatory = $true, ParameterSetName = "ProvenanceOnly")]
    [switch]$ProvenanceOnly,
    [switch]$ContinueOnError = $true
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path

function Resolve-RequiredFile([string]$Path, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label must name an existing regular file: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

$python = Resolve-RequiredFile `
    (Join-Path $RepoRoot "venv\Scripts\pythonw.exe") `
    "venv pythonw"
$wrapperScript = Resolve-RequiredFile `
    (Join-Path $RepoRoot "scripts\ops\daily_refresh.ps1") `
    "daily refresh wrapper"
$contractScript = Resolve-RequiredFile `
    (Join-Path $RepoRoot "scripts\ops\daily_refresh_contract.ps1") `
    "daily refresh contract"
. $contractScript

$powerShellCommand = Get-Command $PowerShellExecutable `
    -CommandType Application -ErrorAction Stop
$PowerShellExecutable = [string]$powerShellCommand.Source

$productionEvidenceArgumentsB64 = ""
if (-not $ProvenanceOnly) {
    if (-not $CapturedInputParityServed -or $CapturedInputParityServed.Count -eq 0) {
        throw "At least one -CapturedInputParityServed file is required."
    }
    if (-not $CapturedInputParityReplay -or $CapturedInputParityReplay.Count -eq 0) {
        throw "At least one -CapturedInputParityReplay file is required."
    }
    if (-not $ProductionReadinessServedArtifact -or $ProductionReadinessServedArtifact.Count -eq 0) {
        throw "At least one -ProductionReadinessServedArtifact ROLE=PATH binding is required."
    }

    $productionEvidenceArguments = @("--fail-on-production-readiness-block")
    foreach ($path in $CapturedInputParityServed) {
        $resolved = Resolve-RequiredFile $path "Captured-input served parity input"
        $productionEvidenceArguments += @("--captured-input-parity-served", $resolved)
    }
    foreach ($path in $CapturedInputParityReplay) {
        $resolved = Resolve-RequiredFile $path "Captured-input replay parity input"
        $productionEvidenceArguments += @("--captured-input-parity-replay", $resolved)
    }
    foreach ($binding in $ProductionReadinessServedArtifact) {
        $separator = $binding.IndexOf("=")
        if ($separator -le 0) {
            throw "Production readiness served artifacts must use ROLE=PATH: $binding"
        }
        $role = $binding.Substring(0, $separator).Trim()
        $path = $binding.Substring($separator + 1).Trim()
        if ([string]::IsNullOrWhiteSpace($role)) {
            throw "Production readiness served artifacts must use a nonempty ROLE=PATH binding: $binding"
        }
        $resolved = Resolve-RequiredFile $path "Served artifact '$role'"
        $productionEvidenceArguments += @(
            "--production-readiness-served-artifact",
            "$role=$resolved"
        )
    }
    $servedRoute = Resolve-RequiredFile `
        $ProductionReadinessServedRoute `
        "Production readiness served route"
    $productionEvidenceArguments += @(
        "--production-readiness-served-route",
        $servedRoute
    )
    $productionEvidenceArgumentsB64 = ConvertTo-SchedulerArgumentContract `
        -Tokens $productionEvidenceArguments
}

$commonActionParameters = @{
    RepoRoot = $RepoRoot
    ScriptPath = $wrapperScript
    EvidenceTaskName = $EvidenceTaskName
    SchedulerTaskExecutable = $PowerShellExecutable
    ContinueOnError = [bool]$ContinueOnError
}
if ($ProvenanceOnly) {
    $commonActionParameters["ProvenanceOnly"] = $true
} else {
    $commonActionParameters["ProductionEvidenceArgumentsB64"] = $productionEvidenceArgumentsB64
}

$stageAActionParameters = $commonActionParameters.Clone()
$stageAActionParameters["Stage"] = "settlement"
$stageAActionParameters["SchedulerTaskName"] = $TaskName
$stageAActionTokens = @(Get-DailyRefreshTaskActionTokens @stageAActionParameters)
$stageAArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $stageAActionTokens

$stageBActionParameters = $commonActionParameters.Clone()
$stageBActionParameters["Stage"] = "evidence"
$stageBActionParameters["SchedulerTaskName"] = $EvidenceTaskName
$stageBActionTokens = @(Get-DailyRefreshTaskActionTokens @stageBActionParameters)
$stageBArguments = ConvertTo-ScheduledTaskArgumentString -Tokens $stageBActionTokens

$stageAAction = New-ScheduledTaskAction `
    -Execute $PowerShellExecutable `
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

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $stageAAction `
    -Trigger $stageATrigger `
    -Settings $stageASettings `
    -Principal $principal `
    -Description "Runs daily weather-market settlement truth through fleet observability (daily_refresh --stage settlement)." `
    -Force | Out-Null

$stageBAction = New-ScheduledTaskAction `
    -Execute $PowerShellExecutable `
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
    -Principal $principal `
    -Description "Runs daily weather-market evidence recomputation and learning when the Stage-A manifest is fresh (daily_refresh --stage evidence)." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName': settlement stage daily at $At."
Write-Host "Registered scheduled task '$EvidenceTaskName': evidence stage fallback at $($EvidenceAt -join ', ')."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Verify evidence with: Get-ScheduledTask -TaskName $EvidenceTaskName | Get-ScheduledTaskInfo"
