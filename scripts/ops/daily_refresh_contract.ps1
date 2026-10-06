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
# nightly (lease until 04:45), and 05:00 would have collided with daily CLOB
# projection tiering (05:00, PT31M) and raw-tape tiering (06:00, PT41M), which
# skip on a busy lease without retrying. 06:45 follows every recurring
# overnight lease holder's hard end and keeps the 08:35 SLA / 09:00 teardown /
# 09:15 Scheduler-limit endpoints: 6600 + 240 < 8100 < 9000 seconds from the
# trigger. The lease wait stays inside the 300-second scheduler correlation so
# provenance still binds.
$script:DailyRefreshEvidenceSchedule = [ordered]@{
    TriggerAt = "06:45"
    ProducerSlaSeconds = 6600
    TeardownMinute = 9 * 60
    SchedulerLimitIso = "PT2H30M"
    SchedulerLimitMinutes = 150
    LeaseWaitSeconds = 240
    LeaseRetrySeconds = 15
}

# Scripts and modules whose quoted .ps1 paths are data (hash lists,
# manifests, status probes, generated references), never launches. Their
# references do not make them lease holders. Registrars (register_*.ps1) name
# the script a task will run but never run it, so they are reference-only too.
$script:DailyRefreshReferenceOnlyScripts = @(
    "status.ps1",
    "integration_attempt_contract.ps1",
    "weather.operations.operating_reference",
    "weather.reporting.serving_gates.registration_parameters"
)

function Get-DailyRefreshEvidenceSchedule {
    return $script:DailyRefreshEvidenceSchedule
}

