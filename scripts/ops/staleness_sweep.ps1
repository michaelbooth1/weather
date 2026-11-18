<#
.SYNOPSIS
    Daily sweep for things that were correct when written and quietly expired.

.DESCRIPTION
    This project's dominant failure mode is not breakage, it is silent staleness. Five separate
    defects found on 2026-08-06 were all the same shape -- something correct at the time that
    went wrong by the calendar moving, with nothing watching:

      season window (5,10)-(6,30)   expired 2026-06-30, archive covered zero target dates
      daily_learning rollup         last wrote 2026-07-10, 27 chain runs never reached it
      market-beating scoreboard     last wrote 2026-07-10, the objective's own scorecard
      clob_enrichment closure       last reported 2026-07-13, roll verdicts derived without it
      HGB serving artifacts         fitted 2026-06-10..13, still serving in August

    Every existing monitor answers "is it broken now?". None answers "should this have been
    refreshed by now?". That is the gap this fills.

    Each check DECLARES its own expected freshness and the reason. Adding a watch is one row.
    The reason is printed with the violation, so a stale item explains its own cost rather than
    being a bare timestamp someone has to interpret at 08:00.

    Cheap by construction: explicit paths only, no recursive walks under data/. A runaway
    recursive scan starved capture on 2026-07-12 and again nearly did on 2026-08-06.

.PARAMETER JsonOut
    Append-only history. Default data\alerts\staleness_sweep.jsonl
.PARAMETER MarkdownOut
    Latest human-readable snapshot. Default data\alerts\STALENESS_SWEEP.md
.OUTPUTS
    Exit 0 all fresh, 1 one or more WARN, 2 one or more CRITICAL. A KNOWN row (a listed,
    still-held $knownCriticals entry) counts toward none of them. Each JSONL row also carries
    known_count and task_results, a last-run snapshot of every config\scheduled_tasks.json task.
#>
[CmdletBinding()]
param(
    [string]$JsonOut = "",
    [string]$MarkdownOut = ""
)

$ErrorActionPreference = "Continue"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $JsonOut) { $JsonOut = Join-Path $repo "data\alerts\staleness_sweep.jsonl" }
if (-not $MarkdownOut) { $MarkdownOut = Join-Path $repo "data\alerts\STALENESS_SWEEP.md" }
$now = Get-Date
# File ages use UTC on both sides; a local LastWriteTime is off by up to an hour across DST.
$nowUtc = [DateTime]::UtcNow
$findings = @()

function Add-Finding($name, $severity, $detail, $why, $ageDays, $limitDays) {
    $script:findings += [PSCustomObject]@{
        check = $name; severity = $severity; detail = $detail; why = $why
        age_days = $(if ($null -ne $ageDays) { [math]::Round($ageDays, 2) } else { $null })
        limit_days = $limitDays
    }
}

function Test-FileAge($name, $relPath, $warnDays, $critDays, $why) {
    $path = Join-Path $repo $relPath
    if (-not (Test-Path -LiteralPath $path)) {
        Add-Finding $name "CRITICAL" "missing: $relPath" $why $null $warnDays; return
    }
    $age = ($nowUtc - (Get-Item -LiteralPath $path).LastWriteTimeUtc).TotalDays
    $sev = if ($age -gt $critDays) { "CRITICAL" } elseif ($age -gt $warnDays) { "WARN" } else { "OK" }
    Add-Finding $name $sev ("{0} is {1:N1}d old" -f $relPath, $age) $why $age $warnDays
}

function Get-WeatherStageAChainFinding {
    # Did the latest Stage-A run COMPLETE? The report mtime cannot answer this: the chain
    # checkpoints daily_refresh_report.md after every step, so a chain killed at its 11:55
    # deadline leaves a fresh report. The Stage-A manifest is published COMPLETED only by the
    # end-of-run write (checkpoints write RUNNING), so it is the authority. The report is a
    # fallback only when the manifest is missing or unreadable.
    param([string]$ManifestPath, [string]$ReportPath, [datetime]$Now,
          [double]$WarnDays = 1, [double]$CritDays = 2)
    $manifest = $null
    if (Test-Path -LiteralPath $ManifestPath) {
        try { $manifest = Get-Content -LiteralPath $ManifestPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop }
        catch { $manifest = $null }
    }
    if ($null -ne $manifest -and $manifest.status) {
        $status = [string]$manifest.status
        $age = ($Now - (Get-Item -LiteralPath $ManifestPath).LastWriteTime).TotalDays
        if ($status -eq 'COMPLETED') {
            $sev = if ($age -gt $CritDays) { 'CRITICAL' } elseif ($age -gt $WarnDays) { 'WARN' } else { 'OK' }
            $detail = 'latest Stage-A run COMPLETED at {0}; manifest is {1:N1}d old' -f $manifest.completed_at_utc, $age
        } elseif ($status -eq 'RUNNING' -and $age -le (2 / 24)) {
            $sev = 'WARN'
            $detail = 'latest Stage-A run (started {0}) is RUNNING; last checkpoint {1:N1}h ago - in progress, or killed if this persists' -f $manifest.started_at_utc, ($age * 24)
        } else {
            $sev = 'CRITICAL'
            $detail = 'latest Stage-A run (started {0}) never reached COMPLETED: manifest status {1}, last written {2:N1}d ago (a chain killed mid-run still leaves a fresh checkpointed report)' -f $manifest.started_at_utc, $status, $age
        }
        return [PSCustomObject]@{ severity = $sev; detail = $detail; age_days = $age; source = 'manifest' }
    }
    if (-not (Test-Path -LiteralPath $ReportPath)) {
        return [PSCustomObject]@{ severity = 'CRITICAL'; detail = 'Stage-A manifest unreadable and report missing'; age_days = $null; source = 'none' }
    }
    $age = ($Now - (Get-Item -LiteralPath $ReportPath).LastWriteTime).TotalDays
    $text = ''
    try { $text = [string](Get-Content -LiteralPath $ReportPath -Raw -ErrorAction Stop) } catch { $text = '' }
    if ($text -match 'Status: \*\*running\*\*') {
        return [PSCustomObject]@{ severity = 'CRITICAL'; age_days = $age; source = 'report'
            detail = ('Stage-A manifest unreadable; report ({0:N1}d old) is a mid-run checkpoint (Status: running), so the chain did not complete' -f $age) }
    }
    $sev = if ($age -gt $CritDays) { 'CRITICAL' } elseif ($age -gt $WarnDays) { 'WARN' } else { 'OK' }
    return [PSCustomObject]@{ severity = $sev; age_days = $age; source = 'report'
        detail = ('Stage-A manifest unreadable; report is {0:N1}d old and not a running checkpoint' -f $age) }
}

