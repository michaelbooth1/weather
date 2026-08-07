# Merge a validated topic branch into master during the quiet window, verifying that the
# capture fleet survives the code roll BEFORE anything is published.
#
#   .\scripts\ops\quiet_window_merge.ps1 -Branch origin/codex/... [-Force] [-DryRun]
#
# Why this exists: merging a branch that touches modules the capture loops have imported
# makes the supervisors readopt the new code (STALE_CODE restart). If that code is bad,
# capture dies. Doing the merge locally first, proving capture recovers, and only then
# pushing means a bad merge is undone by `git reset --hard origin/master` with nothing
# published and no history to rewrite.
#
# Refuses to run outside 01:00-04:00 without -Force: a roll inside the 12:00-18:00 graded
# window can cost the streak day. See docs/ops/streak-soak.md.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [switch]$Force,
    [switch]$DryRun,
    [int]$SettleSeconds = 300
)

$ErrorActionPreference = "Stop"
$repo = "C:\Users\micha\Desktop\github\weather"
$py = Join-Path $repo "venv\Scripts\python.exe"
$reportPath = Join-Path $repo "data\alerts\quiet_window_merge_last.json"
$historyPath = Join-Path $repo "data\alerts\quiet_window_merge_history.jsonl"
$log = New-Object System.Collections.Generic.List[string]
function Note($m) {
    $line = "{0}  {1}" -f (Get-Date -Format "HH:mm:ss"), $m
    $log.Add($line); Write-Output $line
}
function Fail($m) {
    Note "ABORT: $m"
    Save-Report -ok $false -stage "abort" -detail $m
    exit 1
}
function Save-Report($ok, $stage, $detail) {
    $record = [ordered]@{
        ts = (Get-Date).ToString("o"); branch = $Branch; ok = $ok
        stage = $stage; detail = $detail; log = @($log)
    }
    try {
        $record | ConvertTo-Json -Depth 5 | Set-Content -Path $reportPath -Encoding utf8
    }
    catch {}
    # $reportPath is a single most-recent slot, so a later run ERASES an earlier one. On
    # 2026-08-01 three scheduled merges aborted at 01:15/01:50/02:25 (the config-drift trap)
    # and a manual re-run at 02:55 succeeded and overwrote all three -- leaving no on-disk
    # trace of the failures at all, only the task exit codes. That is exactly how the aborts
    # were later mis-read as a cosmetic exit code. Append every outcome so history survives.
    try {
        $record | ConvertTo-Json -Depth 5 -Compress | Add-Content -Path $historyPath -Encoding utf8
    }
    catch {}
}

# ---- window guard, proportional to the branch's actual roll verdict ----
# This used to demand 01:00-04:00 for EVERY branch, including branches that cannot roll
# anything. That is a guard against a risk the branch does not carry, and it was the real
# reason the merge queue backed up: 25 unmerged branches queued for three hours a night,
# most of them roll-free. A guard that costs more than the risk it prevents gets worked
# around, and then it protects nothing.
#
# So ask first. roll_verdict.ps1 derives the answer from the live closures rather than by
# hand -- exit 0 roll-free, 2 roll-free-only-while-a-loop-stays-dormant, 3 roll-sensitive,
# 1 undecidable. Anything that is not a clean 0 is treated as roll-sensitive: the cost of a
# wrong "free" is a streak day, the cost of a wrong "sensitive" is waiting until 01:00.
$h = (Get-Date).Hour + ((Get-Date).Minute / 60.0)
$verdictScript = Join-Path $repo "scripts\ops\roll_verdict.ps1"
$rollFree = $false
if (Test-Path -LiteralPath $verdictScript) {
    & $verdictScript -Branch $Branch | ForEach-Object { Note "roll_verdict: $_" }
    $rollFree = ($LASTEXITCODE -eq 0)
    Note ("roll verdict exit {0} -> {1}" -f $LASTEXITCODE, $(if ($rollFree) { "ROLL-FREE" } else { "treated as ROLL-SENSITIVE" }))
}
else { Note "roll_verdict.ps1 not found - treating branch as ROLL-SENSITIVE" }

# 12:00-18:00 is graded and 18:00-00:30 is the protected near-close window; heavy work is
# barred from both by HOST_LOAD_POLICY regardless of roll sensitivity, because the merge
# still runs a test suite beside live capture.
if ($h -ge 12 -and $h -lt 18) { Fail "inside the 12:00-18:00 graded capture window - never merge here" }
if ($h -ge 18 -or $h -lt 0.5) { Fail ("inside the 18:00-00:30 protected near-close window (now {0:N2}) - no heavy work here" -f $h) }

