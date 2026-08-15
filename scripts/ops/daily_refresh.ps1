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
$repairChild = $null
$repairJob = $null
$childExitCode = $null
$localMinute = ((Get-Date).Hour * 60) + (Get-Date).Minute
if ($localMinute -ge 715 -or $localMinute -lt 30) {
    Write-Output "REFUSED: daily refresh cannot run inside 11:55-00:30 protected host time"
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
        if ($minute -ge 715 -or $minute -lt 30) {
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

        # A hard Job teardown cannot execute the Python parent's finally block.
        # Run the canonical dead-owner-correlated repair in a fresh contained
        # child, then independently require a terminal durable status.  Exit 77
        # makes a failed repair visible instead of disguising it as the expected
        # protected-window result 75.
        $repairStatusPath = if ($Stage -eq "evidence") {
            Join-Path $RepoRoot "data\backtest\daily_refresh_evidence_status.json"
        } else {
            Join-Path $RepoRoot "data\backtest\daily_refresh_status.json"
        }
        $repairArgs = @(
            "-m", "weather.operations.daily_refresh",
            "repair-stale-locks",
            "--stage", $Stage,
            "--status-out", $repairStatusPath,
            "--repo-root", $RepoRoot
        )
        $repairStatus = $null
        $repairExitCode = $null
        $repairError = ""
        try {
            $repairJob = New-WeatherKillOnCloseJob
            $repairChild = Start-WeatherProcessInJob `
                -Job $repairJob `
                -FilePath $python `
                -ArgumentString (ConvertTo-ScheduledTaskArgumentString -Tokens $repairArgs) `
                -WorkingDirectory $RepoRoot
            $repairChild.WaitForExit()
            $repairExitCode = $repairChild.ExitCode
            if (Test-Path -LiteralPath $repairStatusPath -PathType Leaf) {
                $repairStatus = Get-Content -LiteralPath $repairStatusPath -Raw |
                    ConvertFrom-Json
            }
        }
        catch {
            $repairError = [string]$_.Exception.Message
        }
        $repairCorrelated = (
            $null -ne $repairStatus -and
            [string]$repairStatus.owner_pid -eq [string]$child.Id
        )
        $repairTerminal = (
            $null -ne $repairStatus -and
            [bool]$repairStatus.terminal -and
            [string]$repairStatus.status -ne "running"
        )
        if ($repairExitCode -eq 0 -and $repairCorrelated -and $repairTerminal) {
            $childExitCode = 75
            Write-Output (
                "STOPPED: daily refresh reached the 11:55 protected-window " +
                "deadline; durable status is $($repairStatus.status)"
            )
        } else {
            $childExitCode = 77
            Write-Output (
                "FAILED: daily refresh stopped at the protected-window deadline " +
                "but terminal-status repair did not verify " +
                "(repair_exit=$repairExitCode correlated=$repairCorrelated " +
                "terminal=$repairTerminal error=$repairError)"
            )
        }
    }
    else {
        $child.WaitForExit()
        $childExitCode = $child.ExitCode
    }
}
finally {
    if ($repairJob) { $repairJob.Dispose() }
    if ($repairChild) { $repairChild.Dispose() }
    if ($childJob) { $childJob.Dispose() }
    if ($child) { $child.Dispose() }
    Exit-WeatherHeavyWorkloadLease -Lease $workloadLease
}
exit $childExitCode
