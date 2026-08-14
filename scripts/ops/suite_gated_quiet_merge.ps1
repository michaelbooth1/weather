# Require an exact successful bounded-suite receipt before invoking the guarded
# quiet-window merge. This wrapper never runs tests, merges, or pushes on its own;
# every failure before the final invocation is a fail-closed refusal.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [Parameter(Mandatory = $true)][string]$ExpectedTip,
    [Parameter(Mandatory = $true)][string]$SuiteTaskName,
    [Parameter(Mandatory = $true)][string]$SuiteLogPath,
    [ValidateRange(60, 1800)][int]$SettleSeconds = 300
)

$ErrorActionPreference = "Stop"
$repo = "C:\Users\micha\Desktop\github\weather"
$ExpectedTip = $ExpectedTip.Trim().ToLowerInvariant()
$SuiteLogPath = [IO.Path]::GetFullPath($SuiteLogPath)

function Refuse-SuiteGate {
    param([Parameter(Mandatory = $true)][string]$Reason)

    Write-Output ("SUITE GATE REFUSED: {0}" -f $Reason)
    exit 1
}

if ($ExpectedTip -notmatch "^[0-9a-f]{40}$") {
    Refuse-SuiteGate "ExpectedTip must be a full 40-character hexadecimal commit SHA"
}

$suiteTask = Get-ScheduledTask -TaskName $SuiteTaskName -ErrorAction SilentlyContinue
if ($null -eq $suiteTask) { Refuse-SuiteGate "suite task not found: $SuiteTaskName" }
$suiteInfo = Get-ScheduledTaskInfo -TaskName $SuiteTaskName -ErrorAction SilentlyContinue
if ($null -eq $suiteInfo) { Refuse-SuiteGate "suite task info is unreadable: $SuiteTaskName" }
if ([string]$suiteTask.State -eq "Running") { Refuse-SuiteGate "suite task is still running" }
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
if ($actionArguments -notlike "*bounded_worktree_test_suite.ps1*") {
    Refuse-SuiteGate "suite task action is not the repository bounded-suite wrapper"
}
$tipPattern = "(?i)(?:^|\s)-ExpectedTip\s+" + [regex]::Escape($ExpectedTip) + "(?:\s|$)"
$branchPattern = "(?i)(?:^|\s)-BranchRef\s+" + [regex]::Escape($Branch) + "(?:\s|$)"
$logPattern = "(?i)(?:^|\s)-LogPath\s+`"?" + [regex]::Escape($SuiteLogPath) + "`"?(?:\s|$)"
if ($actionArguments -notmatch $tipPattern) { Refuse-SuiteGate "suite task action is not bound to ExpectedTip" }
if ($actionArguments -notmatch $branchPattern) { Refuse-SuiteGate "suite task action is not bound to Branch" }
if ($actionArguments -notmatch $logPattern) { Refuse-SuiteGate "suite task action is not bound to SuiteLogPath" }

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
if ($lastLine -notmatch "VERDICT: ALL CHUNKS PASSED \(\d+/\d+\); exact tip eligible for separate reviewed merge$") {
    Refuse-SuiteGate "suite log does not end in the exact full-suite pass verdict"
}

$mergeScript = Join-Path $repo "scripts\ops\quiet_window_merge.ps1"
if (-not (Test-Path -LiteralPath $mergeScript -PathType Leaf)) {
    Refuse-SuiteGate "quiet-window merge wrapper is missing"
}
Write-Output "SUITE GATE PASSED: invoking exact-tip quiet-window merge"
& $mergeScript -Branch $Branch -ExpectedTip $ExpectedTip -SettleSeconds $SettleSeconds
exit $LASTEXITCODE
