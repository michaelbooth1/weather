# Delegated-child wrapper for the split daily settlement/evidence refresh.
#
# Task Scheduler runs this PowerShell action. The Python daily-refresh child
# attests the exact registered wrapper tokens, its own executable/arguments,
# and the observed wrapper lineage before scheduled evidence is countable.

[CmdletBinding(DefaultParameterSetName = "Full")]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)]
    [ValidateSet("settlement", "evidence")]
    [string]$Stage,
    [Parameter(Mandatory = $true)]
    [string]$SchedulerTaskName,
    [Parameter(Mandatory = $true)]
    [string]$EvidenceTaskName,
    [Parameter(Mandatory = $true)]
    [string]$SchedulerTaskExecutable,
    [switch]$ContinueOnError,
    [Parameter(Mandatory = $true, ParameterSetName = "Full")]
    [string]$ProductionEvidenceArgumentsB64,
    [Parameter(Mandatory = $true, ParameterSetName = "ProvenanceOnly")]
    [switch]$ProvenanceOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$scriptPath = (Resolve-Path -LiteralPath $PSCommandPath -ErrorAction Stop).Path
$contractScript = Join-Path $RepoRoot "scripts\ops\daily_refresh_contract.ps1"
if (-not (Test-Path -LiteralPath $contractScript -PathType Leaf)) {
    throw "daily refresh contract script not found at $contractScript"
}
. $contractScript
$jobScript = Join-Path $RepoRoot "scripts\ops\windows_kill_on_close_job.ps1"
$workloadLeaseScript = Join-Path $RepoRoot "scripts\ops\workload_admission.ps1"
foreach ($requiredScript in @($jobScript, $workloadLeaseScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "daily refresh helper not found at $requiredScript"
    }
}
. $jobScript
. $workloadLeaseScript

$schedulerCommand = Get-Command $SchedulerTaskExecutable `
    -CommandType Application -ErrorAction Stop
$SchedulerTaskExecutable = [string]$schedulerCommand.Source
$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "venv pythonw not found at $python -- run from the repo with its venv created."
}
$python = (Resolve-Path -LiteralPath $python -ErrorAction Stop).Path

$actionParameters = @{
    RepoRoot = $RepoRoot
    ScriptPath = $scriptPath
    Stage = $Stage
    SchedulerTaskName = $SchedulerTaskName
    EvidenceTaskName = $EvidenceTaskName
    SchedulerTaskExecutable = $SchedulerTaskExecutable
    ContinueOnError = [bool]$ContinueOnError
}
if ($ProvenanceOnly) {
    $actionParameters["ProvenanceOnly"] = $true
    $productionEvidenceArguments = @()
} else {
    $actionParameters["ProductionEvidenceArgumentsB64"] = $ProductionEvidenceArgumentsB64
    $productionEvidenceArguments = @(
        ConvertFrom-DailyRefreshProductionEvidenceArguments `
            -ArgumentsB64 $ProductionEvidenceArgumentsB64
    )
}
$scheduledActionTokens = @(Get-DailyRefreshTaskActionTokens @actionParameters)
$schedulerActionArgumentsB64 = ConvertTo-SchedulerArgumentContract `
    -Tokens $scheduledActionTokens

$childParameters = @{
    RepoRoot = $RepoRoot
    Stage = $Stage
    SchedulerTaskName = $SchedulerTaskName
    EvidenceTaskName = $EvidenceTaskName
    SchedulerTaskExecutable = $SchedulerTaskExecutable
    SchedulerTaskActionArgumentsB64 = $schedulerActionArgumentsB64
    SchedulerProcessExecutable = $python
    ContinueOnError = [bool]$ContinueOnError
}
if ($ProvenanceOnly) {
    $childParameters["ProvenanceOnly"] = $true
} else {
    $childParameters["ProductionEvidenceArguments"] = $productionEvidenceArguments
}
$childArgs = @(Get-DailyRefreshChildTokens @childParameters)

$childArgumentString = ConvertTo-ScheduledTaskArgumentString -Tokens $childArgs
$child = $null
$childJob = $null
$childExitCode = $null
$deadlineMinute = if ($Stage -eq "evidence") { 9 * 60 } else { 11 * 60 + 55 }
$deadlineLabel = if ($Stage -eq "evidence") { "09:00" } else { "11:55" }
$localMinute = ((Get-Date).Hour * 60) + (Get-Date).Minute
if ($localMinute -ge $deadlineMinute -or $localMinute -lt 30) {
    Write-Output "REFUSED: daily refresh stage '$Stage' cannot run outside 00:30-$deadlineLabel"
    exit 75
}
$workloadLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $RepoRoot `
    -Workload "daily_refresh_$Stage" `
    -AllowStageAWindow:($Stage -eq "settlement")
if ($null -eq $workloadLease) {
    Write-Output "REFUSED: another heavyweight host workload owns data/logs/heavy_workload.lock"
    exit 76
}
try {
    # Create the delegated refresh suspended, assign it to the kill-on-close
    # Job, and only then resume its first thread. Future descendants inherit
    # the Job, and no Python instruction can run outside containment.
    $childJob = New-WeatherKillOnCloseJob
    $child = Start-WeatherProcessInJob `
        -Job $childJob `
        -FilePath $python `
        -ArgumentString $childArgumentString `
        -WorkingDirectory $RepoRoot
    $deadlineReached = $false
    while (-not $child.HasExited) {
        $now = Get-Date
        $minute = ($now.Hour * 60) + $now.Minute
        if ($minute -ge $deadlineMinute -or $minute -lt 30) {
            $deadlineReached = $true
            break
        }
        Start-Sleep -Seconds 2
        $child.Refresh()
    }
    if ($deadlineReached) {
        # Closing the kill-on-close Job is the authoritative child-tree teardown.
        $childJob.Dispose()
        $childJob = $null
        $child.WaitForExit()
        $childExitCode = 75
        Write-Output "STOPPED: daily refresh stage '$Stage' reached its $deadlineLabel teardown deadline"
    }
    else {
        $child.WaitForExit()
        $childExitCode = $child.ExitCode
    }
}
finally {
    if ($childJob) { $childJob.Dispose() }
    if ($child) { $child.Dispose() }
    Exit-WeatherHeavyWorkloadLease -Lease $workloadLease
}
exit $childExitCode
