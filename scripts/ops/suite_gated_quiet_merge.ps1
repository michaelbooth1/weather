# Require an exact successful bounded-suite receipt before invoking the guarded
# quiet-window merge. The optional baseline, worktree, script hashes, and
# attempt-specific report make the first landing of a repaired merge wrapper
# immutable even though production cannot invoke code that has not landed yet.
# This wrapper never runs tests, merges, or pushes on its own; every failure
# before the final invocation is a fail-closed refusal.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [Parameter(Mandatory = $true)][string]$ExpectedTip,
    [Parameter(Mandatory = $true)][string]$SuiteTaskName,
    [Parameter(Mandatory = $true)][string]$SuiteLogPath,
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$WorktreeRoot = "",
    [string]$ExpectedBaseline = "",
    [string]$QuietMergeScriptPath = "",
    [string]$ExpectedGateSha256 = "",
    [string]$ExpectedQuietMergeSha256 = "",
    [string]$ExpectedSuiteTaskXmlSha256 = "",
    [string]$AttemptReportPath = "",
    [string]$ExpectedSuiteAtLocal = "",
    [ValidateRange(0, 120)][int]$SuiteRunningWaitMinutes = 0,
    [ValidateRange(60, 1800)][int]$SettleSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\', '/')
$ExpectedTip = $ExpectedTip.Trim().ToLowerInvariant()
$SuiteLogPath = [IO.Path]::GetFullPath($SuiteLogPath)
$ExpectedBaseline = $ExpectedBaseline.Trim().ToLowerInvariant()
$ExpectedGateSha256 = $ExpectedGateSha256.Trim().ToLowerInvariant()
$ExpectedQuietMergeSha256 = $ExpectedQuietMergeSha256.Trim().ToLowerInvariant()
$ExpectedSuiteTaskXmlSha256 = $ExpectedSuiteTaskXmlSha256.Trim().ToLowerInvariant()

function Refuse-SuiteGate {
    param([Parameter(Mandatory = $true)][string]$Reason)

    Write-Output ("SUITE GATE REFUSED: {0}" -f $Reason)
    exit 1
}

if ($ExpectedTip -notmatch "^[0-9a-f]{40}$") {
    Refuse-SuiteGate "ExpectedTip must be a full 40-character hexadecimal commit SHA"
}
if (-not (Test-Path -LiteralPath $repo -PathType Container)) {
    Refuse-SuiteGate "RepoRoot does not exist: $repo"
}
if ($ExpectedBaseline -and $ExpectedBaseline -notmatch "^[0-9a-f]{40}$") {
    Refuse-SuiteGate "ExpectedBaseline must be a full 40-character hexadecimal commit SHA"
}
foreach ($hashSpec in @(
    [pscustomobject]@{ Name = "ExpectedGateSha256"; Value = $ExpectedGateSha256 },
    [pscustomobject]@{ Name = "ExpectedQuietMergeSha256"; Value = $ExpectedQuietMergeSha256 },
    [pscustomobject]@{ Name = "ExpectedSuiteTaskXmlSha256"; Value = $ExpectedSuiteTaskXmlSha256 }
)) {
    if ($hashSpec.Value -and $hashSpec.Value -notmatch '^[0-9a-f]{64}$') {
        Refuse-SuiteGate "$($hashSpec.Name) must be a full SHA256"
    }
}
if ($ExpectedGateSha256) {
    if (-not $ExpectedQuietMergeSha256 -or -not $ExpectedSuiteTaskXmlSha256 -or
        -not $ExpectedBaseline -or -not $WorktreeRoot -or -not $ExpectedSuiteAtLocal) {
        Refuse-SuiteGate "hash-bound bootstrap mode requires the quiet-wrapper hash, suite-task XML hash, baseline, worktree, and exact suite trigger"
    }
    $actualGateSha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualGateSha256 -ne $ExpectedGateSha256) {
        Refuse-SuiteGate "suite-gate script changed after task freeze"
    }
}

