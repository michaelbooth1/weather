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
    Branch to judge, e.g. origin/codex/workstation-....

.PARAMETER Base
    The ref the merge will be applied to. Default `master`, which is auto-corrected to
    origin/master when local master is strictly behind it -- see the base resolution below.

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
    [string]$Base = "master",
    [int]$MaxStatusAgeHours = 24,
    [string]$JsonOut = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $repo

function Get-OptionalPropertyValue {
    param(
        [AllowNull()][object]$InputObject,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if ($null -ne $InputObject -and $InputObject.PSObject.Properties.Name -contains $Name) {
        return $InputObject.$Name
    }
    return $null
}

# The three streak-critical closures, the historical enrichment closure, and
# the auxiliary public execution-tape closure while that producer is armed or
# still running. An unarmed optional producer cannot roll and must not make all
# ordinary verdicts undecidable merely because it has never emitted a status.
#
# The former `loop_status_supervisor_status.json` was a frozen DEAD snapshot tombstone and was
# retired from the live namespace on 2026-08-14. A hand-derived verdict on 2026-08-06 read it as a
# fifth closure and simultaneously missed clob_enrichment_status.json, which does not match a
# `*_supervisor_status.json` glob. That is the exact error this explicit list prevents: the union
# looked complete and was wrong in both directions at once.
$statusFiles = @(
    "data\snapshots\loop_supervisor_status.json"              # snapshot
    "data\snapshots\clob_loop_supervisor_status.json"         # CLOB
    "data\snapshots\observation_trigger_supervisor_status.json" # observation-trigger
    "data\snapshots\clob_enrichment_status.json"              # CLOB-enrichment
)
$executionTask = Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor" -ErrorAction SilentlyContinue
$executionWorkerStatus = Join-Path $repo "data\snapshots\execution_tape_status.json"
$executionWriterLock = Join-Path $repo "data\snapshots\.execution_tape_status.json.writer.lock"
$executionActive = $false
if ($executionTask -and [string]$executionTask.State -ne "Disabled") {
    $executionActive = $true
}
elseif (Test-Path -LiteralPath $executionWriterLock) {
    # A disabled/missing task does not prove its detached child is gone.
    $executionActive = $true
}
elseif (Test-Path -LiteralPath $executionWorkerStatus) {
    try {
        $executionWorker = Get-Content -LiteralPath $executionWorkerStatus -Raw | ConvertFrom-Json
        $executionState = [string](Get-OptionalPropertyValue -InputObject $executionWorker -Name "state")
        $executionActive = $executionState -ne "STOPPED"
    }
    catch {
        # No task and no writer lock means an unreadable retained bounded-pilot
        # artifact cannot describe a currently rollable process.
        $executionActive = $false
    }
}
if ($executionActive) {
    $statusFiles += "data\snapshots\execution_tape_supervisor_status.json"
}

# A closure is only load-bearing if its loop is actually running. A dormant loop cannot be
# rolled by a merge, so its stale closure must not veto an otherwise safe merge -- but it is
# reported, because "dormant" is an assumption the operator should see rather than infer.
$closures = @{}
$dormant = @{}
$dormantAge = @{}
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
    $sourceScopeFiles = Get-OptionalPropertyValue -InputObject $identity -Name "source_scope_files"
    if (-not $identity -or -not $sourceScopeFiles) {
        $problems += "no source_scope_files in $rel"; continue
    }

    $ageH = ((Get-Date) - (Get-Item -LiteralPath $path).LastWriteTime).TotalHours
    $state = [string](Get-OptionalPropertyValue -InputObject $doc -Name "state")
    $ensureStatus = [string](Get-OptionalPropertyValue -InputObject $doc -Name "ensure_status")
    $reason = [string](Get-OptionalPropertyValue -InputObject $doc -Name "reason")
    $isTombstone = ($state -eq "DEAD") -or ($ensureStatus -eq "BLOCKED")
    if ($isTombstone) {
        $problems += ("tombstone ignored: {0} state={1} reason={2}" -f $rel, $state, $reason)
        continue
    }
    if ($ageH -gt $MaxStatusAgeHours) {
        $dormant[$name] = @($sourceScopeFiles)
        $dormantAge[$name] = $ageH
        continue
    }
    $closures[$name] = @($sourceScopeFiles)
}

