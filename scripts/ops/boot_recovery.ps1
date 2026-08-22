# Runs at every boot. Records WHY we rebooted, heals anything a hard power loss can leave
# broken, and verifies the fleet actually came back.
#
# Why this exists: this host loses power. Event-log forensics on 2026-07-25 found five
# unexpected shutdowns in 90 days -- four of them with bugcheck=0, powerButton=0 and no
# BSOD, which is the signature of abrupt power loss rather than a crash. That is roughly
# one every three weeks against a 14-day contiguous streak requirement, and nothing in the
# monitoring noticed any of them: the digest reported a healthy host either side of a
# 29-minute outage on 2026-07-21 (day 1 of the current streak).
#
# Two things a power loss can leave behind that nothing else repairs:
#   1. A half-finished merge. quiet_window_merge.ps1 deliberately keeps MERGE_HEAD while
#      waiting for recovery and writes an exact baseline/pre-merge marker. A power cut in
#      that interval must abort the merge, restore synchronized master, and preserve only
#      the two generated config contents as allowlisted working-tree drift. A merge that
#      was already recovery-proved and committed is preserved for explicit reconciliation;
#      boot recovery never guesses that an unpublished commit should be pushed.
#   2. Nobody knowing it happened. The boot record below is the only place an unattended
#      outage is written down in project terms rather than the Windows event log.
[CmdletBinding()]
param(
    [switch]$NoWait,
    [string]$ExpectedSelfSha256 = ""
)

$ErrorActionPreference = "Continue"
if ($ExpectedSelfSha256) {
    $ExpectedSelfSha256 = $ExpectedSelfSha256.Trim().ToLowerInvariant()
    if ($ExpectedSelfSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "ExpectedSelfSha256 must be a full SHA256."
    }
    $actualSelfSha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    if ($actualSelfSha256 -ne $ExpectedSelfSha256) {
        throw "Boot-recovery script changed after its task action was frozen."
    }
}
$repo = "C:\Users\micha\Desktop\github\weather"
$alertDir = Join-Path $repo "data\alerts"
$logPath = Join-Path $alertDir "boot_events.jsonl"
$mergeMarkerPath = Join-Path $alertDir "quiet_window_merge_in_progress.json"
$notes = New-Object System.Collections.Generic.List[string]

$os = Get-CimInstance Win32_OperatingSystem
$boot = $os.LastBootUpTime

# ---- was the previous shutdown clean? ----
# Kernel-Power 41 is written on the way back UP, describing the shutdown that just ended.
# bugcheck=0 with no power-button timestamp means the machine simply stopped -- power loss
# or a hard hang -- as opposed to a BSOD (non-zero bugcheck) or a held power button.
$unclean = $false
$cause = "clean"
try {
    $e41 = Get-WinEvent -FilterHashtable @{LogName = 'System'; Id = 41; StartTime = $boot.AddMinutes(-10) } -MaxEvents 1 -EA SilentlyContinue
    if ($e41) {
        $unclean = $true
        $d = @{}
        ([xml]$e41.ToXml()).Event.EventData.Data | ForEach-Object { $d[$_.Name] = $_.'#text' }
        $cause = if ([int]$d['BugcheckCode'] -ne 0) { "bugcheck 0x{0:X}" -f [int]$d['BugcheckCode'] }
        elseif ($d['LongPowerButtonPressDetected'] -eq 'true') { "power button held" }
        else { "power loss or hard hang" }
    }
}
catch {}
$notes.Add("boot $boot; previous shutdown: $cause")