function Get-WeatherSharedLeaseEntryPoints {
    # Derives, from source rather than a hand list, every scripts/ops script
    # and weather.* module that takes the shared heavy-workload lease, directly
    # or by launching something that does: scripts that call
    # Enter-WeatherHeavyWorkloadLease or Enter-WeatherHeavyWorkloadLeaseQueued (never the
    # defining library workload_admission.ps1); scripts or modules that name one of
    # those in a quoted path literal (a launch such as '-File',
    # (Join-Path ... 'x.ps1')); scripts that name a holder module as a quoted
    # 'weather.x.y' token (-m); and modules that import a holder module.
    # Comments and prose strings containing whitespace do not count.
    param([string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))

    $opsRoot = Join-Path $RepoRoot "scripts\ops"
    $srcRoot = Join-Path $RepoRoot "src"
    $code = @{}
    $kind = @{}
    foreach ($file in @(Get-ChildItem -LiteralPath $opsRoot -Filter "*.ps1" -File)) {
        $raw = [regex]::Replace([IO.File]::ReadAllText($file.FullName), '(?s)<#.*?#>', '')
        $node = $file.Name.ToLowerInvariant()
        $code[$node] = @($raw -split "`r?`n" | Where-Object { $_ -notmatch '^\s*#' }) -join "`n"
        $kind[$node] = "ps1"
    }
    $srcPrefix = (Resolve-Path -LiteralPath $srcRoot).Path.TrimEnd('\') + '\'
    foreach ($file in @(Get-ChildItem -LiteralPath (Join-Path $srcRoot "weather") -Filter "*.py" -File -Recurse)) {
        $relative = $file.FullName.Substring($srcPrefix.Length)
        $node = $relative.Substring(0, $relative.Length - 3).Replace([IO.Path]::DirectorySeparatorChar, [char]".")
        if ($node.EndsWith(".__init__")) { $node = $node.Substring(0, $node.Length - 9) }
        $raw = [IO.File]::ReadAllText($file.FullName)
        $code[$node] = @($raw -split "`r?`n" | Where-Object { $_ -notmatch '^\s*#' }) -join "`n"
        $kind[$node] = "py"
    }

    # Both the direct and the queued entry take the lease. workload_admission.ps1 defines
    # them (and its queued entry calls the direct one), so the defining library is never
    # itself a holder; a script that only dot-sources it is not either.
    $leaseCall = [regex]'(?m)^(?!\s*function\b)[^#\n]*\bEnter-WeatherHeavyWorkloadLease(?:Queued)?\b'
    $leaseLibrary = "workload_admission.ps1"
    $pathLiteral = [regex]'([''"])[^''"\s]*?([A-Za-z0-9_.-]+\.ps1)\1'
    $moduleLiteral = [regex]'([''"])(weather(?:\.\w+)+)\1'
    $fromImport = [regex]'(?m)^\s*from\s+(\.+[\w.]*|weather[\w.]*)\s+import\s+(?:\(([^)]*)\)|([^\n]+))'
    $plainImport = [regex]'(?m)^\s*import\s+(weather[\w.]*)'
    $holders = @{}
    $edges = @{}
    foreach ($node in @($code.Keys)) {
        $text = $code[$node]
        $targets = @{}
        if ($kind[$node] -eq "ps1" -and $node -ne $leaseLibrary -and $leaseCall.IsMatch($text)) { $holders[$node] = $true }
        $referenceOnly = $script:DailyRefreshReferenceOnlyScripts -contains $node -or
            ($kind[$node] -eq "ps1" -and $node.StartsWith("register_"))
        if (-not $referenceOnly) {
            foreach ($match in $pathLiteral.Matches($text)) {
                $targets[$match.Groups[2].Value.ToLowerInvariant()] = $true
            }
        }
        if ($kind[$node] -eq "ps1") {
            foreach ($match in $moduleLiteral.Matches($text)) { $targets[$match.Groups[2].Value] = $true }
        } else {
            $package = if ($node.Contains(".")) { $node.Substring(0, $node.LastIndexOf(".")) } else { $node }
            foreach ($match in $fromImport.Matches($text)) {
                $base = $match.Groups[1].Value
                if ($base.StartsWith(".")) {
                    $parent = $package
                    for ($level = 1; $level -lt ($base.Length - $base.TrimStart(".").Length); $level++) {
                        $parent = $parent.Substring(0, [Math]::Max(0, $parent.LastIndexOf(".")))
                    }
                    $rest = $base.TrimStart(".")
                    $base = if ($rest) { "$parent.$rest" } else { $parent }
                }
                $targets[$base] = $true
                $names = if ($match.Groups[2].Success) { $match.Groups[2].Value } else { $match.Groups[3].Value }
                foreach ($word in [regex]::Matches($names, '\w+')) { $targets["$base.$($word.Value)"] = $true }
            }
            foreach ($match in $plainImport.Matches($text)) { $targets[$match.Groups[1].Value] = $true }
        }
        $edges[$node] = @($targets.Keys | Where-Object { $_ -ne $node -and $_ -ne $leaseLibrary -and $code.ContainsKey($_) })
    }
    do {
        $grew = $false
        foreach ($node in @($code.Keys)) {
            if ($holders.ContainsKey($node)) { continue }
            foreach ($target in $edges[$node]) {
                if ($holders.ContainsKey($target)) {
                    $holders[$node] = $true
                    $grew = $true
                    break
                }
            }
        }
    } while ($grew)
    return @($holders.Keys | Sort-Object)
}

function Get-DailyRefreshEvidenceLeaseHolders {
    # Turns scheduled tasks into lease-holder trigger rows for the collision
    # check. A task holds the lease when any action names a lease-taking
    # script (path component) or module (-m token). Boot, logon, event and repeating triggers have no fixed clock
    # window, so they get an empty (unbounded) limit and fail closed.
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [object[]]$Tasks,
        [Parameter(Mandatory = $true)]
        [string[]]$LeaseEntryPoints,
        [string[]]$ExcludeTaskNames = @()
    )

    $holders = @()
    foreach ($task in $Tasks) {
        if ($ExcludeTaskNames -contains [string]$task.TaskName) { continue }
        if ([string]$task.State -eq "Disabled") { continue }
        $actionText = (@($task.Actions) | ForEach-Object {
            "{0} {1}" -f [string]$_.Execute, [string]$_.Arguments
        }) -join " "
        $runsLeaseScript = $false
        foreach ($name in $LeaseEntryPoints) {
            $pattern = '(?i)(^|[\\/"''\s])' + [regex]::Escape($name) + '($|["''\s])'
            if ($actionText -match $pattern) { $runsLeaseScript = $true; break }
        }
        if (-not $runsLeaseScript) { continue }
        foreach ($trigger in @($task.Triggers)) {
            if ($trigger.Enabled -eq $false) { continue }
            $triggerClass = [string]$trigger.CimClass.CimClassName
            $limit = [string]$task.Settings.ExecutionTimeLimit
            $repeats = [bool]($trigger.Repetition -and $trigger.Repetition.Interval)
            $isOnce = $triggerClass -ceq "MSFT_TaskTimeTrigger" -and -not $repeats
            if ($triggerClass -cnotin @("MSFT_TaskDailyTrigger", "MSFT_TaskTimeTrigger") -or
                $repeats -or -not $trigger.StartBoundary) {
                $limit = ""
            }
            # Compare wall clocks as registered: both tasks carry the same
            # registration-time offset, so a DST conversion would skew only one.
            $boundary = if ($trigger.StartBoundary) {
                [datetime]::ParseExact(
                    ([string]$trigger.StartBoundary).Substring(0, 19), "s",
                    [Globalization.CultureInfo]::InvariantCulture)
            } else { (Get-Date).Date }
            $holders += [pscustomobject]@{
                TaskName = [string]$task.TaskName
                StartBoundary = $boundary
                Recurring = -not $isOnce
                ExecutionTimeLimit = $limit
            }
        }
    }
    return $holders
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
        # From the 06:45 trigger the child SLA ends at 08:35, leaving 25
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
