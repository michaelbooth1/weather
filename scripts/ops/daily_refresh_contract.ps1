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

# Stage B's one overnight schedule. 00:35 collided with the 00:30 cold-snapshot
# nightly, which holds the shared lease until its absolute 04:45 teardown, so
# Stage B refused every night. 05:00 follows every recurring overnight lease
# holder's hard end (training window and restore by 04:45, quiet merges by
# 04:00) and keeps the 08:35 SLA / 09:00 teardown / 09:15 Scheduler-limit
# endpoints: 12900 < 14400 < 15300 seconds from the trigger. The lease wait
# stays inside the 300-second scheduler correlation so provenance still binds.
$script:DailyRefreshEvidenceSchedule = [ordered]@{
    TriggerAt = "05:00"
    ProducerSlaSeconds = 12900
    TeardownMinute = 9 * 60
    SchedulerLimitIso = "PT4H15M"
    SchedulerLimitMinutes = 255
    LeaseWaitSeconds = 240
    LeaseRetrySeconds = 15
    OvernightLeaseHolderTaskPatterns = @(
        "WeatherColdSnapshotNightly",
        "WeatherTrainingWindow",
        "WeatherNightlyRetrainValidatePromote",
        "WeatherIntegrationSuite_*",
        "WeatherIntegrationMerge_*"
    )
}

function Get-DailyRefreshEvidenceSchedule {
    return $script:DailyRefreshEvidenceSchedule
}

function Get-DailyRefreshEvidenceTriggerCollisions {
    # Returns every scheduled lease-holder window that overlaps Stage B's
    # [trigger, trigger + Scheduler limit) clock interval. Each holder row has
    # TaskName, StartBoundary, Recurring and ExecutionTimeLimit (ISO 8601).
    # A one-shot whose start has passed can no longer fire; an absent or zero
    # limit is unbounded and therefore always collides.
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Holders,
        [Parameter(Mandatory = $true)]
        [string]$EvidenceAt,
        [Parameter(Mandatory = $true)]
        [int]$EvidenceLimitMinutes,
        [datetime]$Now = (Get-Date)
    )

    $evidenceStart = [datetime]::ParseExact(
        $EvidenceAt, "HH:mm", [Globalization.CultureInfo]::InvariantCulture
    )
    $bStart = $evidenceStart.Hour * 60 + $evidenceStart.Minute
    $bEnd = $bStart + $EvidenceLimitMinutes
    $collisions = @()
    foreach ($holder in $Holders) {
        $start = [datetime]$holder.StartBoundary
        if (-not [bool]$holder.Recurring -and $start -le $Now) {
            continue
        }
        $limitText = [string]$holder.ExecutionTimeLimit
        $limitMinutes = $null
        if (-not [string]::IsNullOrWhiteSpace($limitText)) {
            $limitMinutes = [System.Xml.XmlConvert]::ToTimeSpan($limitText).TotalMinutes
        }
        $hStart = $start.Hour * 60 + $start.Minute
        $overlaps = $true
        if ($null -ne $limitMinutes -and $limitMinutes -gt 0) {
            $hEnd = $hStart + $limitMinutes
            $overlaps = $false
            foreach ($shift in @(-1440, 0, 1440)) {
                if ($hStart + $shift -lt $bEnd -and $bStart -lt $hEnd + $shift) {
                    $overlaps = $true
                }
            }
        }
        if ($overlaps) {
            $collisions += [pscustomobject]@{
                TaskName = [string]$holder.TaskName
                StartBoundary = $start.ToString("s")
                ExecutionTimeLimit = $limitText
            }
        }
    }
    return $collisions
}

function Enter-DailyRefreshLeaseWithin {
    # Polls the non-blocking shared-lease acquisition until it succeeds or the
    # wait budget is spent. It never waits past the budget and never takes the
    # lease from its holder; on expiry it returns $null so the caller refuses.
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Acquire,
        [Parameter(Mandatory = $true)]
        [int]$WaitSeconds,
        [Parameter(Mandatory = $true)]
        [int]$RetrySeconds,
        [scriptblock]$Sleep = { param($seconds) Start-Sleep -Seconds $seconds },
        [scriptblock]$Clock = { [DateTime]::UtcNow }
    )

    $deadline = (& $Clock).AddSeconds($WaitSeconds)
    while ($true) {
        $lease = & $Acquire
        if ($null -ne $lease) {
            return $lease
        }
        $remaining = ($deadline - (& $Clock)).TotalSeconds
        if ($remaining -le 0) {
            return $null
        }
        & $Sleep ([int][Math]::Ceiling([Math]::Min([double]$RetrySeconds, $remaining)))
    }
}

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
            "--skip-fleet-trading-replay",
            # Owner paused the paper maker 2026-09-24 (both tasks disabled). Without
            # this explicit flag 95c's settlement-only learning lane stays coupled to
            # maker readiness and the learning artifacts never refresh. Remove it when
            # the paper maker is resumed.
            "--paper-maker-paused",
            # Retired taker artifacts must not block settled-day learning.
            "--skip-taker-finalization-watchdog",
            "--skip-taker-edge-permission-map",
            "--skip-taker-tail-casebook"
        )
        $producerSlaSeconds = 14400
    } else {
        $tokens += @(
            "--status-out", "data\backtest\daily_refresh_evidence_status.json",
            "--report-out", "data\backtest\daily_refresh_evidence_report.md"
        )
        # From the 05:00 trigger the child SLA ends at 08:35, leaving 25
        # minutes for the wrapper's 09:00 teardown and 40 minutes before
        # Scheduler's 09:15 hard limit.
        $producerSlaSeconds = $script:DailyRefreshEvidenceSchedule.ProducerSlaSeconds
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
