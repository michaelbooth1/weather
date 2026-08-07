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
# A closure that stops reporting silently removes itself from every roll verdict derived after.
$closureFiles = @{
    "snapshot"            = "data\snapshots\loop_supervisor_status.json"
    "clob"                = "data\snapshots\clob_loop_supervisor_status.json"
    "observation-trigger" = "data\snapshots\observation_trigger_supervisor_status.json"
    "clob-enrichment"     = "data\snapshots\clob_enrichment_status.json"
}
foreach ($name in $closureFiles.Keys | Sort-Object) {
    Test-FileAge "closure/$name" $closureFiles[$name] 1 3 `
        "a closure that stops reporting is silently dropped from every later roll verdict; merges then look safer than they are"
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
$manifest = Join-Path $repo "data\forecast_history\cyyz\manifest.json"
if (Test-Path -LiteralPath $manifest) {
    try {
        $m = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
        if ($m.season_window) {
            $s = $m.season_window.start; $e = $m.season_window.end
            $today = $now.Date
            $winStart = Get-Date -Year $today.Year -Month $s[0] -Day $s[1]
            $winEnd = Get-Date -Year $today.Year -Month $e[0] -Day $e[1]
            $covers = ($today -ge $winStart -and $today -le $winEnd)
            $sev = if ($covers) { "OK" } else { "CRITICAL" }
            Add-Finding "archive/season_relevance" $sev `
                ("archive season is {0:00}-{1:00} to {2:00}-{3:00}; today {4:MM-dd} is {5}" -f $s[0], $s[1], $e[0], $e[1], $today, $(if ($covers) { "inside" } else { "OUTSIDE" })) `
                "a target outside the archive season gets ZERO training rows; this is why the first retrain blocks at 0/12,600 cells" `
                $null $null
        }
    }
    catch {}
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