if ($WorktreeRoot) {
    $WorktreeRoot = [IO.Path]::GetFullPath($WorktreeRoot).TrimEnd('\', '/')
    if (-not (Test-Path -LiteralPath $WorktreeRoot -PathType Container)) {
        Refuse-SuiteGate "frozen suite worktree is missing"
    }
    $worktreeTip = (& git -C $WorktreeRoot rev-parse HEAD).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $worktreeTip -ne $ExpectedTip) {
        Refuse-SuiteGate "frozen suite worktree no longer has ExpectedTip checked out"
    }
    $worktreeDirty = @(& git -C $WorktreeRoot status --porcelain | Where-Object { $_ })
    if ($LASTEXITCODE -ne 0 -or $worktreeDirty.Count -ne 0) {
        Refuse-SuiteGate "frozen suite worktree is no longer clean"
    }
}

if ($ExpectedBaseline) {
    $productionHead = (& git -C $repo rev-parse HEAD).Trim().ToLowerInvariant()
    $productionMaster = (& git -C $repo rev-parse master).Trim().ToLowerInvariant()
    $productionOrigin = (& git -C $repo rev-parse origin/master).Trim().ToLowerInvariant()
    $productionBranch = (& git -C $repo symbolic-ref --quiet --short HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $productionBranch -ne "master" -or
        $productionHead -ne $ExpectedBaseline -or
        $productionMaster -ne $ExpectedBaseline -or
        $productionOrigin -ne $ExpectedBaseline) {
        Refuse-SuiteGate "production baseline or checked-out master changed after suite freeze"
    }
}
$resolvedBranchTip = (& git -C $repo rev-parse ("{0}^{{commit}}" -f $Branch)).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $resolvedBranchTip -ne $ExpectedTip) {
    Refuse-SuiteGate "production branch ref no longer resolves to ExpectedTip"
}