function Get-WeatherStageABarrierFinding {
    # Completion and success are separate contracts: a contained barrier error
    # publishes COMPLETED with payload_status=critical so learning can continue.
    param([string]$ManifestPath)
    function Get-BarrierProperty($Object, [string]$Name) {
        if ($null -eq $Object) { return $null }
        $property = $Object.PSObject.Properties[$Name]
        if ($null -ne $property) { return ,$property.Value }
        return $null
    }
    try {
        $raw = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 -ErrorAction Stop
        # Pipeline enumeration can unwrap a one-element JSON array on some
        # PowerShell versions; require an object before deserializing it.
        if ($raw -isnot [string] -or -not $raw.TrimStart().StartsWith('{')) { throw 'manifest root is not an object' }
        $manifest = $raw | ConvertFrom-Json -ErrorAction Stop
        $manifestStatus = Get-BarrierProperty $manifest 'status'
        if ($manifestStatus -isnot [string] -or -not $manifestStatus) { throw 'manifest status missing or invalid' }
    } catch {
        return [pscustomobject]@{ severity = 'CRITICAL'; detail = 'Stage-A barrier unavailable: manifest missing or unreadable' }
    }
    if ($manifestStatus -ceq 'RUNNING') {
        return [pscustomobject]@{ severity = 'WARN'; detail = 'Stage-A barrier pending; see the independent chain completion check' }
    }
    $barrier = Get-BarrierProperty $manifest 'barrier'
    $payloadStatus = Get-BarrierProperty $manifest 'payload_status'
    $target = Get-BarrierProperty $manifest 'target_date'
    $barrierTarget = Get-BarrierProperty $barrier 'target_date'
    $barrierStatus = Get-BarrierProperty $barrier 'status'
    $barrierStepStatus = Get-BarrierProperty $barrier 'step_status'
    $blockerCount = Get-BarrierProperty $barrier 'blocker_count'
    $parsedTarget = [datetime]::MinValue
    $validTarget = $target -is [string] -and [datetime]::TryParseExact($target, 'yyyy-MM-dd',
        [cultureinfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsedTarget)
    $stringFields = $payloadStatus -is [string] -and $barrierTarget -is [string] -and
        $barrierStatus -is [string] -and $barrierStepStatus -is [string]
    $noBlockers = ($blockerCount -is [int] -or $blockerCount -is [long]) -and $blockerCount -eq 0
    $severity = 'CRITICAL'
    # Later rollup freshness may mark the parent critical while Stage B is
    # held. This check owns only the barrier, not the aggregate pipeline.
    if ($manifestStatus -ceq 'COMPLETED' -and $stringFields -and
        $payloadStatus -cin @('ok', 'critical') -and
        $barrierStatus -cin @('PASS', 'DIAGNOSTIC_ONLY') -and $barrierStepStatus -ceq 'ok' -and
        $validTarget -and $barrierTarget -ceq $target -and $noBlockers) {
        # Partial settled labels are non-blocking in the chain. Warn only when
        # the receipt is otherwise valid; malformed diagnostics still fail closed.
        $severity = if ($barrierStatus -ceq 'PASS') { 'OK' } else { 'WARN' }
    }
    $detail = 'Stage-A target {0}: manifest={1}, payload={2}, barrier={3}, barrier target={4}, blockers={5}; inspect data/backtest/settled_day_analysis_barrier.json and daily_refresh_status.json' -f `
        $target, $manifestStatus, $payloadStatus, $barrierStatus, $barrierTarget, $blockerCount
    return [pscustomobject]@{ severity = $severity; detail = $detail }
}

function Get-WeatherRewardCaptureFinding {
    param([string]$Root, [object]$Task, [datetimeoffset]$Now = [datetimeoffset]::UtcNow)
    $detail = 'no producer registered (WeatherMakerEvidenceCapture)'
    $severity = 'CRITICAL'; $age = $null; $newest = $null
    if ($null -ne $Task -and [string]$Task.State -eq 'Disabled') {
        $detail = 'reward-record producer is registered but disabled'
    } elseif ($null -ne $Task) {
        try {
            # 88a's explicit UTC day/hour layout; never walk the evidence tree.
            # Older/compressed segments cannot prove the five-minute freshness SLA.
            $folders = @()
            foreach ($hoursAgo in 0..2) {
                $hour = $Now.UtcDateTime.AddHours(-$hoursAgo)
                $day = Join-Path $Root $hour.ToString('yyyy-MM-dd')
                if (Test-Path -LiteralPath $day) {
                    $folders += @(Get-ChildItem -LiteralPath $day -Directory -Filter ($hour.ToString('HH') + '-*') -ErrorAction Stop |
                        Select-Object -First 33)
                }
            }
            if ($folders.Count -gt 32) { throw 'reward segment count exceeds monitor bound (32)' }
            $files = @($folders | ForEach-Object {
                Get-ChildItem -LiteralPath $_.FullName -File -Filter 'reward-*.jsonl' -ErrorAction Stop
            } | Select-Object -First 513)
            if ($files.Count -gt 512) { throw 'reward file count exceeds monitor bound (512)' }
            foreach ($file in $files) {
                # Seek a bounded suffix. Get-Content -Tail in Windows PowerShell can
                # scan from byte zero; a fresh heartbeat alone proves no reward read.
                $stream = [IO.File]::Open($file.FullName, 'Open', 'Read', 'ReadWrite')
                try {
                    $start = [Math]::Max(0, $stream.Length - 32768)
                    [void]$stream.Seek($start, 'Begin')
                    $reader = [IO.BinaryReader]::new($stream)
                    try { $tail = [Text.Encoding]::UTF8.GetString($reader.ReadBytes(32768)) } finally { $reader.Dispose() }
                } finally { $stream.Dispose() }
                $lines = @($tail -split "`n")
                if ($start -gt 0) { $lines = @($lines | Select-Object -Skip 1) }
                foreach ($line in $lines) {
                    try {
                        $row = $line | ConvertFrom-Json -ErrorAction Stop
                        if ([string]$row.kind -cne 'rewards' -or $row.http_status -ne 200 -or
                            [string]$row.content_sha256 -notmatch '^[0-9a-f]{64}$') { continue }
                        $at = [datetimeoffset]::Parse([string]$row.captured_at_utc)
                        if ($at -gt $Now) { throw 'future reward timestamp' }
                        if ($null -eq $newest -or $at -gt $newest) { $newest = $at }
                    } catch { continue }
                }
            }
            if ($null -eq $newest) { $detail = 'no readable successful reward record in the current/previous two UTC hours' }
            else {
                $age = ($Now - $newest).TotalMinutes
                $severity = if ($age -gt 15) { 'CRITICAL' } elseif ($age -gt 5) { 'WARN' } else { 'OK' }
                $detail = 'newest successful reward record {0:o}, {1:N1} minutes old' -f $newest, $age
            }
        } catch { $detail = 'reward capture unreadable: ' + $_.Exception.Message }
    }
    return [pscustomobject]@{ severity = $severity; detail = $detail; age_minutes = $age }
}

