# Reviewed retirement of the durable quiet-merge marker for an ORDINARY
# synchronized merge (operation_mode ordinary_synchronized_merge_v0.1) that
# reached `documented_unpublished` and was then published outside the wrapper
# (for example by the owner after WeatherOneShotPush could not run).
#
# reconcile_integration_attempt.ps1 covers the same marker only for a
# manifest-backed integration attempt. An ad-hoc quiet-window merge has no
# manifest, so without this script the marker can never be retired: the wrapper
# refuses every further merge while it exists, and boot recovery would treat a
# master that moved past the marker's merge commit as an unverified merge and
# hard-reset production to the pre-merge commit.
#
# This script never pushes, resets, merges, or edits the marker. It proves the
# marker is hash-bound to the caller's review, that Git independently shows
# HEAD == master == origin/master == marker.merge_commit with the recorded
# parents and baseline ancestry, that the documentation transaction snapshot
# still binds that merge, and that capture (and the execution tape when the
# marker required it) is healthy now. Only then does it write an immutable
# receipt embedding the marker's exact bytes, append the outcome to the
# quiet-merge history, and delete the marker by compare-and-retire.

[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{64}$")][string]$ExpectedActiveMarkerSha256,
    [Parameter(Mandatory = $true)][string]$ReviewReference,
    [string]$Python = "",
    [string]$Notes = "",
    [int]$ExecutionTapeRetrySeconds = 4,
    [int]$ExecutionTapeReads = 5,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path.TrimEnd('\')
if (-not $Python) { $Python = Join-Path $RepoRoot "venv\Scripts\python.exe" }
if ([string]::IsNullOrWhiteSpace($ReviewReference)) { throw "ReviewReference must name the review that authorizes retirement." }

$expectedSha256 = $ExpectedActiveMarkerSha256.ToLowerInvariant()
$markerPath = Join-Path $RepoRoot "data\alerts\quiet_window_merge_in_progress.json"
$historyPath = Join-Path $RepoRoot "data\alerts\quiet_window_merge_history.jsonl"
$receiptDir = Join-Path $RepoRoot "data\alerts\quiet_window_merge_reconciliations"
$receiptPath = Join-Path $receiptDir ("ordinary-{0}.json" -f $expectedSha256)
$configPaths = @("config/locations.json", "config/location_market_events.json")

function Note([string]$m) { Write-Host ("[reconcile-ordinary] {0}" -f $m) }

function Get-Sha256Hex([byte[]]$bytes) {
    $h = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($h.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant() }
    finally { $h.Dispose() }
}

function Get-FileSha256Hex([string]$path) {
    return Get-Sha256Hex ([IO.File]::ReadAllBytes($path))
}

# Read-only git. Native stderr is scoped to Continue so a routine notice cannot
# terminate the script under the Stop preference; the exit code is what counts.
function Invoke-GitLines([string[]]$arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = @(& git -C $RepoRoot @arguments 2>&1 | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw ("git {0} failed (exit {1}): {2}" -f ($arguments -join ' '), $code, ($out -join ' | ')) }
    return @($out | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

function Invoke-GitLine([string[]]$arguments) {
    $lines = @(Invoke-GitLines $arguments)
    if ($lines.Count -eq 0) { throw ("git {0} returned nothing" -f ($arguments -join ' ')) }
    return ([string]$lines[-1]).ToLowerInvariant()
}

function Test-PathEqual([string]$left, [string]$right) {
    try {
        $l = (Resolve-Path -LiteralPath $left).Path.TrimEnd('\')
        $r = (Resolve-Path -LiteralPath $right).Path.TrimEnd('\')
    }
    catch { return $false }
    return [string]::Equals($l, $r, [StringComparison]::OrdinalIgnoreCase)
}

function Invoke-PythonJson([string[]]$arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = @(& $Python @arguments 2>$null | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    try { $payload = (($out -join "`n") | ConvertFrom-Json) }
    catch { throw ("{0} produced unreadable JSON" -f ($arguments -join ' ')) }
    return [pscustomobject]@{ exit = $code; payload = $payload }
}

# ---- 1. hash-bound marker ----
if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) { throw "No active quiet-merge marker exists at $markerPath" }
$markerBytes = [IO.File]::ReadAllBytes($markerPath)
$markerSha256 = Get-Sha256Hex $markerBytes
if ($markerSha256 -ne $expectedSha256) { throw "Active marker hash mismatch. Expected $expectedSha256; got $markerSha256" }
try { $markerRaw = (New-Object System.Text.UTF8Encoding($false, $true)).GetString($markerBytes) }
catch { throw "Active marker is not strict UTF-8." }
try { $marker = $markerRaw | ConvertFrom-Json }
catch { throw "Active marker JSON is unreadable." }
Note "marker hash-bound: $markerSha256"

$hex40 = '^[0-9a-f]{40}$'
$hex64 = '^[0-9a-f]{64}$'
$mergeCommit = ([string]$marker.merge_commit).ToLowerInvariant()
$preMerge = ([string]$marker.pre_merge_commit).ToLowerInvariant()
$baseline = ([string]$marker.baseline_commit).ToLowerInvariant()
$sourceTip = ([string]$marker.resolved_branch_tip).ToLowerInvariant()
$expectedTip = ([string]$marker.expected_tip).ToLowerInvariant()
$phase = [string]$marker.phase
if ([string]$marker.schema -ne "quiet_window_merge_in_progress_v0.1") { throw "Marker schema is not quiet_window_merge_in_progress_v0.1." }
if ([string]$marker.operation_mode -cne "ordinary_synchronized_merge_v0.1") {
    throw "Marker operation_mode '$($marker.operation_mode)' is not an ordinary synchronized merge; use the attempt or production-baseline reconciler."
}
if (-not (Test-PathEqual ([string]$marker.repo_root) $RepoRoot)) { throw "Marker repo_root does not name this repository." }
if ($phase -notin @("documented_unpublished", "published")) { throw "Marker phase '$phase' is pre-documentation; boot recovery owns it." }
if ($mergeCommit -notmatch $hex40 -or $preMerge -notmatch $hex40 -or $baseline -notmatch $hex40 -or
    $sourceTip -notmatch $hex40 -or $expectedTip -notmatch $hex40 -or $sourceTip -ne $expectedTip -or
    ([string]$marker.expected_baseline).ToLowerInvariant() -ne $baseline) {
    throw "Marker commit identity fields are incomplete or inconsistent."
}
if ($marker.capture_recovery_proved -ne $true) { throw "Marker never proved capture recovery; this is not a verified merge." }
if ($marker.execution_tape_recovery_required -eq $true -and $marker.execution_tape_recovery_proved -ne $true) {
    throw "Marker required execution-tape recovery and never proved it."
}
if ($marker.documentation_transaction_recorded -ne $true) { throw "Marker phase $phase without a recorded documentation transaction." }
if ($phase -eq "published" -and $marker.publication_acknowledged -ne $true) { throw "Marker phase published without publication_acknowledged." }

# ---- 2. documentation transaction snapshot ----
$pendingSha256 = ([string]$marker.documentation_transaction_pending_sha256).ToLowerInvariant()
$snapshotRelative = ([string]$marker.documentation_transaction_snapshot_path).Replace('\', '/')
if ($pendingSha256 -notmatch $hex64 -or $snapshotRelative -cne "data/alerts/documentation_transactions/pending-$pendingSha256.json") {
    throw "Documentation transaction snapshot identity is missing or non-canonical."
}
$snapshotPath = Join-Path $RepoRoot ($snapshotRelative -replace '/', '\')
if (-not (Test-Path -LiteralPath $snapshotPath -PathType Leaf)) { throw "Documentation transaction snapshot is missing: $snapshotRelative" }
if ((Get-FileSha256Hex $snapshotPath) -ne $pendingSha256) { throw "Documentation transaction snapshot hash does not match the marker." }
$snapshot = Get-Content -LiteralPath $snapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json
$matching = @($snapshot.integrations | Where-Object {
        ([string]$_.integration_tip).ToLowerInvariant() -eq $mergeCommit -and
        [string]$_.branch -ceq [string]$marker.branch -and
        ([string]$_.expected_tip).ToLowerInvariant() -eq $expectedTip
    })
if ([string]$snapshot.schema_version -ne "documentation_transaction_pending_v0.1" -or
    [string]$snapshot.status -ne "PENDING" -or
    ([string]$snapshot.latest_integration_tip).ToLowerInvariant() -ne $mergeCommit -or
    $matching.Count -ne 1) {
    throw "Documentation transaction snapshot does not bind the exact merge, branch, and source tip."
}
Note "documentation transaction bound: pending-$pendingSha256"

# ---- 3. Git proves publication ----
$mergeHeadPath = Invoke-GitLine @("rev-parse", "--git-path", "MERGE_HEAD")
if (-not [IO.Path]::IsPathRooted($mergeHeadPath)) { $mergeHeadPath = Join-Path $RepoRoot $mergeHeadPath }
if (Test-Path -LiteralPath $mergeHeadPath -PathType Leaf) { throw "A merge is in progress (MERGE_HEAD exists)." }
$symbolic = Invoke-GitLine @("symbolic-ref", "-q", "HEAD")
if ($symbolic -ne "refs/heads/master") { throw "Checked-out branch is '$symbolic', not master." }
$head = Invoke-GitLine @("rev-parse", "--verify", "HEAD^{commit}")
$localMaster = Invoke-GitLine @("rev-parse", "--verify", "refs/heads/master^{commit}")
$originMaster = Invoke-GitLine @("rev-parse", "--verify", "refs/remotes/origin/master^{commit}")
if ($head -ne $mergeCommit -or $localMaster -ne $mergeCommit -or $originMaster -ne $mergeCommit) {
    throw "Git does not prove publication: HEAD=$head master=$localMaster origin/master=$originMaster marker=$mergeCommit"
}
$parentRow = @((Invoke-GitLine @("rev-list", "--parents", "-n", "1", $mergeCommit)) -split '\s+' | Where-Object { $_ })
if ($parentRow.Count -ne 3 -or $parentRow[0] -ne $mergeCommit -or $parentRow[1] -ne $preMerge -or $parentRow[2] -ne $sourceTip) {
    throw "Merge commit parents do not match the marker (pre-merge, source tip)."
}
if ($preMerge -ne $baseline) {
    $preRow = @((Invoke-GitLine @("rev-list", "--parents", "-n", "1", $preMerge)) -split '\s+' | Where-Object { $_ })
    $preChanges = @(Invoke-GitLines @("diff", "--name-only", $baseline, $preMerge))
    if ($preRow.Count -ne 2 -or $preRow[1] -ne $baseline -or $preChanges.Count -eq 0 -or
        @($preChanges | Where-Object { $configPaths -notcontains $_ }).Count -ne 0) {
        throw "Pre-merge commit is not the baseline or an exact generated-config child of it."
    }
}
$dirty = @(Invoke-GitLines @("status", "--porcelain", "--untracked-files=no"))
$dirtyPaths = @()
foreach ($row in $dirty) {
    # Rows arrive trimmed: ' M p' -> 'M p', 'M  p' and 'MM p' keep their shape.
    if ($row -notmatch '^(?:M|MM)\s+(.+)$') { throw "Tracked worktree holds a non-modification change: $row" }
    $rel = $Matches[1].Trim().Replace('\', '/')
    if ($configPaths -notcontains $rel) { throw "Tracked worktree is modified outside the generated-config set: $rel" }
    $dirtyPaths += $rel
}
Note "git proves publication: HEAD == master == origin/master == $mergeCommit"

# ---- 4. capture and execution-tape health now ----
$capture = Invoke-PythonJson @("-m", "weather.operations.capture_recovery_check", "--repo-root", $RepoRoot, "--json")
if ($capture.exit -ne 0 -or $capture.payload.ok -ne $true -or @($capture.payload.workers).Count -ne 3 -or
    @($capture.payload.workers | Where-Object { $_.ok -ne $true }).Count -ne 0) {
    throw "Current capture state is not healthy for all three workers; retirement remains blocked."
}
Note "capture healthy: 3 of 3 workers"

$tapeSummary = $null
if ($marker.execution_tape_recovery_required -eq $true) {
    $writerLockPath = Join-Path $RepoRoot "data\snapshots\.execution_tape_status.json.writer.lock"
    $attempt = 0
    $tapeOk = $false
    $tapeSeen = "no read"
    while (-not $tapeOk -and $attempt -lt $ExecutionTapeReads) {
        $attempt++
        try {
            $tape = Invoke-PythonJson @("-m", "weather.operations.execution_tape_supervisor", "status", "--stale-after-seconds", "180")
            $writerLock = Get-Content -LiteralPath $writerLockPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $health = $tape.payload.health
            $status = $tape.payload.status
            # A read that races the writer's replace yields the reduced UNKNOWN
            # health shape (no evidence_integrity); under StrictMode that access
            # would throw, so the summary is built from what is present.
            $tapeSeen = "exit=$($tape.exit) " + (($health.PSObject.Properties | Where-Object { $_.Name -in @("state", "pid_alive", "runtime_identity_matches_current", "evidence_integrity", "detail") } | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join " ") + " status=$($status.state) pid=$($status.pid) lock=$($writerLock.pid)"
            if (-not ($health.PSObject.Properties.Name -contains "evidence_integrity")) { throw "reduced health payload (status file unreadable during rewrite)" }
            $tapeOk = ($tape.exit -eq 0 -and
                [string]$health.state -in @("RUNNING", "DEGRADED") -and
                $health.pid_alive -eq $true -and
                $health.runtime_identity_matches_current -eq $true -and
                [string]$health.evidence_integrity -eq "PASS" -and
                [string]$status.state -eq "CONNECTED" -and
                [int]$status.pid -gt 0 -and
                [int]$status.pid -eq [int]$status.managed_process.pid -and
                [int]$status.pid -eq [int]$writerLock.pid)
        }
        catch { $tapeOk = $false; $tapeSeen = "read failed: $($_.Exception.Message) [$tapeSeen]" }
        # The status file is rewritten every 10 s and the reader sees nothing
        # while it is replaced; the retry interval must not phase-lock with it.
        if (-not $tapeOk -and $attempt -lt $ExecutionTapeReads) { Start-Sleep -Seconds $ExecutionTapeRetrySeconds }
    }
    if (-not $tapeOk) { throw "Current execution-tape status/lock/process proof is unhealthy after $attempt read(s): $tapeSeen" }
    $tapeSummary = [pscustomobject]@{ state = [string]$status.state; health = [string]$health.state; pid = [int]$status.pid; reads = $attempt }
    Note "execution tape healthy: $($tapeSummary.health)/$($tapeSummary.state) pid $($tapeSummary.pid)"
}

# ---- 5. receipt, history, compare-and-retire ----
$now = [datetimeoffset]::Now
$receipt = [ordered]@{
    schema = "quiet_window_merge_reconciliation_v0.1"
    kind = "ordinary_synchronized_merge_marker_retirement"
    stage = "reconciled_published"
    at = $now.ToString("o")
    repo_root = $RepoRoot
    review_reference = $ReviewReference
    notes = $Notes
    dry_run = [bool]$DryRun.IsPresent
    branch = [string]$marker.branch
    expected_tip = $expectedTip
    baseline_commit = $baseline
    pre_merge_commit = $preMerge
    merge_commit = $mergeCommit
    marker_phase = $phase
    marker_sha256 = $markerSha256
    marker_raw = $markerRaw
    documentation_transaction_pending_sha256 = $pendingSha256
    git = [ordered]@{ head = $head; master = $localMaster; origin_master = $originMaster; dirty_generated_config = $dirtyPaths }
    capture = [ordered]@{ ok = $true; workers = @($capture.payload.workers | ForEach-Object { [string]$_.name }) }
    execution_tape = $tapeSummary
    downstream_authority = "none"
}
$receiptJson = $receipt | ConvertTo-Json -Depth 8
if ($DryRun) {
    Note "DRY RUN: every proof passed; marker retained"
    Write-Output $receiptJson
    exit 0
}
if (Test-Path -LiteralPath $receiptPath) { throw "Reconciliation receipt already exists: $receiptPath" }
if (-not (Test-Path -LiteralPath $receiptDir -PathType Container)) { New-Item -ItemType Directory -Path $receiptDir -Force | Out-Null }
[IO.File]::WriteAllText($receiptPath, $receiptJson, (New-Object System.Text.UTF8Encoding($false)))
$receiptSha256 = Get-FileSha256Hex $receiptPath
$historyRow = [ordered]@{
    ts = $now.ToString("o"); ok = $true; stage = "reconciled_published"; branch = [string]$marker.branch
    merge_commit = $mergeCommit; marker_sha256 = $markerSha256; receipt_path = $receiptPath
    receipt_sha256 = $receiptSha256; review_reference = $ReviewReference; detail = "ordinary marker retired after Git-proved publication"
}
# BOM-free append: Add-Content -Encoding utf8 stamps a BOM when it creates the file.
[IO.File]::AppendAllText($historyPath, (($historyRow | ConvertTo-Json -Depth 4 -Compress) + "`n"), (New-Object System.Text.UTF8Encoding($false)))
if ((Get-FileSha256Hex $markerPath) -ne $markerSha256) { throw "Active marker changed between proof and retirement; receipt written, marker retained." }
Remove-Item -LiteralPath $markerPath -Force -ErrorAction Stop
if (Test-Path -LiteralPath $markerPath) { throw "Active marker still exists after retirement." }
Note "marker retired; receipt $receiptPath ($receiptSha256)"
Write-Output $receiptJson
exit 0
