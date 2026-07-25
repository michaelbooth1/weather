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
$dirtyTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
if ($dirtyTracked.Count -gt 0) {
    Fail "tracked files are modified; commit or stash first so rollback cannot lose work:`n$($dirtyTracked -join "`n")"
}
& git fetch origin --prune | Out-Null
$preMerge = (& git rev-parse HEAD).Trim()
$originMaster = (& git rev-parse origin/master).Trim()
if ($preMerge -ne $originMaster) { Fail "local master ($preMerge) != origin/master ($originMaster); reconcile first" }
& git rev-parse --verify "$Branch" *>$null
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
    & git merge --no-commit --no-ff $Branch *>$null
    $conflicts = @(& git diff --name-only --diff-filter=U | Where-Object { $_ })
    & git merge --abort 2>$null
    Note "DRY RUN: conflicts=$($conflicts.Count)"
    Save-Report -ok $true -stage "dry_run" -detail "conflicts=$($conflicts.Count)"
    exit 0
}

# ---- merge locally (this is what triggers the readoption roll) ----
& git merge --no-ff $Branch -m "Merge $Branch into master"
if ($LASTEXITCODE -ne 0) {
    & git merge --abort 2>$null
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