$suiteTaskMatches = @(Get-ScheduledTask -TaskName $SuiteTaskName -ErrorAction SilentlyContinue)
if ($suiteTaskMatches.Count -eq 0) { Refuse-SuiteGate "suite task not found: $SuiteTaskName" }
if ($suiteTaskMatches.Count -ne 1) {
    Refuse-SuiteGate "suite task name must resolve exactly once"
}
$suiteTask = $suiteTaskMatches[0]
if ($ExpectedSuiteTaskXmlSha256) {
    try {
        $suiteTaskXml = [string](Export-ScheduledTask -TaskName $SuiteTaskName -TaskPath "\" -ErrorAction Stop)
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $actualSuiteTaskXmlSha256 = ([BitConverter]::ToString(
                    $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($suiteTaskXml))
                ) -replace '-', '').ToLowerInvariant()
        }
        finally { $sha.Dispose() }
    }
    catch { Refuse-SuiteGate "suite task XML could not be exported for exact binding" }
    if ($actualSuiteTaskXmlSha256 -ne $ExpectedSuiteTaskXmlSha256) {
        Refuse-SuiteGate "suite task definition changed after freeze"
    }
}
$suiteInfo = Get-ScheduledTaskInfo -TaskName $SuiteTaskName -ErrorAction SilentlyContinue
if ($null -eq $suiteInfo) { Refuse-SuiteGate "suite task info is unreadable: $SuiteTaskName" }
if ([string]$suiteTask.State -eq "Running") {
    if ($SuiteRunningWaitMinutes -le 0) {
        Refuse-SuiteGate "suite task is still running"
    }
    $suiteWaitDeadline = (Get-Date).AddMinutes($SuiteRunningWaitMinutes)
    Write-Output ("SUITE GATE WAIT: suite task is still running; waiting at most {0} minute(s)" -f $SuiteRunningWaitMinutes)
    while ([string]$suiteTask.State -eq "Running" -and (Get-Date) -lt $suiteWaitDeadline) {
        Start-Sleep -Seconds 15
        $suiteTaskMatches = @(Get-ScheduledTask -TaskName $SuiteTaskName -ErrorAction SilentlyContinue)
        if ($suiteTaskMatches.Count -ne 1) {
            Refuse-SuiteGate "suite task identity changed while waiting"
        }
        $suiteTask = $suiteTaskMatches[0]
        $suiteInfo = Get-ScheduledTaskInfo -TaskName $SuiteTaskName -ErrorAction SilentlyContinue
        if ($null -eq $suiteInfo) {
            Refuse-SuiteGate "suite task info became unreadable while waiting"
        }
    }
    if ([string]$suiteTask.State -eq "Running") {
        Refuse-SuiteGate "suite task remained running past the bounded wait"
    }
    if ($ExpectedSuiteTaskXmlSha256) {
        try {
            $postWaitSuiteTaskXml = [string](Export-ScheduledTask -TaskName $SuiteTaskName -TaskPath "\" -ErrorAction Stop)
            $postWaitSha = [Security.Cryptography.SHA256]::Create()
            try {
                $postWaitSuiteTaskXmlSha256 = ([BitConverter]::ToString(
                        $postWaitSha.ComputeHash([Text.Encoding]::UTF8.GetBytes($postWaitSuiteTaskXml))
                    ) -replace '-', '').ToLowerInvariant()
            }
            finally { $postWaitSha.Dispose() }
        }
        catch { Refuse-SuiteGate "suite task XML could not be re-exported after waiting" }
        if ($postWaitSuiteTaskXmlSha256 -ne $ExpectedSuiteTaskXmlSha256) {
            Refuse-SuiteGate "suite task definition changed while waiting"
        }
    }
}
if ([datetime]$suiteInfo.LastRunTime -lt (Get-Date).Date) {
    Refuse-SuiteGate "suite task did not run on the current local day"
}
if ([int]$suiteInfo.LastTaskResult -ne 0) {
    Refuse-SuiteGate ("suite task result is 0x{0:X}, not success" -f [int]$suiteInfo.LastTaskResult)
}

$actions = @($suiteTask.Actions)
if ($actions.Count -ne 1) { Refuse-SuiteGate "suite task must have exactly one action" }
$action = $actions[0]
$actionArguments = [string]$action.Arguments
$expectedPowerShell = [IO.Path]::GetFullPath((Join-Path $PSHOME "powershell.exe"))
if (-not [string]::Equals(
        [IO.Path]::GetFullPath([string]$action.Execute),
        $expectedPowerShell,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or
    -not [string]::Equals(
        [IO.Path]::GetFullPath([string]$action.WorkingDirectory).TrimEnd('\', '/'),
        $repo,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    Refuse-SuiteGate "suite task executable or working directory changed after freeze"
}
if ($actionArguments -notlike "*bounded_worktree_test_suite.ps1*") {
    Refuse-SuiteGate "suite task action is not the repository bounded-suite wrapper"
}
$tipPattern = "(?i)(?:^|\s)-ExpectedTip\s+" + [regex]::Escape($ExpectedTip) + "(?:\s|$)"
$branchPattern = "(?i)(?:^|\s)-BranchRef\s+" + [regex]::Escape($Branch) + "(?:\s|$)"
$logPattern = "(?i)(?:^|\s)-LogPath\s+`"?" + [regex]::Escape($SuiteLogPath) + "`"?(?:\s|$)"
$worktreePattern = if ($WorktreeRoot) {
    "(?i)(?:^|\s)-WorktreeRoot\s+`"?" + [regex]::Escape($WorktreeRoot) + "`"?(?:\s|$)"
} else { $null }
if ($actionArguments -notmatch $tipPattern) { Refuse-SuiteGate "suite task action is not bound to ExpectedTip" }
if ($actionArguments -notmatch $branchPattern) { Refuse-SuiteGate "suite task action is not bound to Branch" }
if ($actionArguments -notmatch $logPattern) { Refuse-SuiteGate "suite task action is not bound to SuiteLogPath" }
if ($worktreePattern -and $actionArguments -notmatch $worktreePattern) {
    Refuse-SuiteGate "suite task action is not bound to the frozen WorktreeRoot"
}
if ($ExpectedGateSha256) {
    if (-not [string]::Equals(
            [string]$suiteTask.Principal.UserId,
            [string]$env:USERNAME,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$suiteTask.Principal.LogonType -ne "S4U" -or
        [string]$suiteTask.Principal.RunLevel -ne "Limited" -or
        -not [bool]$suiteTask.Settings.WakeToRun -or
        [bool]$suiteTask.Settings.StartWhenAvailable -or
        [string]$suiteTask.Settings.MultipleInstances -ne "IgnoreNew" -or
        [string]$suiteTask.Settings.ExecutionTimeLimit -ne "PT8H" -or
        [bool]$suiteTask.Settings.DisallowStartIfOnBatteries -or
        [bool]$suiteTask.Settings.StopIfGoingOnBatteries -or
        [bool]$suiteTask.Settings.RunOnlyIfIdle -or
        [bool]$suiteTask.Settings.RunOnlyIfNetworkAvailable) {
        Refuse-SuiteGate "suite task principal or fail-closed settings changed after freeze"
    }
    if ($ExpectedSuiteAtLocal) {
        try {
            $expectedSuiteAt = [datetime]::ParseExact(
                $ExpectedSuiteAtLocal,
                "yyyy-MM-dd'T'HH:mm:ss",
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::None
            )
            $suiteTriggers = @($suiteTask.Triggers)
            $actualSuiteAt = [datetimeoffset]::Parse(
                [string]$suiteTriggers[0].StartBoundary,
                [Globalization.CultureInfo]::InvariantCulture
            ).DateTime
        }
        catch { Refuse-SuiteGate "suite task trigger boundary is unreadable" }
        if ($suiteTriggers.Count -ne 1 -or
            [string]$suiteTriggers[0].CimClass.CimClassName -ne "MSFT_TaskTimeTrigger" -or
            -not [bool]$suiteTriggers[0].Enabled -or
            $actualSuiteAt -ne $expectedSuiteAt -or
            -not [string]::IsNullOrEmpty([string]$suiteTriggers[0].EndBoundary) -or
            -not [string]::IsNullOrEmpty([string]$suiteTriggers[0].Repetition.Interval) -or
            -not [string]::IsNullOrEmpty([string]$suiteTriggers[0].Repetition.Duration)) {
            Refuse-SuiteGate "suite task trigger changed after freeze"
        }
    }
}

if ($WorktreeRoot) {
    # The suite wrapper proves this at its own terminal verdict. Re-prove it
    # after any bounded Scheduler wait and immediately before consuming that
    # verdict, so later edits cannot borrow a PASS earned by different bytes.
    $postWaitWorktreeTip = (& git -C $WorktreeRoot rev-parse HEAD).Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $postWaitWorktreeTip -ne $ExpectedTip) {
        Refuse-SuiteGate "frozen suite worktree changed after the suite run"
    }
    $postWaitWorktreeDirty = @(& git -C $WorktreeRoot status --porcelain | Where-Object { $_ })
    if ($LASTEXITCODE -ne 0 -or $postWaitWorktreeDirty.Count -ne 0) {
        Refuse-SuiteGate "frozen suite worktree became dirty after the suite run"
    }
}

if (-not (Test-Path -LiteralPath $SuiteLogPath -PathType Leaf)) {
    Refuse-SuiteGate "suite log does not exist"
}
$logItem = Get-Item -LiteralPath $SuiteLogPath
if ($logItem.LastWriteTime -lt [datetime]$suiteInfo.LastRunTime) {
    Refuse-SuiteGate "suite log predates the task run"
}
$lines = @(Get-Content -LiteralPath $SuiteLogPath)
$runStart = -1
for ($index = 0; $index -lt $lines.Count; $index++) {
    if ([string]$lines[$index] -like "*=== bounded worktree suite starting ===") {
        $runStart = $index
    }
}
if ($runStart -lt 0) { Refuse-SuiteGate "suite log has no run boundary" }
$runLines = @($lines[$runStart..($lines.Count - 1)])
$runStartedAt = $null
if ([string]$runLines[0] -match "^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})") {
    $runStartedAt = [datetime]::ParseExact($Matches[1], "yyyy-MM-dd HH:mm:ss", $null)
}
if ($null -eq $runStartedAt -or [math]::Abs(($runStartedAt - [datetime]$suiteInfo.LastRunTime).TotalMinutes) -gt 5) {
    Refuse-SuiteGate "suite log run boundary does not correlate to LastRunTime"
}

$identityPattern = "branch=" + [regex]::Escape($Branch) + "\s+expected_tip=" + [regex]::Escape($ExpectedTip)
if (-not ($runLines -match $identityPattern)) {
    Refuse-SuiteGate "suite log identity does not bind Branch and ExpectedTip"
}
if ($runLines -match "CHUNK\(S\) FAILED|SMOKE PASSED|PREFLIGHT PASSED") {
    Refuse-SuiteGate "suite log contains a non-full or failed verdict"
}
$lastLine = [string](@($runLines | Where-Object { $_ })[-1])
$verdictMatch = [regex]::Match(
    $lastLine,
    "VERDICT: ALL CHUNKS PASSED \((?<passed>\d+)/(?<planned>\d+)\); exact tip eligible for separate reviewed merge$"
)
if (-not $verdictMatch.Success -or
    [int]$verdictMatch.Groups["passed"].Value -le 0 -or
    [int]$verdictMatch.Groups["passed"].Value -ne [int]$verdictMatch.Groups["planned"].Value) {
    Refuse-SuiteGate "suite log does not end in the exact full-suite pass verdict"
}

$mergeScript = if ($QuietMergeScriptPath) {
    [IO.Path]::GetFullPath($QuietMergeScriptPath)
} else {
    Join-Path $repo "scripts\ops\quiet_window_merge.ps1"
}
if (-not (Test-Path -LiteralPath $mergeScript -PathType Leaf)) {
    Refuse-SuiteGate "quiet-window merge wrapper is missing"
}
if ($ExpectedQuietMergeSha256) {
    $actualQuietMergeSha256 = (Get-FileHash -LiteralPath $mergeScript -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualQuietMergeSha256 -ne $ExpectedQuietMergeSha256) {
        Refuse-SuiteGate "quiet-window merge wrapper changed after task freeze"
    }
}
if ($AttemptReportPath) {
    $AttemptReportPath = [IO.Path]::GetFullPath($AttemptReportPath)
    if (Test-Path -LiteralPath $AttemptReportPath) {
        Refuse-SuiteGate "attempt-specific quiet-merge report already exists"
    }
}
Write-Output "SUITE GATE PASSED: invoking exact-tip quiet-window merge"
$mergeArgs = @{
    Branch = $Branch
    ExpectedTip = $ExpectedTip
    RepoRoot = $repo
    SettleSeconds = $SettleSeconds
}
if ($ExpectedBaseline) { $mergeArgs.ExpectedBaseline = $ExpectedBaseline }
if ($AttemptReportPath) { $mergeArgs.AttemptReportPath = $AttemptReportPath }
if ($ExpectedQuietMergeSha256) { $mergeArgs.ExpectedSelfSha256 = $ExpectedQuietMergeSha256 }
# The guarded merge is a standalone operational program, not a strict-mode
# child of this validator.  Inheriting this gate's StrictMode caused sparse but
# valid retained status records to terminate the child before it could write a
# refusal report.  The child owns its own fail-closed checks and error policy.
Set-StrictMode -Off
& $mergeScript @mergeArgs
exit $LASTEXITCODE
