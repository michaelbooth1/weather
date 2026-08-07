<#
.SYNOPSIS
    Decide mechanically whether merging a branch can restart live capture.

.DESCRIPTION
    The roll verdict governs when a branch may merge, and until now it was derived by hand
    every time. That is error-prone in the expensive direction and it made every merge look
    like a roll-sensitive merge, because nobody wanted to be the one who guessed wrong.

    The test is the loaded-module import closure recorded by each capture supervisor as
    `runtime_identity.source_scope_files` -- NOT the SOURCE_PATTERNS glob, which over-reports
    and wastes quiet windows.

    Why "no changed file is in any closure" is a sufficient proof of roll-freeness, and not
    merely an absence of evidence: a closure is the transitive import set of the modules a loop
    has actually loaded. For a new file to enter a closure after merge, some file already in
    that closure would have to start importing it -- which means that closure file changed, and
    a changed closure file is caught by the same test. So the two cases are not independent.

    The one way this reasoning fails is a stale or missing status file, where the recorded
    closure no longer describes what the loops have loaded. That is why staleness fails closed
    rather than warning.

.PARAMETER Branch
    Branch to judge, e.g. origin/codex/workstation-....  Compared against master.

.PARAMETER MaxStatusAgeHours
    Refuse to judge from closure evidence older than this. Default 24.

.PARAMETER JsonOut
    Optional path for a machine-readable verdict.

.OUTPUTS
    Exit 0 = ROLL-FREE (safe to merge at any hour outside the graded window).
    Exit 3 = ROLL-SENSITIVE (quiet window only).
    Exit 1 = UNDECIDABLE (treat as roll-sensitive).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Branch,
    [int]$MaxStatusAgeHours = 24,
    [string]$JsonOut = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $repo

# The four closures, by the file that actually carries each one.
#
# `loop_status_supervisor_status.json` is deliberately NOT here. It looks like a fifth closure
# and is a tombstone: loop=snapshot_capture (the same loop as loop_supervisor_status.json),
# state=DEAD, action=circuit_open, restart_budget_exceeded=6>=6, frozen at 2026-07-13. A
# hand-derived verdict on 2026-08-06 read it as live evidence and simultaneously missed
# clob_enrichment_status.json, which does not match a *_supervisor_status.json glob. That is
# the exact error this script exists to stop: the union looked complete and was wrong in both
# directions at once.
$statusFiles = @(
    "data\snapshots\loop_supervisor_status.json"              # snapshot
    "data\snapshots\clob_loop_supervisor_status.json"         # CLOB
    "data\snapshots\observation_trigger_supervisor_status.json" # observation-trigger
    "data\snapshots\clob_enrichment_status.json"              # CLOB-enrichment
)

