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
#   09:30-11:00  DAILY CHAIN - settlement/grading of yesterday runs here.
#   01:00-04:00  QUIET WINDOW - the only safe slot for code merges and heavy steps.
#   23:30-00:45  DAY ROLLOVER - stale location config here blacks out capture (2026-06-29).
#
# Writes an append-only jsonl log, a latest-state file, and a regenerated human briefing.
# Deduplicates by flag fingerprint so a standing condition does not spam the log, but always
# records CRITICAL and emits a heartbeat so silence is distinguishable from a dead watchdog.
# Pure host tooling; imports nothing from a capture loop -> roll-free.
[CmdletBinding()]
param()

$ErrorActionPreference = "SilentlyContinue"
$repo = "C:\Users\micha\Desktop\github\weather"
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
$statusScript = Join-Path $repo "scripts\ops\status.ps1"
$psExe = Join-Path $PSHOME "powershell.exe"
$raw = & $psExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $statusScript -Json 2>$null
$status = $null
try { $status = ($raw | Out-String) | ConvertFrom-Json } catch {}
if ($null -eq $status) {
    # The digest itself failing is a real fault: we are now blind.
    $status = [PSCustomObject]@{
        verdict = "ATTENTION"; flags = @("status.ps1 did not return parseable JSON - host digest is BLIND")
        warns   = @(); streak = $null
    }
}

# ---- which window are we in? ----
$now = Get-Date
$h = $now.Hour + ($now.Minute / 60.0)
$inCapture = ($h -ge 12 -and $h -lt 18)
$inChain = ($h -ge 9.5 -and $h -lt 11)
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
    if ($text -match "capture loop DOWN|TODAY capture AT_RISK|capture alert raised") { return "capture" }
    if ($text -match "LOW RAM") { return "memory" }
    if ($text -match "LOW DISK") { return "capacity" }
    if ($text -match "SETTLEMENT HOLE") { return "settlement" }
    if ($text -match "mirror") { return "durability" }
    if ($text -match "REBOOT PENDING|logon-dependent") { return "resilience" }
    if ($text -match "streak checker failed|BLIND") { return "observability" }
    return "scheduled_job"
}
function Get-FlagAction($class) {
    $actionWindow = @{
        reconciliation_publication = "preserve the exact marker and evidence; do not manually invoke or retry WeatherOneShotPush; obtain reviewed recovery authority"
        capture       = "NOW - the graded window is 12:00-18:00"
        memory        = "NOW - memory pressure is the streak's primary failure mode"
        capacity      = "any time; tiering/cleanup is memory-light"
        settlement    = "tonight - scripts\ops\chain_recovery_run.ps1 -ResumeFrom <failed step> -TargetDate <date> -Refetch, in the quiet window"
        durability    = "any time; mirror runs nightly 04:30"
        resilience    = "any time, but a reboot must not happen before it is fixed"
        observability = "NOW - nothing else is watching while this is broken"
        scheduled_job = "next scheduled run, or resume in the quiet window 01:00-04:00"
    }
    return [string]$actionWindow[[string]$class]
}
$entries = @()
foreach ($f in @($status.flags)) {
    if (-not $f) { continue }
    $class = Get-FlagClass $f
    $sev = switch ($class) {
        "capture" { if ($inCapture) { "CRITICAL" } elseif ($inRollover) { "HIGH" } else { "HIGH" } }
        "memory" { if ($inCapture) { "CRITICAL" } else { "HIGH" } }
        "reconciliation_publication" { "HIGH" }
        "observability" { "HIGH" }
        "capacity" { "HIGH" }
        # A settlement hole is not a scheduled-job hiccup. The evidence is already lost
        # for that date and no future run reclaims it, so this outranks anything whose
        # cost is bounded by "wait for the next run". It escalates with age because each
        # extra day is another backfill nobody has scheduled: the 2026-08-06 hole sat at
        # MEDIUM, below 33 routine state_change entries, while it was the only thing in
        # the briefing that was actively costing us evidence.
        "settlement" {
            $holeDays = 0
            if ($f -match "\((\d+) day") { $holeDays = [int]$Matches[1] }
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
$entries = @($entries | Sort-Object { $rank[$_.severity] })
$top = if ($entries.Count -gt 0) { $entries[0].severity } else { "OK" }

# ---- dedupe: log on change, on CRITICAL, or as a heartbeat ----
$fingerprint = ""
if ($entries.Count -gt 0) {
    $fingerprint = (($entries | ForEach-Object { "$($_.severity)|$($_.flag)" } | Sort-Object) -join "##")
}
$prev = $null
if (Test-Path $statePath) { try { $prev = Get-Content $statePath -Raw | ConvertFrom-Json } catch {} }
$prevFp = if ($prev) { [string]$prev.fingerprint } else { "<none>" }
$lastLogged = $null
if ($prev -and $prev.last_logged) { try { $lastLogged = [datetime]$prev.last_logged } catch {} }
$hoursSince = if ($lastLogged) { ((Get-Date) - $lastLogged).TotalHours } else { 999 }

$changed = ($fingerprint -ne $prevFp)
$shouldLog = $changed -or ($top -eq "CRITICAL") -or ($hoursSince -ge $HEARTBEAT_HOURS)
$reason = if ($changed) { "state_change" } elseif ($top -eq "CRITICAL") { "critical_repeat" } else { "heartbeat" }

$record = [ordered]@{
    ts = $now.ToString("o"); window = $window; verdict = [string]$status.verdict
    top_severity = $top; log_reason = $reason
    streak = $(if ($status.streak) { "$($status.streak.days)/$($status.streak.target)" } else { "?" })
    today = $(if ($status.streak) { [string]$status.streak.today } else { "?" })
    alerts = @($entries | ForEach-Object { [ordered]@{ severity = $_.severity; class = $_.class; flag = $_.flag; act = $_.act } })
    notes = @($status.warns)
    reconciliation_publication = $status.reconciliation_publication
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
[ordered]@{ fingerprint = $fingerprint; last_logged = $(if ($shouldLog) { $now.ToString("o") } elseif ($lastLogged) { $lastLogged.ToString("o") } else { $now.ToString("o") }) } |
ConvertTo-Json | Set-Content -Path $statePath -Encoding utf8

# ---- regenerate the human briefing (what happened while nobody was looking) ----
$since = (Get-Date).AddHours(-24)
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
if (@($status.warns).Count -gt 0) {
    $md.Add("")
    $md.Add("## Standing notes")
    $md.Add("")
    foreach ($w in @($status.warns)) { $md.Add("- $w") }
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
