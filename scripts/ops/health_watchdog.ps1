# Time-aware host health watchdog for the weather production PC.
#
#   .\scripts\ops\health_watchdog.ps1          # one pass (scheduled every 15 min)
#
# status.ps1 answers "what is wrong right now" for a human who is looking. This asks the
# question nobody is around to ask overnight: "does this need someone, and can it even be
# acted on at this hour?" The same FLAG means very different things at different times --
# a capture loop down at 14:00 is losing the day's grade as it happens, while at 03:00 it
# has hours of slack. So severity is a function of the clock, not just the condition.
#
# Windows that matter (host local time, America/Toronto):
#   12:00-18:00  GRADED CAPTURE WINDOW - the streak day is being decided; capture faults
#                are CRITICAL and every minute counts.
#   09:30-11:55  DAILY CHAIN - scheduled Stage A, with an absolute teardown deadline.
#   01:00-04:00  QUIET WINDOW - roll-sensitive merges; ad-hoc heavy work is 00:30-09:00.
#   23:30-00:45  DAY ROLLOVER - stale location config here blacks out capture (2026-06-29).
#
# Writes an append-only jsonl log, a latest-state file, and a regenerated human briefing.
# Deduplicates by flag fingerprint so a standing condition does not spam the log, but always
# records CRITICAL and emits a heartbeat so silence is distinguishable from a dead watchdog.
# Pure host tooling; imports nothing from a capture loop -> roll-free.
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$ExpectedSelfSha256 = "",
    [string]$StatusScriptPath = "",
    [string]$ExpectedStatusScriptSha256 = "",
    # Fixture evaluation only: evaluate windows, escalation and dedupe as of this local
    # time instead of the clock. The registered task never passes it.
    [string]$AsOf = ""
)

$ErrorActionPreference = "Stop"
if ($ExpectedSelfSha256) {
    if ($ExpectedSelfSha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
        (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256 -ErrorAction Stop).Hash -ine $ExpectedSelfSha256) {
        throw "watchdog script differs from its reviewed source binding"
    }
}
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$repo = [IO.Path]::GetFullPath($RepoRoot)
$statusScript = Join-Path $repo "scripts\ops\status.ps1"
if ($StatusScriptPath -or $ExpectedStatusScriptSha256) {
    if (-not [IO.Path]::IsPathRooted($StatusScriptPath) -or
        $ExpectedStatusScriptSha256 -notmatch '^[0-9A-Fa-f]{64}$' -or
        -not (Test-Path -LiteralPath $StatusScriptPath -PathType Leaf)) {
        throw "diagnostic status source requires an absolute file and exact SHA256"
    }
    $statusScript = (Get-Item -LiteralPath $StatusScriptPath -ErrorAction Stop).FullName
    if ((Get-FileHash -LiteralPath $statusScript -Algorithm SHA256 -ErrorAction Stop).Hash -ine $ExpectedStatusScriptSha256) {
        throw "status script differs from its reviewed source binding"
    }
}
$ErrorActionPreference = "SilentlyContinue"
$alertDir = Join-Path $repo "data\alerts"
if (-not (Test-Path $alertDir)) { New-Item -ItemType Directory -Path $alertDir -Force | Out-Null }
$log = Join-Path $alertDir "host_health_alerts.jsonl"
$latestPath = Join-Path $alertDir "host_health_latest.json"
$statePath = Join-Path $alertDir "host_health_watchdog_state.json"
$briefingPath = Join-Path $alertDir "MORNING_BRIEFING.md"
$HEARTBEAT_HOURS = 6

function Add-WeatherWatchdogLog {
    param([string]$Path, [string]$Line, [long]$MaxBytes = 16MB,
          [datetimeoffset]$Now = [datetimeoffset]::UtcNow)
    $ErrorActionPreference = 'Stop'
    $bytes = [Text.Encoding]::UTF8.GetByteCount($Line + "`n")
    if ($bytes -gt $MaxBytes) { throw 'watchdog record exceeds rotation limit' }
    # Serialize size-check/rename/append across overlapping watchdog invocations.
    # Failure must not fall back to opening the oversized active log in place.
    $lease = [IO.File]::Open($Path + '.append.lock', 'OpenOrCreate', 'ReadWrite', 'None')
    try {
        if ((Test-Path -LiteralPath $Path) -and (Get-Item -LiteralPath $Path).Length + $bytes -gt $MaxBytes) {
            $archive = Join-Path (Split-Path -Parent $Path) (
                'host_health_alerts.{0}.{1}.jsonl' -f $Now.UtcDateTime.ToString('yyyyMMddTHHmmssfffffffZ'), [guid]::NewGuid().ToString('N'))
            [IO.File]::Move($Path, $archive)
        }
        [IO.File]::AppendAllText($Path, $Line + "`n", [Text.UTF8Encoding]::new($false))
    } finally { $lease.Dispose() }
}

