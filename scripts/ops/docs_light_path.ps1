# Fail-forward light path for a docs-only branch (Operations agent role, section 6, rule 2).
#
#   .\scripts\ops\docs_light_path.ps1 -Branch origin/codex/... -ExpectedTip <full-sha> [-CheckOnly]
#
# A branch whose roll verdict is ROLL-FREE and whose diff is only Markdown under
# docs/ cannot restart capture, so it lands without the heavy lease or the quiet
# window: a plain local --no-ff merge, then WeatherOneShotPush, then proof that
# origin/master is the merge commit. Every outcome after the merge writes an
# immutable receipt under data/alerts/quiet_window_merge_reconciliations/.
#
# This script never writes the quiet-merge marker (the merge tool's -DryRun did,
# on 2026-09-24, and blocked a night), never force-pushes, and never resets past
# its own unpublished merge. -CheckOnly runs every precondition and changes nothing.
#
# Exit codes: 0 published (or -CheckOnly passed); 1 refused, nothing changed or
# the unpublished merge was undone; 3 merged locally but publication is unproven
# (re-run WeatherOneShotPush or investigate; the receipt names the merge commit).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [Parameter(Mandatory = $true)][ValidatePattern("^[0-9a-fA-F]{40}$")][string]$ExpectedTip,
    [string]$RepoRoot = "",
    [ValidateRange(30, 1800)][int]$PushTimeoutSeconds = 300,
    [ValidateRange(1, 60)][int]$PollSeconds = 5,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path.TrimEnd('\')
$ExpectedTip = $ExpectedTip.ToLowerInvariant()
$pushTaskName = "WeatherOneShotPush"
$markerPath = Join-Path $RepoRoot "data\alerts\quiet_window_merge_in_progress.json"
$receiptDir = Join-Path $RepoRoot "data\alerts\quiet_window_merge_reconciliations"
$docsOnlyPattern = '^docs/.+\.md$'

$receipt = [ordered]@{
    schema = "docs_light_path_receipt_v0.1"
    kind = "fail_forward_docs_only_landing"
    at = (Get-Date).ToString("o")
    repo_root = $RepoRoot
    branch = $Branch
    expected_tip = $ExpectedTip
    pre_merge_head = $null
    origin_master_before = $null
    remote_master_before = $null
    fetch_ok = $false
    roll_verdict = $null
    branch_diff_paths = @()
    unrelated_dirty_paths = @()
    merge_commit = $null
    merge_diff_paths = @()
    push = $null
    published_commit = $null
    publication_verified_by = $null
    stage = $null
    ok = $false
    detail = $null
    downstream_authority = "none"
}

function Note([string]$m) { Write-Host ("[docs-light-path] {0}" -f $m) }

# Native stderr is scoped to Continue so a routine git notice cannot terminate
# the script under the Stop preference; the exit code is what counts.
function Invoke-Git([string[]]$arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = @(& git -C $RepoRoot @arguments 2>&1 | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    return [pscustomobject]@{
        code = $code
        lines = @($out | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    }
}

function Get-GitLines([string[]]$arguments) {
    $r = Invoke-Git $arguments
    if ($r.code -ne 0) { throw ("git {0} failed (exit {1}): {2}" -f ($arguments -join ' '), $r.code, ($r.lines -join ' | ')) }
    return @($r.lines)
}

function Get-GitCommit([string]$ref) {
    $lines = @(Get-GitLines @("rev-parse", "--verify", "$ref^{commit}"))
    if ($lines.Count -ne 1) { throw "cannot resolve $ref to one commit" }
    return ([string]$lines[0]).ToLowerInvariant()
}

function Get-RemoteMaster {
    $r = Invoke-Git @("ls-remote", "origin", "refs/heads/master")
    if ($r.code -ne 0 -or $r.lines.Count -ne 1) { return $null }
    $sha = (([string]$r.lines[0]) -split '\s+')[0].ToLowerInvariant()
    if ($sha -notmatch '^[0-9a-f]{40}$') { return $null }
    return $sha
}

function Get-NonDocsPaths([string[]]$paths) {
    return @($paths | Where-Object { $_ -cnotmatch $docsOnlyPattern })
}

function Save-Receipt([string]$stage, [bool]$ok, [string]$detail) {
    $receipt.stage = $stage
    $receipt.ok = $ok
    $receipt.detail = $detail
    if (-not (Test-Path -LiteralPath $receiptDir -PathType Container)) {
        New-Item -ItemType Directory -Path $receiptDir -Force | Out-Null
    }
    $name = "docs-light-{0}-{1}.json" -f (Get-Date -Format "yyyyMMddTHHmmss"), $ExpectedTip.Substring(0, 12)
    $path = Join-Path $receiptDir $name
    $temp = Join-Path $receiptDir (".{0}.{1}.tmp" -f $name, [guid]::NewGuid().ToString("N"))
    $json = $receipt | ConvertTo-Json -Depth 6
    try {
        [IO.File]::WriteAllText($temp, $json, (New-Object System.Text.UTF8Encoding($false)))
        # File.Move is exclusive: an existing receipt is never overwritten.
        [IO.File]::Move($temp, $path)
    }
    finally { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
    $sha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    Note "receipt $path (sha256 $sha)"
}

function Refuse([string]$m) {
    Note "REFUSED: $m"
    exit 1
}

# ---- 1. repository state: on master, synchronized, nothing in flight ----
$symbolic = Invoke-Git @("symbolic-ref", "-q", "HEAD")
if ($symbolic.code -ne 0 -or $symbolic.lines.Count -ne 1 -or $symbolic.lines[0] -cne "refs/heads/master") {
    Refuse "HEAD is not the master branch"
}
if ((Invoke-Git @("rev-parse", "-q", "--verify", "MERGE_HEAD")).code -eq 0) { Refuse "a merge is in progress (MERGE_HEAD exists)" }
if (Test-Path -LiteralPath $markerPath) { Refuse "the quiet-merge marker exists: $markerPath" }
if ((Invoke-Git @("diff", "--cached", "--quiet")).code -ne 0) { Refuse "the index has staged changes" }
$dirty = @(Get-GitLines @("diff", "--name-only", "--no-renames"))
$dirtyDocs = @($dirty | Where-Object { $_ -like "docs/*" })
if ($dirtyDocs.Count -gt 0) { Refuse ("tracked docs files are modified: {0}" -f ($dirtyDocs -join ', ')) }
# Fleet-generated config drift may be present on production; the merge cannot
# touch it (docs-only) and it is left exactly as found.
$receipt.unrelated_dirty_paths = $dirty

$fetch = Invoke-Git @("fetch", "origin", "--prune")
$receipt.fetch_ok = ($fetch.code -eq 0)
if (-not $receipt.fetch_ok) { Note "WARNING: git fetch failed; relying on ls-remote and the local tracking ref" }
$preMerge = Get-GitCommit "HEAD"
$originMaster = Get-GitCommit "refs/remotes/origin/master"
$remoteMaster = Get-RemoteMaster
$receipt.pre_merge_head = $preMerge
$receipt.origin_master_before = $originMaster
$receipt.remote_master_before = $remoteMaster
if ($preMerge -ne $originMaster) { Refuse "HEAD $preMerge is not origin/master $originMaster" }
if ($remoteMaster -and $remoteMaster -ne $preMerge) { Refuse "HEAD $preMerge is not the remote master $remoteMaster" }
Note "HEAD == origin/master == $preMerge"

# ---- 2. the exact branch tip, not yet merged ----
try { $resolvedTip = Get-GitCommit $Branch }
catch { Refuse "branch is not resolvable: $Branch" }
if ($resolvedTip -ne $ExpectedTip) { Refuse "branch $Branch is at $resolvedTip, expected $ExpectedTip" }
if ((Invoke-Git @("merge-base", "--is-ancestor", $ExpectedTip, $preMerge)).code -eq 0) {
    Refuse "$ExpectedTip is already contained in master"
}

# ---- 3. docs-only diff ----
$branchPaths = @(Get-GitLines @("diff", "--no-renames", "--name-only", "$preMerge...$ExpectedTip"))
$receipt.branch_diff_paths = $branchPaths
if ($branchPaths.Count -eq 0) { Refuse "the branch changes nothing relative to master" }
$nonDocs = @(Get-NonDocsPaths $branchPaths)
if ($nonDocs.Count -gt 0) { Refuse ("diff is not docs/**/*.md only: {0}" -f ($nonDocs -join ', ')) }
Note ("diff is docs/**/*.md only ({0} files)" -f $branchPaths.Count)

# ---- 4. mechanical roll verdict (never derived by hand) ----
$verdictScript = Join-Path $RepoRoot "scripts\ops\roll_verdict.ps1"
if (-not (Test-Path -LiteralPath $verdictScript -PathType Leaf)) { Refuse "roll_verdict.ps1 is missing" }
$verdictJson = Join-Path ([IO.Path]::GetTempPath()) ("weather-docs-light-verdict-{0}.json" -f [guid]::NewGuid().ToString("N"))
try {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $verdictScript `
            -Branch $ExpectedTip -JsonOut $verdictJson 2>&1 | ForEach-Object { Note ("roll_verdict: {0}" -f $_) }
        $verdictExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    $verdictName = $null
    $verdictSha = $null
    if (Test-Path -LiteralPath $verdictJson -PathType Leaf) {
        $verdictSha = (Get-FileHash -LiteralPath $verdictJson -Algorithm SHA256).Hash.ToLowerInvariant()
        try { $verdictName = [string](Get-Content -LiteralPath $verdictJson -Raw | ConvertFrom-Json).verdict }
        catch { $verdictName = $null }
    }
}
finally { Remove-Item -LiteralPath $verdictJson -Force -ErrorAction SilentlyContinue }
$receipt.roll_verdict = [ordered]@{ exit_code = $verdictExit; verdict = $verdictName; json_sha256 = $verdictSha }
if ($verdictExit -ne 0) { Refuse "roll verdict exit $verdictExit ($verdictName) is not ROLL-FREE; use quiet_window_merge.ps1" }
Note "roll verdict ROLL-FREE"

# ---- 5. the publication task is present and idle ----
$tasks = @(Get-ScheduledTask -TaskName $pushTaskName -ErrorAction SilentlyContinue)
if ($tasks.Count -ne 1) { Refuse "expected exactly one $pushTaskName task, found $($tasks.Count)" }
if ([string]$tasks[0].State -ne "Ready") { Refuse "$pushTaskName is $($tasks[0].State), not Ready" }

if ($CheckOnly) {
    Note "CHECK PASS: $Branch @ $ExpectedTip may land on the light path (nothing changed)"
    exit 0
}

# ---- 6. local merge, then prove its own diff ----
$branchLabel = $Branch -replace '^origin/', ''
$merge = Invoke-Git @("merge", "--no-ff", "--no-edit", "-m",
    "Merge $branchLabel into master (fail-forward light path, docs only)", $ExpectedTip)
if ($merge.code -ne 0) {
    [void](Invoke-Git @("merge", "--abort"))
    $after = Get-GitCommit "HEAD"
    if ($after -ne $preMerge) { Save-Receipt "merge_failed" $false "merge failed and HEAD $after is not the pre-merge commit"; exit 3 }
    Save-Receipt "merge_failed" $false ("git merge failed and was aborted: {0}" -f ($merge.lines -join ' | '))
    exit 1
}
$mergeCommit = Get-GitCommit "HEAD"
$receipt.merge_commit = $mergeCommit
$mergePaths = @(Get-GitLines @("diff", "--no-renames", "--name-only", $preMerge, $mergeCommit))
$receipt.merge_diff_paths = $mergePaths
$mergeNonDocs = @(Get-NonDocsPaths $mergePaths)
if ($mergeNonDocs.Count -gt 0) {
    # Unpublished, so undoing our own merge rewrites nothing; --keep preserves
    # any unrelated working-tree drift.
    [void](Get-GitLines @("reset", "--keep", $preMerge))
    Save-Receipt "rolled_back" $false ("merge result touched non-docs paths: {0}" -f ($mergeNonDocs -join ', '))
    exit 1
}
Note "merged locally: $mergeCommit"

# ---- 7. publish through WeatherOneShotPush and wait for it to finish ----
$preRun = (Get-ScheduledTaskInfo -TaskName $pushTaskName).LastRunTime
$preRunUtc = if ($preRun) { ([datetime]$preRun).ToUniversalTime() } else { [datetime]::MinValue }
$push = [ordered]@{
    task = $pushTaskName
    pre_last_run_time = if ($preRun) { ([datetime]$preRun).ToString("o") } else { $null }
    last_run_time = $null
    last_task_result = $null
    completed = $false
}
$receipt.push = $push
Start-ScheduledTask -TaskName $pushTaskName
$deadline = (Get-Date).AddSeconds($PushTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds $PollSeconds
    $info = Get-ScheduledTaskInfo -TaskName $pushTaskName
    $state = [string](Get-ScheduledTask -TaskName $pushTaskName).State
    if ($info.LastRunTime -and ([datetime]$info.LastRunTime).ToUniversalTime() -gt $preRunUtc -and $state -eq "Ready") {
        $push.last_run_time = ([datetime]$info.LastRunTime).ToString("o")
        $push.last_task_result = [long]$info.LastTaskResult
        $push.completed = $true
        break
    }
}
if (-not $push.completed) {
    Save-Receipt "merged_unpushed" $false "$pushTaskName did not finish within $PushTimeoutSeconds s"
    exit 3
}
if ($push.last_task_result -ne 0) {
    Save-Receipt "merged_unpushed" $false "$pushTaskName finished with result $($push.last_task_result)"
    exit 3
}

# ---- 8. verify origin/master is the merge commit ----
$remoteAfter = Get-RemoteMaster
if ($remoteAfter) {
    $receipt.publication_verified_by = "ls_remote"
    $published = $remoteAfter
}
else {
    # The push updates the tracking ref only after the remote accepted it.
    $receipt.publication_verified_by = "tracking_ref"
    $published = Get-GitCommit "refs/remotes/origin/master"
}
$receipt.published_commit = $published
if ($published -ne $mergeCommit) {
    Save-Receipt "merged_unpushed" $false "origin/master is $published, not the merge commit $mergeCommit"
    exit 3
}
Save-Receipt "pushed" $true "published $mergeCommit (verified by $($receipt.publication_verified_by))"
Note "PUBLISHED: origin/master == $mergeCommit"
exit 0
