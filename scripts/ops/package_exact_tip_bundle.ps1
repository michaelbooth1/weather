# Package a clean, fully tested branch as a committed-source-only Git bundle.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$WorktreeRoot,
    [Parameter(Mandatory = $true)][string]$BranchRef,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$ExpectedTip,
    [Parameter(Mandatory = $true)][string]$SuiteTaskName,
    [Parameter(Mandatory = $true)][string]$SuiteLog,
    [Parameter(Mandatory = $true)][datetime]$EarliestSuiteRun,
    [Parameter(Mandatory = $true)][string]$BundlePath,
    [Parameter(Mandatory = $true)][string]$ManifestPath
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$WorktreeRoot = (Resolve-Path -LiteralPath $WorktreeRoot).Path
$ExpectedTip = $ExpectedTip.ToLowerInvariant()
$BundlePath = [IO.Path]::GetFullPath($BundlePath)
$ManifestPath = [IO.Path]::GetFullPath($ManifestPath)
$partialBundlePath = "$BundlePath.partial"

$localNow = Get-Date
$localMinute = ($localNow.Hour * 60) + $localNow.Minute
if ($localMinute -ge (12 * 60) -or $localMinute -lt 30) {
    throw "bundle packaging is prohibited during the 12:00-00:30 protected host window"
}
foreach ($requiredPath in @($SuiteLog, (Split-Path -Parent $BundlePath), (Split-Path -Parent $ManifestPath))) {
    if (-not (Test-Path -LiteralPath $requiredPath)) { throw "required bundle path is missing: $requiredPath" }
}
foreach ($outputPath in @($BundlePath, $ManifestPath, $partialBundlePath)) {
    if (Test-Path -LiteralPath $outputPath) { throw "bundle output already exists: $outputPath" }
}

$task = Get-ScheduledTask -TaskName $SuiteTaskName -ErrorAction Stop
$taskInfo = Get-ScheduledTaskInfo -TaskName $SuiteTaskName -ErrorAction Stop
if ($task.State -eq "Running") { throw "exact-tip suite is still running" }
if ($taskInfo.LastRunTime -lt $EarliestSuiteRun -or $taskInfo.LastTaskResult -ne 0) {
    throw "exact-tip suite has not completed successfully after the required start time"
}

$logLines = @(Get-Content -LiteralPath $SuiteLog)
$startIndexes = @(for ($index = 0; $index -lt $logLines.Count; $index++) {
        if ($logLines[$index] -like "*=== bounded worktree suite starting ===*") { $index }
    })
if ($startIndexes.Count -eq 0) { throw "suite log contains no run boundary" }
$latestRun = @($logLines[$startIndexes[-1]..($logLines.Count - 1)])
if (-not ($latestRun | Where-Object { $_ -like "*expected_tip=$ExpectedTip*" })) {
    throw "latest suite log is not bound to the expected tip"
}
# An -InterpreterPath run qualifies an interpreter and is never merge evidence;
# its receipt line carries probe output, so refuse it before reading any verdict.
if ($latestRun | Where-Object { $_ -like "*interpreter_override *" }) {
    throw "latest suite log is an interpreter-override run, not merge evidence"
}
# Only the final non-empty line can be the verdict, with the same anchored
# pattern suite_gated_quiet_merge.ps1 uses, so no earlier line can satisfy it.
$lastLine = [string](@($latestRun | Where-Object { $_ })[-1])
$verdictMatch = [regex]::Match(
    $lastLine,
    "VERDICT: ALL CHUNKS PASSED \((?<passed>\d+)/(?<planned>\d+)\); exact tip eligible for separate reviewed merge$"
)
if (-not $verdictMatch.Success -or
    [int]$verdictMatch.Groups["passed"].Value -le 0 -or
    [int]$verdictMatch.Groups["passed"].Value -ne [int]$verdictMatch.Groups["planned"].Value) {
    throw "latest suite log has no full-suite PASS verdict"
}
if ($latestRun | Where-Object { $_ -like "*CHUNK(S) FAILED*" }) {
    throw "latest suite log contains a failed-chunk verdict"
}

$worktreeTip = (& git -C $WorktreeRoot rev-parse HEAD).Trim().ToLowerInvariant()
$branchTip = (& git -C $RepoRoot rev-parse $BranchRef).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $worktreeTip -ne $ExpectedTip -or $branchTip -ne $ExpectedTip) {
    throw "branch/worktree identity changed after the suite"
}
if (@(& git -C $WorktreeRoot status --porcelain).Count -ne 0) {
    throw "worktree changed after the suite"
}

try {
    & git -C $RepoRoot bundle create $partialBundlePath $BranchRef
    if ($LASTEXITCODE -ne 0) { throw "git bundle create failed" }
    & git -C $RepoRoot bundle verify $partialBundlePath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "git bundle verify failed" }
    Move-Item -LiteralPath $partialBundlePath -Destination $BundlePath

    $bundle = Get-Item -LiteralPath $BundlePath
    $manifest = [ordered]@{
        schema_version = "exact_tip_source_bundle_v1"
        status = "PASS"
        created_at_local = (Get-Date).ToString("o")
        branch_ref = $BranchRef
        exact_tip = $ExpectedTip
        bundle_file = $bundle.Name
        bundle_sha256 = (Get-FileHash -LiteralPath $BundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
        bundle_bytes = $bundle.Length
        committed_source_only = $true
        includes_working_tree_files = $false
        includes_ignored_data = $false
        includes_external_credentials = $false
        suite_task = $SuiteTaskName
        suite_last_run_local = $taskInfo.LastRunTime.ToString("o")
        suite_log_sha256 = (Get-FileHash -LiteralPath $SuiteLog -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8
    Write-Output "PASS: exact-tip source bundle and manifest created"
}
catch {
    # All output paths were proven absent before this run, so these can only be this run's
    # incomplete artifacts. Never remove a pre-existing operator artifact.
    foreach ($failedOutput in @($partialBundlePath, $BundlePath, $ManifestPath)) {
        if (Test-Path -LiteralPath $failedOutput) { Remove-Item -LiteralPath $failedOutput -Force }
    }
    throw
}
