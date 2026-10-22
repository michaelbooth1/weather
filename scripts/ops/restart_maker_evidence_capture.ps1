<#
.SYNOPSIS
Explicit 88a-R restart of the passive maker evidence recorder (data layer v2 Q11).

.DESCRIPTION
Owner Q11 (2026-10-15): new capture families adopt code by explicit restart, with running-vs-disk
code identity shown in status. This is that restart for the core 88a recorder
(WeatherMakerEvidenceCapture, data\maker_evidence). Report-only unless -Apply.

It stops the running recorder process and lets the task's existing frozen PT5M trigger start the
new one. It never starts, registers, re-registers or disables a scheduled task (never run
register_maker_evidence_capture.ps1: it writes PT1M over the live PT5M), and never touches a
capture family recorder or any graded capture loop.

Refuses unless all hold: local time 00:30-01:00; data\maker_evidence\status.json is readable and
names a live pid whose command line is the core recorder (no --family, no --dry-run); no raw
update window is active (an LFC session's 30-minute windows). After -Apply it polls up to
-WaitSeconds for a new pid in CAPTURING state, then prints a JSON receipt with the capture gap and
the running-vs-disk identity (Get-MakerEvidenceCodeIdentity, loaded from status.ps1 so there is
one copy). Record the gap in the panel notes. Exit 0 only on CURRENT identity after the restart.

Runbook: docs/operations/passive-maker-evidence-capture.md "Explicit restart (88a-R)".
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [ValidateRange(60, 900)][int]$WaitSeconds = 420,
    [string]$RepoRoot = ""
)
$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path }

function Read-MakerStatus([string]$Path) {
    $item = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($item.Length -gt 262144) { throw "status exceeds byte bound" }
    return (Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop)
}

function Import-CodeIdentityFunction([string]$StatusScript) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($StatusScript, [ref]$tokens, [ref]$errors)
    if (@($errors).Count -ne 0) { throw "status.ps1 does not parse" }
    $definition = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq "Get-MakerEvidenceCodeIdentity"
    }, $true))
    if ($definition.Count -ne 1) { throw "status.ps1 lacks a unique Get-MakerEvidenceCodeIdentity" }
    return $definition[0].Extent.Text
}

$statusPath = Join-Path $RepoRoot "data\maker_evidence\status.json"
. ([scriptblock]::Create((Import-CodeIdentityFunction (Join-Path $RepoRoot "scripts\ops\status.ps1"))))
$refusals = @()
$now = Get-Date
$minutes = $now.Hour * 60 + $now.Minute
if ($minutes -lt 30 -or $minutes -ge 60) { $refusals += "outside the 00:30-01:00 88a-R window (local $($now.ToString('HH:mm')))" }
$before = $null
try { $before = Read-MakerStatus $statusPath } catch { $refusals += "status unreadable: $($_.Exception.Message)" }
$process = $null
if ($before) {
    $process = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f [int]$before.pid) -ErrorAction SilentlyContinue
    if (-not $process) { $refusals += "status pid $($before.pid) is not running" }
    elseif ([string]$process.CommandLine -notmatch 'weather\.market\.maker_evidence_capture' -or
            [string]$process.CommandLine -match '--family|--dry-run') {
        $refusals += "pid $($before.pid) is not the core 88a recorder"
    }
    if (@($before.PSObject.Properties.Name) -contains "update_window_end_utc" -and $before.update_window_end_utc) {
        $refusals += "a raw update window is active until $($before.update_window_end_utc)"
    }
}
$identityBefore = if ($before) {
    $source = if (@($before.PSObject.Properties.Name) -contains "source_sha256") { $before.source_sha256 } else { $null }
    Get-MakerEvidenceCodeIdentity -RepoRoot $RepoRoot -SourceSha256 $source
} else { $null }

$receipt = [ordered]@{
    action = "88a-R explicit restart"; applied = $false; checked_at_local = $now.ToString("o")
    pid_before = $(if ($before) { $before.pid } else { $null })
    identity_before = $identityBefore; refusals = @($refusals)
}
if ($refusals.Count -gt 0 -or -not $Apply) {
    $receipt.result = $(if ($refusals.Count -gt 0) { "REFUSED" } else { "REPORT_ONLY" })
    $receipt | ConvertTo-Json -Depth 6
    exit $(if ($refusals.Count -gt 0) { 2 } else { 0 })
}

$stoppedAt = (Get-Date).ToUniversalTime()
Stop-Process -Id ([int]$before.pid) -ErrorAction Stop
$after = $null
$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 10
    try { $candidate = Read-MakerStatus $statusPath } catch { continue }
    if ([int]$candidate.pid -ne [int]$before.pid -and [string]$candidate.state -eq "CAPTURING") { $after = $candidate; break }
}
$receipt.applied = $true
$receipt.stopped_at_utc = $stoppedAt.ToString("o")
if (-not $after) {
    $receipt.result = "NOT_RESTARTED_WITHIN_WAIT"
    $receipt | ConvertTo-Json -Depth 6
    exit 3
}
$receipt.pid_after = $after.pid
$receipt.started_at_utc = $after.started_at_utc
$receipt.gap_seconds = [int](([DateTimeOffset]::Parse([string]$after.started_at_utc).UtcDateTime - $stoppedAt).TotalSeconds)
$receipt.identity_after = Get-MakerEvidenceCodeIdentity -RepoRoot $RepoRoot -SourceSha256 $after.source_sha256
$receipt.result = $(if ($receipt.identity_after.state -eq "CURRENT") { "RESTARTED_CURRENT" } else { "RESTARTED_NOT_CURRENT" })
$receipt | ConvertTo-Json -Depth 6
exit $(if ($receipt.result -eq "RESTARTED_CURRENT") { 0 } else { 4 })