# ---- known criticals: dated, condition-bound holds (DL R18) ----
# A listed CRITICAL becomes KNOWN (Markdown '## Known' section and JSONL only; never the
# CRITICAL table that status.ps1 reads) only while EVERY producer task is exactly Disabled and
# the row has not expired. Anything else keeps the CRITICAL and adds a CRITICAL known/lapsed
# row; an invalid row adds CRITICAL known/malformed. A row lives at most 60 days and each
# renewal needs its own dated DECISION_LOG row. Until B's look closes, an expiry is never
# answered by running Stage B (WeatherEveningEvidenceRefresh).
$knownCriticalMaxDays = 60
$knownCriticals = @(
    [pscustomobject]@{
        check = 'learning/daily_learning'
        producers = @('WeatherEveningEvidenceRefresh', 'WeatherTrainingWindow')
        recorded = '2026-11-04'; expires = '2026-12-31'; decision = 'DL R18'
    }
    [pscustomobject]@{
        check = 'learning/market_beating_scoreboard'
        producers = @('WeatherEveningEvidenceRefresh')
        recorded = '2026-11-04'; expires = '2026-12-31'; decision = 'DL R18'
    }
)

function Get-WeatherKnownCriticalDisposition {
    # Pure: no scheduler, file or clock reads. $ProducerStates maps task name -> State string;
    # a producer absent from the map is not held. Returns disposition KNOWN, LAPSED,
    # MALFORMED or NONE (the finding is not CRITICAL, so there is nothing to hold).
    param([object]$Row, [object]$Finding, [hashtable]$ProducerStates = @{}, [datetime]$Now,
          [int]$MaxDays = 60)
    $inv = [cultureinfo]::InvariantCulture
    $check = [string]$(if ($null -ne $Row) { $Row.check })
    $producers = @(if ($null -ne $Row) { @($Row.producers) | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) } })
    $recorded = [datetime]::MinValue; $expires = [datetime]::MinValue
    $bad = $null
    if ($null -eq $Row -or [string]::IsNullOrWhiteSpace($check)) { $bad = 'row has no check name' }
    elseif ($producers.Count -eq 0) { $bad = 'row names no producer task' }
    elseif ([string]::IsNullOrWhiteSpace([string]$Row.decision)) { $bad = 'row cites no decision' }
    elseif (-not [datetime]::TryParseExact([string]$Row.recorded, 'yyyy-MM-dd', $inv, 'None', [ref]$recorded)) { $bad = 'recorded is not yyyy-MM-dd' }
    elseif (-not [datetime]::TryParseExact([string]$Row.expires, 'yyyy-MM-dd', $inv, 'None', [ref]$expires)) { $bad = 'expires is not yyyy-MM-dd' }
    elseif ($expires -lt $recorded) { $bad = 'expires before recorded' }
    elseif (($expires - $recorded).TotalDays -gt $MaxDays) { $bad = ('span {0:N0}d exceeds the {1}-day cap' -f ($expires - $recorded).TotalDays, $MaxDays) }
    if ($bad) { return [pscustomobject]@{ disposition = 'MALFORMED'; reason = $bad } }
    if ($null -eq $Finding -or [string]$Finding.severity -cne 'CRITICAL') {
        return [pscustomobject]@{ disposition = 'NONE'; reason = 'finding is not CRITICAL' }
    }
    foreach ($producer in $producers) {
        $name = [string]$producer
        if ($null -eq $ProducerStates -or -not $ProducerStates.ContainsKey($name)) {
            return [pscustomobject]@{ disposition = 'LAPSED'; reason = "producer $name is not registered or unreadable" }
        }
        $state = [string]$ProducerStates[$name]
        if ($state -cne 'Disabled') {
            return [pscustomobject]@{ disposition = 'LAPSED'; reason = "producer $name is $state, not Disabled" }
        }
    }
    if ($Now.Date -gt $expires.Date) {
        return [pscustomobject]@{ disposition = 'LAPSED'; reason = ('expired {0:yyyy-MM-dd}; renew with a dated DECISION_LOG row' -f $expires) }
    }
    return [pscustomobject]@{ disposition = 'KNOWN'; reason = ('held by {0} until {1:yyyy-MM-dd}' -f [string]$Row.decision, $expires) }
}

function Get-WeatherTaskResults {
    # Daily snapshot of each task's last run from the Task Scheduler API only; never the event
    # log. A task that is simply not registered is state 'NotRegistered', not a failure.
    # Returns rows plus the list of failures (unreadable registry, or a task query error).
    param([string]$ConfigPath, [string[]]$ExtraNames = @())
    $rows = New-Object System.Collections.Generic.List[object]
    $failures = New-Object System.Collections.Generic.List[string]
    $names = New-Object System.Collections.Generic.List[string]
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        $configured = @($config.tasks | ForEach-Object { [string]$_.name } | Where-Object { $_ })
        if ($configured.Count -eq 0) { throw 'no tasks[].name rows' }
        foreach ($n in $configured) { if (-not $names.Contains($n)) { $names.Add($n) } }
    }
    catch { $failures.Add(('scheduled_tasks.json unreadable: {0}' -f $_.Exception.Message)) }
    foreach ($n in @($ExtraNames)) { if ($n -and -not $names.Contains([string]$n)) { $names.Add([string]$n) } }
    # One enumeration (under a second on a typical host) instead of one CIM query per name;
    # a per-name query of an unregistered task costs about half a second to fail.
    $byName = @{}
    $listed = $true
    try {
        foreach ($t in @(Get-ScheduledTask -ErrorAction Stop)) {
            $key = [string]$t.TaskName
            if ($key -and -not $byName.ContainsKey($key)) { $byName[$key] = $t }
        }
    }
    catch {
        $listed = $false
        $failures.Add(('task list unreadable: {0}' -f $_.Exception.Message))
    }
    foreach ($name in $names) {
        $row = [ordered]@{ name = $name; last_run_utc = $null; result_hex = $null; state = $null }
        try {
            if (-not $listed) { $rows.Add([pscustomobject]$row); continue }
            $task = if ($byName.ContainsKey($name)) { $byName[$name] } else { $null }
            if ($null -eq $task) { $row.state = 'NotRegistered' }
            else {
                $row.state = [string]$task.State
                $info = $task | Get-ScheduledTaskInfo -ErrorAction Stop
                $last = $info.LastRunTime
                if ($null -ne $last -and ([datetime]$last).Year -ge 2000) {
                    $row.last_run_utc = ([datetime]$last).ToUniversalTime().ToString('o')
                }
                if ($null -ne $info.LastTaskResult) {
                    $code = [int64]$info.LastTaskResult
                    if ($code -lt 0) { $code += 4294967296 }
                    $row.result_hex = '0x{0:X}' -f $code
                }
            }
        }
        catch { $failures.Add(('{0}: {1}' -f $name, $_.Exception.Message)) }
        $rows.Add([pscustomobject]$row)
    }
    return [pscustomobject]@{ rows = $rows.ToArray(); failures = $failures.ToArray() }
}

