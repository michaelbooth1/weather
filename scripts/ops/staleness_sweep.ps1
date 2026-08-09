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
    Exit 0 all fresh, 1 one or more WARN, 2 one or more CRITICAL.
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
    $age = ($now - (Get-Item -LiteralPath $path).LastWriteTime).TotalDays
    $sev = if ($age -gt $critDays) { "CRITICAL" } elseif ($age -gt $warnDays) { "WARN" } else { "OK" }
    Add-Finding $name $sev ("{0} is {1:N1}d old" -f $relPath, $age) $why $age $warnDays
}

# ---- 1. capture closures: freshness AND tombstones ----
# A closure that stops reporting silently removes itself from every roll verdict derived after --
# but ONLY for the files it alone contributes. On 2026-08-06 clob-enrichment sat at CRITICAL for
# 10.5 days while contributing ZERO unique files: its 21-file closure is a strict subset of the live
# CLOB loop's 23. A CRITICAL that cannot possibly produce a wrong roll verdict is alarm fatigue, and
# alarm fatigue is what makes the next real one get waved through. So compute the unique surface
# rather than assert it, and when it is non-empty NAME the files -- those are exactly the ones a
# merge would roll blind. See RETRACTED_AND_FALSE_LEADS.md section 3.
$closureFiles = [ordered]@{
    "snapshot"            = "data\snapshots\loop_supervisor_status.json"
    "clob"                = "data\snapshots\clob_loop_supervisor_status.json"
    "observation-trigger" = "data\snapshots\observation_trigger_supervisor_status.json"
    "clob-enrichment"     = "data\snapshots\clob_enrichment_status.json"
}
function Get-ClosureScope($path) {
    try { $j = Get-Content -LiteralPath $path -Raw -ErrorAction Stop | ConvertFrom-Json } catch { return $null }
    foreach ($k in "current_runtime_identity", "runtime_identity_before", "runtime_identity") {
        $node = $j.$k
        if ($node -and $node.source_scope_files) { return @($node.source_scope_files) }
    }
    return $null
}
$closureState = @{}
foreach ($name in $closureFiles.Keys) {
    $p = Join-Path $repo $closureFiles[$name]
    if (-not (Test-Path -LiteralPath $p)) { $closureState[$name] = $null; continue }
    $closureState[$name] = [PSCustomObject]@{
        Age   = ($now - (Get-Item -LiteralPath $p).LastWriteTime).TotalDays
        Scope = Get-ClosureScope $p
    }
}
# Union of everything a still-reporting closure covers. Anything in here cannot go dark.
$liveScope = New-Object System.Collections.Generic.HashSet[string]([StringComparer]::OrdinalIgnoreCase)
foreach ($name in $closureFiles.Keys) {
    $c = $closureState[$name]
    if ($c -and $c.Age -le 1 -and $c.Scope) { foreach ($f in $c.Scope) { [void]$liveScope.Add($f) } }
}
$closureWhy = "a closure that stops reporting is silently dropped from every later roll verdict; merges then look safer than they are"
foreach ($name in $closureFiles.Keys) {
    $rel = $closureFiles[$name]
    $c = $closureState[$name]
    if (-not $c) { Add-Finding "closure/$name" "CRITICAL" "missing: $rel" $closureWhy $null 1; continue }
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
# Tombstones masquerade as live evidence. This one was read as a fifth closure on 2026-08-06.
$tomb = Join-Path $repo "data\snapshots\loop_status_supervisor_status.json"
if (Test-Path -LiteralPath $tomb) {
    try {
        $t = Get-Content -LiteralPath $tomb -Raw | ConvertFrom-Json
        if ([string]$t.state -eq "DEAD" -or [string]$t.ensure_status -eq "BLOCKED") {
            Add-Finding "closure/tombstone" "WARN" `
                ("loop_status_supervisor_status.json is a DEAD tombstone (state={0}, {1})" -f $t.state, $t.reason) `
                "it carries a full source_scope_files list and reads as live closure evidence; roll_verdict.ps1 rejects it, hand analysis did not" `
                $null $null
        }
    }
    catch {}
}

# ---- 2. the learning loop's own outputs ----
Test-FileAge "learning/daily_learning" "data\backtest\daily_learning.json" 2 5 `
    "the learning rollup; it sat 27 days stale while the chain reported all steps ok, because it is 21 steps past the settled-day barrier"
Test-FileAge "learning/market_beating_scoreboard" "data\backtest\market_beating_objective_scoreboard.json" 2 5 `
    "the scorecard for objective #2 -- while this is stale we cannot see the model-vs-market gap at all"
Test-FileAge "chain/daily_refresh_report" "data\backtest\daily_refresh_report.md" 1 2 `
    "the chain's own output; if this stops moving the chain is not completing"

# ---- 3. serving artifacts ----
# Not a bug on its own -- but an artifact serving a season it never trained on is (see 4b/2).
$hgb = Join-Path $repo "artifacts\models\hgb\feature_model_hgb.pkl"
if (Test-Path -LiteralPath $hgb) {
    $age = ($now - (Get-Item -LiteralPath $hgb).LastWriteTime).TotalDays
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
            $sev = if ($covers) { "OK" } else { "CRITICAL" }
            Add-Finding "archive/season_relevance" $sev `
                ("archive season is {0:00}-{1:00} to {2:00}-{3:00}; today {4:MM-dd} is {5}" -f $s[0], $s[1], $e[0], $e[1], $today, $(if ($covers) { "inside" } else { "OUTSIDE" })) `
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
    $sev = if ($branches.Count -ge 30) { "WARN" } else { "OK" }
    Add-Finding "git/unmerged_branches" $sev "$($branches.Count) unmerged remote branch(es)" `
        "agent reports live only on unmerged branches; a growing count means evidence is accumulating off master" $null 30
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
            try { $td = (ConvertFrom-Json $line).target_date } catch { continue }
            if (-not $td) { continue }
            try { $d = [datetime]::ParseExact([string]$td, "yyyy-MM-dd", $null) } catch { continue }
            if (($null -eq $latest) -or ($d -gt $latest)) { $latest = $d }
        }
    }
    if ($latest) {
        $behind = ($now.Date - $latest).TotalDays
        $sev = if ($behind -ge 3) { "CRITICAL" } elseif ($behind -ge 2 -and $now.Hour -ge 12) { "WARN" } else { "OK" }
        Add-Finding "settlement/latest" $sev ("latest settled target is {0:yyyy-MM-dd}, {1:N0}d behind" -f $latest, $behind) `
            "each chain run settles only yesterday; a missed day is never retried and needs an explicit backfill" $behind 2
    }
}

# ---- 7. log rotation (bounded: known dirs only, never a recursive data/ walk) ----
foreach ($dir in @("data\snapshots", "data\logs", "data\alerts")) {
    $full = Join-Path $repo $dir
    if (-not (Test-Path -LiteralPath $full)) { continue }
    foreach ($f in @(Get-ChildItem -LiteralPath $full -File -Include *.log, *.jsonl -ErrorAction SilentlyContinue)) {
        $mb = $f.Length / 1MB
        if ($mb -gt 256) {
            Add-Finding "logs/unrotated" "WARN" ("{0} is {1:N0} MB" -f $f.Name, $mb) `
                "an unrotated 489 MB clob_diagnostics.jsonl was the write that crash-looped the CLOB loop on 2026-07-12" $null $null
        }
    }
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
    $orphans = @($opsDocs | Where-Object { -not $linked.Contains($_.FullName) })
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
    $age = ($now - (Get-Item -LiteralPath $sop).LastWriteTime).TotalDays
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

# ---- 10. has the in-flight table drifted from the newest commissioned work? ----
# On 2026-08-06 a handoff was committed and STATE_OF_PLAY was NOT updated in the same change, so
# the entry point silently omitted the one mission aimed at the gap it calls unowned. A cold agent
# would have commissioned it a third time.
#
# This deliberately does NOT try to decide dispatch state. The first cut of this check did, and
# reported 47 completed missions as leaks: a branch is deleted after merge, and reports are named
# by CALENDAR date while handoffs are named by MISSION ref, so the two filenames share only the
# slug. Deciding dispatch needs all four records in mission-dispatch-reconciliation.md, including a
# withdrawal grep -- too ambiguous for an unattended check, and a WARN nobody can clear is worse
# than no WARN. So check the one thing that is unambiguous: the newest handoffs are named here.
$handoffDir = Join-Path $repo "docs\roadmap"
$sopPath = Join-Path $repo "docs\operations\STATE_OF_PLAY.md"
if ((Test-Path -LiteralPath $handoffDir) -and (Test-Path -LiteralPath $sopPath)) {
    $newest = @(& git -C $repo log --diff-filter=A --name-only --format="" -n 400 -- "docs/roadmap/workstation-handoff-*.md" 2>$null |
        Where-Object { $_ } | Select-Object -Unique -First 4)
    if ($newest.Count -gt 0) {
        $sopText = Get-Content -LiteralPath $sopPath -Raw
        $missing = @()
        foreach ($rel in $newest) {
            if ((Split-Path $rel -Leaf) -notmatch '^workstation-handoff-\d{4}-(\d{2}-\d+[a-z])-') { continue }
            $short = "-" + $Matches[1]     # e.g. "-09-36a", the form STATE_OF_PLAY uses
            if ($sopText -notlike "*$short*") { $missing += $short }
        }
        if ($missing.Count -gt 0) {
            Add-Finding "docs/in_flight_drift" "WARN" `
                ("STATE_OF_PLAY.md does not mention the recently commissioned {0}" -f ($missing -join ", ")) `
                "the in-flight table is the only record of what has been commissioned; a handoff committed without updating it is invisible to a cold agent, who will commission the same work again" `
                $null $null
        }
    }
}

# ---- 11. is anything actually scheduled to merge? ----
# The window guard was made proportional so roll-free branches would stop queueing for the 01:00
# quiet window. That removed the blocker but left nothing driving the queue: on 2026-08-06 four
# branches were mechanically ROLL-FREE and mergeable at any hour, and had been sitting for days,
# because "mergeable at any hour" turned out to mean nobody merged them. One of them was the sole
# blocker for the learning loop, the market-beating scoreboard, and the disk tiering path.
$unmergedCount = @(& git -C $repo branch -r --no-merged origin/master 2>$null | Where-Object { $_ -and $_ -notmatch "HEAD" }).Count
if ($unmergedCount -gt 0) {
    $armed = @()
    try {
        $armed = @(Get-ScheduledTask -ErrorAction SilentlyContinue |
            Where-Object { $_.TaskName -like "*Merge*" -and $_.State -ne "Disabled" } |
            Where-Object { ($_ | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue).NextRunTime })
    }
    catch {}
    if ($armed.Count -eq 0) {
        Add-Finding "git/no_merge_trigger" "WARN" `
            ("{0} unmerged branch(es) and no merge task has a next run time" -f $unmergedCount) `
            "roll-free branches no longer need the quiet window, so nothing forces them through; check scripts\ops\roll_verdict.ps1 and arm scripts\ops\quiet_window_merge.ps1 rather than waiting for a window" `
            $null $null
    }
}

# ---- 12. duplicate bot workers (the orphan that eats the capture budget) ----
# A daily-roll supervisor stops exactly ONE pid: the one recorded in its status file
# (bot_daily_roll_supervisor.ps1 stop_daily_roll_process -> status.get("pid")). So a worker
# orphaned by a start race is invisible to every later stop and runs until the host reboots.
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
                "more than one live run of the same bot means an unreapable orphan is holding memory capture needs" $null $null
        }
        if ($roots.Count -gt 1) {
            $starts = (($roots | Sort-Object CreationDate | ForEach-Object { $_.CreationDate.ToString('HH:mm:ss') }) -join ', ')
            Add-Finding "bots/duplicate_worker" "CRITICAL" `
                ("{0} has {1} live runs (started {2})" -f $modName, $roots.Count, $starts) `
                "a daily-roll supervisor only ever stops the one pid in its status file, so an orphan from a start race is unreapable; each holds ~430 MB and capture admission needs 3.49 GB free per worker -- on 2026-08-07 this caused 430 memory-admission refusals and two in-window capture gaps. Identify the orphan by StartTime against the pid in data\mm_runs\daily_roll_status.json, then stop it." `
                $null $null
        }
    }
}
catch {
    Add-Finding "bots/duplicate_worker" "WARN" "could not enumerate bot processes: $($_.Exception.Message)" `
        "without this check a duplicate worker is invisible until capture starts failing memory admission" $null $null
}

# ---- report ----
$crit = @($findings | Where-Object { $_.severity -eq "CRITICAL" })
$warn = @($findings | Where-Object { $_.severity -eq "WARN" })
$verdict = if ($crit.Count -gt 0) { "CRITICAL" } elseif ($warn.Count -gt 0) { "WARN" } else { "OK" }

$record = [ordered]@{
    ts = $now.ToString("o"); verdict = $verdict
    critical_count = $crit.Count; warn_count = $warn.Count; check_count = $findings.Count
    findings = @($findings | Where-Object { $_.severity -ne "OK" })
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
$md.Add("**Verdict: $verdict** - $($crit.Count) critical, $($warn.Count) warn, $($findings.Count) checks.")
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
$md.Add("## All checks")
$md.Add("")
foreach ($f in $findings) { $md.Add(("- ``{0}`` {1} - {2}" -f $f.check, $f.severity, $f.detail)) }
try { Set-Content -Path $MarkdownOut -Value ($md -join "`n") -Encoding utf8 } catch {}

Write-Output "staleness sweep: $verdict ($($crit.Count) critical, $($warn.Count) warn, $($findings.Count) checks)"
foreach ($f in @($crit + $warn)) { Write-Output ("  [{0}] {1}: {2}" -f $f.severity, $f.check, $f.detail) }
Write-Output "wrote $MarkdownOut"

if ($crit.Count -gt 0) { exit 2 } elseif ($warn.Count -gt 0) { exit 1 } else { exit 0 }
