# Merge a validated topic branch into master during the quiet window, verifying that the
# capture fleet survives the code roll BEFORE anything is published.
#
#   .\scripts\ops\quiet_window_merge.ps1 -Branch origin/codex/... `
#       [-ExpectedTip <full-commit-sha>] [-Force] [-DryRun]
#
# Why this exists: merging a branch that touches modules the capture loops have imported
# makes the supervisors readopt the new code (STALE_CODE restart). If that code is bad,
# capture dies. Doing the merge locally first, proving capture recovers, and only then
# publishing means a bad merge is undone by resetting to the exact pre-merge commit with nothing
# published and no history to rewrite.
#
# Refuses to run outside 01:00-04:00 without -Force: a roll inside the 12:00-18:00 graded
# window can cost the streak day. See docs/ops/streak-soak.md.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [string]$ExpectedTip = "",
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [switch]$Force,
    [switch]$DryRun,
    [int]$SettleSeconds = 300,
    [ValidateRange(60, 3600)][int]$RollbackRecoverySeconds = 1200
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$py = Join-Path $repo "venv\Scripts\python.exe"
$workloadLeaseScript = Join-Path $repo "scripts\ops\workload_admission.ps1"
. $workloadLeaseScript
$reportPath = Join-Path $repo "data\alerts\quiet_window_merge_last.json"
$historyPath = Join-Path $repo "data\alerts\quiet_window_merge_history.jsonl"
$log = New-Object System.Collections.Generic.List[string]
$resolvedBranchTip = $null
$mergeTarget = $Branch
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
        expected_tip = $ExpectedTip; resolved_branch_tip = $resolvedBranchTip
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