# ---- reward producer: required even before registration ----
$rewardTask = Get-ScheduledTask -TaskName 'WeatherMakerEvidenceCapture' -ErrorAction SilentlyContinue
$rewardFinding = Get-WeatherRewardCaptureFinding -Root (Join-Path $repo 'data\maker_evidence') -Task $rewardTask -Now $now
Add-Finding 'capture/reward_records' $rewardFinding.severity $rewardFinding.detail `
    'without refreshed reward terms the maker economics evidence silently stops; producer heartbeat is not a reward record' `
    $(if ($null -ne $rewardFinding.age_minutes) { $rewardFinding.age_minutes / 1440 } else { $null }) (15.0 / 1440)

# ---- 1. capture closures: freshness AND tombstones ----
# A closure that stops reporting silently removes itself from every roll verdict derived after --
# but ONLY for the files it alone contributes. On 2026-08-06 clob-enrichment sat at CRITICAL for
# 10.5 days while contributing ZERO unique files: its 21-file closure is a strict subset of the live
# CLOB loop's 23. A CRITICAL that cannot possibly produce a wrong roll verdict is alarm fatigue, and
# alarm fatigue is what makes the next real one get waved through. So compute the unique surface
# rather than assert it, and when it is non-empty NAME the files -- those are exactly the ones a
# merge would roll blind. See RETRACTED_AND_FALSE_LEADS.md section 3.
# The closure list is shared with roll_verdict.ps1 through config\capture_families.json
# (platform.roll_closures, data layer v2 S1). An unreadable registry is itself a CRITICAL
# finding: with no list, no closure can be checked.
$closureFiles = [ordered]@{}
try {
    $closureRegistry = Get-Content -LiteralPath (Join-Path $repo "config\capture_families.json") -Raw -ErrorAction Stop |
        ConvertFrom-Json -ErrorAction Stop
    $closureRows = @($closureRegistry.platform.roll_closures)
    if ($closureRows.Count -eq 0) { throw "no platform.roll_closures rows" }
    foreach ($row in $closureRows) {
        if ([string]$row.id -notmatch '^[a-z][a-z0-9-]*$' -or [string]$row.status_path -notmatch '^data/[A-Za-z0-9_./-]+\.json$' -or
            [string]$row.arming -notin @("always", "while_armed_or_active")) {
            throw ("malformed roll_closures row: {0}" -f [string]$row.id)
        }
        # Same rule as roll_verdict.ps1: an optional producer is judged by its task's state, so a
        # row without one is malformed rather than silently "not armed".
        if ([string]$row.arming -eq "while_armed_or_active" -and
            -not [string]($row.PSObject.Properties["task"] | ForEach-Object { $_.Value })) {
            throw ("malformed roll_closures row: {0} (optional producer without a task)" -f [string]$row.id)
        }
        $rel = [string]$row.status_path -replace '/', '\'
        if ([string]$row.arming -eq "always") { $closureFiles[[string]$row.id] = $rel; continue }
        # Optional producer: required only while armed or still running.
        $optionalTask = Get-ScheduledTask -TaskName ([string]$row.task) -ErrorAction SilentlyContinue
        $optionalActive = $false
        if ($optionalTask -and [string]$optionalTask.State -ne "Disabled") {
            $optionalActive = $true
        }
        elseif ($row.writer_lock -and (Test-Path -LiteralPath (Join-Path $repo ([string]$row.writer_lock -replace '/', '\')))) {
            $optionalActive = $true
        }
        elseif ($row.worker_status -and (Test-Path -LiteralPath (Join-Path $repo ([string]$row.worker_status -replace '/', '\')))) {
            try {
                $optionalWorker = Get-Content -LiteralPath (Join-Path $repo ([string]$row.worker_status -replace '/', '\')) -Raw | ConvertFrom-Json
                $optionalActive = [string]$optionalWorker.state -ne "STOPPED"
            }
            catch { $optionalActive = $false }
        }
        if ($optionalActive) { $closureFiles[[string]$row.id] = $rel }
    }
}
catch {
    $closureFiles = [ordered]@{}
    Add-Finding "closure/registry" "CRITICAL" ("config\capture_families.json platform.roll_closures unreadable: {0}" -f $_.Exception.Message) `
        "without the registry no capture closure is checked, and roll_verdict.ps1 refuses to judge" $null 1
}
function Get-ClosureStatus($path) {
    try { $j = Get-Content -LiteralPath $path -Raw -ErrorAction Stop | ConvertFrom-Json } catch { return $null }
    $scope = $null
    foreach ($k in "current_runtime_identity", "runtime_identity_before", "runtime_identity") {
        $node = $j.$k
        if ($node -and $node.source_scope_files) { $scope = @($node.source_scope_files); break }
    }
    return [PSCustomObject]@{
        Scope        = $scope
        State        = [string]$j.state
        EnsureStatus = [string]$j.ensure_status
        Reason       = [string]$j.reason
        Tombstone    = ([string]$j.state -eq "DEAD") -or ([string]$j.ensure_status -eq "BLOCKED")
    }
}
$closureState = @{}
foreach ($name in $closureFiles.Keys) {
    $p = Join-Path $repo $closureFiles[$name]
    if (-not (Test-Path -LiteralPath $p)) { $closureState[$name] = $null; continue }
    $parsed = Get-ClosureStatus $p
    if (-not $parsed) { $closureState[$name] = $null; continue }
    $closureState[$name] = [PSCustomObject]@{
        Age          = ($nowUtc - (Get-Item -LiteralPath $p).LastWriteTimeUtc).TotalDays
        Scope        = $parsed.Scope
        State        = $parsed.State
        EnsureStatus = $parsed.EnsureStatus
        Reason       = $parsed.Reason
        Tombstone    = $parsed.Tombstone
    }
}
# Union of everything a still-reporting closure covers. Anything in here cannot go dark.
$liveScope = New-Object System.Collections.Generic.HashSet[string]([StringComparer]::OrdinalIgnoreCase)
foreach ($name in $closureFiles.Keys) {
    $c = $closureState[$name]
    if ($c -and -not $c.Tombstone -and $c.Age -le 1 -and $c.Scope) {
        foreach ($f in $c.Scope) { [void]$liveScope.Add($f) }
    }
}
$closureWhy = "a closure that stops reporting is silently dropped from every later roll verdict; merges then look safer than they are"
foreach ($name in $closureFiles.Keys) {
    $rel = $closureFiles[$name]
    $c = $closureState[$name]
    if (-not $c) { Add-Finding "closure/$name" "CRITICAL" "missing: $rel" $closureWhy $null 1; continue }
    if ($c.Tombstone) {
        Add-Finding "closure/$name" "CRITICAL" `
            ("{0} is a tombstone (state={1}, ensure_status={2}, reason={3})" -f $rel, $c.State, $c.EnsureStatus, $c.Reason) `
            "a DEAD or BLOCKED status is not live closure evidence; restore the owning loop and require a fresh healthy identity before evaluating a roll" `
            $c.Age 1
        continue
    }
    if ($c.Age -le 1) {
        Add-Finding "closure/$name" "OK" ("{0} is {1:N1}d old" -f $rel, $c.Age) $closureWhy $c.Age 1
        continue
    }
    if (-not $c.Scope) {
        Add-Finding "closure/$name" "CRITICAL" `
            ("{0} is {1:N1}d old and carries no readable source_scope_files" -f $rel, $c.Age) `
            $closureWhy $c.Age 1
        continue
    }
    $unique = @($c.Scope | Where-Object { -not $liveScope.Contains($_) })
    if ($unique.Count -eq 0) {
        Add-Finding "closure/$name" "OK" `
            ("{0} is {1:N1}d old but contributes 0 unique files (all {2} are covered by a live closure) - it cannot change a roll verdict" -f $rel, $c.Age, $c.Scope.Count) `
            "stale-but-subsumed: every file it would contribute is already reported by a closure refreshing every 60s, so its silence is not a blind spot" `
            $c.Age 1
    }
    else {
        Add-Finding "closure/$name" "CRITICAL" `
            ("{0} is {1:N1}d old and is the ONLY source for {2} file(s): {3}" -f $rel, $c.Age, $unique.Count, (($unique | Select-Object -First 5) -join ", ")) `
            $closureWhy $c.Age 1
    }
}
# ---- 2. the learning loop's own outputs ----
# Both are Stage-B outputs (steps after promotion_refresh), so Stage A completing says nothing
# about them. While their producers are deliberately Disabled the rows are held by
# $knownCriticals below, never by editing the age limits here.
Test-FileAge "learning/daily_learning" "data\backtest\daily_learning.json" 2 5 `
    "the learning rollup; a Stage-B output (after promotion_refresh), also written by nightly_retrain under WeatherTrainingWindow, and settlement-gated, so it refreshes only when one of those producers runs on settled days"
Test-FileAge "learning/market_beating_scoreboard" "data\backtest\market_beating_objective_scoreboard.json" 2 5 `
    "the objective scoreboard; a Stage-B output (after promotion_refresh) and settlement-gated, so it refreshes only when Stage B runs on settled days - while it is stale the model-vs-market gap is not measured"
$stageA = Get-WeatherStageAChainFinding `
    -ManifestPath (Join-Path $repo "data\backtest\daily_refresh_settlement_truth_manifest.json") `
    -ReportPath (Join-Path $repo "data\backtest\daily_refresh_report.md") -Now $now
Add-Finding "chain/daily_refresh_report" $stageA.severity $stageA.detail `
    "the chain's own completion record; per-step checkpoints keep the report fresh even when the chain is killed, so only a COMPLETED Stage-A manifest proves the chain completed" `
    $stageA.age_days 1
$stageABarrier = Get-WeatherStageABarrierFinding `
    -ManifestPath (Join-Path $repo "data\backtest\daily_refresh_settlement_truth_manifest.json")
Add-Finding "chain/settled_day_barrier" $stageABarrier.severity $stageABarrier.detail `
    "COMPLETED proves termination; the settlement barrier must be visible independently of held Stage-B learning alarms. A passing barrier does not certify the aggregate pipeline or promotion readiness" $null $null

# ---- 3. serving artifacts ----
# Not a bug on its own -- but an artifact serving a season it never trained on is (see 4b/2).
$hgb = Join-Path $repo "artifacts\models\hgb\feature_model_hgb.pkl"
if (Test-Path -LiteralPath $hgb) {
    $age = ($nowUtc - (Get-Item -LiteralPath $hgb).LastWriteTimeUtc).TotalDays
    $sev = if ($age -gt 60) { "WARN" } else { "OK" }
    Add-Finding "model/serving_artifact_age" $sev ("feature_model_hgb.pkl fitted {0:N0}d ago" -f $age) `
        "measured -1.0193 C-eq cool out-of-season vs -0.1848 in-season; age is the proxy for seasonal distance from its training window" $age 60
}

# ---- 4. does the forecast archive cover what we would train for TODAY? ----
# The defect that hid for five weeks: fleet-coverage reported OK 12/12 against an archive
# holding zero rows for the target window, because it never asked about date relevance.
#
# TWO manifest shapes. -09-33a (inside the -09-43a stack) replaces the fixed `season_window`
# with a target-derived `target_window`, so this check has to read both -- and, crucially, must
# NOT fall silent when it recognises neither. The original version was `if ($m.season_window)`
# with a bare `catch {}`: once the key was renamed, a CRITICAL that had been firing daily would
# simply stop appearing, and the disappearance reads exactly like a fix. That is the same defect
# this whole script exists to catch, one level up -- see the file header.
$manifest = Join-Path $repo "data\forecast_history\cyyz\manifest.json"
if (Test-Path -LiteralPath $manifest) {
    $why = "a target outside the archive window gets ZERO training rows; this is what blocked the first retrain at 0/12,600 cells (the-season-window-blocks-the-retrain.md)"
    $today = $now.Date
    $resolved = $false
    try {
        $m = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json

        if ($m.target_window -and $m.target_window.target_date) {
            # Target-derived shape: the archive was fetched for ONE declared target, covering
            # target +/- archive_radius_days in each year. Ask whether today still falls in it.
            $resolved = $true
            $tgt = [datetime]::ParseExact([string]$m.target_window.target_date, "yyyy-MM-dd", $null)
            $radius = [int]$m.target_window.archive_radius_days
            # .Date matters: Get-Date carries the CURRENT clock time, which makes the drift
            # fractional and biases it DOWN by up to a day -- a target one day outside the
            # radius would read as inside. Compare midnight to midnight.
            $anchor = (Get-Date -Year $today.Year -Month $tgt.Month -Day $tgt.Day).Date
            $drift = [Math]::Abs(($today - $anchor).TotalDays)
            $covers = ($drift -le $radius)
            $sev = if ($covers) { "OK" } elseif ($drift -le ($radius * 2)) { "WARN" } else { "CRITICAL" }
            Add-Finding "archive/target_relevance" $sev `
                ("archive was fetched for target {0:yyyy-MM-dd} +/-{1}d; today {2:MM-dd} is {3:N0}d off that anchor and is {4}" -f $tgt, $radius, $today, $drift, $(if ($covers) { "inside" } else { "OUTSIDE" })) `
                $why $drift $radius
        }
        elseif ($m.season_window) {
            # Legacy fixed-season shape.
            $resolved = $true
            $s = $m.season_window.start; $e = $m.season_window.end
            $winStart = Get-Date -Year $today.Year -Month $s[0] -Day $s[1]
            $winEnd = Get-Date -Year $today.Year -Month $e[0] -Day $e[1]
            $covers = ($today -ge $winStart -and $today -le $winEnd)
            $trainingTask = Get-ScheduledTask -TaskName "WeatherTrainingWindow" `
                -ErrorAction SilentlyContinue
            $trainingHeld = (
                $null -ne $trainingTask -and
                [string]$trainingTask.State -eq "Disabled"
            )
            $sev = if ($covers) {
                "OK"
            }
            elseif ($trainingHeld) {
                "WARN"
            }
            else {
                "CRITICAL"
            }
            Add-Finding "archive/season_relevance" $sev `
                ("archive season is {0:00}-{1:00} to {2:00}-{3:00}; today {4:MM-dd} is {5}{6}" -f $s[0], $s[1], $e[0], $e[1], $today, $(if ($covers) { "inside" } else { "OUTSIDE" }), $(if ($trainingHeld -and -not $covers) { " while training is operator-held" } else { "" })) `
                $why $null $null
        }
    }
    catch {
        $resolved = $false
    }
    if (-not $resolved) {
        Add-Finding "archive/window_unreadable" "CRITICAL" `
            "manifest.json declares neither target_window.target_date nor season_window - archive coverage CANNOT be evaluated" `
            "this check went silent rather than green; an unreadable window is not a covered window, and the silence would be mistaken for a fix" `
            $null $null
    }
}

# ---- 5. git: the traps that silently abort merges ----
Set-Location $repo
$unpushed = & git rev-list --count origin/master..master 2>$null
if ($unpushed -and [int]$unpushed -gt 0) {
    Add-Finding "git/unpushed" "WARN" "$unpushed commit(s) unpushed" `
        "an unpushed commit trips the merge tool's HEAD != origin/master guard; this silently aborted all three merges on 2026-08-01" $null $null
}
$branches = @(& git branch -r --no-merged master 2>$null | Where-Object { $_ -and $_ -notmatch 'HEAD' })
if ($branches.Count -gt 0) {
    Add-Finding "git/unmerged_branches" "OK" "$($branches.Count) retained unmerged remote branch(es)" `
        "inventory only: held branches preserve unique code and reports; only an explicit immutable exact-tip queue authorizes integration, and branch deletion is forbidden" $null $null
}

# ---- 6. settlement continuity (the consequence, not the chain event) ----
$settleRoot = Join-Path $repo "data\settlements"
if (Test-Path -LiteralPath $settleRoot) {
    $latest = $null
    foreach ($dir in @(Get-ChildItem -LiteralPath $settleRoot -Directory -ErrorAction SilentlyContinue)) {
        $ledger = Join-Path $dir.FullName "ledger.jsonl"
        if (-not (Test-Path -LiteralPath $ledger)) { continue }
        foreach ($line in @(Get-Content -LiteralPath $ledger -Tail 50 -ErrorAction SilentlyContinue)) {
            if (-not $line) { continue }
            try { $row = ConvertFrom-Json $line } catch { continue }
            $source = [string]$row.settlement_source
            $highProperty = $row.PSObject.Properties["settlement_high"]
            if (-not $source -or $source -in @("none", "null") -or
                $null -eq $highProperty -or $null -eq $highProperty.Value) {
                continue
            }
            $td = $row.target_date
            if (-not $td) { continue }
            try { $d = [datetime]::ParseExact([string]$td, "yyyy-MM-dd", $null) } catch { continue }
            if (($null -eq $latest) -or ($d -gt $latest)) { $latest = $d }
        }
    }
    if ($latest) {
        $behind = ($now.Date - $latest).TotalDays
        $sev = if ($behind -ge 3) { "CRITICAL" } elseif ($behind -ge 2 -and $now.Hour -ge 12) { "WARN" } else { "OK" }
        Add-Finding "settlement/latest" $sev ("latest real settlement target is {0:yyyy-MM-dd}, {1:N0}d behind" -f $latest, $behind) `
            "each chain run settles only yesterday; a missed day is never retried and needs an explicit backfill" $behind 2
    }
}

# ---- 7. log rotation (bounded: known dirs only, never a recursive data/ walk) ----
#
# 2026-08-09: this check listed ALREADY-ROTATED files as "unrotated", so after a rotation the one
# signal that matters -- a LIVE file still growing -- sat buried among five dead archives, and the
# warning could never go green. A warning that never goes green is one nobody reads.
#
# The split is not cosmetic, because the two have different failure modes:
#   LIVE .jsonl   - written by append_jsonl, which REOPENS the file on every append. That reopen is
#                   what raised PermissionError on a 625 MB diagnostics.jsonl on 2026-08-09 and
#                   killed the snapshot capture loop for 5h54m. THIS is the crash risk.
#   LIVE .log     - a console redirect whose handle is opened once at process start and held, so it
#                   has no reopen to fail. Large is a DISK problem here, not a crash problem.
#   ROTATED       - nothing appends to it. Never a crash risk; only cold-storage candidates.
$rotatedPattern = '\.\d{8}T\d+Z\.'
$rotatedMb = 0.0
$rotatedCount = 0
foreach ($dir in @("data\snapshots", "data\logs", "data\alerts")) {
    $full = Join-Path $repo $dir
    if (-not (Test-Path -LiteralPath $full)) { continue }
    foreach ($f in @(Get-ChildItem -LiteralPath $full -File -Include *.log, *.jsonl -ErrorAction SilentlyContinue)) {
        $mb = $f.Length / 1MB
        if ($mb -le 256) { continue }
        if ($f.Name -match $rotatedPattern) {
            $rotatedMb += $mb
            $rotatedCount++
            continue
        }
        if ($f.Extension -eq ".jsonl") {
            Add-Finding "logs/live_append_oversized" "CRITICAL" ("{0} is {1:N0} MB and is APPENDED TO" -f $f.Name, $mb) `
                "append_jsonl reopens the file every write; that reopen failed on a 625 MB diagnostics.jsonl and killed capture for 5h54m on 2026-08-09 -- rotate it" $mb 256
        }
        else {
            Add-Finding "logs/live_console_oversized" "WARN" ("{0} is {1:N0} MB" -f $f.Name, $mb) `
                "a console redirect holds one handle so it cannot fail on reopen; this is disk cost, not a crash risk, and rotating it needs a loop restart" $mb 256
        }
    }
}
if ($rotatedCount -gt 0) {
    Add-Finding "logs/cold_storage_eligible" "WARN" ("{0} rotated file(s), {1:N0} MB total" -f $rotatedCount, $rotatedMb) `
        "already rotated, so nothing appends to them and they cannot crash a loop -- they are pure disk and are the safe thing to move to cold storage first" $rotatedMb $null
}

# ---- 8. unreachable operations docs ----
# The CI docs audit checks that links are not BROKEN. Nothing checks that a document is
# REACHABLE. On 2026-08-06 that let a canonical decision reversing the project's top priority
# sit unlinked from every index, alongside git-lfs-policy.md and the deleted-branch recovery
# manifest -- both load-bearing, both invisible to a cold agent. A document nobody can find is
# a document that will be re-derived, or worse, contradicted.
$opsDocs = @(Get-ChildItem -LiteralPath (Join-Path $repo "docs\operations") -Filter *.md -File -ErrorAction SilentlyContinue)
if ($opsDocs.Count -gt 0) {
    $linked = New-Object System.Collections.Generic.HashSet[string]
    $scan = @(Get-ChildItem -LiteralPath (Join-Path $repo "docs") -Filter *.md -File -Recurse -ErrorAction SilentlyContinue)
    $scan += @(Get-ChildItem -LiteralPath $repo -Filter *.md -File -ErrorAction SilentlyContinue)
    foreach ($f in $scan) {
        try { $text = Get-Content -LiteralPath $f.FullName -Raw -ErrorAction Stop } catch { continue }
        foreach ($m in [regex]::Matches($text, '\]\(([^)]+)\)')) {
            $tgt = ($m.Groups[1].Value -split '#')[0].Trim()
            if (-not $tgt -or $tgt -match '^(https?:|mailto:)') { continue }
            try { $full = [IO.Path]::GetFullPath((Join-Path $f.DirectoryName $tgt)) } catch { continue }
            [void]$linked.Add($full)
        }
    }
    # Dated incident/research files are historical evidence by repository contract, not cold-agent
    # entry points. OVERNIGHT_BRIEFINGS.md is the one undated historical aggregate. Requiring an
    # index link for those files turned preservation into a permanent warning and obscured genuinely
    # unreachable canonical documents.
    $historicalUnindexedNames = @("OVERNIGHT_BRIEFINGS.md")
    $orphans = @($opsDocs | Where-Object {
        -not $linked.Contains($_.FullName) -and
        $_.Name -notmatch '(?:19|20)\d{2}[-_]\d{2}[-_]\d{2}' -and
        $_.Name -notin $historicalUnindexedNames
    })
    if ($orphans.Count -gt 0) {
        $sev = if ($orphans.Count -ge 10) { "CRITICAL" } else { "WARN" }
        Add-Finding "docs/unreachable" $sev `
            ("{0} of {1} docs/operations files are unreachable by any markdown link: {2}" -f $orphans.Count, $opsDocs.Count, (($orphans | Select-Object -First 6 | ForEach-Object { $_.Name }) -join ', ')) `
            "the CI audit checks for broken links, not unreachable files; an unlinked canonical doc is invisible to a cold agent and will be re-derived or contradicted" `
            $null $null
    }
}

# ---- 9. STATE_OF_PLAY freshness and its length cap ----
# It is the entry point for a compacted or cold agent. Stale content here is worse than none,
# because it will be believed; and it stops being readable the moment it starts accreting.
$sop = Join-Path $repo "docs\operations\STATE_OF_PLAY.md"
if (Test-Path -LiteralPath $sop) {
    $age = ($nowUtc - (Get-Item -LiteralPath $sop).LastWriteTimeUtc).TotalDays
    $lines = @(Get-Content -LiteralPath $sop).Count
    $sev = if ($age -gt 14) { "CRITICAL" } elseif ($age -gt 5) { "WARN" } else { "OK" }
    Add-Finding "docs/state_of_play_age" $sev ("STATE_OF_PLAY.md is {0:N1}d old" -f $age) `
        "the entry point for a cold or compacted agent; stale content here is believed rather than ignored" $age 5
    if ($lines -gt 100) {
        Add-Finding "docs/state_of_play_length" "WARN" "STATE_OF_PLAY.md is $lines lines (cap ~90)" `
            "it is capped so it stays readable; over the cap means something in it has stopped being current and should be cut, not carried" $null 100
    }
}
else {
    Add-Finding "docs/state_of_play_age" "CRITICAL" "STATE_OF_PLAY.md is missing" `
        "the entry point for a cold or compacted agent" $null $null
}

# ---- 11. duplicate bot workers (the orphan that eats the capture budget) ----
# A daily-roll supervisor stops exactly ONE pid: the one recorded in its status file
# (bot_daily_roll_supervisor.ps1 stop_daily_roll_process -> status.get("pid")). Maker and taker
# lifecycle decisions are now process-lock serialized, so a duplicate is an invariant breach,
# not an expected race outcome. Keep this independent process-table check as defence in depth.
# Measured 2026-08-07: two market_making_run workers started 47s apart, the status file kept the
# second, the 19:29 restart stopped that one, and the 18:29:09 worker survived holding 431 MB.
# That is not just waste -- capture admission needs 3.49 GB free per worker, so the orphan helped
# drive 430 memory-admission refusals between 11:00 and 18:00 and put the streak day AT_RISK with
# two in-window gaps (24 min and 41 min). Same defect class as the taker orphan of 2026-06-30 and
# 2026-07-04. Nothing detected any of them; the supervisors all reported healthy.
# Counts LOGICAL runs: each run is a venv shim plus its real worker, so a matching process whose
# parent is also matching is the child half and is not counted twice. Process table only -- no
# data/ walk.
try {
    $botProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop |
        Where-Object { $_.CommandLine -match 'market_making_run|weather\.market\.taker_bot' })
    $botPids = @($botProcs | ForEach-Object { $_.ProcessId })
    foreach ($modName in @('market_making_run', 'taker_bot')) {
        $ofMod = @($botProcs | Where-Object { $_.CommandLine -match $modName })
        # keep only the outermost process of each launch chain
        $roots = @($ofMod | Where-Object { $botPids -notcontains $_.ParentProcessId })
        # Emit OK explicitly. A check that says nothing when healthy is indistinguishable from a
        # check that silently stopped running -- which is the exact failure this file exists for.
        if ($roots.Count -le 1) {
            Add-Finding "bots/duplicate_worker" "OK" `
                ("{0}: {1} live run(s)" -f $modName, $roots.Count) `
                "more than one live run of the same bot is an invariant breach and can strand memory capture needs" $null $null
        }
        if ($roots.Count -gt 1) {
            $starts = (($roots | Sort-Object CreationDate | ForEach-Object { $_.CreationDate.ToString('HH:mm:ss') }) -join ', ')
            Add-Finding "bots/duplicate_worker" "CRITICAL" `
                ("{0} has {1} live runs (started {2})" -f $modName, $roots.Count, $starts) `
                "daily-roll launch locking should prevent duplicate managed starts, so this is an invariant breach; the supervisor can stop only its recorded pid. Compare StartTime and command line with the applicable maker or taker daily-roll status, then use the owning fail-closed retirement path for the exact orphan." `
                $null $null
        }
    }
}
catch {
    Add-Finding "bots/duplicate_worker" "WARN" "could not enumerate bot processes: $($_.Exception.Message)" `
        "without this check a duplicate worker is invisible until capture starts failing memory admission" $null $null
}

# ---- 12. task last-run snapshot (Task Scheduler API only, never the event log) ----
$knownProducerNames = @($knownCriticals | ForEach-Object { @($_.producers) } | Where-Object { $_ } | Select-Object -Unique)
$taskResults = @()
$taskSnapshotFailures = @()
try {
    $taskSnapshot = Get-WeatherTaskResults -ConfigPath (Join-Path $repo "config\scheduled_tasks.json") -ExtraNames $knownProducerNames
    $taskResults = @($taskSnapshot.rows)
    $taskSnapshotFailures = @($taskSnapshot.failures)
}
catch { $taskSnapshotFailures = @("task snapshot failed: $($_.Exception.Message)") }
if ($taskSnapshotFailures.Count -gt 0) {
    Add-Finding "tasks/task_results" "WARN" `
        ("{0} task snapshot failure(s): {1}" -f $taskSnapshotFailures.Count, (($taskSnapshotFailures | Select-Object -First 3) -join '; ')) `
        "the daily task_results snapshot is the only record of each task's last run outside the event log; a gap here is not a task failure" $null $null
}

# ---- known-criticals post-pass (after every finding exists) ----
$producerStates = @{}
$producerRows = @{}
foreach ($t in $taskResults) {
    if ($t.state -and [string]$t.state -ne 'NotRegistered') { $producerStates[[string]$t.name] = [string]$t.state }
    $producerRows[[string]$t.name] = $t
}
$knownRows = New-Object System.Collections.Generic.List[object]
foreach ($kc in $knownCriticals) {
    $matched = @($findings | Where-Object { $_.check -eq [string]$kc.check })
    $targets = if ($matched.Count -gt 0) { $matched } else { @($null) }
    foreach ($finding in $targets) {
        $disp = Get-WeatherKnownCriticalDisposition -Row $kc -Finding $finding -ProducerStates $producerStates -Now $now -MaxDays $knownCriticalMaxDays
        switch ($disp.disposition) {
            'KNOWN' {
                $finding.severity = 'KNOWN'
                $producerText = (@($kc.producers) | ForEach-Object {
                    $pr = $producerRows[[string]$_]
                    $lastRun = if ($pr -and $pr.last_run_utc) { $pr.last_run_utc } else { 'never' }
                    "{0} {1}, last run {2}" -f $_, $(if ($pr) { $pr.state } else { 'unknown' }), $lastRun
                }) -join '; '
                $knownRows.Add([pscustomobject]@{
                    check = $finding.check; detail = $finding.detail; age_days = $finding.age_days
                    producers = $producerText; expires = [string]$kc.expires; decision = [string]$kc.decision
                })
            }
            'LAPSED' {
                Add-Finding "known/lapsed" "CRITICAL" ("{0}: {1}" -f $kc.check, $disp.reason) `
                    "a known-critical hold stopped applying; the original CRITICAL stands. Decide and record a dated DECISION_LOG row - never answer an expiry by running Stage B before B's look closes" $null $null
            }
            'MALFORMED' {
                Add-Finding "known/malformed" "CRITICAL" ("{0}: {1}" -f $(if ($kc.check) { $kc.check } else { '(unnamed)' }), $disp.reason) `
                    "an invalid known-criticals row holds nothing; fix the row in staleness_sweep.ps1 with its DECISION_LOG reference" $null $null
            }
        }
        if ($disp.disposition -eq 'MALFORMED') { break }
    }
}

# ---- report ----
$crit = @($findings | Where-Object { $_.severity -eq "CRITICAL" })
$warn = @($findings | Where-Object { $_.severity -eq "WARN" })
$known = @($findings | Where-Object { $_.severity -eq "KNOWN" })
$verdict = if ($crit.Count -gt 0) { "CRITICAL" } elseif ($warn.Count -gt 0) { "WARN" } else { "OK" }

$record = [ordered]@{
    ts = $now.ToString("o"); verdict = $verdict
    critical_count = $crit.Count; warn_count = $warn.Count; known_count = $known.Count; check_count = $findings.Count
    findings = @($findings | Where-Object { $_.severity -ne "OK" })
    task_results = @($taskResults)
}
try {
    $dir = Split-Path $JsonOut -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $record | ConvertTo-Json -Depth 6 -Compress | Add-Content -Path $JsonOut -Encoding utf8
}
catch {}

$md = New-Object System.Collections.Generic.List[string]
$md.Add("# Staleness sweep")
$md.Add("")
$md.Add(("Generated {0:yyyy-MM-dd HH:mm}. Regenerated every run; do not edit." -f $now))
$md.Add("")
$md.Add("**Verdict: $verdict** - $($crit.Count) critical, $($warn.Count) warn, $($known.Count) known, $($findings.Count) checks.")
$md.Add("")
$md.Add("Answers *should this have refreshed by now?* - the question the other monitors do not ask.")
$md.Add("")
if ($crit.Count -or $warn.Count) {
    $md.Add("| Sev | Check | Detail | Why it matters |")
    $md.Add("| --- | --- | --- | --- |")
    foreach ($f in @($crit + $warn)) {
        $md.Add(("| **{0}** | ``{1}`` | {2} | {3} |" -f $f.severity, $f.check, $f.detail, $f.why))
    }
}
else { $md.Add("Everything watched is within its declared freshness.") }
$md.Add("")
if ($knownRows.Count -gt 0) {
    # Never in the CRITICAL table above: status.ps1 counts only '| **CRITICAL** |' rows.
    $md.Add("## Known")
    $md.Add("")
    $md.Add("Listed CRITICALs held while every producer is Disabled and the row has not expired.")
    $md.Add("")
    $md.Add("| Check | Age | Producers (State, last run UTC) | Expires | Decision |")
    $md.Add("| --- | --- | --- | --- | --- |")
    foreach ($k in $knownRows) {
        $ageText = if ($null -ne $k.age_days) { "{0:N1}d" -f $k.age_days } else { $k.detail }
        $md.Add(("| ``{0}`` | {1} | {2} | {3} | {4} |" -f $k.check, $ageText, $k.producers, $k.expires, $k.decision))
    }
    $md.Add("")
}
$md.Add("## All checks")
$md.Add("")
foreach ($f in $findings) { $md.Add(("- ``{0}`` {1} - {2}" -f $f.check, $f.severity, $f.detail)) }
try { Set-Content -Path $MarkdownOut -Value ($md -join "`n") -Encoding utf8 } catch {}

Write-Output "staleness sweep: $verdict ($($crit.Count) critical, $($warn.Count) warn, $($known.Count) known, $($findings.Count) checks)"
foreach ($f in @($crit + $warn)) { Write-Output ("  [{0}] {1}: {2}" -f $f.severity, $f.check, $f.detail) }
Write-Output "wrote $MarkdownOut"

if ($crit.Count -gt 0) { exit 2 } elseif ($warn.Count -gt 0) { exit 1 } else { exit 0 }
