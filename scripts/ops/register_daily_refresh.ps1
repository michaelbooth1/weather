# Registers the split daily settlement/evidence refresh as Windows Scheduled Tasks.
#
# Stage A runs settlement truth through fleet observability at 09:30.
# Stage B runs evidence recomputation and learning once at 06:45, after every
# recurring overnight lease holder's hard end and before the 09:00 deadline.
# Registration refuses while any enabled task that runs a lease-taking script
# has a scheduled window overlapping Stage B's. Stage B remains disabled unless
# -EnableEvidenceTask is supplied explicitly.
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
    [ValidateSet("06:45")]
    [string]$EvidenceAt = "06:45",
    [string]$PowerShellExecutable = "powershell.exe",
    [switch]$EnableEvidenceTask,
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

$evidenceSchedule = Get-DailyRefreshEvidenceSchedule
if ($EvidenceAt -cne $evidenceSchedule.TriggerAt) {
    throw "EvidenceAt $EvidenceAt disagrees with the evidence schedule contract"
}
$evidenceStartMinute = [int]$EvidenceAt.Substring(0, 2) * 60 + [int]$EvidenceAt.Substring(3, 2)
$evidenceWrapperSpanSeconds = ($evidenceSchedule.TeardownMinute - $evidenceStartMinute) * 60
$evidenceLimitSeconds = $evidenceSchedule.SchedulerLimitMinutes * 60
if (-not (
    $evidenceSchedule.ProducerSlaSeconds + $evidenceSchedule.LeaseWaitSeconds -lt $evidenceWrapperSpanSeconds -and
    $evidenceWrapperSpanSeconds -lt $evidenceLimitSeconds -and
    [System.Xml.XmlConvert]::ToTimeSpan($evidenceSchedule.SchedulerLimitIso).TotalSeconds -eq $evidenceLimitSeconds
)) {
    throw "evidence schedule must compose SLA + lease wait < wrapper span < Scheduler limit"
}

# Refuse before registering anything while any enabled scheduled task that
# runs a lease-taking script or module (derived from source, not a hand list)
# could still own the shared lease inside Stage B's scheduled window.
$overnightHolders = @(Get-DailyRefreshEvidenceLeaseHolders `
    -Tasks @(Get-ScheduledTask) `
    -LeaseEntryPoints @(Get-WeatherSharedLeaseEntryPoints -RepoRoot $RepoRoot) `
    -ExcludeTaskNames @($EvidenceTaskName))
$evidenceCollisions = @(Get-DailyRefreshEvidenceTriggerCollisions `
    -Holders $overnightHolders `
    -EvidenceAt $EvidenceAt `
    -EvidenceLimitMinutes $evidenceSchedule.SchedulerLimitMinutes)
if ($evidenceCollisions.Count -gt 0) {
    $detail = ($evidenceCollisions | ForEach-Object {
        "{0} at {1} limit {2}" -f $_.TaskName, $_.StartBoundary, $_.ExecutionTimeLimit
    }) -join "; "
    throw "evidence trigger $EvidenceAt overlaps an enabled shared-lease holder: $detail"
}

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

$stageBTrigger = New-ScheduledTaskTrigger -Daily -At $EvidenceAt

$stageBSettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -ExecutionTimeLimit (New-TimeSpan -Minutes $evidenceSchedule.SchedulerLimitMinutes) `
    -WakeToRun `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $EvidenceTaskName `
    -Action $stageBAction `
    -Trigger $stageBTrigger `
    -Settings $stageBSettings `
    -Principal $principal `
    -Description "Runs daily weather-market evidence recomputation and learning when the Stage-A manifest is fresh (daily_refresh --stage evidence)." `
    -Force | Out-Null

if ($EnableEvidenceTask) {
    Enable-ScheduledTask -TaskName $EvidenceTaskName -ErrorAction Stop | Out-Null
}
else {
    Disable-ScheduledTask -TaskName $EvidenceTaskName -ErrorAction Stop | Out-Null
}
$evidenceTaskReadback = @(Get-ScheduledTask -TaskName $EvidenceTaskName -ErrorAction Stop)
if ($evidenceTaskReadback.Count -ne 1) {
    throw "expected exactly one registered evidence task '$EvidenceTaskName'"
}
$evidenceTaskState = [string]$evidenceTaskReadback[0].State
$evidenceTaskTriggers = @($evidenceTaskReadback[0].Triggers)
if (
    $evidenceTaskTriggers.Count -ne 1 -or
    ([datetime]$evidenceTaskTriggers[0].StartBoundary).ToString("HH:mm") -ne $EvidenceAt -or
    [string]$evidenceTaskReadback[0].Settings.ExecutionTimeLimit -ne $evidenceSchedule.SchedulerLimitIso
) {
    throw "evidence task '$EvidenceTaskName' trigger or $($evidenceSchedule.SchedulerLimitIso) cleanup limit disagrees"
}
if (-not $EnableEvidenceTask -and $evidenceTaskState -ne "Disabled") {
    throw "evidence task '$EvidenceTaskName' must remain disabled without -EnableEvidenceTask"
}
if ($EnableEvidenceTask -and $evidenceTaskState -eq "Disabled") {
    throw "evidence task '$EvidenceTaskName' was explicitly enabled but read back Disabled"
}

Write-Host "Registered scheduled task '$TaskName': settlement stage daily at $At."
Write-Host "Registered scheduled task '$EvidenceTaskName': evidence stage overnight at $EvidenceAt (state $evidenceTaskState)."
Write-Host "Verify with: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Verify evidence with: Get-ScheduledTask -TaskName $EvidenceTaskName | Get-ScheduledTaskInfo"
