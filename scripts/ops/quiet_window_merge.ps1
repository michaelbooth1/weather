# Merge a validated topic branch into master during the quiet window, verifying that the
# capture fleet survives the code roll BEFORE anything is published.
#
#   .\scripts\ops\quiet_window_merge.ps1 -Branch origin/codex/... `
#       [-ExpectedTip <full-commit-sha>] [-ExpectedBaseline <full-master-sha>] `
#       [-Force] [-DryRun] [-OwnerApprovedException <one-time-token>]
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
    [string]$ExpectedBaseline = "",
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$AttemptReportPath = "",
    [string]$ExpectedSelfSha256 = "",
    [string]$OwnerApprovedException = "",
    [switch]$RequireLiveOrigin,
    [switch]$Force,
    [switch]$DryRun,
    [int]$SettleSeconds = 300,
    [ValidateRange(60, 3600)][int]$RollbackRecoverySeconds = 1200
)

$ErrorActionPreference = "Stop"
$ExpectedSelfSha256 = $ExpectedSelfSha256.Trim().ToLowerInvariant()
if ($ExpectedSelfSha256) {
    if ($ExpectedSelfSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "ExpectedSelfSha256 must be a full SHA256"
    }
    $actualSelfSha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($actualSelfSha256 -ne $ExpectedSelfSha256) {
        throw "quiet-window merge script changed after its caller froze the launch contract"
    }
}
$repo = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path
$py = Join-Path $repo "venv\Scripts\python.exe"
if ($OwnerApprovedException) {
    if (
        $OwnerApprovedException -cne
            "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" -or
        (Get-Date).ToString("yyyy-MM-dd") -cne "2026-08-23"
    ) {
        throw "owner-approved protected-window exception is invalid or expired"
    }
    $workloadLeaseScript = Join-Path $PSScriptRoot "workload_admission.ps1"
    $expectedWorkloadLeaseSha256 =
        "3e2de64fb02e98e3016c71163bd7b297cf72488bbdfa593b38b237441f396389"
    $actualWorkloadLeaseSha256 =
        (Get-FileHash -LiteralPath $workloadLeaseScript -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($actualWorkloadLeaseSha256 -cne $expectedWorkloadLeaseSha256) {
        throw "owner-approved workload admission source changed"
    }
}
else {
    $workloadLeaseScript = Join-Path $repo "scripts\ops\workload_admission.ps1"
}
. $workloadLeaseScript
. (Join-Path $repo "scripts\ops\integration_attempt_quiet_merge_preflight.ps1")
$reportPath = Join-Path $repo "data\alerts\quiet_window_merge_last.json"
$historyPath = Join-Path $repo "data\alerts\quiet_window_merge_history.jsonl"
$activeMarkerPath = Join-Path $repo "data\alerts\quiet_window_merge_in_progress.json"
$log = New-Object System.Collections.Generic.List[string]
$resolvedBranchTip = $null
$mergeTarget = $Branch
$mergeCommit = $null
$baselineCommit = $null
$preMerge = $null
$rollbackContentSha256 = [ordered]@{}
$captureRecoveryProved = $false
$executionTapeRecoveryRequired = $false
$executionTapeReadoptionExpected = $false
$executionTapeRolledButInactiveSkipped = $false
$executionTapeRecoveryProved = $false
$executionTapeSourceBefore = $null
$publicationAcknowledged = $false
$documentationTransactionRecorded = $false
$documentationTransactionPendingSha256 = $null
$documentationTransactionSnapshotPath = $null
$documentedMarkerSha256 = $null
$activeMarkerOwned = $false
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
        schema = "quiet_window_merge_report_v0.2"
        ts = (Get-Date).ToString("o"); repo_root = $repo; branch = $Branch; ok = $ok
        expected_tip = $ExpectedTip; expected_baseline = $ExpectedBaseline
        resolved_branch_tip = $resolvedBranchTip
        baseline_commit = $baselineCommit
        pre_merge_commit = $preMerge
        rollback_content_sha256 = $rollbackContentSha256
        merge_commit = $mergeCommit
        capture_recovery_proved = $captureRecoveryProved
        execution_tape_recovery_required = $executionTapeRecoveryRequired
        execution_tape_readoption_expected = $executionTapeReadoptionExpected
        execution_tape_rolled_but_inactive_skipped = $executionTapeRolledButInactiveSkipped
        execution_tape_recovery_proved = $executionTapeRecoveryProved
        execution_tape_source_before = $executionTapeSourceBefore
        documentation_transaction_recorded = $documentationTransactionRecorded
        documentation_transaction_pending_sha256 = $documentationTransactionPendingSha256
        documentation_transaction_snapshot_path = $documentationTransactionSnapshotPath
        publication_acknowledged = $publicationAcknowledged
        stage = $stage; detail = $detail; log = @($log)
    }
    $json = $record | ConvertTo-Json -Depth 8
    $reportPersisted = $false
    $attemptReportPersisted = $false
    $attemptReportExpectedSha256 = $null
    # An integration attempt supplies its own unused evidence path. Create it
    # in one same-directory rename before touching the mutable compatibility
    # slots, so a parent killed immediately after this child returns still has
    # an exact attempt-local report. File.Move is exclusive: an immutable
    # report is never overwritten by a retry or a different attempt.
    if ($AttemptReportPath) {
        $attemptParent = Split-Path -Parent $AttemptReportPath
        $attemptLeaf = Split-Path -Leaf $AttemptReportPath
        $attemptTemp = Join-Path $attemptParent (".{0}.{1}.tmp" -f $attemptLeaf, [guid]::NewGuid().ToString("N"))
        try {
            $reportBytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($json)
            $reportSha = [Security.Cryptography.SHA256]::Create()
            try {
                $attemptReportExpectedSha256 = ([BitConverter]::ToString(
                        $reportSha.ComputeHash($reportBytes)
                    ) -replace '-', '').ToLowerInvariant()
            }
            finally { $reportSha.Dispose() }
            [IO.File]::WriteAllText(
                $attemptTemp,
                $json,
                (New-Object System.Text.UTF8Encoding($false))
            )
            [IO.File]::Move($attemptTemp, $AttemptReportPath)
            if (-not (Test-Path -LiteralPath $AttemptReportPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $AttemptReportPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                    $attemptReportExpectedSha256) {
                throw "attempt-local immutable quiet-merge report failed its post-create hash proof"
            }
            $attemptReportPersisted = $true
            $reportPersisted = $true
        }
        finally {
            if (Test-Path -LiteralPath $attemptTemp) {
                Remove-Item -LiteralPath $attemptTemp -Force -ErrorAction SilentlyContinue
            }
        }
    }
    try {
        $json | Set-Content -Path $reportPath -Encoding utf8
        $reportPersisted = $true
    }
    catch {}
    # $reportPath is a single most-recent slot, so a later run ERASES an earlier one. On
    # 2026-08-01 three scheduled merges aborted at 01:15/01:50/02:25 (the config-drift trap)
    # and a manual re-run at 02:55 succeeded and overwrote all three -- leaving no on-disk
    # trace of the failures at all, only the task exit codes. That is exactly how the aborts
    # were later mis-read as a cosmetic exit code. Append every outcome so history survives.
    try {
        ($record | ConvertTo-Json -Depth 8 -Compress) | Add-Content -Path $historyPath -Encoding utf8
        $reportPersisted = $true
    }
    catch {}
    if ($AttemptReportPath -and -not $attemptReportPersisted) {
        throw "attempt-local immutable quiet-window terminal report could not be persisted"
    }
    if (-not $reportPersisted) {
        throw "quiet-window terminal report could not be persisted"
    }
    # Retire the durable marker only after a terminal report proves publication
    # or an exact baseline restoration. Merged-unpushed and unproven rollback
    # states retain it so boot/status/reconciliation cannot lose the recovery
    # target merely because a failure report was written.
    $markerCanRetire = (
        ($stage -eq "pushed" -and $publicationAcknowledged) -or
        $stage -eq "rolled_back" -or
        $stage -eq "abort" -or
        $stage -eq "dry_run"
    )
    if ($activeMarkerOwned -and $markerCanRetire) {
        if ($AttemptReportPath -and
            (-not (Test-Path -LiteralPath $AttemptReportPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $AttemptReportPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                    $attemptReportExpectedSha256)) {
            throw "attempt-local immutable report changed before active-marker retirement"
        }
        Remove-Item -LiteralPath $activeMarkerPath -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $activeMarkerPath) {
            throw "active quiet-merge marker still exists after terminal retirement"
        }
    }
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

function Write-QuietMergeMarker {
    param([Parameter(Mandatory = $true)][string]$Phase)

    $marker = [ordered]@{
        schema = "quiet_window_merge_in_progress_v0.1"
        updated_at = (Get-Date).ToString("o")
        repo_root = $repo
        phase = $Phase
        branch = $Branch
        expected_tip = $ExpectedTip
        expected_baseline = $ExpectedBaseline
        resolved_branch_tip = $resolvedBranchTip
        baseline_commit = $baselineCommit
        pre_merge_commit = $preMerge
        merge_commit = $mergeCommit
        capture_recovery_proved = $captureRecoveryProved
        execution_tape_recovery_required = $executionTapeRecoveryRequired
        execution_tape_readoption_expected = $executionTapeReadoptionExpected
        execution_tape_rolled_but_inactive_skipped = $executionTapeRolledButInactiveSkipped
        execution_tape_recovery_proved = $executionTapeRecoveryProved
        execution_tape_source_before = $executionTapeSourceBefore
        documentation_transaction_recorded = $documentationTransactionRecorded
        documentation_transaction_pending_sha256 = $documentationTransactionPendingSha256
        documentation_transaction_snapshot_path = $documentationTransactionSnapshotPath
        publication_acknowledged = $publicationAcknowledged
        auto_refreshed_paths = @(
            "config/locations.json",
            "config/location_market_events.json"
        )
        auto_refreshed_sha256 = $rollbackContentSha256
    }
    $parent = Split-Path -Parent $activeMarkerPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $leaf = Split-Path -Leaf $activeMarkerPath
    $temp = Join-Path $parent (".{0}.{1}.tmp" -f $leaf, [guid]::NewGuid().ToString("N"))
    $backup = Join-Path $parent (".{0}.{1}.bak" -f $leaf, [guid]::NewGuid().ToString("N"))
    try {
        [IO.File]::WriteAllText(
            $temp,
            ($marker | ConvertTo-Json -Depth 8),
            (New-Object System.Text.UTF8Encoding($false))
        )
        if (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf) {
            [IO.File]::Replace($temp, $activeMarkerPath, $backup, $true)
        }
        else {
            [IO.File]::Move($temp, $activeMarkerPath)
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    }
}

function Test-ExecutionTapeActive {
    # Mirror roll_verdict.ps1's activation contract without changing task
    # state. A disabled optional task is skipped only when no detached writer
    # remains active; this must never enable an intentionally held producer.
    $task = Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor" -ErrorAction SilentlyContinue
    if ($task -and [string]$task.State -ne "Disabled") { return $true }
    $statusPath = Join-Path $repo "data\snapshots\execution_tape_status.json"
    $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
    if (Test-Path -LiteralPath $writerLockPath -PathType Leaf) { return $true }
    if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
        try {
            $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
            if ([string]$status.state -eq "STOPPED" -or [int]$status.pid -le 0) {
                return $false
            }
            # A retained CONNECTED status is not a live writer. With the task
            # disabled and no lock, require the recorded PID to still exist
            # before treating the optional producer as rollable.
            return $null -ne (Get-Process -Id ([int]$status.pid) -ErrorAction SilentlyContinue)
        }
        catch { return $false }
    }
    return $false
}

function Assert-OneShotPushTask {
    # Publication is deliberately delegated to the one interactive task whose
    # account can reach Windows Credential Manager. Prove that dependency before
    # any ref or working-tree mutation; discovering a disabled, S4U, renamed, or
    # command-drifted task after the recovery-proved commit would strand master
    # locally ahead of origin by design.
    try {
        $pushTasks = @(Get-ScheduledTask -TaskName "WeatherOneShotPush" -ErrorAction Stop)
    }
    catch {
        throw "WeatherOneShotPush is unavailable: $($_.Exception.Message)"
    }
    if ($pushTasks.Count -ne 1) {
        throw "WeatherOneShotPush must resolve to exactly one scheduled task; found $($pushTasks.Count)"
    }
    $pushTask = $pushTasks[0]
    $expectedPushTaskXmlSha256 = "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
    try {
        $pushTaskXml = [string](Export-ScheduledTask -TaskName "WeatherOneShotPush" -TaskPath "\" -ErrorAction Stop)
        $pushTaskSha = [Security.Cryptography.SHA256]::Create()
        try {
            $actualPushTaskXmlSha256 = ([BitConverter]::ToString(
                    $pushTaskSha.ComputeHash([Text.Encoding]::UTF8.GetBytes($pushTaskXml))
                ) -replace '-', '').ToLowerInvariant()
        }
        finally { $pushTaskSha.Dispose() }
    }
    catch {
        throw "WeatherOneShotPush definition could not be hash-verified: $($_.Exception.Message)"
    }
    if ($actualPushTaskXmlSha256 -ne $expectedPushTaskXmlSha256) {
        throw "WeatherOneShotPush task XML changed from the reviewed trigger/settings/action contract"
    }
    $pushActions = @($pushTask.Actions)
    $expectedPushSid = "S-1-5-21-1525964525-1566663060-3901869365-1001"
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $expectedWorkingDirectory = [IO.Path]::GetFullPath($repo).TrimEnd('\')
    $actualWorkingDirectory = try {
        [IO.Path]::GetFullPath([string]$pushActions[0].WorkingDirectory).TrimEnd('\')
    }
    catch { "" }
    $expectedPushArguments = '/c git -C c:\Users\micha\Desktop\github\weather push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1'
    $pushTaskBound = (
        [string]$pushTask.TaskPath -ceq "\" -and
        [string]$pushTask.State -ceq "Ready" -and
        $pushTask.Settings.Enabled -eq $true -and
        [string]$pushTask.Principal.UserId -ieq "micha" -and
        $currentSid -ceq $expectedPushSid -and
        [string]$pushTask.Principal.LogonType -ceq "Interactive" -and
        [string]$pushTask.Principal.RunLevel -ceq "Limited" -and
        $pushActions.Count -eq 1 -and
        [string]$pushActions[0].Execute -ieq "cmd.exe" -and
        [string]$pushActions[0].Arguments -ieq $expectedPushArguments -and
        $actualWorkingDirectory -ieq $expectedWorkingDirectory
    )
    if (-not $pushTaskBound) {
        throw "WeatherOneShotPush is not exactly bound to the enabled current-user Interactive/Limited git-push contract"
    }
    Note "WeatherOneShotPush exact publication binding passed"
}

if ($AttemptReportPath) {
    if (-not [IO.Path]::IsPathRooted($AttemptReportPath)) {
        throw "AttemptReportPath must be an absolute path"
    }
    $AttemptReportPath = [IO.Path]::GetFullPath($AttemptReportPath)
    $attemptReportParent = Split-Path -Parent $AttemptReportPath
    if (-not (Test-Path -LiteralPath $attemptReportParent -PathType Container)) {
        throw "AttemptReportPath parent directory does not exist: $attemptReportParent"
    }
    if (Test-Path -LiteralPath $AttemptReportPath) {
        throw "AttemptReportPath is immutable and already exists: $AttemptReportPath"
    }
    if ($AttemptReportPath -ieq $reportPath -or $AttemptReportPath -ieq $historyPath) {
        throw "AttemptReportPath must not reuse a mutable quiet-merge report path"
    }
}

$ExpectedTip = $ExpectedTip.Trim().ToLowerInvariant()
if ($ExpectedTip -and $ExpectedTip -notmatch '^[0-9a-f]{40}$') {
    Fail "ExpectedTip must be a full 40-character hexadecimal commit SHA"
}
$ExpectedBaseline = $ExpectedBaseline.Trim().ToLowerInvariant()
if ($ExpectedBaseline -and $ExpectedBaseline -notmatch '^[0-9a-f]{40}$') {
    Fail "ExpectedBaseline must be a full 40-character hexadecimal commit SHA"
}

$ownerProtectedWindowException = $false
if ($OwnerApprovedException) {
    $authorizedRoot = "71f7e46690e822a498f80412c11d550bcee949d2"
    $authorizedBaseline = "9d54f94760855a5f91ac603f3f14b02ba06ae239"
    $ownerAncestorExit = 1
    if ($ExpectedTip -match '^[0-9a-f]{40}$') {
        & git -C $repo merge-base --is-ancestor $authorizedRoot $ExpectedTip
        $ownerAncestorExit = $LASTEXITCODE
    }
    if (
        $OwnerApprovedException -cne
            "OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823" -or
        -not $Force -or
        (Get-Date).ToString("yyyy-MM-dd") -cne "2026-08-23" -or
        $Branch -cne "origin/codex/live-readiness-closure-20260823" -or
        $ExpectedBaseline -cne $authorizedBaseline -or
        $ownerAncestorExit -ne 0
    ) {
        Fail "owner-approved protected-window exception is invalid, unbound, or expired"
    }
    $ownerProtectedWindowException = $true
    Note "one-time repository-owner protected-window exception accepted for exact branch lineage and baseline"
}

# The broad host windows do not depend on the roll verdict. Refuse them before
# taking the shared lease, then serialize the verdict and every subsequent Git,
# recovery, documentation, and publication decision under that one OS handle.
$h = (Get-Date).Hour + ((Get-Date).Minute / 60.0)
if (-not $ownerProtectedWindowException -and $h -ge 12 -and $h -lt 18) {
    Fail "inside the 12:00-18:00 graded capture window - never merge here"
}
if (-not $ownerProtectedWindowException -and ($h -ge 18 -or $h -lt 0.5)) {
    Fail ("inside the 18:00-00:30 protected near-close window (now {0:N2}) - no heavy work here" -f $h)
}
$workloadLease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $repo `
    -Workload "quiet_window_merge" `
    -OwnerApprovedException $OwnerApprovedException
if ($null -eq $workloadLease) { Fail "another heavyweight host workload owns data/logs/heavy_workload.lock" }
try {

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
$verdictScript = Join-Path $repo "scripts\ops\roll_verdict.ps1"
$rollFree = $false
$rollVerdictReadable = $false
$executionTapeActive = Test-ExecutionTapeActive
if (-not $ExpectedTip) {
    # Classify the exact already-fetched object. A later fetch that moves the
    # branch then fails the equality check instead of borrowing this verdict.
    $preVerdictCommitRef = "{0}^{{commit}}" -f $Branch
    $preVerdictBranchTip = @(& git -C $repo rev-parse --verify $preVerdictCommitRef)
    if ($LASTEXITCODE -ne 0 -or $preVerdictBranchTip.Count -ne 1 -or
        ([string]$preVerdictBranchTip[0]).Trim().ToLowerInvariant() -notmatch '^[0-9a-f]{40}$') {
        Fail "branch is not locally resolvable before roll classification: $Branch"
    }
    $ExpectedTip = ([string]$preVerdictBranchTip[0]).Trim().ToLowerInvariant()
    Note "observed branch tip frozen before roll classification: $Branch -> $ExpectedTip"
}
$verdictRef = $ExpectedTip
if (Test-Path -LiteralPath $verdictScript) {
    $verdictJsonPath = Join-Path ([IO.Path]::GetTempPath()) ("weather-roll-verdict-{0}.json" -f [guid]::NewGuid().ToString("N"))
    try {
        & $verdictScript -Branch $verdictRef -JsonOut $verdictJsonPath |
            ForEach-Object { Note "roll_verdict: $_" }
        $verdictExitCode = $LASTEXITCODE
        $rollFree = ($verdictExitCode -eq 0)
        if (Test-Path -LiteralPath $verdictJsonPath -PathType Leaf) {
            try {
                $verdictPayload = Get-Content -LiteralPath $verdictJsonPath -Raw | ConvertFrom-Json
                $rollVerdictReadable = $true
                $executionTapeReadoptionExpected = @(
                    $verdictPayload.files |
                        Where-Object {
                            $_.rolls -eq $true -and
                            @($_.closures) -contains "execution_tape"
                        }
                ).Count -gt 0
            }
            catch {
                Note "WARNING: roll-verdict JSON was unreadable; any active execution tape will be gated conservatively"
            }
        }
        Note ("roll verdict exit {0} -> {1}" -f $verdictExitCode, $(if ($rollFree) { "ROLL-FREE" } else { "treated as ROLL-SENSITIVE" }))
    }
    finally {
        Remove-Item -LiteralPath $verdictJsonPath -Force -ErrorAction SilentlyContinue
    }
}
else { Note "roll_verdict.ps1 not found - treating branch as ROLL-SENSITIVE" }

# Gate the auxiliary producer exactly when its live closure rolls. If the
# mechanical verdict could not emit its structured closure proof, fail safe by
# gating an active producer; do not start or enable a disabled inactive task.
$executionTapeRecoveryRequired = ($executionTapeReadoptionExpected -and $executionTapeActive) -or
    ($executionTapeActive -and -not $rollVerdictReadable)
$executionTapeRolledButInactiveSkipped = $executionTapeReadoptionExpected -and -not $executionTapeActive
if ($executionTapeRecoveryRequired) {
    Note ("execution-tape recovery proof required ({0})" -f $(if ($executionTapeReadoptionExpected) { "closure rolls" } else { "active producer with unreadable closure verdict" }))
}
elseif ($executionTapeRolledButInactiveSkipped) {
    Note "execution-tape closure was listed but the optional producer is held inactive; leaving it disabled and skipping recovery proof"
}

if (-not $rollFree -and -not $Force -and -not ($h -ge 1 -and $h -lt 4)) {
    Fail ("roll-sensitive branch outside the 01:00-04:00 quiet window (now {0:N2}); use -Force only if you are certain a capture roll is safe right now" -f $h)
}
if ($rollFree) { Note ("roll-free branch: 01:00-04:00 not required (now {0:N2})" -f $h) }

# ---- preconditions ----
Set-Location $repo
# Never start on top of a merge that is already in progress. WeatherBootRecovery cleans one
# up after a power loss, but if that has not run yet the tree still holds unreviewed merged
# code, and merging again on top of it would bury the problem instead of surfacing it.
if (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf) {
    $priorMarkerReason = "a prior quiet-window merge marker still exists - let WeatherBootRecovery reconcile it before another merge"
    Note "ABORT: $priorMarkerReason"
    if ($AttemptReportPath) {
        # A stronger post-commit crash marker may belong to this same attempt.
        # Do not poison its still-unused immutable report path with a weaker
        # retry-time abort; the parent/reconciler must inspect the marker.
        throw $priorMarkerReason
    }
    Save-Report -ok $false -stage "abort" -detail $priorMarkerReason
    exit 1
}
$existingMergeHeadPath = (& git rev-parse --git-path MERGE_HEAD).Trim()
if (-not [IO.Path]::IsPathRooted($existingMergeHeadPath)) {
    $existingMergeHeadPath = Join-Path $repo $existingMergeHeadPath
}
if (Test-Path -LiteralPath $existingMergeHeadPath -PathType Leaf) {
    Fail "a merge is already in progress (.git/MERGE_HEAD exists) - resolve or abort it first; see data/alerts/boot_events.jsonl for an interrupted-merge record"
}
try {
    Assert-WeatherIntegrationQuietMergePreconditions -RepositoryRoot $repo |
        Out-Null
    Note "shared quiet-merge production preflight passed"
}
catch { Fail $_.Exception.Message }
try { Assert-OneShotPushTask }
catch { Fail $_.Exception.Message }
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
$gitFetchExit = Invoke-GitAllowingNativeStderr { & git fetch origin --prune | Out-Null }
if ($gitFetchExit -ne 0 -and $RequireLiveOrigin) {
    Fail "manifest-bound integration requires a successful live origin refresh immediately before merge"
}
if ($gitFetchExit -ne 0) { Note "WARNING: git fetch failed (no credential vault under S4U?); merging the last-fetched copy of $Branch" }
$branchCommitRef = "{0}^{{commit}}" -f $Branch
$branchVerifyExit = Invoke-GitAllowingNativeStderr { & git rev-parse --verify $branchCommitRef | Out-Null }
if ($branchVerifyExit -ne 0) { Fail "branch not found: $Branch" }
$resolvedBranchTip = (& git rev-parse $branchCommitRef).Trim().ToLowerInvariant()
if ($resolvedBranchTip -ne $ExpectedTip) {
    Fail "branch tip moved: $Branch resolves to $resolvedBranchTip, expected reviewed tip $ExpectedTip"
}
Note "exact-tip binding passed: $Branch -> $resolvedBranchTip"
# Merge the immutable object, not the movable ref, even for an interactive
# caller that omitted ExpectedTip. A later ref update cannot change the tree.
$mergeTarget = $resolvedBranchTip
$head = (& git rev-parse HEAD).Trim()
$originMaster = (& git rev-parse origin/master).Trim()
$currentBranchOutput = @(& git symbolic-ref --quiet --short HEAD)
$currentBranchExit = $LASTEXITCODE
$currentBranch = if ($currentBranchOutput.Count -eq 0) { "" } else { ([string]$currentBranchOutput[-1]).Trim() }
if ($currentBranchExit -ne 0 -or $currentBranch -ne "master") {
    Fail "production working tree must have master checked out; current branch is $currentBranch"
}
if ($head -ne $originMaster) { Fail "local master ($head) != origin/master ($originMaster); reconcile first" }
if ($ExpectedBaseline -and ($head.ToLowerInvariant() -ne $ExpectedBaseline -or
    $originMaster.ToLowerInvariant() -ne $ExpectedBaseline)) {
    Fail "production baseline moved: master=$head origin/master=$originMaster expected=$ExpectedBaseline"
}
$baselineCommit = $head.ToLowerInvariant()
if (-not $ExpectedBaseline) {
    # Direct/manual callers historically omitted the frozen baseline. Once the
    # synchronized local/remote identity is proved under the workload lease,
    # bind that observed baseline into every crash marker and terminal report.
    $ExpectedBaseline = $baselineCommit
    Note "observed synchronized baseline bound for crash recovery: $ExpectedBaseline"
}
foreach ($relativePath in $autoRefreshed) {
    $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
    if (Test-Path -LiteralPath $absolutePath -PathType Leaf) {
        $rollbackContentSha256[$relativePath] = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
if ($rollbackContentSha256.Count -ne $autoRefreshed.Count) {
    Fail "both fleet-generated config files must exist before merge preparation"
}

function Restore-PreparedBaseline {
    $resetExit = Invoke-GitAllowingNativeStderr {
        & git reset --mixed $baselineCommit | Out-Null
    }
    $actualHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $tracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
    $unexpectedPaths = @($tracked | Where-Object {
            $path = ($_ -replace '^..\s*', '').Trim()
            $autoRefreshed -notcontains $path
        })
    $contentMismatch = @()
    foreach ($relativePath in $rollbackContentSha256.Keys) {
        $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                [string]$rollbackContentSha256[$relativePath]) {
            $contentMismatch += $relativePath
        }
    }
    return [PSCustomObject]@{
        ok = ($resetExit -eq 0 -and $actualHead -eq $baselineCommit -and
            $unexpectedPaths.Count -eq 0 -and $contentMismatch.Count -eq 0)
        git_exit = $resetExit
        actual_head = $actualHead
        unexpected_paths = @($unexpectedPaths)
        content_mismatch = @($contentMismatch)
    }
}

function Stop-AfterPreparationFailure {
    param([Parameter(Mandatory = $true)][string]$Reason)

    $restored = Restore-PreparedBaseline
    if (-not $restored.ok) {
        $detail = "pre-merge failure could not restore successor-resumable baseline $baselineCommit; git_exit=$($restored.git_exit) head=$($restored.actual_head) unexpected_dirty=$(@($restored.unexpected_paths).Count) content_mismatch=$(@($restored.content_mismatch) -join ','); original=$Reason"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }
    Note "ABORT: $Reason; synchronized baseline restored with generated config preserved as allowlisted drift"
    Save-Report -ok $false -stage "abort" -detail $Reason
    exit 1
}

# Journal before the optional generated-config commit. A hard kill after git
# add or commit but before the later prepared-phase update can then restore the
# synchronized baseline with the exact pre-recorded config bytes intact.
$preMerge = $baselineCommit
try {
    Write-QuietMergeMarker -Phase "preparing"
    $activeMarkerOwned = $true
}
catch {
    Stop-AfterPreparationFailure "durable quiet-merge preparation marker could not be created"
}

if ($dirtyTracked.Count -gt 0) {
    Note "committing $($dirtyTracked.Count) fleet-generated drift file(s) so the merge starts clean"
    $gitAddExit = Invoke-GitAllowingNativeStderr { & git add -- $autoRefreshed }
    if ($gitAddExit -ne 0) { Stop-AfterPreparationFailure "failed to stage fleet-generated drift (git exit $gitAddExit)" }
    $gitCommitExit = Invoke-GitAllowingNativeStderr {
        & git commit -m "ops: preserve fleet-generated drift (pre-merge, automated)" | Out-Null
    }
    if ($gitCommitExit -ne 0) { Stop-AfterPreparationFailure "failed to commit fleet-generated drift (git exit $gitCommitExit)" }
}
# Take the immediate rollback point after the drift commit. Failure first
# restores this exact tree, then mixed-resets the original baseline so the
# generated contents survive as allowlisted working-tree drift.
$preMerge = (& git rev-parse HEAD).Trim()
try {
    # Refresh the preparation journal with the exact temporary config commit,
    # but do not call it prepared until the pre-roll producer identities below
    # are durable too. In particular, an active execution tape needs its old
    # source fingerprint recorded before a staged merge can touch the tree.
    Write-QuietMergeMarker -Phase "preparing"
}
catch {
    # If the optional generated-drift commit succeeded but its crash marker
    # could not be persisted, restore synchronized master while retaining the
    # generated contents as the same two allowlisted working-tree changes.
    Stop-AfterPreparationFailure "durable quiet-merge crash marker could not be created"
}
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

function Get-ExecutionTapeState {
    $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
    try {
        $raw = @(& $py -m weather.operations.execution_tape_supervisor status --stale-after-seconds 180)
        $exitCode = $LASTEXITCODE
        $payload = (($raw -join "`n") | ConvertFrom-Json)
        $health = $payload.health
        $status = $payload.status
        $reasons = New-Object System.Collections.Generic.List[string]
        if ($exitCode -ne 0) { $reasons.Add("status_exit_$exitCode") }
        if (@("RUNNING", "DEGRADED") -notcontains [string]$health.state) {
            $reasons.Add("health_$([string]$health.state)")
        }
        if ($health.pid_alive -ne $true) { $reasons.Add("pid_not_alive") }
        if ($health.runtime_identity_matches_current -ne $true) { $reasons.Add("runtime_identity_stale") }
        if ([string]$health.evidence_integrity -ne "PASS") { $reasons.Add("evidence_integrity_$([string]$health.evidence_integrity)") }
        if ([string]$status.state -ne "CONNECTED") { $reasons.Add("capture_$([string]$status.state)") }
        if ([string]$status.market -ne "all" -or [string]$status.runner -ne "managed_execution_tape") {
            $reasons.Add("managed_scope_mismatch")
        }
        if ($status.managed_process.verified_at_capture -ne $true) {
            $reasons.Add("managed_process_unverified")
        }
        if (-not (Test-Path -LiteralPath $writerLockPath -PathType Leaf)) {
            $reasons.Add("writer_lock_missing")
            $writerLock = $null
        }
        else {
            $writerLock = Get-Content -LiteralPath $writerLockPath -Raw | ConvertFrom-Json
            if ([int]$status.pid -le 0 -or
                [int]$status.pid -ne [int]$status.managed_process.pid -or
                [int]$status.pid -ne [int]$writerLock.pid -or
                [int]$status.pid -ne [int]$writerLock.managed_process.pid -or
                [string]$status.managed_process.creation_time_token -cne
                    [string]$writerLock.managed_process.creation_time_token) {
                $reasons.Add("writer_identity_mismatch")
            }
        }
        $lastHeartbeat = if ($status.last_heartbeat) {
            [string]$status.last_heartbeat
        }
        else {
            [string]$status.updated_at_utc
        }
        return [PSCustomObject]@{
            ok = ($reasons.Count -eq 0)
            pid = [int]$status.pid
            last_heartbeat = $lastHeartbeat
            recorded_source_fingerprint = [string]$status.runtime_identity.source_fingerprint
            reasons = @($reasons)
            health = $health
            status = $status
            writer_lock = $writerLock
        }
    }
    catch {
        return [PSCustomObject]@{
            ok = $false
            pid = 0
            last_heartbeat = $null
            recorded_source_fingerprint = $null
            reasons = @($_.Exception.Message)
            health = $null
            status = $null
            writer_lock = $null
        }
    }
}

function Invoke-RollbackAndProve {
    param(
        [Parameter(Mandatory = $true)][string[]]$Reasons,
        [ValidateSet("rolled_back", "dry_run")][string]$RecoveredStage = "rolled_back",
        [bool]$RecoveredOk = $false,
        [ValidateSet(0, 2)][int]$RecoveredExitCode = 2
    )

    $primaryDetail = ($Reasons | Where-Object { $_ }) -join "; "
    if (-not $primaryDetail) { $primaryDetail = "guarded merge did not complete" }
    Note "merge will not be committed: $primaryDetail"

    $mergeHeadPath = (& git rev-parse --git-path MERGE_HEAD).Trim()
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $repo $mergeHeadPath
    }
    $restoreExit = 0
    if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) {
        $restoreExit = Invoke-GitAllowingNativeStderr { & git merge --abort | Out-Null }
    }
    else {
        # A successful explicit commit removes MERGE_HEAD. This path is used
        # only if a later structural check on that unpublished commit failed.
        $restoreExit = Invoke-GitAllowingNativeStderr { & git reset --hard $preMerge | Out-Null }
    }
    if ($restoreExit -ne 0) {
        $restoreExit = Invoke-GitAllowingNativeStderr { & git reset --hard $preMerge | Out-Null }
    }

    $restoredHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $remainingMergeHead = Test-Path -LiteralPath $mergeHeadPath -PathType Leaf
    $remainingTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
    if ($restoreExit -ne 0 -or $restoredHead -ne $preMerge.ToLowerInvariant() -or
        $remainingMergeHead -or $remainingTracked.Count -ne 0) {
        $detail = "merge rollback could not restore exact pre-merge tree $preMerge; git_exit=$restoreExit head=$restoredHead merge_head=$remainingMergeHead dirty=$($remainingTracked.Count); original=$primaryDetail"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    # The automatic generated-config commit is a temporary merge preparation,
    # not a new production baseline. Move master back to the originally
    # synchronized commit with a mixed reset so the exact generated contents
    # survive as the same two allowlisted working-tree changes. A successor can
    # then re-run without first reconciling an unpublished local commit.
    if ($preMerge.ToLowerInvariant() -ne $baselineCommit.ToLowerInvariant()) {
        $baselineResetExit = Invoke-GitAllowingNativeStderr {
            & git reset --mixed $baselineCommit | Out-Null
        }
        if ($baselineResetExit -ne 0) {
            $detail = "merge rollback reached $preMerge but could not restore synchronized baseline $baselineCommit; git_exit=$baselineResetExit; original=$primaryDetail"
            Note $detail
            Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
            exit 4
        }
    }
    $finalRollbackHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $finalTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
    $unexpectedRollbackPaths = @($finalTracked | Where-Object {
            $path = ($_ -replace '^..\s*', '').Trim()
            $autoRefreshed -notcontains $path
        })
    $contentMismatch = @()
    foreach ($relativePath in $rollbackContentSha256.Keys) {
        $absolutePath = Join-Path $repo ($relativePath -replace '/', '\')
        if (-not (Test-Path -LiteralPath $absolutePath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                [string]$rollbackContentSha256[$relativePath]) {
            $contentMismatch += $relativePath
        }
    }
    if ($finalRollbackHead -ne $baselineCommit.ToLowerInvariant() -or
        $unexpectedRollbackPaths.Count -ne 0 -or $contentMismatch.Count -ne 0) {
        $detail = "merge rollback did not leave a successor-resumable baseline; expected_head=$baselineCommit actual_head=$finalRollbackHead unexpected_dirty=$($unexpectedRollbackPaths.Count) content_mismatch=$($contentMismatch -join ','); original=$primaryDetail"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    Note "rolled back to synchronized baseline $baselineCommit with generated config preserved as allowlisted drift; nothing was pushed. Waiting up to ${RollbackRecoverySeconds}s for every affected producer to re-adopt the rollback..."
    $rollbackDeadline = (Get-Date).AddSeconds($RollbackRecoverySeconds)
    do {
        $rollbackState = Get-CaptureState
        $rollbackCoreOk = $rollbackState.ok -and @($rollbackState.workers).Count -eq 3
        $rollbackExecutionState = $null
        $rollbackExecutionOk = $true
        if ($executionTapeRecoveryRequired) {
            $rollbackExecutionState = Get-ExecutionTapeState
            $rollbackExecutionOk = $rollbackExecutionState.ok -and
                [string]$rollbackExecutionState.recorded_source_fingerprint -ceq
                    [string]$executionBefore.recorded_source_fingerprint
        }
        if ($rollbackCoreOk -and $rollbackExecutionOk) { break }
        if ((Get-Date) -lt $rollbackDeadline) { Start-Sleep -Seconds 15 }
    } while ((Get-Date) -lt $rollbackDeadline)

    if (-not $rollbackCoreOk -or -not $rollbackExecutionOk) {
        $rollbackWhy = @(
            $rollbackState.workers |
                Where-Object { -not $_.ok } |
                ForEach-Object { "$($_.name)=$($_.reasons -join ',')" }
        )
        if ($rollbackState.error) { $rollbackWhy += [string]$rollbackState.error }
        if ($executionTapeRecoveryRequired -and -not $rollbackExecutionOk) {
            $rollbackWhy += "execution_tape=$(@($rollbackExecutionState.reasons) -join ','); expected_source=$($executionBefore.recorded_source_fingerprint); actual_source=$($rollbackExecutionState.recorded_source_fingerprint)"
        }
        if ($rollbackWhy.Count -eq 0) { $rollbackWhy += "recovery contract unreadable" }
        $detail = "merge recovery failed: $primaryDetail; rollback recovery unproven: $($rollbackWhy -join '; ')"
        Note $detail
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail $detail
        exit 4
    }

    Note "every affected producer re-adopted the rollback and satisfies its exact recovery contract"
    Save-Report -ok $RecoveredOk -stage $RecoveredStage -detail $primaryDetail
    exit $RecoveredExitCode
}

$before = Get-CaptureState
Note "capture before: ok=$($before.ok), workers=$(@($before.workers).Count)"
if (-not $before.ok -or @($before.workers).Count -ne 3) {
    $detail = @($before.workers | Where-Object { -not $_.ok } | ForEach-Object { "$($_.name)=$($_.reasons -join ',')" }) -join "; "
    if (-not $detail) { $detail = [string]$before.error }
    Stop-AfterPreparationFailure "capture recovery contract is not healthy before merge: $detail"
}
$executionBefore = $null
if ($executionTapeRecoveryRequired) {
    $executionBefore = Get-ExecutionTapeState
    Note "execution tape before: ok=$($executionBefore.ok), pid=$($executionBefore.pid), source=$($executionBefore.recorded_source_fingerprint)"
    if (-not $executionBefore.ok) {
        Stop-AfterPreparationFailure "execution-tape recovery contract is not healthy before merge: $(@($executionBefore.reasons) -join ',')"
    }
    $executionTapeSourceBefore = [string]$executionBefore.recorded_source_fingerprint
}
try {
    Write-QuietMergeMarker -Phase "prepared"
}
catch {
    Stop-AfterPreparationFailure "durable quiet-merge marker could not bind the pre-roll recovery identities"
}

if ($DryRun) {
    $dryMergeExit = Invoke-GitAllowingNativeStderr { & git merge --no-commit --no-ff $mergeTarget | Out-Null }
    $conflicts = @(& git diff --name-only --diff-filter=U | Where-Object { $_ })
    # Always unwind: leaving a half-merged tree changes loop-loaded modules on disk and
    # provokes a STALE_CODE readoption roll. `merge --abort` restores the pre-merge state
    # including uncommitted config drift. At this point tracked drift has already been
    # committed, so a hard reset to the exact pre-merge point is a safe fallback.
    $dryAbortExit = Invoke-GitAllowingNativeStderr { & git merge --abort | Out-Null }
    if ($dryAbortExit -ne 0) {
        $dryAbortExit = Invoke-GitAllowingNativeStderr { & git reset --hard $preMerge | Out-Null }
    }
    if ($dryAbortExit -ne 0 -or (& git rev-parse HEAD).Trim() -ne $preMerge) {
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail "dry-run merge could not restore $preMerge"
        exit 4
    }
    $dryRestore = Restore-PreparedBaseline
    if (-not $dryRestore.ok) {
        Save-Report -ok $false -stage "rollback_recovery_failed" -detail "dry-run merge could not restore synchronized baseline $baselineCommit with generated bytes intact"
        exit 4
    }
    Note "DRY RUN: conflicts=$($conflicts.Count)"
    # Staging the dry merge exposed target bytes to the same supervisors as a
    # real merge. Do not retire its marker merely because Git was restored;
    # prove every affected producer has re-adopted the rollback first.
    $dryRunOk = $dryMergeExit -eq 0
    $dryRunExitCode = if ($dryRunOk) { 0 } else { 2 }
    Invoke-RollbackAndProve `
        -Reasons @("dry-run merge_exit=$dryMergeExit conflicts=$($conflicts.Count)") `
        -RecoveredStage "dry_run" `
        -RecoveredOk $dryRunOk `
        -RecoveredExitCode $dryRunExitCode
}

# ---- stage locally without committing (this triggers the readoption roll) ----
# MERGE_HEAD is the durable crash marker. Keep it present through the complete
# recovery proof so WeatherBootRecovery can always abort an interrupted,
# unverified roll after power loss. Only a successful proof earns the explicit
# merge commit below.
$mergeCommitted = $false
try {
    $mergeExit = Invoke-GitAllowingNativeStderr {
        & git merge --no-commit --no-ff $mergeTarget | Out-Null
    }
    if ($mergeExit -ne 0) {
        Invoke-RollbackAndProve -Reasons @("merge failed or conflicted (git exit $mergeExit)")
    }
    $mergeHeadPath = (& git rev-parse --git-path MERGE_HEAD).Trim()
    if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) {
        $mergeHeadPath = Join-Path $repo $mergeHeadPath
    }
    if (-not (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) -or
        (& git rev-parse HEAD).Trim() -ne $preMerge) {
        Invoke-RollbackAndProve -Reasons @("no-commit merge did not preserve MERGE_HEAD and the exact pre-merge HEAD")
    }
    Write-QuietMergeMarker -Phase "merge_uncommitted"
    Note "merge staged with MERGE_HEAD preserved (NOT committed or pushed)"

    # ---- wait for every affected producer to readopt, then prove recovery ----
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

    $executionAfter = $null
    if ($executionTapeRecoveryRequired) {
        $executionAfter = Get-ExecutionTapeState
        Note "execution tape after: ok=$($executionAfter.ok), pid=$($executionAfter.pid), source=$($executionAfter.recorded_source_fingerprint)"
        if (-not $executionAfter.ok) {
            $ok = $false
            $why += "execution_tape=$(@($executionAfter.reasons) -join ',')"
        }
        if ($executionTapeReadoptionExpected) {
            if ([string]$executionAfter.recorded_source_fingerprint -ceq
                [string]$executionBefore.recorded_source_fingerprint) {
                $ok = $false
                $why += "execution_tape closure rolled but loaded-source fingerprint did not change"
            }
            try {
                if ([datetime]$executionAfter.last_heartbeat -le [datetime]$executionBefore.last_heartbeat) {
                    $ok = $false
                    $why += "execution_tape readopted but heartbeat did not advance ($($executionBefore.last_heartbeat) -> $($executionAfter.last_heartbeat))"
                }
            }
            catch {
                $ok = $false
                $why += "execution_tape readoption heartbeat comparison failed"
            }
        }
    }

    if (-not $ok) {
        Invoke-RollbackAndProve -Reasons $why
    }
    $captureRecoveryProved = $true
    if ($executionTapeRecoveryRequired) { $executionTapeRecoveryProved = $true }
    Write-QuietMergeMarker -Phase "capture_recovered_uncommitted"

    # Recovery is proved while MERGE_HEAD still makes the operation boot-
    # recoverable. Commit only now, then verify the exact two-parent identity.
    $mergeCommitExit = Invoke-GitAllowingNativeStderr {
        & git commit -m "Merge $Branch into master" | Out-Null
    }
    if ($mergeCommitExit -ne 0) {
        Invoke-RollbackAndProve -Reasons @("recovery passed but explicit merge commit failed (git exit $mergeCommitExit)")
    }
    $candidateMergeCommit = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $firstParent = (& git rev-parse "$candidateMergeCommit^1").Trim().ToLowerInvariant()
    $secondParent = (& git rev-parse "$candidateMergeCommit^2").Trim().ToLowerInvariant()
    if ((Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) -or
        $firstParent -ne $preMerge.ToLowerInvariant() -or
        $secondParent -ne $resolvedBranchTip.ToLowerInvariant()) {
        Invoke-RollbackAndProve -Reasons @("explicit merge commit did not bind the exact pre-merge and reviewed-tip parents")
    }
    $mergeCommit = $candidateMergeCommit
    Write-QuietMergeMarker -Phase "merge_committed_unpublished"
    $mergeCommitted = $true
    Note "recovery-proved merge committed locally as $mergeCommit (NOT pushed yet)"
}
catch {
    if (-not $mergeCommitted) {
        Invoke-RollbackAndProve -Reasons @("unexpected pre-commit failure: $($_.Exception.GetType().Name)")
    }
    throw
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
$previousDocumentationErrorPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $documentationOutput = & $py @documentationArgs
    $documentationExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousDocumentationErrorPreference
}
if ($documentationExit -ne 0) {
    Note "documentation transaction could not be recorded: $($documentationOutput -join ' ')"
    # `begin` atomically updates a shared pending transaction and then its
    # content-addressed snapshot. A nonzero child can therefore be ambiguous
    # about whether that durable mutation happened. Without a compensating
    # transaction it is unsafe to delete the merge it may now reference.
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation transaction begin failed or was ambiguous for local commit $mergeCommit; reviewed resume required"
    exit 3
}
try {
    $documentationPayload = (($documentationOutput -join "`n") | ConvertFrom-Json)
    $pendingSha256 = ([string]$documentationPayload.pending_sha256).ToLowerInvariant()
    $matchingDocumentationEntry = @(
        $documentationPayload.integrations |
            Where-Object {
                ([string]$_.integration_tip).ToLowerInvariant() -eq $mergeCommit -and
                [string]$_.branch -ceq $Branch
            }
    ) | Select-Object -First 1
    if ($pendingSha256 -notmatch '^[0-9a-f]{64}$' -or
        ([string]$documentationPayload.latest_integration_tip).ToLowerInvariant() -ne $mergeCommit -or
        $null -eq $matchingDocumentationEntry -or
        ($ExpectedTip -and ([string]$matchingDocumentationEntry.expected_tip).ToLowerInvariant() -ne $ExpectedTip)) {
        throw "documentation transaction output did not bind the exact integration"
    }
    $documentationPendingPath = Join-Path $repo "data\alerts\documentation_transaction_pending.json"
    $documentationSnapshotRelative = "data/alerts/documentation_transactions/pending-$pendingSha256.json"
    $documentationSnapshotPath = Join-Path $repo ($documentationSnapshotRelative -replace '/', '\')
    if (-not (Test-Path -LiteralPath $documentationPendingPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $documentationSnapshotPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $documentationPendingPath -Algorithm SHA256).Hash -ine $pendingSha256 -or
        (Get-FileHash -LiteralPath $documentationSnapshotPath -Algorithm SHA256).Hash -ine $pendingSha256) {
        throw "documentation transaction pending state and immutable snapshot do not match"
    }
    $documentationTransactionPendingSha256 = $pendingSha256
    $documentationTransactionSnapshotPath = $documentationSnapshotRelative
    $documentationTransactionRecorded = $true
}
catch {
    Note "documentation transaction returned success without exact durable identity: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation transaction identity is ambiguous for local commit $mergeCommit; reviewed resume required"
    exit 3
}
Note "documentation transaction recorded for $mergeCommit"
try {
    Write-QuietMergeMarker -Phase "documented_unpublished"
    $documentedMarkerSha256 = (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}
catch {
    # The pending documentation transaction now names this merge. Preserve both
    # and the prior merge_committed_unpublished marker for reviewed, idempotent
    # reconciliation; resetting would create an orphan transaction.
    Note "documentation succeeded but its durable merge marker could not be updated; preserving local merge for reviewed resume"
    Save-Report -ok $true -stage "merged_unpushed" -detail "documentation marker update failed for local commit $mergeCommit; reviewed resume required"
    exit 3
}

# ---- only now publish, through the credential-bearing scheduled task ----
# Interactive git push is forbidden on this host. The scheduled task owns the credential
# context, and origin/master is the acknowledgement that the immutable merge commit landed.
$prePublicationFailure = $null
try {
    $finalHead = (& git rev-parse HEAD).Trim().ToLowerInvariant()
    $finalMaster = (& git rev-parse master).Trim().ToLowerInvariant()
    $finalOriginMaster = (& git rev-parse origin/master).Trim().ToLowerInvariant()
    $finalBranch = (& git symbolic-ref --quiet --short HEAD).Trim()
    $finalMergeHeadPath = (& git rev-parse --git-path MERGE_HEAD).Trim()
    if (-not [IO.Path]::IsPathRooted($finalMergeHeadPath)) {
        $finalMergeHeadPath = Join-Path $repo $finalMergeHeadPath
    }
    if ($finalBranch -ne "master" -or $finalHead -ne $mergeCommit -or
        $finalMaster -ne $mergeCommit -or
        $finalOriginMaster -notin @($baselineCommit, $mergeCommit) -or
        (Test-Path -LiteralPath $finalMergeHeadPath -PathType Leaf)) {
        throw "Git identity changed after recovery proof"
    }

    $finalMarkerShaBefore = (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if (-not $documentedMarkerSha256 -or $finalMarkerShaBefore -ne $documentedMarkerSha256) {
        throw "durable merge/documentation marker changed after recovery proof"
    }
    $finalMarkerRaw = [IO.File]::ReadAllText($activeMarkerPath, [Text.Encoding]::UTF8)
    $finalMarker = $finalMarkerRaw | ConvertFrom-Json
    $finalMarkerShaAfter = (Get-FileHash -LiteralPath $activeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($finalMarkerShaAfter -ne $documentedMarkerSha256) {
        throw "durable merge/documentation marker changed while it was being verified"
    }
    if ([string]$finalMarker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
        [string]$finalMarker.phase -ne "documented_unpublished" -or
        ([string]$finalMarker.merge_commit).ToLowerInvariant() -ne $mergeCommit -or
        ([string]$finalMarker.baseline_commit).ToLowerInvariant() -ne $baselineCommit -or
        ([string]$finalMarker.resolved_branch_tip).ToLowerInvariant() -ne $resolvedBranchTip -or
        $finalMarker.documentation_transaction_recorded -ne $true -or
        ([string]$finalMarker.documentation_transaction_pending_sha256).ToLowerInvariant() -ne
            $documentationTransactionPendingSha256 -or
        [string]$finalMarker.documentation_transaction_snapshot_path -cne
            $documentationTransactionSnapshotPath -or
        $finalMarker.publication_acknowledged -eq $true) {
        throw "durable merge/documentation marker changed after recovery proof"
    }
    $finalDocumentationSnapshotPath = Join-Path $repo (
        $documentationTransactionSnapshotPath -replace '/', '\'
    )
    if (-not (Test-Path -LiteralPath $finalDocumentationSnapshotPath -PathType Leaf) -or
        (Get-FileHash -LiteralPath $finalDocumentationSnapshotPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $documentationTransactionPendingSha256) {
        throw "immutable documentation transaction snapshot changed before publication"
    }

    $finalCapture = Get-CaptureState
    if (-not $finalCapture.ok -or @($finalCapture.workers).Count -ne 3) {
        throw "exact three-worker capture recovery no longer passes"
    }
    if ($executionTapeRecoveryRequired) {
        $finalExecutionTape = Get-ExecutionTapeState
        if (-not $finalExecutionTape.ok) {
            throw "execution-tape recovery no longer passes: $(@($finalExecutionTape.reasons) -join ',')"
        }
    }
}
catch {
    $prePublicationFailure = $_.Exception.Message
}
if ($prePublicationFailure) {
    Note "publication boundary proof failed: $prePublicationFailure"
    Save-Report -ok $true -stage "merged_unpushed" -detail "publication boundary proof failed; commit $mergeCommit is local: $prePublicationFailure"
    exit 3
}
try { Assert-OneShotPushTask }
catch {
    Note "WeatherOneShotPush changed after its pre-mutation check: $($_.Exception.Message)"
    Save-Report -ok $true -stage "merged_unpushed" -detail "push task binding changed before publication; commit $mergeCommit is local"
    exit 3
}
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
$publicationAcknowledged = $true
try {
    Write-QuietMergeMarker -Phase "published"
}
catch {
    # The remote acknowledgement plus the attempt-local terminal report below
    # are authoritative. If that report also fails, the previous durable
    # documented_unpublished marker remains for Git-backed reconciliation.
    Note "WARNING: publication succeeded but the durable marker phase could not be advanced"
}
Note "pushed $mergeCommit via WeatherOneShotPush"
Save-Report -ok $true -stage "pushed" -detail "$mergeCommit (via WeatherOneShotPush)"
exit 0
}
finally { Exit-WeatherHeavyWorkloadLease -Lease $workloadLease }
