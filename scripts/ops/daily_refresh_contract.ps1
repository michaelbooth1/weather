# Shared action-token contract for delegated daily-refresh registration.
#
# The registration script and running wrapper both build the exact same
# PowerShell action token vector here. The wrapper passes its base64-encoded
# copy to the Python child so producer provenance can compare it with the
# registered task action and observed process lineage.

$trainingWindowContract = Join-Path $PSScriptRoot "training_window_contract.ps1"
if (-not (Test-Path -LiteralPath $trainingWindowContract -PathType Leaf)) {
    throw "training window contract script not found at $trainingWindowContract"
}
. $trainingWindowContract

function Get-DailyRefreshTaskActionTokens {
    [CmdletBinding(DefaultParameterSetName = "Full")]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,
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

    $tokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $ScriptPath,
        "-RepoRoot", $RepoRoot,
        "-Stage", $Stage,
        "-SchedulerTaskName", $SchedulerTaskName,
        "-EvidenceTaskName", $EvidenceTaskName,
        "-SchedulerTaskExecutable", $SchedulerTaskExecutable
    )
    if ($ContinueOnError) {
        $tokens += "-ContinueOnError"
    }
    if ($ProvenanceOnly) {
        $tokens += "-ProvenanceOnly"
    } else {
        $tokens += @(
            "-ProductionEvidenceArgumentsB64",
            $ProductionEvidenceArgumentsB64
        )
    }
    return $tokens
}

function Get-DailyRefreshChildTokens {
    [CmdletBinding(DefaultParameterSetName = "Full")]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet("settlement", "evidence")]
        [string]$Stage,
        [Parameter(Mandatory = $true)]
        [string]$SchedulerTaskName,
        [Parameter(Mandatory = $true)]
        [string]$EvidenceTaskName,
        [Parameter(Mandatory = $true)]
        [string]$SchedulerTaskExecutable,
        [Parameter(Mandatory = $true)]
        [string]$SchedulerTaskActionArgumentsB64,
        [Parameter(Mandatory = $true)]
        [string]$SchedulerProcessExecutable,
        [switch]$ContinueOnError,
        [Parameter(Mandatory = $true, ParameterSetName = "Full")]
        [string[]]$ProductionEvidenceArguments,
        [Parameter(Mandatory = $true, ParameterSetName = "ProvenanceOnly")]
        [switch]$ProvenanceOnly
    )

    $tokens = @(
        "-m", "weather.operations.daily_refresh", "run",
        "--fail-on-variant-evidence-alert"
    )
    if ($ContinueOnError) {
        $tokens += "--continue-on-error"
    }
    $tokens += @("--stage", $Stage)
    if ($Stage -eq "settlement") {
        $tokens += @(
            "--evidence-task-name", $EvidenceTaskName,
            # Stage B owns one overnight trigger after Stage A has released
            # the shared lease.  Suppress the old immediate lease race.
            "--disable-stage-trigger",
            # The full 2000-2025 audit cannot fit the bounded morning tail.
            # Live fleet health remains current; historical audit is a
            # separately invoked research operation.
            "--skip-historical-audits",
            # Trust scoring replays every settled snapshots_long tape. Keep
            # that full-corpus work out of the bounded scheduled tail too.
            "--skip-fleet-trust-replay",
            # Runtime-identity evidence currently scans every snapshot tape
            # before filtering. Omit it from the scheduled bounded tail.
            "--skip-fleet-runtime-identity-replay",
            # Stage A already produced current trading evidence. Avoid the
            # observability tail's duplicate all-run MM/taker enumeration.
            "--skip-fleet-trading-replay"
        )
        $producerSlaSeconds = 14400
    } else {
        $tokens += @(
            "--status-out", "data\backtest\daily_refresh_evidence_status.json",
            "--report-out", "data\backtest\daily_refresh_evidence_report.md"
        )
        # The child SLA ends at 08:35, leaving 25 minutes for the wrapper's
        # 09:00 teardown and 40 minutes before Scheduler's 09:15 hard limit.
        $producerSlaSeconds = 28800
    }

    $releasePointer = Join-Path $RepoRoot "artifacts\releases\current_release.json"
    $releasesRoot = Join-Path $RepoRoot "artifacts\releases"
    $tokens += @(
        "--scheduler-invocation-topology", "delegated_child",
        "--scheduler-task-name", $SchedulerTaskName,
        "--scheduler-task-executable", $SchedulerTaskExecutable,
        "--scheduler-task-working-directory", $RepoRoot,
        "--scheduler-task-action-arguments-b64", $SchedulerTaskActionArgumentsB64,
        "--scheduler-process-executable", $SchedulerProcessExecutable,
        "--scheduler-correlation-seconds", "300",
        "--producer-sla-seconds", ([string]$producerSlaSeconds),
        "--active-release-pointer", $releasePointer,
        "--releases-root", $releasesRoot,
        "--repo-root", $RepoRoot
    )
    if (-not $ProvenanceOnly) {
        $tokens += $ProductionEvidenceArguments
    }
    return $tokens
}

function ConvertFrom-DailyRefreshProductionEvidenceArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArgumentsB64
    )

    try {
        $json = [Text.Encoding]::UTF8.GetString(
            [Convert]::FromBase64String($ArgumentsB64)
        )
    } catch {
        throw "Production evidence argument contract is not valid base64 UTF-8: $($_.Exception.Message)"
    }
    if (-not $json.TrimStart().StartsWith("[")) {
        throw "Production evidence argument contract must encode a JSON array."
    }
    try {
        $parsed = $json | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "Production evidence argument contract is not valid JSON: $($_.Exception.Message)"
    }
    if ($parsed -isnot [System.Array]) {
        throw "Production evidence argument contract must decode to a JSON array."
    }
    $tokens = [object[]]$parsed
    if ($tokens.Count -lt 9 -or $tokens[0] -ne "--fail-on-production-readiness-block") {
        throw "Production evidence argument contract is incomplete or has an invalid leading flag."
    }

    $counts = @{
        "--captured-input-parity-served" = 0
        "--captured-input-parity-replay" = 0
        "--production-readiness-served-artifact" = 0
        "--production-readiness-served-route" = 0
    }
    for ($index = 1; $index -lt $tokens.Count; $index += 2) {
        if ($index + 1 -ge $tokens.Count) {
            throw "Production evidence argument contract has a flag without a value."
        }
        $flag = $tokens[$index]
        $value = $tokens[$index + 1]
        if ($flag -isnot [string] -or -not $counts.ContainsKey($flag)) {
            throw "Production evidence argument contract contains an unsupported flag: $flag"
        }
        if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) {
            throw "Production evidence argument contract contains an empty value for $flag."
        }
        $counts[$flag] += 1
    }
    foreach ($flag in @(
        "--captured-input-parity-served",
        "--captured-input-parity-replay",
        "--production-readiness-served-artifact"
    )) {
        if ($counts[$flag] -lt 1) {
            throw "Production evidence argument contract is missing $flag."
        }
    }
    if ($counts["--production-readiness-served-route"] -ne 1) {
        throw "Production evidence argument contract must contain exactly one --production-readiness-served-route."
    }
    return $tokens
}