# Report dormancy only once every closure has been read, so "is this dormant loop's scope already
# covered by a live one?" can be answered mechanically instead of asked of the operator.
#
# The old message said "CONFIRM that before relying on it", which is a manual step nobody performs
# reliably -- hand-derived roll verdicts on this project have been right by luck more than once. In
# the common case there is nothing to confirm: on 2026-08-06 the dormant clob-enrichment closure's
# 21 files were a STRICT SUBSET of the live CLOB loop's 23, so every file it covers is still
# reported every 60 seconds and its silence cannot hide a roll. Say that, rather than raise a
# warning that has no action attached to it.
$liveFiles = New-Object System.Collections.Generic.HashSet[string]([StringComparer]::OrdinalIgnoreCase)
foreach ($k in $closures.Keys) { foreach ($f in $closures[$k]) { [void]$liveFiles.Add($f) } }
foreach ($name in ($dormant.Keys | Sort-Object)) {
    $uncovered = @($dormant[$name] | Where-Object { -not $liveFiles.Contains($_) })
    if ($uncovered.Count -eq 0) {
        $problems += ("dormant closure {0} ({1:N1}h old) is SUBSUMED: all {2} of its files are also covered by a live closure, so its dormancy cannot affect this verdict" -f $name, $dormantAge[$name], @($dormant[$name]).Count)
    }
    else {
        $problems += ("DORMANT closure: {0} is {1:N1}h old (max {2}h) and is the only source for {3} file(s), e.g. {4} - a merge cannot roll a loop that is not live, but this verdict is only valid while it stays down" -f $name, $dormantAge[$name], $MaxStatusAgeHours, $uncovered.Count, (($uncovered | Select-Object -First 3) -join ", "))
    }
}

if ($closures.Count -eq 0) {
    Write-Output "UNDECIDABLE: no live closure evidence"
    $problems | ForEach-Object { Write-Output "  $_" }
    exit 1
}

# Compare against the ref the merge will ACTUALLY be applied to.
#
# This was a bare `master...$Branch`. Local master is routinely behind origin/master -- the merge
# drivers reconcile before calling this, but a hand-run verdict does not -- and a stale base
# silently inflates the changed set with everything that landed on origin in between. The -09-68a
# report classified 67 paths for a 3-file mission that way. It stayed ROLL-FREE by luck of file
# types, but a wrong changed set can just as easily attribute a roll to the wrong file, and the
# whole point of this script is that hand-derived verdicts are wrong in both directions at once.
#
# Correcting the base can only REMOVE files that are already on origin/master, and a file already
# on the base cannot be changed by merging the branch -- so it cannot hide a real roll. It is a
# correctness fix, not a relaxation. The automated path is unaffected: the drivers reconcile
# first, so `behind` is 0 there and the base stays exactly `master`.
$baseRef = $Base
$baseNote = $null
$originRef = "origin/master"
& git rev-parse --verify --quiet "$originRef^{commit}" | Out-Null
$haveOrigin = ($LASTEXITCODE -eq 0)
if ($haveOrigin -and $Base -eq "master") {
    $counts = @((& git rev-list --left-right --count "master...$originRef") -split "\s+" | Where-Object { $_ })
    if ($counts.Count -eq 2) {
        $ahead = [int]$counts[0]
        $behind = [int]$counts[1]
        if ($behind -gt 0 -and $ahead -eq 0) {
            $baseRef = $originRef
            $baseNote = "local master is $behind commit(s) behind $originRef and 0 ahead; judged against $originRef, which is the tree the merge lands on"
        }
        elseif ($behind -gt 0 -and $ahead -gt 0) {
            $baseNote = "DIVERGED: local master is $ahead ahead and $behind behind $originRef. Judged against local master. Reconcile before trusting this verdict."
        }
    }
}
$baseSha = (& git rev-parse --short "$baseRef")

$changed = @(& git diff --name-only "$baseRef...$Branch" 2>$null | Where-Object { $_ })
if ($changed.Count -eq 0) {
    Write-Output "UNDECIDABLE: no changed files found for $Branch against $baseRef ($baseSha) (is it fetched?)"
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
Write-Output "base:     $baseRef ($baseSha)"
if ($baseNote) { Write-Output "base:     $baseNote" }
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
        base_ref = $baseRef; base_sha = $baseSha; base_note = $baseNote
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