# A scheduled caller may redirect this script's complete output to a task log.
# In Windows PowerShell 5.1 that turns native stderr into PowerShell error records;
# with the script-wide Stop preference, a harmless git warning can terminate the
# wrapper before we inspect git's actual exit code. Scope Continue to the native
# call, then restore Stop immediately. This does not hide a git failure: callers
# must still check the returned process exit code.
function Invoke-GitAllowingNativeStderr {
    param([Parameter(Mandatory = $true)][scriptblock]$Action)

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Action
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

$ExpectedTip = $ExpectedTip.Trim().ToLowerInvariant()
if ($ExpectedTip -and $ExpectedTip -notmatch '^[0-9a-f]{40}$') {
    Fail "ExpectedTip must be a full 40-character hexadecimal commit SHA"
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
$verdictRef = $(if ($ExpectedTip) { $ExpectedTip } else { $Branch })
if (Test-Path -LiteralPath $verdictScript) {
    & $verdictScript -Branch $verdictRef | ForEach-Object { Note "roll_verdict: $_" }
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
# WeatherLocationConfigRefresh rewrites the two config files every 6 hours, including once
# just before this window. Refusing that generated drift would make this tool abort on an
# otherwise normal production tree. The guard exists so a rollback cannot destroy WORK;
# these two files are fleet-regenerated state, not authored work. Commit them rather than
# ignore them, which both cleans the tree and preserves the drift, and only then take the
# rollback point. Keep this list exact: no other dirty tracked path may pass automatically.
$autoRefreshed = @(
    "config/locations.json",
    "config/location_market_events.json"
)
$dirtyTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
$unexpected = @($dirtyTracked | Where-Object {
        $p = ($_ -replace '^..\s*', '').Trim()
        $autoRefreshed -notcontains $p
    })
if ($unexpected.Count -gt 0) {
    Fail "tracked files are modified outside the fleet-generated drift set; commit or stash first so rollback cannot lose work:`n$($unexpected -join "`n")"
}

# This runs S4U in session 0, which cannot reach the credential vault, so fetch can fail
# exactly the way push does. That is survivable -- the local refs are what we merge -- but
# it means merging whatever copy of the branch was last fetched, so say so rather than
# letting a stale merge look like a fresh one.
& git fetch origin --prune | Out-Null
if ($LASTEXITCODE -ne 0) { Note "WARNING: git fetch failed (no credential vault under S4U?); merging the last-fetched copy of $Branch" }
$branchCommitRef = "{0}^{{commit}}" -f $Branch
& git rev-parse --verify $branchCommitRef | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "branch not found: $Branch" }
$resolvedBranchTip = (& git rev-parse $branchCommitRef).Trim().ToLowerInvariant()
if ($ExpectedTip) {
    if ($resolvedBranchTip -ne $ExpectedTip) {
        Fail "branch tip moved: $Branch resolves to $resolvedBranchTip, expected reviewed tip $ExpectedTip"
    }
    # Merge the immutable object, not the movable ref, so the reviewed identity remains
    # bound even if another process updates the branch after this check.
    $mergeTarget = $resolvedBranchTip
    Note "exact-tip binding passed: $Branch -> $resolvedBranchTip"
}
$head = (& git rev-parse HEAD).Trim()
$originMaster = (& git rev-parse origin/master).Trim()
if ($head -ne $originMaster) { Fail "local master ($head) != origin/master ($originMaster); reconcile first" }

if ($dirtyTracked.Count -gt 0 -and -not $DryRun) {
    Note "committing $($dirtyTracked.Count) fleet-generated drift file(s) so the merge starts clean"
    $gitAddExit = Invoke-GitAllowingNativeStderr { & git add -- $autoRefreshed }
    if ($gitAddExit -ne 0) { Fail "failed to stage fleet-generated drift (git exit $gitAddExit)" }
    $gitCommitExit = Invoke-GitAllowingNativeStderr {
        & git commit -m "ops: preserve fleet-generated drift (pre-merge, automated)" | Out-Null
    }
    if ($gitCommitExit -ne 0) { Fail "failed to commit fleet-generated drift (git exit $gitCommitExit)" }
}
# Take the rollback point AFTER the drift commit: resetting to origin/master would throw the
# drift away, and a rollback must undo only the merge.
$preMerge = (& git rev-parse HEAD).Trim()
# NEVER redirect a native command's stderr here (no *>$null, no 2>&1). Under
# $ErrorActionPreference='Stop', PowerShell 5.1 wraps each redirected stderr line in a
# NativeCommandError and terminates -- and git writes routine notices to stderr, so a
# harmless "CRLF will be replaced by LF" warning killed a dry run mid-merge and left the
# tree in a half-merged state (2026-07-25). Send stdout to Out-Null and let stderr print.
Note "pre-merge HEAD $preMerge; merging $Branch ($($resolvedBranchTip.Substring(0, 12)))"

# ---- capture baseline (what we will require to still be true afterwards) ----
# Command lines are hidden for S4U-owned processes, and one fresh snapshot heartbeat says
# nothing about the CLOB or observation workers. The checker validates all three workers'
# status + writer-lock PID, process liveness, heartbeat freshness, and loaded-source
# fingerprint against the current tree. That is the same recovery contract supervisors own.
$workloadLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload "quiet_window_merge"
if ($null -eq $workloadLease) { Fail "another heavyweight host workload owns data/logs/heavy_workload.lock" }
try {
function Get-CaptureState {
    try {
        $raw = @(& $py -m weather.operations.capture_recovery_check --repo-root $repo --json)
        $exitCode = $LASTEXITCODE
        $state = (($raw -join "`n") | ConvertFrom-Json)
        if ($exitCode -ne 0) { $state.ok = $false }
        return $state
    }
    catch {
        return [PSCustomObject]@{ ok = $false; workers = @(); error = $_.Exception.Message }
    }
}
$before = Get-CaptureState
Note "capture before: ok=$($before.ok), workers=$(@($before.workers).Count)"
if (-not $before.ok -or @($before.workers).Count -ne 3) {
    $detail = @($before.workers | Where-Object { -not $_.ok } | ForEach-Object { "$($_.name)=$($_.reasons -join ',')" }) -join "; "
    if (-not $detail) { $detail = [string]$before.error }
    Fail "capture recovery contract is not healthy before merge: $detail"
}

if ($DryRun) {
    & git merge --no-commit --no-ff $mergeTarget | Out-Null
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
& git merge --no-ff $mergeTarget -m "Merge $Branch into master"
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
Note "capture after: ok=$($after.ok), workers=$(@($after.workers).Count)"

$ok = $true
$why = @()
if (-not $after.ok -or @($after.workers).Count -ne 3) {
    $ok = $false
    $why += @($after.workers | Where-Object { -not $_.ok } | ForEach-Object { "$($_.name)=$($_.reasons -join ',')" })
    if ($after.error) { $why += [string]$after.error }
}
foreach ($beforeWorker in @($before.workers)) {
    $afterWorker = @($after.workers | Where-Object { $_.name -eq $beforeWorker.name }) | Select-Object -First 1
    if (-not $afterWorker) {
        $ok = $false; $why += "$($beforeWorker.name) missing after merge"; continue
    }
    # The snapshot worker normally heartbeats once per roughly ten-minute cycle, longer
    # than the default five-minute settle. Requiring every healthy worker to advance here
    # made a CLOB-only roll depend on where the unrelated snapshot sleep happened to fall.
    # The recovery checker above still requires every worker to be fresh, live, locked by
    # the matching PID, and loaded from the current tree. Require heartbeat advancement in
    # addition when this worker actually readopted (PID or recorded source identity changed).
    $workerReadopted = (
        [int]$afterWorker.pid -ne [int]$beforeWorker.pid -or
        [string]$afterWorker.recorded_source_fingerprint -ne [string]$beforeWorker.recorded_source_fingerprint
    )
    if (-not $workerReadopted) { continue }
    try {
        if ([datetime]$afterWorker.last_heartbeat -le [datetime]$beforeWorker.last_heartbeat) {
            $ok = $false
            $why += "$($beforeWorker.name) readopted but heartbeat did not advance ($($beforeWorker.last_heartbeat) -> $($afterWorker.last_heartbeat))"
        }
    }
    catch { $ok = $false; $why += "$($beforeWorker.name) readoption heartbeat comparison failed" }
}

if (-not $ok) {
    Note "capture did NOT recover: $($why -join '; ')"
    & git reset --hard $preMerge | Out-Null
    Note "rolled back to $preMerge; nothing was pushed. Waiting up to ${RollbackRecoverySeconds}s for all workers to re-adopt the rollback..."
    $rollbackDeadline = (Get-Date).AddSeconds($RollbackRecoverySeconds)
    $rollbackState = Get-CaptureState
    while (
        (-not $rollbackState.ok -or @($rollbackState.workers).Count -ne 3) -and
        (Get-Date) -lt $rollbackDeadline
    ) {
        Start-Sleep -Seconds 15
        $rollbackState = Get-CaptureState
    }
    if (-not $rollbackState.ok -or @($rollbackState.workers).Count -ne 3) {
        $rollbackWhy = @(
            $rollbackState.workers |
                Where-Object { -not $_.ok } |
                ForEach-Object { "$($_.name)=$($_.reasons -join ',')" }
        )
        if ($rollbackState.error) { $rollbackWhy += [string]$rollbackState.error }
        if ($rollbackWhy.Count -eq 0) { $rollbackWhy += "capture recovery contract unreadable" }
        $detail = "merge recovery failed: $($why -join '; '); rollback recovery unproven: $($rollbackWhy -join '; ')"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }
    Note "all three workers re-adopted the rollback and satisfy the capture recovery contract"
    Save-Report -ok $false -stage "rolled_back" -detail ($why -join "; ")
    exit 2
}

# ---- bind the post-integration documentation transaction before publication ----
# The documentation closeout cannot truthfully finish until the exact merge and live recovery
# exist. Record that debt now, before publication, so a missing morning closeout is visible in
# status and a later transaction can cover the exact pending-state hash. Stacked overnight
# merges append to the same bounded transaction.
$documentationArgs = @(
    "-m", "weather.operations.documentation_transaction",
    "--repo-root", $repo,
    "begin",
    "--integration-tip", $mergeCommit,
    "--branch", $Branch
)
if ($ExpectedTip) { $documentationArgs += @("--expected-tip", $ExpectedTip) }
$documentationOutput = & $py @documentationArgs
if ($LASTEXITCODE -ne 0) {
    Note "documentation transaction could not be recorded: $($documentationOutput -join ' ')"
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation transaction begin failed for $mergeCommit"
    exit 3
}
Note "documentation transaction recorded for $mergeCommit"

# ---- only now publish, through the credential-bearing scheduled task ----
# Interactive git push is forbidden on this host. The scheduled task owns the credential
# context, and origin/master is the acknowledgement that the immutable merge commit landed.
Note "capture healthy after the roll; handing $mergeCommit to WeatherOneShotPush"
try { Start-ScheduledTask -TaskName WeatherOneShotPush -ErrorAction Stop }
catch {
    Note "could not start WeatherOneShotPush: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "push task start failed; commit $mergeCommit is local"
    exit 3
}
$pushed = $false
for ($i = 0; $i -lt 18; $i++) {
    Start-Sleep -Seconds 10
    if ((& git rev-parse origin/master).Trim() -eq $mergeCommit) { $pushed = $true; break }
}
if (-not $pushed) {
    Note "WeatherOneShotPush did not publish within 3 min. Merge is committed locally and capture is healthy."
    Save-Report -ok $true -stage "merged_unpushed" -detail "push task did not acknowledge commit $mergeCommit"
    exit 3
}
Note "pushed $mergeCommit via WeatherOneShotPush"
Save-Report -ok $true -stage "pushed" -detail "$mergeCommit (via WeatherOneShotPush)"
exit 0
}
finally { Exit-WeatherHeavyWorkloadLease -Lease $workloadLease }