# ---- heal or surface an interrupted guarded merge ----
$mergeHealed = $false
$mergeRecoveryFailed = $false
$mergeReconciliationRequired = $false
$mergeMarkerPhase = $null
$mergeRollbackTarget = $null
$markerRemovalPending = $false
$unmarkedRecoveryPending = $false
$gitLockRecoveryRequired = $false
Set-Location $repo
$gitDirectory = (& git rev-parse --absolute-git-dir 2>$null).Trim()
$preBootGitLocks = @()
if ($gitDirectory -and [IO.Path]::IsPathRooted($gitDirectory)) {
    # A write interrupted by power loss can leave one of these exact workflow
    # locks behind. Detect and record it, but never delete it at boot: safe
    # removal also requires a repo-wide Git mutation mutex and proof that no
    # current process owns the lock. The retained merge marker keeps this
    # condition fail-closed for reviewed recovery.
    $knownGitLockPaths = @(
        "index.lock",
        "HEAD.lock",
        "ORIG_HEAD.lock",
        "MERGE_HEAD.lock",
        "AUTO_MERGE.lock",
        "refs\auto-merge.lock",
        "refs\heads\master.lock",
        "refs\remotes\origin\master.lock"
    )
    foreach ($relativeLockPath in $knownGitLockPaths) {
        $absoluteLockPath = Join-Path $gitDirectory $relativeLockPath
        if (Test-Path -LiteralPath $absoluteLockPath -PathType Leaf) {
            try {
                $lockItem = Get-Item -LiteralPath $absoluteLockPath -ErrorAction Stop
                $preBootGitLocks += [ordered]@{
                    path = $absoluteLockPath
                    last_write_utc = $lockItem.LastWriteTimeUtc.ToString("o")
                    predates_boot = $lockItem.LastWriteTimeUtc -lt $boot.ToUniversalTime()
                }
            }
            catch {
                $preBootGitLocks += [ordered]@{
                    path = $absoluteLockPath
                    last_write_utc = $null
                    predates_boot = $null
                }
            }
        }
    }
}
if ($preBootGitLocks.Count -gt 0) {
    $gitLockRecoveryRequired = $true
    $notes.Add("detected $($preBootGitLocks.Count) exact Git workflow lock(s); preserved for reviewed recovery")
}
$mergeHeadPath = (& git rev-parse --git-path MERGE_HEAD 2>$null).Trim()
if ($mergeHeadPath -and -not [IO.Path]::IsPathRooted($mergeHeadPath)) {
    $mergeHeadPath = Join-Path $repo $mergeHeadPath
}
$mergeHeadExists = $mergeHeadPath -and (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf)
$fullHead = (& git rev-parse HEAD 2>$null).Trim().ToLowerInvariant()
$originMaster = (& git rev-parse origin/master 2>$null).Trim().ToLowerInvariant()
$currentBranchOutput = @(& git symbolic-ref --quiet --short HEAD 2>$null)
$currentBranchExit = $LASTEXITCODE
$currentBranch = if ($currentBranchOutput.Count -eq 0) { "" } else { ([string]$currentBranchOutput[-1]).Trim() }
$onMaster = $currentBranchExit -eq 0 -and $currentBranch -eq "master"
$marker = $null
$markerReadable = $false
$mergeMarkerSha256 = $null
$mergeMarkerPresent = Test-Path -LiteralPath $mergeMarkerPath -PathType Leaf
if ($mergeMarkerPresent) {
    try {
        $mergeMarkerSha256 = (Get-FileHash -LiteralPath $mergeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
        $marker = Get-Content -LiteralPath $mergeMarkerPath -Raw | ConvertFrom-Json
        if ([string]$marker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
            [string]$marker.baseline_commit -notmatch '^[0-9a-fA-F]{40}$' -or
            [string]$marker.pre_merge_commit -notmatch '^[0-9a-fA-F]{40}$') {
            throw "marker identity is invalid"
        }
        $markerReadable = $true
        $mergeMarkerPhase = [string]$marker.phase
    }
    catch {
        $mergeRecoveryFailed = $true
        $notes.Add("quiet-window merge marker is unreadable or invalid; preserving it for manual reconciliation")
    }
}
$untrustedMergeHeadRecoveryRequired = $mergeHeadExists -and -not $markerReadable

if ($markerReadable) {
    $baseline = ([string]$marker.baseline_commit).ToLowerInvariant()
    $preMerge = ([string]$marker.pre_merge_commit).ToLowerInvariant()
    $markerMergeCommit = ([string]$marker.merge_commit).ToLowerInvariant()
    $expectedTip = ([string]$marker.expected_tip).ToLowerInvariant()
    $resolvedTip = ([string]$marker.resolved_branch_tip).ToLowerInvariant()
    $expectedPaths = @(
        "config/locations.json",
        "config/location_market_events.json"
    )

    # Booleans in a mutable recovery marker are not enough to preserve a
    # committed tree. Re-derive the exact Git shape: synchronized reviewed
    # baseline, optional one-parent generated-config preparation, and the
    # expected two-parent merge whose second parent is the frozen source tip.
    $preMergeBaselineValid = $false
    & git merge-base --is-ancestor $baseline $preMerge 2>$null
    $baselineIsAncestor = $LASTEXITCODE -eq 0
    if ($baselineIsAncestor -and $preMerge -eq $baseline) {
        $preMergeBaselineValid = $true
    }
    elseif ($baselineIsAncestor) {
        $preMergeParentRow = (& git rev-list --parents -n 1 $preMerge 2>$null).Trim().ToLowerInvariant()
        $preMergeParentParts = @($preMergeParentRow -split '\s+' | Where-Object { $_ })
        $preMergeChanges = @(& git diff --name-only $baseline $preMerge 2>$null | Where-Object { $_ })
        $preMergeBaselineValid = (
            $preMergeParentParts.Count -eq 2 -and
            $preMergeParentParts[0] -eq $preMerge -and
            $preMergeParentParts[1] -eq $baseline -and
            $preMergeChanges.Count -gt 0 -and
            @($preMergeChanges | Where-Object { $expectedPaths -notcontains $_ }).Count -eq 0
        )
    }
    $markerRepoRoot = [string]$marker.repo_root
    $markerRepoValid = $false
    if ($markerRepoRoot -and [IO.Path]::IsPathRooted($markerRepoRoot)) {
        try {
            $markerRepoValid = [IO.Path]::GetFullPath($markerRepoRoot).TrimEnd('\') -ieq
                [IO.Path]::GetFullPath($repo).TrimEnd('\')
        }
        catch { $markerRepoValid = $false }
    }
    $markerIdentityValid = (
        $onMaster -and
        $markerRepoValid -and
        -not [string]::IsNullOrWhiteSpace([string]$marker.branch) -and
        $expectedTip -match '^[0-9a-f]{40}$' -and
        $resolvedTip -eq $expectedTip -and
        ([string]$marker.expected_baseline).ToLowerInvariant() -eq $baseline
    )
    $mergeParentsValid = $false
    if ($markerMergeCommit -match '^[0-9a-f]{40}$') {
        $mergeParentRow = (& git rev-list --parents -n 1 $markerMergeCommit 2>$null).Trim().ToLowerInvariant()
        $mergeParentParts = @($mergeParentRow -split '\s+' | Where-Object { $_ })
        $mergeParentsValid = (
            $mergeParentParts.Count -eq 3 -and
            $mergeParentParts[0] -eq $markerMergeCommit -and
            $mergeParentParts[1] -eq $preMerge -and
            $mergeParentParts[2] -eq $resolvedTip
        )
    }
    $executionProofOk = $marker.execution_tape_recovery_required -ne $true -or
        $marker.execution_tape_recovery_proved -eq $true
    $postCommitPhase = [string]$marker.phase -in @(
        "merge_committed_unpublished",
        "documented_unpublished",
        "published"
    )
    $documentationPendingSha256 = ([string]$marker.documentation_transaction_pending_sha256).ToLowerInvariant()
    $documentationSnapshotRelative = [string]$marker.documentation_transaction_snapshot_path
    $expectedDocumentationSnapshotRelative = "data/alerts/documentation_transactions/pending-$documentationPendingSha256.json"
    $documentationIdentityValid = $false
    if ($documentationPendingSha256 -match '^[0-9a-f]{64}$' -and
        $documentationSnapshotRelative -ceq $expectedDocumentationSnapshotRelative) {
        try {
            $documentationSnapshotPath = Join-Path $repo ($documentationSnapshotRelative -replace '/', '\')
            $documentationSnapshotHashValid = (
                (Get-FileHash -LiteralPath $documentationSnapshotPath -Algorithm SHA256 -ErrorAction Stop).Hash -ieq
                $documentationPendingSha256
            )
            $documentationSnapshot = Get-Content -LiteralPath $documentationSnapshotPath -Raw -ErrorAction Stop |
                ConvertFrom-Json
            $matchingDocumentationEntries = @($documentationSnapshot.integrations | Where-Object {
                    ([string]$_.integration_tip).ToLowerInvariant() -eq $markerMergeCommit -and
                    [string]$_.branch -ceq [string]$marker.branch -and
                    ([string]$_.expected_tip).ToLowerInvariant() -eq $expectedTip
                })
            $documentationIdentityValid = (
                $documentationSnapshotHashValid -and
                [string]$documentationSnapshot.schema_version -eq "documentation_transaction_pending_v0.1" -and
                [string]$documentationSnapshot.status -eq "PENDING" -and
                ([string]$documentationSnapshot.latest_integration_tip).ToLowerInvariant() -eq
                    $markerMergeCommit -and
                $matchingDocumentationEntries.Count -eq 1
            )
        }
        catch { $documentationIdentityValid = $false }
    }
    $phaseEvidenceValid = switch ([string]$marker.phase) {
        "merge_committed_unpublished" {
            $marker.documentation_transaction_recorded -ne $true -and
                $marker.publication_acknowledged -ne $true
        }
        "documented_unpublished" {
            $marker.documentation_transaction_recorded -eq $true -and
                $documentationIdentityValid
        }
        "published" {
            $marker.documentation_transaction_recorded -eq $true -and
                $documentationIdentityValid -and
                $marker.publication_acknowledged -eq $true
        }
        default { $false }
    }
    $committedRecoveryProved = (
        $postCommitPhase -and
        $phaseEvidenceValid -and
        $markerIdentityValid -and
        $preMergeBaselineValid -and
        $mergeParentsValid -and
        $marker.capture_recovery_proved -eq $true -and
        $executionProofOk -and
        $fullHead -eq $markerMergeCommit
    )
    if (-not $markerIdentityValid) {
        # A marker for another repository/branch identity is not authority to
        # move the currently checked-out ref. Leave both marker and tree for a
        # reviewed recovery rather than resetting unrelated work.
        $mergeRecoveryFailed = $true
        $notes.Add("quiet-window marker identity does not exactly bind this master checkout; refusing marker-driven Git mutation")
        if ($mergeHeadExists) {
            # MERGE_HEAD is independent authority to remove the staged target
            # tree even when the adjacent marker is corrupt or belongs to a
            # different checkout. Keep that marker and the nonzero result;
            # use no marker-derived ref as the rollback target.
            $untrustedMergeHeadRecoveryRequired = $true
        }
    }
    elseif ($committedRecoveryProved -and -not $mergeHeadExists) {
        # This is not unverified code: recovery passed before the explicit
        # commit. Preserve it, but require a reviewed caller to reconcile its
        # publication/attempt receipt instead of pushing or resetting at boot.
        $mergeReconciliationRequired = $true
        $publishedState = $originMaster -eq $markerMergeCommit
        $notes.Add("recovery-proved guarded merge $markerMergeCommit survived reboot; published=$publishedState; explicit reconciliation required")
    }
    else {
        # First remove the unverified target tree regardless of remote movement.
        # Refusing before merge --abort would let supervisors start that code.
        $notes.Add("FOUND AN UNVERIFIED GUARDED MERGE (phase=$mergeMarkerPhase) - removing target tree")
        $restoreExit = 0
        $preparingPhase = $mergeMarkerPhase -eq "preparing" -and -not $mergeHeadExists
        if ($preparingPhase) {
            # The marker is written before git add/commit. HEAD is therefore
            # either still the baseline or an exact config-only child created
            # just before power loss. A mixed reset handles both while keeping
            # the pre-recorded generated bytes in the working tree.
            $preparingHeadValid = $fullHead -eq $baseline
            if (-not $preparingHeadValid) {
                $preparingParentRow = (& git rev-list --parents -n 1 $fullHead 2>$null).Trim().ToLowerInvariant()
                $preparingParentParts = @($preparingParentRow -split '\s+' | Where-Object { $_ })
                $preparingChanges = @(& git diff --name-only $baseline $fullHead 2>$null | Where-Object { $_ })
                $preparingHeadValid = (
                    $preparingParentParts.Count -eq 2 -and
                    $preparingParentParts[0] -eq $fullHead -and
                    $preparingParentParts[1] -eq $baseline -and
                    $preparingChanges.Count -gt 0 -and
                    @($preparingChanges | Where-Object { $expectedPaths -notcontains $_ }).Count -eq 0
                )
            }
            if ($preparingHeadValid) {
                & git reset --mixed $baseline | Out-Null
                $restoreExit = $LASTEXITCODE
            }
            else {
                $restoreExit = 1
                $notes.Add("preparing marker HEAD is neither baseline nor an exact generated-config child")
            }
        }
        elseif ($mergeHeadExists) {
            & git merge --abort | Out-Null
            $restoreExit = $LASTEXITCODE
        }
        elseif ($preMergeBaselineValid) {
            & git reset --hard $preMerge | Out-Null
            $restoreExit = $LASTEXITCODE
        }
        else {
            $restoreExit = 1
            $notes.Add("marker pre-merge/baseline ancestry is invalid; no automatic hard reset target is trusted")
        }
        if ($restoreExit -ne 0) {
            if ($preMergeBaselineValid) {
                & git reset --hard $preMerge | Out-Null
                $restoreExit = $LASTEXITCODE
                $notes.Add("merge --abort failed; reset --hard to the validated pre-merge commit")
            }
        }
        $afterPreMerge = (& git rev-parse HEAD 2>$null).Trim().ToLowerInvariant()
        $mergeHeadStillExists = $mergeHeadPath -and (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf)
        $expectedPreMergeAfterRestore = if ($preparingPhase) { $baseline } else { $preMerge }
        $targetTreeRemoved = $restoreExit -eq 0 -and
            $afterPreMerge -eq $expectedPreMergeAfterRestore -and
            -not $mergeHeadStillExists
        if (-not $targetTreeRemoved) {
            $mergeRecoveryFailed = $true
            $notes.Add("unverified target tree removal FAILED: git_exit=$restoreExit head=$afterPreMerge expected=$preMerge merge_head=$mergeHeadStillExists")
        }
        elseif ($originMaster -ne $baseline) {
            # The dangerous target tree is gone. Do not perform the second
            # mixed reset across an independently moved remote baseline; keep
            # the marker and exact pre-merge tree for reviewed reconciliation.
            $mergeRecoveryFailed = $true
            $mergeRollbackTarget = $preMerge
            $notes.Add("unverified target tree removed to $preMerge, but origin/master $originMaster moved from marker baseline $baseline; preserving marker and refusing baseline reset")
        }
        else {
            if ($preMerge -ne $baseline) {
                # Mixed reset preserves the generated config bytes from the
                # preparation commit while returning master to origin/master.
                & git reset --mixed $baseline | Out-Null
                $restoreExit = $LASTEXITCODE
            }
            $dirtyTracked = @(& git status --porcelain | Where-Object { $_ -and $_ -notmatch '^\?\?' })
            $unexpectedDirty = @($dirtyTracked | Where-Object {
                    $path = ($_ -replace '^..\s*', '').Trim()
                    $expectedPaths -notcontains $path
                })
            $hashMismatch = @()
            $markerHashProperties = @($marker.auto_refreshed_sha256.PSObject.Properties)
            if ($markerHashProperties.Count -ne $expectedPaths.Count -or
                @($expectedPaths | Where-Object { $markerHashProperties.Name -notcontains $_ }).Count -ne 0) {
                $hashMismatch += "marker_hash_contract"
            }
            foreach ($property in $markerHashProperties) {
                if ($expectedPaths -notcontains [string]$property.Name -or
                    [string]$property.Value -notmatch '^[0-9a-fA-F]{64}$') {
                    $hashMismatch += [string]$property.Name
                    continue
                }
                $absolute = Join-Path $repo (([string]$property.Name) -replace '/', '\')
                if (-not (Test-Path -LiteralPath $absolute -PathType Leaf) -or
                    (Get-FileHash -LiteralPath $absolute -Algorithm SHA256).Hash -ine [string]$property.Value) {
                    $hashMismatch += [string]$property.Name
                }
            }
            $finalHead = (& git rev-parse HEAD 2>$null).Trim().ToLowerInvariant()
            if ($restoreExit -eq 0 -and $finalHead -eq $baseline -and
                $unexpectedDirty.Count -eq 0 -and $hashMismatch.Count -eq 0) {
                $markerRemovalPending = $true
                $mergeRollbackTarget = $baseline
                $notes.Add("interrupted merge Git state restored; retaining marker until exact capture recovery is proved")
            }
            else {
                $mergeRecoveryFailed = $true
                $notes.Add("guarded-merge rollback could not prove exact recovery: git_exit=$restoreExit head=$finalHead expected=$baseline unexpected_dirty=$($unexpectedDirty.Count) hash_mismatch=$($hashMismatch.Count)")
            }
        }
    }
}
if ($untrustedMergeHeadRecoveryRequired) {
    # Compatibility recovery for a hand-run or older wrapper that predates the
    # durable marker, and safety recovery for a corrupt/mismatched marker.
    # MERGE_HEAD itself authorizes aborting the unverified staged tree;
    # ORIG_HEAD is the fallback target. Marker-derived refs are never trusted.
    $origHead = (& git rev-parse --verify ORIG_HEAD 2>$null).Trim().ToLowerInvariant()
    $mergeHeadRecoveryLabel = if ($mergeMarkerPresent) { "UNTRUSTED-MARKER" } else { "UNMARKED" }
    $notes.Add("FOUND AN $mergeHeadRecoveryLabel INTERRUPTED MERGE (MERGE_HEAD present) - aborting staged target tree")
    & git merge --abort | Out-Null
    $abortExit = $LASTEXITCODE
    if ($abortExit -ne 0 -and $origHead -match '^[0-9a-f]{40}$') {
        & git reset --hard $origHead | Out-Null
        $abortExit = $LASTEXITCODE
        $notes.Add("merge --abort failed; reset --hard to exact ORIG_HEAD instead")
    }
    $mergeHeadStillExists = $mergeHeadPath -and (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf)
    $afterAbort = (& git rev-parse HEAD 2>$null).Trim().ToLowerInvariant()
    if ($abortExit -eq 0 -and -not $mergeHeadStillExists -and
        ($origHead -notmatch '^[0-9a-f]{40}$' -or $afterAbort -eq $origHead)) {
        $unmarkedRecoveryPending = $true
        $mergeRollbackTarget = $afterAbort
        $notes.Add("unmarked interrupted merge Git state undone; awaiting exact affected-producer recovery proof")
    }
    else {
        $mergeRecoveryFailed = $true
        $notes.Add("unmarked interrupted merge recovery FAILED; exit=$abortExit head=$afterAbort orig=$origHead merge_head=$mergeHeadStillExists")
    }
}
$head = (& git rev-parse --short HEAD 2>$null)
if ($head) { $notes.Add("HEAD $head") }

# ---- did the fleet come back? ----
# The supervisors are S4U on 1-2 minute repeating triggers, so they should self-start with
# nobody logged on. Verify rather than assume: this is the one failure mode that silences
# every other check, and a boot is exactly when it would show up.
function Test-BootExactCaptureRecovery {
    $python = Join-Path $repo "venv\Scripts\python.exe"
    try {
        $captureRaw = @(& $python -m weather.operations.capture_recovery_check --repo-root $repo --json 2>$null)
        $captureExit = $LASTEXITCODE
        $captureProof = (($captureRaw -join "`n") | ConvertFrom-Json)
        return (
            $captureExit -eq 0 -and
            $captureProof.ok -eq $true -and
            @($captureProof.workers).Count -eq 3 -and
            @($captureProof.workers | Where-Object { $_.ok -ne $true }).Count -eq 0
        )
    }
    catch { return $false }
}

function Count-Loops {
    @(Get-CimInstance Win32_Process | Where-Object {
            ($_.CommandLine -like '*weather.collection.snapshot_tracker*' -or
            $_.CommandLine -like '*weather.market.market_microstructure*' -or
            $_.CommandLine -like '*weather.operations.observation_trigger*') -and
            $_.CommandLine -notlike '*hot_capture*' -and
            $_.CommandLine -notlike '*--expected-runtime-fingerprint*'
        }).Count
}
# Always take a reading; -NoWait only skips the retry loop (it exists so the script can be
# tested on an already-running host without a 5-minute pause).
$loops = Count-Loops
$recovered = Test-BootExactCaptureRecovery
if (-not $NoWait) {
    for ($i = 0; $i -lt 20 -and -not $recovered; $i++) {
        Start-Sleep -Seconds 15
        $loops = Count-Loops
        $recovered = Test-BootExactCaptureRecovery
    }
}
$notes.Add("raw capture-like process count after boot: $loops (diagnostic only)")
$notes.Add("canonical exact capture recovery: $(if ($recovered) { 'recovered unattended' } else { 'NOT RECOVERED' })")

$markerCoreRecoveryProved = $false
$markerExecutionRecoveryProved = $false
$markerCaptureRecoveryProved = $false
$unmarkedCoreRecoveryProved = $false
$unmarkedExecutionRecoveryProved = $false
$unmarkedCaptureRecoveryProved = $false

function Test-BootExecutionTapeActive {
    $task = Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor" -ErrorAction SilentlyContinue
    if ($task -and [string]$task.State -ne "Disabled") { return $true }
    $statusPath = Join-Path $repo "data\snapshots\execution_tape_status.json"
    $writerLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
    if (Test-Path -LiteralPath $writerLockPath -PathType Leaf) { return $true }
    if (Test-Path -LiteralPath $statusPath -PathType Leaf) {
        try {
            $status = Get-Content -LiteralPath $statusPath -Raw -ErrorAction Stop | ConvertFrom-Json
            if ([string]$status.state -eq "STOPPED" -or [int]$status.pid -le 0) { return $false }
            return $null -ne (Get-Process -Id ([int]$status.pid) -ErrorAction SilentlyContinue)
        }
        catch { return $false }
    }
    return $false
}

function Get-ExactRecoveryProof {
    param(
        [Parameter(Mandatory = $true)][bool]$RequireExecutionTape,
        [string]$ExpectedExecutionSource = ""
    )

    $python = Join-Path $repo "venv\Scripts\python.exe"
    $coreProved = $false
    try {
        $captureRaw = @(& $python -m weather.operations.capture_recovery_check --repo-root $repo --json 2>$null)
        $captureExit = $LASTEXITCODE
        $captureProof = (($captureRaw -join "`n") | ConvertFrom-Json)
        $coreProved = (
            $captureExit -eq 0 -and
            $captureProof.ok -eq $true -and
            @($captureProof.workers).Count -eq 3 -and
            @($captureProof.workers | Where-Object { $_.ok -ne $true }).Count -eq 0
        )
    }
    catch { $coreProved = $false }

    $executionProved = -not $RequireExecutionTape
    if ($coreProved -and $RequireExecutionTape) {
        try {
            $executionRaw = @(& $python -m weather.operations.execution_tape_supervisor status --stale-after-seconds 180 2>$null)
            $executionExit = $LASTEXITCODE
            $executionPayload = (($executionRaw -join "`n") | ConvertFrom-Json)
            $executionHealth = $executionPayload.health
            $executionStatus = $executionPayload.status
            $executionLockPath = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
            $executionLock = Get-Content -LiteralPath $executionLockPath -Raw -ErrorAction Stop | ConvertFrom-Json
            $actualExecutionSource = [string]$executionStatus.runtime_identity.source_fingerprint
            $executionSourceValid = (
                $actualExecutionSource -match '^[0-9a-f]{16}$' -and
                (-not $ExpectedExecutionSource -or
                    $actualExecutionSource -ceq $ExpectedExecutionSource)
            )
            $executionProved = (
                $executionExit -eq 0 -and
                @("RUNNING", "DEGRADED") -contains [string]$executionHealth.state -and
                $executionHealth.pid_alive -eq $true -and
                $executionHealth.runtime_identity_matches_current -eq $true -and
                [string]$executionHealth.evidence_integrity -eq "PASS" -and
                [string]$executionStatus.state -eq "CONNECTED" -and
                [string]$executionStatus.market -eq "all" -and
                [string]$executionStatus.runner -eq "managed_execution_tape" -and
                $executionSourceValid -and
                $executionStatus.managed_process.verified_at_capture -eq $true -and
                [int]$executionStatus.pid -gt 0 -and
                [int]$executionStatus.pid -eq [int]$executionStatus.managed_process.pid -and
                [int]$executionStatus.pid -eq [int]$executionLock.pid -and
                [int]$executionStatus.pid -eq [int]$executionLock.managed_process.pid -and
                [string]$executionStatus.managed_process.creation_time_token -cne "" -and
                [string]$executionStatus.managed_process.creation_time_token -ceq
                    [string]$executionLock.managed_process.creation_time_token
            )
        }
        catch { $executionProved = $false }
    }

    return [PSCustomObject]@{
        core = $coreProved
        execution_tape = $executionProved
        all = ($coreProved -and $executionProved)
    }
}

if ($markerRemovalPending) {
    # Process command lines appear before their status, lock, and loaded-source
    # evidence is necessarily current. Retry the canonical proof on the same
    # bounded boot cadence instead of turning that ordinary startup race into a
    # permanent marker failure. -NoWait deliberately makes exactly one attempt.
    $markerProofAttemptLimit = if ($NoWait) { 1 } else { 21 }
    # The preparing phase precedes any staged target merge, so no auxiliary
    # readoption can have occurred yet and execution_tape_source_before is
    # intentionally null. Every later phase must prove the old exact writer
    # identity when the marker says that producer was part of the roll.
    $markerExecutionRequired = $marker.execution_tape_recovery_required -eq $true -and
        [string]$marker.phase -ne "preparing"
    $markerExpectedExecutionSource = if ($markerExecutionRequired) {
        [string]$marker.execution_tape_source_before
    }
    else { "" }
    for ($markerProofAttempt = 1; $markerProofAttempt -le $markerProofAttemptLimit; $markerProofAttempt++) {
        $markerProof = Get-ExactRecoveryProof `
            -RequireExecutionTape $markerExecutionRequired `
            -ExpectedExecutionSource $markerExpectedExecutionSource
        $markerCoreRecoveryProved = $markerProof.core
        $markerExecutionRecoveryProved = $markerProof.execution_tape
        $markerCaptureRecoveryProved = $markerProof.all
        if ($markerCaptureRecoveryProved) { break }
        if ($markerProofAttempt -lt $markerProofAttemptLimit) {
            Start-Sleep -Seconds 15
        }
    }
    if ($markerCaptureRecoveryProved) {
        $currentMarkerSha256 = $null
        try {
            $currentMarkerSha256 = (Get-FileHash -LiteralPath $mergeMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
        }
        catch {}
        if ($currentMarkerSha256 -eq $mergeMarkerSha256) {
            Remove-Item -LiteralPath $mergeMarkerPath -Force -ErrorAction SilentlyContinue
        }
        if ($currentMarkerSha256 -eq $mergeMarkerSha256 -and
            -not (Test-Path -LiteralPath $mergeMarkerPath)) {
            $mergeHealed = $true
            $notes.Add("exact affected-producer recovery proved after $markerProofAttempt attempt(s); retired the rolled-back quiet-merge marker")
        }
        else {
            $mergeRecoveryFailed = $true
            $notes.Add("capture recovered but the exact unchanged rolled-back quiet-merge marker could not be retired")
        }
    }
    else {
        $mergeRecoveryFailed = $true
        $notes.Add("rolled-back Git state is exact but affected-producer recovery is unproved after $markerProofAttemptLimit attempt(s); retaining quiet-merge marker")
    }
}

if ($unmarkedRecoveryPending) {
    # With no marker there is no closure verdict. Gate a configured or detached
    # execution-tape writer conservatively, while an intentionally disabled and
    # inactive optional producer remains outside the recovery dependency.
    $unmarkedExecutionTapeRequired = Test-BootExecutionTapeActive
    $unmarkedProofAttemptLimit = if ($NoWait) { 1 } else { 21 }
    for ($unmarkedProofAttempt = 1; $unmarkedProofAttempt -le $unmarkedProofAttemptLimit; $unmarkedProofAttempt++) {
        $unmarkedProof = Get-ExactRecoveryProof `
            -RequireExecutionTape $unmarkedExecutionTapeRequired
        $unmarkedCoreRecoveryProved = $unmarkedProof.core
        $unmarkedExecutionRecoveryProved = $unmarkedProof.execution_tape
        $unmarkedCaptureRecoveryProved = $unmarkedProof.all
        if ($unmarkedCaptureRecoveryProved) { break }
        if ($unmarkedProofAttempt -lt $unmarkedProofAttemptLimit) {
            Start-Sleep -Seconds 15
        }
    }
    if ($unmarkedCaptureRecoveryProved) {
        $mergeHealed = $true
        $notes.Add("unmarked rollback exact affected-producer recovery proved after $unmarkedProofAttempt attempt(s)")
    }
    else {
        $mergeRecoveryFailed = $true
        $notes.Add("unmarked rollback Git state is exact but affected-producer recovery is unproved after $unmarkedProofAttemptLimit attempt(s)")
    }
}

# ---- record ----
$rec = [ordered]@{
    ts = (Get-Date).ToString("o")
    boot_time = $boot.ToString("o")
    previous_shutdown_unclean = $unclean
    previous_shutdown_cause = $cause
    interrupted_merge_healed = $mergeHealed
    interrupted_merge_recovery_failed = $mergeRecoveryFailed
    merge_reconciliation_required = $mergeReconciliationRequired
    merge_marker_phase = $mergeMarkerPhase
    merge_marker_sha256 = $mergeMarkerSha256
    merge_rollback_target = $mergeRollbackTarget
    git_lock_recovery_required = $gitLockRecoveryRequired
    preboot_git_locks = @($preBootGitLocks)
    marker_core_recovery_proved = $markerCoreRecoveryProved
    marker_execution_tape_recovery_proved = $markerExecutionRecoveryProved
    marker_capture_recovery_proved = $markerCaptureRecoveryProved
    unmarked_core_recovery_proved = $unmarkedCoreRecoveryProved
    unmarked_execution_tape_recovery_proved = $unmarkedExecutionRecoveryProved
    unmarked_capture_recovery_proved = $unmarkedCaptureRecoveryProved
    head = "$head"
    branch = $currentBranch
    origin_master = $originMaster
    capture_loops = $loops
    capture_recovered = $recovered
    notes = @($notes)
}
$bootRecordPersisted = $false
$bootRecordFailure = $null
try {
    if (-not (Test-Path $alertDir)) {
        New-Item -ItemType Directory -Path $alertDir -Force -ErrorAction Stop | Out-Null
    }
    Add-Content -Path $logPath -Value ($rec | ConvertTo-Json -Depth 4 -Compress) -Encoding utf8 -ErrorAction Stop
    $bootRecordPersisted = $true
}
catch {
    $bootRecordFailure = $_.Exception.Message
    $notes.Add("BOOT EVENT PERSISTENCE FAILED: $bootRecordFailure")
}
$notes | ForEach-Object { Write-Output $_ }
if (-not $bootRecordPersisted) { exit 4 }
if ($mergeRecoveryFailed -or $mergeReconciliationRequired -or $gitLockRecoveryRequired) { exit 3 }
if (-not $recovered) { exit 2 }
exit 0