function Read-WeatherWatchdogTail {
    param([string]$Path, [int]$MaxBytes = 1MB)
    $stream = [IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
    try {
        $start = [Math]::Max(0, $stream.Length - $MaxBytes)
        [void]$stream.Seek($start, 'Begin')
        $reader = [IO.BinaryReader]::new($stream)
        try { $tail = [Text.Encoding]::UTF8.GetString($reader.ReadBytes($MaxBytes)) } finally { $reader.Dispose() }
        $lines = @($tail -split "`n")
        if ($start -gt 0) { $lines = @($lines | Select-Object -Skip 1) }
        $lines | Select-Object -Last 400
    } finally { $stream.Dispose() }
}

# ---- gather (delegate all interpretation of "is this normal" to status.ps1) ----
$psExe = Join-Path $PSHOME "powershell.exe"
if ($ExpectedStatusScriptSha256) {
    $raw = & $psExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $statusScript -RepoRoot $repo -Json -ExpectedSelfSha256 $ExpectedStatusScriptSha256 2>$null
}
else {
    $raw = & $psExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $statusScript -RepoRoot $repo -Json 2>$null
}
$status = $null
try { $status = ($raw | Out-String) | ConvertFrom-Json } catch {}
if ($null -eq $status) {
    # The digest itself failing is a real fault: we are now blind.
    $status = [PSCustomObject]@{
        verdict = "ATTENTION"; flags = @("status.ps1 did not return parseable JSON - host digest is BLIND")
        warns   = @(); streak = $null
    }
}

# ---- reviewed expected-disabled tasks: a named list with reasons, never a blanket silence ----
# Only the disabled-state flag of an exactly named task becomes a note. Every other flag about
# that task, and every other unexpectedly disabled task, still alerts.
$expectedDisabledTasks = [ordered]@{
    "WeatherMarketMakingDailyRoll"           = "live and paper maker paused by owner 2026-09-25"
    "WeatherMarketMakingDailyRollSupervisor" = "live and paper maker paused by owner 2026-09-25"
}
$expectedDisabledNotes = @()

# ---- which window are we in? ----
$now = if ($AsOf) { [datetime]::Parse($AsOf, [cultureinfo]::InvariantCulture) } else { Get-Date }
$h = $now.Hour + ($now.Minute / 60.0)
$inCapture = ($h -ge 12 -and $h -lt 18)
$inChain = ($h -ge 9.5 -and $h -lt (11 + 55.0 / 60.0))
$inQuiet = ($h -ge 1 -and $h -lt 4)
$inRollover = ($h -ge 23.5 -or $h -lt 0.75)
$window = if ($inCapture) { "graded_capture_window" }
elseif ($inChain) { "daily_chain" }
elseif ($inQuiet) { "quiet_window" }
elseif ($inRollover) { "day_rollover" }
else { "off_peak" }

# ---- classify each flag: what is it, how bad NOW, and when can it be acted on ----
function Get-FlagClass($text) {
    if ($text -match "^RECONCILIATION_PUBLICATION_") { return "reconciliation_publication" }
    # Swarm P audit 2026-10-07 G1/G3: these used to fall through to MEDIUM scheduled_job.
    if ($text -match "^UNEXPECTED SHUTDOWN") { return "host_stability" }
    if ($text -match "system clock (is not synchronized|has no successful|last received)") { return "capture_integrity" }
    if ($text -match "^STALENESS_SWEEP") { return "staleness_sweep" }
    if ($text -match "capture loop DOWN|capture loop ERRORING|TODAY capture AT_RISK|capture alert raised") { return "capture" }
    if ($text -match "LOW RAM|HIGH COMMIT") { return "memory" }
    if ($text -match "LOW DISK|disk filling|disk headroom") { return "capacity" }
    if ($text -match "SETTLEMENT HOLE") { return "settlement" }
    if ($text -match "mirror") { return "durability" }
    if ($text -match "REBOOT PENDING|logon-dependent") { return "resilience" }
    if ($text -match "streak checker failed|BLIND|MEMORY GUARD UNKNOWN|deployment PIN MISMATCH") { return "observability" }
    return "scheduled_job"
}
function Get-FlagAction($class) {
    $actionWindow = @{
        reconciliation_publication = "preserve the exact marker and evidence; do not manually invoke or retry WeatherOneShotPush; obtain reviewed recovery authority"
        capture       = "NOW - the graded window is 12:00-18:00"
        memory        = "NOW - memory pressure is the streak's primary failure mode"
        capacity      = "use repository-owned tiering in the admitted 00:30-09:00 window with the shared lease and exact retention gates; preserve unverified evidence"
        settlement    = "tonight - scripts\ops\chain_recovery_run.ps1 -ResumeFrom <failed step> -TargetDate <date> -Refetch, in the quiet window"
        durability    = "verify current archive and restore evidence; do not resume an operator-paused mirror or delete unverified source data"
        resilience    = "any time, but a reboot must not happen before it is fixed"
        observability = "NOW - nothing else is watching while this is broken"
        host_stability = "NOW - verify today's capture grade and that all three capture workers recovered; an outage inside 12:00-18:00 ends the streak"
        capture_integrity = "NOW - restore Windows Time sync (service running, valid source) and record the unsynchronized interval; capture timestamps from it are suspect"
        staleness_sweep = "read data\alerts\STALENESS_SWEEP.md for the owning check; repair the producer in the admitted 00:30-09:00 window, never touch the artifact's timestamp"
        scheduled_job = "next scheduled run, or resume in the quiet window 01:00-04:00"
    }
    return [string]$actionWindow[[string]$class]
}
$entries = @()
foreach ($f in @($status.flags)) {
    if (-not $f) { continue }
    if ([string]$f -cmatch '^(\S+) (?:unexpectedly DISABLED|is armed for .+ but DISABLED - it will not fire)$' -and
        $expectedDisabledTasks.Contains($Matches[1])) {
        $expectedDisabledNotes += "$($Matches[1]) is expected-disabled: $($expectedDisabledTasks[$Matches[1]])"
        continue
    }
    $class = Get-FlagClass $f
    $sev = switch ($class) {
        "capture" { if ($inCapture) { "CRITICAL" } elseif ($inRollover) { "HIGH" } else { "HIGH" } }
        "memory" { if ($inCapture) { "CRITICAL" } else { "HIGH" } }
        "reconciliation_publication" { "HIGH" }
        "observability" { "HIGH" }
        "capacity" { "HIGH" }
        # Graded-window overlap and unclean-boot counts are applied in the second pass.
        "host_stability" { "HIGH" }
        "capture_integrity" { if ($inCapture) { "CRITICAL" } else { "HIGH" } }
        # Carry the sweep's own severity through: its CRITICAL row is at least HIGH here;
        # an unreadable/stale sweep snapshot starts at MEDIUM. Escalation is in the second pass.
        "staleness_sweep" { if ($f -match "^STALENESS_SWEEP CRITICAL") { "HIGH" } else { "MEDIUM" } }
        # A settlement hole is not a scheduled-job hiccup. The evidence is already lost
        # for that date and no future run reclaims it, so this outranks anything whose
        # cost is bounded by "wait for the next run". It escalates with age because each
        # extra day is another backfill nobody has scheduled: the 2026-08-06 hole sat at
        # MEDIUM, below 33 routine state_change entries, while it was the only thing in
        # the briefing that was actively costing us evidence.
        "settlement" {
            $holeDays = 0
            if ($f -match "^SETTLEMENT HOLE: (\d+) date\(s\)") { $holeDays = [int]$Matches[1] }
            if ($holeDays -ge 2) { "CRITICAL" } else { "HIGH" }
        }
        "durability" { "MEDIUM" }
        "resilience" { "MEDIUM" }
        default { if ($inChain) { "HIGH" } else { "MEDIUM" } }
    }
    $entries += [PSCustomObject]@{
        severity = $sev; class = $class; flag = $f; act = (Get-FlagAction $class)
    }
}
$rank = @{ CRITICAL = 0; HIGH = 1; MEDIUM = 2 }

# ---- second pass: graded-window overlap, reviewed demotions, escalation, dedupe keys ----
# Swarm P audit 2026-10-07 G1/G3/G4. Dedupe keys drop volatile numbers (ages, counts, byte
# sizes, timestamps) so a standing condition whose numbers tick does not write a new
# state_change row every pass. "Consecutive failures" counts how often the timestamps inside
# an otherwise unchanged condition moved (a new failed run of the same job); the condition
# age is how long the watchdog has seen it continuously.
#
# Two over-merges would be false silences (PR #255 Defender G4), so these keep identity:
# - LOW DISK depth: the first "<n> GB" figure becomes a depth bucket (<50, <25, <10, <5 GiB,
#   or >=50), so each step down is a new condition while ticks within a bucket still dedupe.
# - SETTLEMENT HOLE dates: the sorted, de-duplicated missing-date set is appended, so a hole
#   moving to (or adding) a date re-alerts while the same set in any order still dedupes.
function Get-WeatherDiskDepthBucket([double]$FreeGiB) {
    if ($FreeGiB -lt 5) { return "<5GiB" }
    if ($FreeGiB -lt 10) { return "<10GiB" }
    if ($FreeGiB -lt 25) { return "<25GiB" }
    if ($FreeGiB -lt 50) { return "<50GiB" }
    return ">=50GiB"
}
function Get-WeatherFlagDedupKey([string]$Text) {
    # The owner-reset annotation is never part of a condition's identity (owner 2026-10-07):
    # acknowledging a reset must not mint a new fingerprint, reset first_seen or re-alert.
    $k = [regex]::Replace([string]$Text, '^(UNEXPECTED SHUTDOWN.*?) - owner reset acknowledged \d{4}-\d{2}-\d{2} \d{2}:\d{2} \(.*\)$', '$1', 'Singleline')
    $depthBucket = $null
    if ($k -match '^LOW DISK') {
        # The lookbehind keeps a comma-decimal "23,5 GB" from parsing as 5 (PR #255 fold Defender N6);
        # such a row falls back to the plain '#' key instead of a wrong, deeper bucket.
        $depth = [regex]::Match($k, '(?<![\d.,])(\d+(?:\.\d+)?) GB')
        if ($depth.Success) {
            $depthBucket = Get-WeatherDiskDepthBucket ([double]::Parse($depth.Groups[1].Value, [cultureinfo]::InvariantCulture))
        }
    }
    $holeDates = $null
    if ($k -match '^SETTLEMENT HOLE: .*?\[([^\]]*)\]') {
        $holeDates = (@($Matches[1] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) |
            Sort-Object -Unique) -join ","
    }
    $k = [regex]::Replace($k, '\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?', '<ts>')
    $k = [regex]::Replace($k, '\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?)?', '<ts>')
    $k = [regex]::Replace($k, '(?<![0-9A-Za-z_])\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?', '<ts>')
    # Plain numbers become '#', but identifiers (Weather110nTask) and result codes (0x1) stay.
    $k = [regex]::Replace($k, '(?<![0-9A-Za-z_])(?!0x[0-9A-Fa-f])\d+(?:[.,]\d+)*', '#')
    # Bucket labels are applied after the '#' pass so their own digits survive.
    if ($depthBucket) { $k = ([regex]'# GB').Replace($k, $depthBucket, 1) }
    if ($null -ne $holeDates) { $k = "$k|dates=$holeDates" }
    return $k
}
function Get-WeatherFlagTimestampTokens([string]$Text) {
    $found = @([regex]::Matches([string]$Text,
        '\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?|\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?)?') |
        ForEach-Object { $_.Value })
    return ($found -join "|")
}
# Owner reset acknowledgement (owner 2026-10-07; scripts\ops\owner_reset_note.ps1): status.ps1
# may append " - owner reset acknowledged <yyyy-MM-dd HH:mm> (<note>)" to an UNEXPECTED SHUTDOWN
# flag. It is annotation only. Class, severity, outage parsing, timestamps and the dedupe key all
# use the text without it, and the alert gains owner_reset_ack. Windows cannot tell an owner
# reset from a crash, so the flag is never suppressed or demoted here.
function Split-WeatherOwnerResetAck([string]$Text) {
    $m = [regex]::Match([string]$Text, '^(UNEXPECTED SHUTDOWN.*?) - owner reset acknowledged (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \((.*)\)$', 'Singleline')
    if (-not $m.Success) { return [pscustomobject]@{ text = [string]$Text; ack = $null } }
    return [pscustomobject]@{ text = $m.Groups[1].Value; ack = [ordered]@{ at = $m.Groups[2].Value; note = $m.Groups[3].Value } }
}
function Test-WeatherOutageOverlapsGradedWindow([datetime]$Start, [datetime]$End) {
    if ($End -lt $Start) { $swap = $Start; $Start = $End; $End = $swap }
    for ($day = $Start.Date; $day -le $End.Date; $day = $day.AddDays(1)) {
        if ($Start -lt $day.AddHours(18) -and $End -gt $day.AddHours(12)) { return $true }
    }
    return $false
}

# Reviewed, reasoned demotions of standing sweep CRITICALs: named checks only, never a blanket
# silence. They stay visible at MEDIUM and never escalate; every other sweep row still does.
$demotedSweepChecks = [ordered]@{
    "learning/daily_learning"            = "standing since 2026-07-10; the daily-learning rollup is off the capture and settlement path (Swarm P audit 2026-10-07 G3)"
    "learning/market_beating_scoreboard" = "standing since 2026-07-10; objective scoreboard staleness costs no capture evidence (Swarm P audit 2026-10-07 G3)"
}

$prev = $null
if (Test-Path $statePath) { try { $prev = Get-Content $statePath -Raw | ConvertFrom-Json } catch {} }
$prevTracking = @{}
if ($prev -and $prev.tracking) {
    foreach ($p in $prev.tracking.PSObject.Properties) { $prevTracking[$p.Name] = $p.Value }
}
$tracking = [ordered]@{}
$invariant = [cultureinfo]::InvariantCulture
foreach ($e in $entries) {
    $key = "$($e.class)|$(Get-WeatherFlagDedupKey $e.flag)"
    $demotedReason = $null
    $uncleanBoots7d = $null
    $ownerAck = Split-WeatherOwnerResetAck $e.flag
    $baseFlag = $ownerAck.text
    if ($e.class -eq "host_stability") {
        $bootText = $null; $startText = $null
        $outage = [regex]::Match($baseFlag, 'outage (\d{4}-\d{2}-\d{2} \d{2}:\d{2}|start unknown) -> (\d{4}-\d{2}-\d{2} \d{2}:\d{2})')
        if ($outage.Success) { $bootText = $outage.Groups[2].Value; $startText = $outage.Groups[1].Value }
        $end = [datetime]::MinValue; $start = [datetime]::MinValue
        $haveEnd = $false
        if ($bootText) { $haveEnd = [datetime]::TryParseExact($bootText, 'yyyy-MM-dd HH:mm', $invariant, 'None', [ref]$end) }
        elseif ($baseFlag -match '^UNEXPECTED SHUTDOWN (.+?) - verify') {
            # Pre-2026-10-07 status format: only the boot time, in the host culture.
            $haveEnd = [datetime]::TryParse($Matches[1], [ref]$end)
        }
        if ($haveEnd) {
            if (-not ($startText -and [datetime]::TryParseExact($startText, 'yyyy-MM-dd HH:mm', $invariant, 'None', [ref]$start))) { $start = $end }
            if (Test-WeatherOutageOverlapsGradedWindow $start $end) { $e.severity = "CRITICAL" }
            # A different unclean boot is a new condition, not a ticking number.
            $key = "$key|boot=$($end.ToString('yyyy-MM-dd HH:mm', $invariant))"
        }
        if ($baseFlag -match '(\d+) unclean boot\(s\) in 7d') { $uncleanBoots7d = [int]$Matches[1] }
    }
    $stamps = Get-WeatherFlagTimestampTokens $baseFlag
    $firstSeen = $now
    $failures = 1
    $before = $prevTracking[$key]
    if ($before) {
        try { $firstSeen = [datetime]::Parse([string]$before.first_seen, $invariant, [Globalization.DateTimeStyles]::RoundtripKind) } catch { $firstSeen = $now }
        $failures = [int]$before.consecutive_failures
        if ($failures -lt 1) { $failures = 1 }
        if ([string]$before.timestamps -cne $stamps) { $failures++ }
    }
    if ($firstSeen -gt $now) { $firstSeen = $now }
    $tracking[$key] = [ordered]@{ first_seen = $firstSeen.ToString("o"); timestamps = $stamps; consecutive_failures = $failures }
    $ageHours = [math]::Round(($now - $firstSeen).TotalHours, 2)
    if ($e.class -eq "staleness_sweep") {
        $check = if ($e.flag -match '^STALENESS_SWEEP CRITICAL \[([^\]]+)\]') { $Matches[1] } else { $null }
        if ($check -and $demotedSweepChecks.Contains($check)) {
            $e.severity = "MEDIUM"
            $demotedReason = [string]$demotedSweepChecks[$check]
        }
        elseif ($check) {
            $reportedDays = 0.0
            if ($e.flag -match '(\d+(?:\.\d+)?)d old') { $reportedDays = [double]::Parse($Matches[1], $invariant) }
            if ($reportedDays -ge 3 -or $ageHours -ge 72 -or $failures -ge 3) { $e.severity = "CRITICAL" }
        }
        elseif ($ageHours -ge 24 -or $failures -ge 2) { $e.severity = "HIGH" }
    }
    elseif ($e.class -eq "scheduled_job") {
        if ($failures -ge 5 -and $ageHours -ge 72) { $e.severity = "CRITICAL" }
        elseif (($failures -ge 2 -or $ageHours -ge 24) -and $e.severity -eq "MEDIUM") { $e.severity = "HIGH" }
    }
    $e | Add-Member -NotePropertyName dedup_key -NotePropertyValue $key
    $e | Add-Member -NotePropertyName consecutive_failures -NotePropertyValue $failures
    $e | Add-Member -NotePropertyName condition_age_hours -NotePropertyValue $ageHours
    $e | Add-Member -NotePropertyName demoted -NotePropertyValue $demotedReason
    $e | Add-Member -NotePropertyName unclean_boots_7d -NotePropertyValue $uncleanBoots7d
    $e | Add-Member -NotePropertyName owner_reset_ack -NotePropertyValue $ownerAck.ack
    if ($demotedReason) { $e.act = "$($e.act) [demoted: $demotedReason]" }
}
$entries = @($entries | Sort-Object { $rank[$_.severity] })
$top = if ($entries.Count -gt 0) { $entries[0].severity } else { "OK" }
$notes = @(@($status.warns) | Where-Object { $_ }) + $expectedDisabledNotes

# ---- dedupe: log on change, on CRITICAL, or as a heartbeat ----
$fingerprint = ""
if ($entries.Count -gt 0) {
    $fingerprint = (($entries | ForEach-Object { "$($_.severity)|$($_.dedup_key)" } | Sort-Object) -join "##")
}
$prevFp = if ($prev) { [string]$prev.fingerprint } else { "<none>" }
$lastLogged = $null
if ($prev -and $prev.last_logged) { try { $lastLogged = [datetime]$prev.last_logged } catch {} }
$hoursSince = if ($lastLogged) { ($now - $lastLogged).TotalHours } else { 999 }

$changed = ($fingerprint -ne $prevFp)
$shouldLog = $changed -or ($top -eq "CRITICAL") -or ($hoursSince -ge $HEARTBEAT_HOURS)
$reason = if ($changed) { "state_change" } elseif ($top -eq "CRITICAL") { "critical_repeat" } else { "heartbeat" }

$record = [ordered]@{
    ts = $now.ToString("o"); window = $window; verdict = [string]$status.verdict
    top_severity = $top; log_reason = $reason
    streak = $(if ($status.streak) { "$($status.streak.days)/$($status.streak.target)" } else { "?" })
    today = $(if ($status.streak) { [string]$status.streak.today } else { "?" })
    alerts = @($entries | ForEach-Object { [ordered]@{ severity = $_.severity; class = $_.class; flag = $_.flag; act = $_.act
                consecutive_failures = $_.consecutive_failures; condition_age_hours = $_.condition_age_hours
                demoted = $_.demoted; unclean_boots_7d = $_.unclean_boots_7d; owner_reset_ack = $_.owner_reset_ack } })
    notes = $notes
    expected_disabled_tasks = $expectedDisabledTasks
    demoted_sweep_checks = $demotedSweepChecks
    host_stability = $status.host_stability
    watchdog_deployment = $status.watchdog_deployment
    reconciliation_publication = $status.reconciliation_publication
    memory_guard = $status.memory_guard
    status_script_path = $statusScript
    expected_status_script_sha256 = $ExpectedStatusScriptSha256
}
$record | ConvertTo-Json -Depth 6 | Set-Content -Path $latestPath -Encoding utf8
if ($shouldLog) {
    try { Add-WeatherWatchdogLog -Path $log -Line ($record | ConvertTo-Json -Depth 6 -Compress) -Now $now }
    catch {
        # Do not advance dedup/heartbeat state after a failed append.
        Write-Error "Watchdog log append/rotation failed: $($_.Exception.Message)" -ErrorAction Continue
        exit 2
    }
}
[ordered]@{ fingerprint = $fingerprint; last_logged = $(if ($shouldLog) { $now.ToString("o") } elseif ($lastLogged) { $lastLogged.ToString("o") } else { $now.ToString("o") })
    tracking = $tracking } |
ConvertTo-Json -Depth 5 | Set-Content -Path $statePath -Encoding utf8

# ---- regenerate the human briefing (what happened while nobody was looking) ----
$since = $now.AddHours(-24)
$recent = @()
$briefingFiles = @(Get-ChildItem -LiteralPath $alertDir -Filter 'host_health_alerts.*.jsonl' -File |
    Sort-Object Name -Descending | Select-Object -First 1)
$briefingFiles += @(Get-Item -LiteralPath $log -ErrorAction SilentlyContinue)
foreach ($briefingFile in $briefingFiles) {
    foreach ($line in (Read-WeatherWatchdogTail -Path $briefingFile.FullName)) {
        if (-not $line) { continue }
        try { $r = $line | ConvertFrom-Json } catch { continue }
        try { if ([datetime]$r.ts -ge $since) { $recent += $r } } catch {}
    }
}
$worst = "OK"
foreach ($r in $recent) {
    $s = [string]$r.top_severity
    if (-not $rank.ContainsKey($s)) { continue }
    if ($worst -eq "OK" -or $rank[$s] -lt $rank[$worst]) { $worst = $s }
}

$md = New-Object System.Collections.Generic.List[string]
$md.Add("# Host health briefing")
$md.Add("")
$md.Add("Generated $($now.ToString('yyyy-MM-dd HH:mm')) - last 24h in bounded tails (up to 400 rows / 1 MiB each from active log and newest archive); may omit older entries. Regenerated every run; do not edit.")
$md.Add("")
$md.Add("**Now:** verdict $([string]$status.verdict), window ``$window``, streak $($record.streak), today $($record.today).")
$md.Add("**Worst in 24h:** $worst over $($recent.Count) logged state change(s).")
$md.Add("")
if ($entries.Count -eq 0) {
    $md.Add("No open flags.")
}
else {
    $md.Add("## Open now")
    $md.Add("")
    foreach ($e in $entries) {
        $md.Add("- **$($e.severity)** [$($e.class)] $($e.flag)")
        $md.Add("  - act: $($e.act)")
    }
}
if ($notes.Count -gt 0) {
    $md.Add("")
    $md.Add("## Standing notes")
    $md.Add("")
    foreach ($w in $notes) { $md.Add("- $w") }
}
if ($recent.Count -gt 0) {
    $md.Add("")
    $md.Add("## Timeline (24h)")
    $md.Add("")
    foreach ($r in ($recent | Select-Object -Last 20)) {
        $when = try { ([datetime]$r.ts).ToString("MM-dd HH:mm") } catch { "?" }
        $md.Add("- ``$when`` [$($r.window)] $($r.top_severity) - $($r.log_reason)")
    }
}
$md -join "`r`n" | Set-Content -Path $briefingPath -Encoding utf8

if ($top -eq "CRITICAL") { exit 2 }
exit 0
