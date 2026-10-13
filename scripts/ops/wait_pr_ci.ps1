# Wait for a pull request's GitHub checks on an exact head commit to finish.
#
#   .\scripts\ops\wait_pr_ci.ps1 -Pr <number|url|branch> [-ExpectedHead <full-sha>] [-Repo owner/name]
#       [-TimeoutSeconds 5400] [-PollSeconds 30] [-NoChecksGraceSeconds 600]
#
# "CI green" means every check on the PR's head commit concluded SUCCESS,
# NEUTRAL or SKIPPED. Pass -ExpectedHead whenever a decision depends on the
# result: a push that moves the head mid-wait would otherwise lend the new
# commit's verdict to the commit you reviewed (or the reverse). Read-only: it
# only calls `gh pr view`; it never re-runs, merges or comments.
#
# Exit codes: 0 all checks green on the expected head; 1 a check failed;
# 2 timed out with checks still pending; 3 no checks appeared within the grace
# period; 4 the head is not -ExpectedHead; 5 gh failed repeatedly.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Pr,
    [ValidatePattern("^([0-9a-fA-F]{40})?$")][string]$ExpectedHead = "",
    [string]$Repo = "",
    [ValidateRange(1, 86400)][int]$TimeoutSeconds = 5400,
    [ValidateRange(1, 600)][int]$PollSeconds = 30,
    [ValidateRange(0, 3600)][int]$NoChecksGraceSeconds = 600,
    [ValidateRange(1, 20)][int]$MaxGhFailures = 5,
    [string]$Gh = "gh"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ExpectedHead = $ExpectedHead.ToLowerInvariant()

$passing = @("SUCCESS", "NEUTRAL", "SKIPPED")
$failing = @("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "STALE")

function Note([string]$m) { Write-Host ("[wait-pr-ci] {0}" -f $m) }

function Read-Pr {
    $arguments = @("pr", "view", $Pr, "--json", "number,url,state,headRefOid,statusCheckRollup")
    if ($Repo) { $arguments += @("--repo", $Repo) }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = @(& $Gh @arguments 2>$null | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { return $null }
    try { return (($out -join "`n") | ConvertFrom-Json) }
    catch { return $null }
}

# One row per check: CheckRun reports status + conclusion, StatusContext a state.
function Get-CheckRows($rollup) {
    foreach ($item in @($rollup)) {
        if ($null -eq $item) { continue }
        $props = @($item.PSObject.Properties.Name)
        if ($props -contains "context") {
            $name = [string]$item.context
            $result = [string]$item.state
        }
        else {
            $name = [string]$item.name
            if ($props -contains "workflowName" -and $item.workflowName) { $name = "{0} / {1}" -f $item.workflowName, $name }
            $result = if ([string]$item.status -eq "COMPLETED") { [string]$item.conclusion } else { [string]$item.status }
        }
        $bucket = if ($passing -contains $result) { "pass" } elseif ($failing -contains $result) { "fail" } else { "pending" }
        [pscustomobject]@{ name = $name; result = $result; bucket = $bucket }
    }
}

function Show-Rows($rows) {
    foreach ($row in @($rows)) { Note ("  {0,-8} {1,-16} {2}" -f $row.bucket, $row.result, $row.name) }
}

$started = Get-Date
$deadline = $started.AddSeconds($TimeoutSeconds)
$ghFailures = 0
$lastSummary = ""
while ($true) {
    $view = Read-Pr
    if ($null -eq $view) {
        $ghFailures++
        Note "gh pr view failed ($ghFailures/$MaxGhFailures)"
        if ($ghFailures -ge $MaxGhFailures) { Note "RESULT: gh unavailable"; exit 5 }
    }
    else {
        $ghFailures = 0
        $head = ([string]$view.headRefOid).ToLowerInvariant()
        if ($ExpectedHead -and $head -ne $ExpectedHead) {
            Note "RESULT: PR $($view.url) head is $head, not the expected $ExpectedHead"
            exit 4
        }
        $rows = @(Get-CheckRows $view.statusCheckRollup)
        $fail = @($rows | Where-Object { $_.bucket -eq "fail" })
        $pending = @($rows | Where-Object { $_.bucket -eq "pending" })
        $summary = "{0} checks: {1} pass, {2} pending, {3} fail" -f $rows.Count, ($rows.Count - $pending.Count - $fail.Count), $pending.Count, $fail.Count
        if ($summary -ne $lastSummary) { Note "$($view.url) @ $($head.Substring(0, 12)): $summary"; $lastSummary = $summary }
        if ($fail.Count -gt 0) {
            Show-Rows $rows
            Note "RESULT: FAILED on $head"
            exit 1
        }
        if ($rows.Count -gt 0 -and $pending.Count -eq 0) {
            Show-Rows $rows
            Note "RESULT: GREEN on $head"
            exit 0
        }
        if ($rows.Count -eq 0 -and ((Get-Date) - $started).TotalSeconds -ge $NoChecksGraceSeconds) {
            Note "RESULT: no checks reported on $head after $NoChecksGraceSeconds s"
            exit 3
        }
    }
    if ((Get-Date).AddSeconds($PollSeconds) -gt $deadline) {
        if ($null -ne $view) { Show-Rows $rows }
        Note "RESULT: timed out after $TimeoutSeconds s with checks pending"
        exit 2
    }
    Start-Sleep -Seconds $PollSeconds
}
