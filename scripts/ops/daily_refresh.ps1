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
$child = Start-Process -FilePath $python `
    -ArgumentList $childArgumentString `
    -WorkingDirectory $RepoRoot `
    -PassThru `
    -WindowStyle Hidden
$child.WaitForExit()
exit $child.ExitCode