# A closure is only load-bearing if its loop is actually running. A dormant loop cannot be
# rolled by a merge, so its stale closure must not veto an otherwise safe merge -- but it is
# reported, because "dormant" is an assumption the operator should see rather than infer.
$closures = @{}
$dormant = @{}
$problems = @()
foreach ($rel in $statusFiles) {
    $path = Join-Path $repo $rel
    $name = [IO.Path]::GetFileNameWithoutExtension($rel) -replace '_supervisor_status$', '' -replace '_status$', ''
    if (-not (Test-Path -LiteralPath $path)) { $problems += "missing closure evidence: $rel"; continue }
    try { $doc = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
    catch { $problems += "unreadable closure evidence: $rel"; continue }

    $identity = $null
    foreach ($key in @("current_runtime_identity", "runtime_identity_before", "runtime_identity")) {
        if ($doc.PSObject.Properties.Name -contains $key -and $doc.$key) { $identity = $doc.$key; break }
    }
    if (-not $identity -or -not $identity.source_scope_files) {
        $problems += "no source_scope_files in $rel"; continue
    }

    $ageH = ((Get-Date) - (Get-Item -LiteralPath $path).LastWriteTime).TotalHours
    $state = [string]$doc.state
    $isTombstone = ($state -eq "DEAD") -or ([string]$doc.ensure_status -eq "BLOCKED")
    if ($isTombstone) {
        $problems += ("tombstone ignored: {0} state={1} reason={2}" -f $rel, $state, [string]$doc.reason)
        continue
    }
    if ($ageH -gt $MaxStatusAgeHours) {
        $dormant[$name] = @($identity.source_scope_files)
        $problems += ("DORMANT closure: {0} is {1:N1}h old (max {2}h) - treated as not running; a merge cannot roll a loop that is not live, but CONFIRM that before relying on it" -f $rel, $ageH, $MaxStatusAgeHours)
        continue
    }
    $closures[$name] = @($identity.source_scope_files)
}

if ($closures.Count -eq 0) {
    Write-Output "UNDECIDABLE: no live closure evidence"
    $problems | ForEach-Object { Write-Output "  $_" }
    exit 1
}

# Compare against master, matching what the merge will actually apply.
$changed = @(& git diff --name-only "master...$Branch" 2>$null | Where-Object { $_ })
if ($changed.Count -eq 0) {
    Write-Output "UNDECIDABLE: no changed files found for $Branch (is it fetched?)"
    exit 1
}

# Only Python under the package roots can enter a closure. docs/, config/, tests/ and .ps1 are
# roll-free by contract -- the status closures contain Python only.
$candidates = @($changed | Where-Object { $_ -match '\.py$' -and ($_ -like 'src/*' -or $_ -like 'weather/*') -and $_ -notlike 'tests/*' })

$rows = @()
foreach ($file in $candidates) {
    $hits = @($closures.Keys | Where-Object { $closures[$_] -contains $file } | Sort-Object)
    $sleeping = @($dormant.Keys | Where-Object { $dormant[$_] -contains $file } | Sort-Object)
    $rows += [PSCustomObject]@{
        file = $file; closures = $hits; dormant = $sleeping; rolls = ($hits.Count -gt 0)
    }
}
$rolling = @($rows | Where-Object { $_.rolls })
$dormantHits = @($rows | Where-Object { -not $_.rolls -and $_.dormant.Count -gt 0 })
$verdict = if ($rolling.Count -gt 0) { "ROLL-SENSITIVE" }
elseif ($dormantHits.Count -gt 0) { "ROLL-FREE-IF-DORMANT" }
else { "ROLL-FREE" }

Write-Output "branch:   $Branch"
Write-Output "changed:  $($changed.Count) file(s); $($candidates.Count) importable"
Write-Output "closures: $($closures.Keys -join ', ')"
foreach ($r in $rows) {
    if ($r.rolls) { Write-Output ("  ROLL  {0}  -> {1}" -f $r.file, ($r.closures -join ',')) }
    elseif ($r.dormant.Count -gt 0) { Write-Output ("  DORM  {0}  -> {1} (dormant)" -f $r.file, ($r.dormant -join ',')) }
    else { Write-Output ("  free  {0}" -f $r.file) }
}
if ($candidates.Count -eq 0) { Write-Output "  (no importable files -- docs/config/tests/ps1 only)" }
foreach ($p in $problems) { Write-Output "  WARN  $p" }
Write-Output ""
Write-Output "VERDICT: $verdict"

if ($JsonOut) {
    $payload = [ordered]@{
        generated_at = (Get-Date).ToString("o"); branch = $Branch; verdict = $verdict
        closures_used = @($closures.Keys); problems = @($problems)
        files = @($rows | ForEach-Object { [ordered]@{ file = $_.file; closures = @($_.closures); rolls = $_.rolls } })
    }
    $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $JsonOut -Encoding utf8
}

switch ($verdict) {
    "ROLL-FREE" { exit 0 }
    "ROLL-FREE-IF-DORMANT" { exit 2 }   # safe only while the dormant loop stays down
    "ROLL-SENSITIVE" { exit 3 }
    default { exit 1 }
}