if (-not $rollFree -and -not $Force -and -not ($h -ge 1 -and $h -lt 4)) {
    Fail ("roll-sensitive branch outside the 01:00-04:00 quiet window (now {0:N2}); use -Force only if you are certain a capture roll is safe right now" -f $h)
}
if ($rollFree) { Note ("roll-free branch: 01:00-04:00 not required (now {0:N2})" -f $h) }

# ---- preconditions ----
Set-Location $repo
# Never start on top of a merge that is already in progress. WeatherBootRecovery cleans one
# up after a power loss, but if that has not run yet the tree still holds unreviewed merged
# code, and merging again on top of it would bury the problem instead of surfacing it.
if (Test-Path (Join-Path $repo ".git\MERGE_HEAD")) {
    Fail "a merge is already in progress (.git/MERGE_HEAD exists) - resolve or abort it first; see data/alerts/boot_events.jsonl for an interrupted-merge record"
}
# WeatherLocationConfigRefresh rewrites these tracked files every 6 hours, including once
# just before this window, so the tree is dirty here most nights. Refusing on that would
# make this tool abort almost every time it ran (caught 2026-07-25, before the first real
# merge). The guard exists so a rollback cannot destroy WORK -- regenerated config is not
# work: the fleet rebuilds it from live data within 6h. So commit it rather than ignore it,
# which both cleans the tree and preserves the drift, and only then take the rollback point.
$autoRefreshed = @("config/locations.json", "config/location_market_events.json")
$dirtyTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
$unexpected = @($dirtyTracked | Where-Object {
        $p = ($_ -replace '^..\s*', '').Trim()
        $autoRefreshed -notcontains $p
    })
