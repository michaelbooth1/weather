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
    try {
        [ordered]@{
            ts = (Get-Date).ToString("o"); branch = $Branch; ok = $ok
            stage = $stage; detail = $detail; log = @($log)
        } | ConvertTo-Json -Depth 5 | Set-Content -Path $reportPath -Encoding utf8
    }
    catch {}
}

# ---- window guard ----
$h = (Get-Date).Hour + ((Get-Date).Minute / 60.0)
if (-not $Force -and -not ($h -ge 1 -and $h -lt 4)) {
    Fail ("outside the 01:00-04:00 quiet window (now {0:N2}); use -Force only if you are certain a capture roll is safe right now" -f $h)
}
if ($h -ge 12 -and $h -lt 18) { Fail "inside the 12:00-18:00 graded capture window - never roll the fleet here" }

# ---- preconditions ----
Set-Location $repo
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

& git fetch origin --prune | Out-Null
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
    Note "push failed (pushes need an interactive logon session). Merge is committed locally and will go out on the next successful push; capture is healthy."
    Save-Report -ok $true -stage "merged_unpushed" -detail "push failed; commit $mergeCommit is local"
    exit 3
}
Note "pushed $mergeCommit"
Save-Report -ok $true -stage "pushed" -detail $mergeCommit
exit 0