if ($unexpected.Count -gt 0) {
    Fail "tracked files are modified outside the auto-refreshed config set; commit or stash first so rollback cannot lose work:`n$($unexpected -join "`n")"
}

# This runs S4U in session 0, which cannot reach the credential vault, so fetch can fail
# exactly the way push does. That is survivable -- the local refs are what we merge -- but
# it means merging whatever copy of the branch was last fetched, so say so rather than
# letting a stale merge look like a fresh one.
& git fetch origin --prune | Out-Null
if ($LASTEXITCODE -ne 0) { Note "WARNING: git fetch failed (no credential vault under S4U?); merging the last-fetched copy of $Branch" }
$head = (& git rev-parse HEAD).Trim()
$originMaster = (& git rev-parse origin/master).Trim()
if ($head -ne $originMaster) { Fail "local master ($head) != origin/master ($originMaster); reconcile first" }

if ($dirtyTracked.Count -gt 0 -and -not $DryRun) {
    Note "committing $($dirtyTracked.Count) auto-refreshed config file(s) so the merge starts clean"
    & git add -- $autoRefreshed
    & git commit -m "config: scheduled location refresh drift (pre-merge, automated)" | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "failed to commit auto-refreshed config drift" }
}
# Take the rollback point AFTER the drift commit: resetting to origin/master would throw the
# drift away, and a rollback must undo only the merge.
$preMerge = (& git rev-parse HEAD).Trim()
# NEVER redirect a native command's stderr here (no *>$null, no 2>&1). Under
# $ErrorActionPreference='Stop', PowerShell 5.1 wraps each redirected stderr line in a
# NativeCommandError and terminates -- and git writes routine notices to stderr, so a
# harmless "CRLF will be replaced by LF" warning killed a dry run mid-merge and left the
# tree in a half-merged state (2026-07-25). Send stdout to Out-Null and let stderr print.
& git rev-parse --verify "$Branch" | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "branch not found: $Branch" }
Note "pre-merge HEAD $preMerge; merging $Branch ($(& git rev-parse --short $Branch))"

# ---- capture baseline (what we will require to still be true afterwards) ----
function Get-CaptureState {
    $s = @{ loops = 0; heartbeat = $null }
    Get-CimInstance Win32_Process | Where-Object {
        ($_.CommandLine -like '*weather.collection.snapshot_tracker*' -or
        $_.CommandLine -like '*weather.market.market_microstructure*' -or
        $_.CommandLine -like '*weather.operations.observation_trigger*') -and
        $_.CommandLine -notlike '*hot_capture*' -and
        $_.CommandLine -notlike '*--expected-runtime-fingerprint*'
    } | ForEach-Object { $s.loops++ }
    try {
        $j = Get-Content (Join-Path $repo "data\snapshots\loop_status.json") -Raw | ConvertFrom-Json
        $s.heartbeat = [datetime]$j.last_heartbeat
    }
    catch {}
    return $s
}
$before = Get-CaptureState
Note "capture before: $($before.loops) loops, heartbeat $($before.heartbeat)"
if ($before.loops -lt 1) { Fail "no capture loops running before the merge; fix that first" }

if ($DryRun) {
    & git merge --no-commit --no-ff $Branch | Out-Null
    $conflicts = @(& git diff --name-only --diff-filter=U | Where-Object { $_ })
    # Always unwind: leaving a half-merged tree changes loop-loaded modules on disk and
    # provokes a STALE_CODE readoption roll. `merge --abort` restores the pre-merge state
    # including uncommitted config drift -- do NOT reset --hard here, that would delete it.
    & git merge --abort | Out-Null
    Note "DRY RUN: conflicts=$($conflicts.Count)"
    Save-Report -ok $true -stage "dry_run" -detail "conflicts=$($conflicts.Count)"
    exit 0
}

# ---- merge locally (this is what triggers the readoption roll) ----
& git merge --no-ff $Branch -m "Merge $Branch into master"
if ($LASTEXITCODE -ne 0) {
    & git merge --abort | Out-Null
    Fail "merge failed or conflicted; working tree restored"
}
$mergeCommit = (& git rev-parse HEAD).Trim()
Note "merged locally as $mergeCommit (NOT pushed yet)"

# ---- wait for the fleet to readopt, then prove capture actually recovered ----
Note "waiting ${SettleSeconds}s for supervisors to readopt the new code..."
Start-Sleep -Seconds $SettleSeconds
$after = Get-CaptureState
Note "capture after: $($after.loops) loops, heartbeat $($after.heartbeat)"

$ok = $true
$why = @()
if ($after.loops -lt $before.loops) { $ok = $false; $why += "loop count fell $($before.loops) -> $($after.loops)" }
if ($null -eq $after.heartbeat) { $ok = $false; $why += "no readable snapshot heartbeat" }
elseif ($before.heartbeat -and $after.heartbeat -le $before.heartbeat) {
    $ok = $false; $why += "snapshot heartbeat did not advance ($($before.heartbeat) -> $($after.heartbeat))"
}
else {
    $age = ((Get-Date) - $after.heartbeat).TotalMinutes
    if ($age -gt 20) { $ok = $false; $why += ("heartbeat stale by {0:N1} min" -f $age) }
}

if (-not $ok) {
    Note "capture did NOT recover: $($why -join '; ')"
    & git reset --hard $preMerge | Out-Null
    Note "rolled back to $preMerge; supervisors will readopt the previous code. Nothing was pushed."
    Save-Report -ok $false -stage "rolled_back" -detail ($why -join "; ")
    exit 2
}

# ---- only now publish ----
Note "capture healthy after the roll; pushing"
& git push origin master
if ($LASTEXITCODE -ne 0) {
    # Expected under S4U: session 0 cannot reach the credential vault. Do NOT stop here --
    # a merge that lands locally but never reaches origin blocks the workstation agent until
    # somebody logs in, which overnight means hours of idle. WeatherOneShotPush is
    # deliberately Interactive and runs in the operator's logon session (which survives an
    # RDP disconnect), so hand the push to it rather than deferring to morning.
    Note "direct push failed (no credential vault under S4U); handing off to WeatherOneShotPush"
    try { Start-ScheduledTask -TaskName WeatherOneShotPush -ErrorAction Stop }
    catch { Note "could not start WeatherOneShotPush: $($_.Exception.Message)" }
    # A successful push updates refs/remotes/origin/master locally, so this verifies the
    # push landed without needing a fetch -- which would need the same credentials.
    $pushed = $false
    for ($i = 0; $i -lt 18; $i++) {
        Start-Sleep -Seconds 10
        if ((& git rev-parse origin/master).Trim() -eq $mergeCommit) { $pushed = $true; break }
    }
    if (-not $pushed) {
        Note "handoff did not publish within 3 min. Merge is committed locally and capture is healthy; run WeatherOneShotPush once a session is available."
        Save-Report -ok $true -stage "merged_unpushed" -detail "push failed; commit $mergeCommit is local"
        exit 3
    }
    Note "pushed $mergeCommit via WeatherOneShotPush"
    Save-Report -ok $true -stage "pushed" -detail "$mergeCommit (via WeatherOneShotPush handoff)"
    exit 0
}
Note "pushed $mergeCommit"
Save-Report -ok $true -stage "pushed" -detail $mergeCommit
exit 0
