"""Failing-first DST execution tests for the Windows ops scripts (DST audit 2026-10-07).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md findings DST-H3 (quiet-window merge heartbeat
advancement compared on the wall clock) and DST-H4 (bounded suite capture-worker heartbeat age computed
on the wall clock). DST-C1 (daily Scheduler triggers stored with a fixed UTC offset) is fixed by the
local-trigger helper and guarded by tests/operations/test_scheduled_task_local_daily_triggers.py; its
xfail here was retired with that fix. DST-H4 is fixed by PR #273 (heartbeat ages are differences of
UTC instants); its xfail was retired with that fix and its probe now passes the test's own instant
through Get-HealthyCaptureWorkerCount -Now. DST-H3 is fixed by comparing the readoption heartbeats
as UTC instants (Test-QuietMergeHeartbeatAdvanced over the status.ps1 timestamp helpers); its xfail
was retired with that fix and its probe now evaluates both real readoption conditions (capture
workers and execution tape) across the fall-back hour and on ordinary days. DST-M5 (reconciliation
push containment deadline) and DST-M6 (rollback and recovery waits in quiet_window_merge.ps1,
suite_gated_quiet_merge.ps1 and adopt_execution_tape_after_merge.ps1) are fixed by holding each
deadline as a [datetimeoffset] instant; their tests were written failing-first against master and
pass with that fix. DST-M4 (the S4U memory guard compared process CreationDate values on the
wall clock) landed with its fix and this file's
test_memory_guard_creation_ages_and_order_are_instants_across_dst, which failed first on master.

Every test executes the repository's own PowerShell (a statement or function
extracted from the script by the PowerShell parser) in a real Windows
PowerShell child whose local time zone is pinned to Eastern, so the result
does not depend on the runner's zone. The clock-dependent cases use fixed
instants inside the 2026-11-01 fall-back hour (and the 2027-03-14 spring-forward
gap). A test added for a new defect is ``xfail(strict=True, raises=AssertionError)``
while the defect is on master: a broken harness raises ``RuntimeError`` and fails
loudly instead of counting as the expected failure. The fixing change must remove
the marker. Every finding listed above is now fixed, so no marker remains.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
POWERSHELL = ("powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command")

WINDOWS_POWERSHELL = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="requires Windows PowerShell",
)

# Pins TimeZoneInfo.Local (and so every [datetime] conversion) to the capture
# host's zone for this child process only.
PIN_EASTERN = r"""
$ErrorActionPreference = 'Stop'
$staticFlags = [Reflection.BindingFlags]'NonPublic,Static'
$instanceFlags = [Reflection.BindingFlags]'NonPublic,Instance'
$cache = [TimeZoneInfo].GetField('s_cachedData', $staticFlags).GetValue($null)
$cache.GetType().GetField('m_localTimeZone', $instanceFlags).SetValue(
    $cache, [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time'))
$oneYear = $cache.GetType().GetField('m_oneYearLocalFromUtc', $instanceFlags)
if ($oneYear) { $oneYear.SetValue($cache, $null) }
if ([TimeZoneInfo]::Local.Id -ne 'Eastern Standard Time') { throw 'time zone pin failed' }
$tokens = $null
$errors = $null
"""


def _run(script: str, env_extra: dict[str, str]) -> dict:
    env = os.environ.copy()
    env.update(env_extra)
    result = subprocess.run(
        [*POWERSHELL, PIN_EASTERN + script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell harness failed: {result.stderr.strip() or result.stdout.strip()}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("PowerShell harness printed nothing")
    return json.loads(lines[-1])


MERGE_HEARTBEAT_PROBE = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'quiet_window_merge.ps1 does not parse' }
# Load whichever timestamp helpers the script defines, so the real call-site
# conditions below evaluate exactly as they would in the merge.
foreach ($functionAst in @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in @('ConvertTo-StatusInstant', 'ConvertTo-StatusUtcInstant', 'Test-QuietMergeHeartbeatAdvanced')
}, $true))) { Invoke-Expression $functionAst.Extent.Text }
# The two readoption checks: capture workers and the execution tape. Each is the
# condition of the one if-statement that compares that pair's heartbeats.
$sites = [ordered]@{
    worker = @('$afterWorker.last_heartbeat', '$beforeWorker.last_heartbeat')
    execution_tape = @('$executionAfter.last_heartbeat', '$executionBefore.last_heartbeat')
}
$conditions = [ordered]@{}
foreach ($site in $sites.Keys) {
    $pair = $sites[$site]
    $found = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.IfStatementAst] -and
            $node.Clauses[0].Item1.Extent.Text.Contains($pair[0]) -and
            $node.Clauses[0].Item1.Extent.Text.Contains($pair[1])
    }, $true))
    if ($found.Count -ne 1) { throw "expected one $site heartbeat comparison, found $($found.Count)" }
    $conditions[$site] = $found[0].Clauses[0].Item1.Extent.Text
}
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DST_CASES)) | ConvertFrom-Json
$results = [ordered]@{}
foreach ($site in $conditions.Keys) {
    $results[$site] = [ordered]@{}
    foreach ($case in @($cases)) {
        $beforeWorker = [pscustomobject]@{ last_heartbeat = $case.before }
        $afterWorker = [pscustomobject]@{ last_heartbeat = $case.after }
        $executionBefore = $beforeWorker
        $executionAfter = $afterWorker
        try {
            $verdict = if ([bool](Invoke-Expression $conditions[$site])) { 'not_advanced' } else { 'advanced' }
        }
        catch { $verdict = 'error' }
        $results[$site][[string]$case.name] = $verdict
    }
}
$results | ConvertTo-Json -Compress
"""

# Toronto falls back at 2026-11-01 06:00Z: 01:59:59 EDT (-04:00) is followed by
# 01:00:00 EST (-05:00). Supervisor heartbeats are written with their offset
# (datetime.isoformat()), so the quiet window sees both 01:xx readings.
MERGE_HEARTBEAT_CASES = [
    # 05:58:40Z -> 06:03:12Z: 4.5 real minutes later, but 01:58 -> 01:03 on the wall.
    ("fall_back_advanced", "2026-11-01T01:58:40.250000-04:00", "2026-11-01T01:03:12.500000-05:00", "advanced"),
    # 06:03:12Z -> 05:58:40Z: really earlier, but 01:03 -> 01:58 on the wall.
    ("fall_back_went_backwards", "2026-11-01T01:03:12.500000-05:00", "2026-11-01T01:58:40.250000-04:00",
     "not_advanced"),
    # The same instant written in two offsets is not an advance.
    ("fall_back_same_instant", "2026-11-01T06:00:30+00:00", "2026-11-01T01:00:30-05:00", "not_advanced"),
    # Outside DST the verdicts are what the wall-clock comparison always gave.
    ("ordinary_advanced", "2026-10-20T01:30:00-04:00", "2026-10-20T01:31:00-04:00", "advanced"),
    ("ordinary_unchanged", "2026-10-20T01:30:00-04:00", "2026-10-20T01:30:00-04:00", "not_advanced"),
    ("ordinary_backwards", "2026-10-20T01:31:00-04:00", "2026-10-20T01:30:00-04:00", "not_advanced"),
    ("offsetless_advanced", "2026-10-20T01:30:00", "2026-10-20T01:31:00", "advanced"),
    ("offsetless_unchanged", "2026-10-20T01:30:00", "2026-10-20T01:30:00", "not_advanced"),
    # Missing or unparseable stamps fail the comparison (the merge rolls back).
    ("unparseable_after", "2026-10-20T01:30:00-04:00", "not-a-time", "error"),
    ("missing_after", "2026-10-20T01:30:00-04:00", None, "error"),
    ("missing_before", None, "2026-10-20T01:30:00-04:00", "error"),
]


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_quiet_merge_heartbeat_advancement_survives_fall_back():
    for name, before, after, expected in MERGE_HEARTBEAT_CASES:
        try:
            real = datetime.fromisoformat(after) > datetime.fromisoformat(before)
        except (TypeError, ValueError):
            continue
        if real != (expected == "advanced"):
            raise RuntimeError(f"fixture {name} does not match its real-time order")
    cases = [{"name": n, "before": b, "after": a} for n, b, a, _ in MERGE_HEARTBEAT_CASES]

    payload = _run(
        MERGE_HEARTBEAT_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "quiet_window_merge.ps1"),
            "DST_CASES": base64.b64encode(json.dumps(cases).encode("utf-8")).decode("ascii"),
        },
    )

    # Both readoption checks (capture workers and the execution tape) judge the
    # heartbeats as instants. The defect cast both to local [datetime], read the
    # readopted worker's later heartbeat as 55 minutes older, and rolled back.
    expected = {name: verdict for name, _, _, verdict in MERGE_HEARTBEAT_CASES}
    assert payload == {"worker": expected, "execution_tape": expected}, payload


HEALTHY_WORKERS_PROBE = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'bounded_worktree_test_suite.ps1 does not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-HealthyCaptureWorkerCount'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing Get-HealthyCaptureWorkerCount' }
$helpers = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in @('ConvertTo-StatusInstant', 'ConvertTo-StatusUtcInstant')
}, $true))
if ($helpers.Count -ne 2) { throw "expected the two timestamp helpers, found $($helpers.Count)" }
foreach ($helper in $helpers) { Invoke-Expression $helper.Extent.Text }
$RepoRoot = $env:DST_REPO_ROOT
$snapshotRoot = Join-Path $RepoRoot 'data\snapshots'
$beats = $env:DST_HEARTBEATS | ConvertFrom-Json
foreach ($name in @('loop_status.json', 'clob_loop_status.json', 'observation_trigger_status.json')) {
    [pscustomobject]@{ pid = $PID; last_heartbeat = [string]$beats.$name } |
        ConvertTo-Json -Compress |
        Set-Content -LiteralPath (Join-Path $snapshotRoot $name) -Encoding UTF8
    [pscustomobject]@{ pid = $PID } | ConvertTo-Json -Compress |
        Set-Content -LiteralPath (Join-Path $snapshotRoot ".$name.writer.lock") -Encoding UTF8
}
# The pinned clock: the test's own instant goes in through -Now, and Get-Date
# resolves to the same moment so a restored wall-clock line is judged at it too.
$now = [datetimeoffset]::Parse($env:DST_NOW)
$script:fakeNow = $now.UtcDateTime.ToLocalTime()
function Get-Date { return $script:fakeNow }
Invoke-Expression $functionAst.Extent.Text
[pscustomobject]@{
    healthy = [int](Get-HealthyCaptureWorkerCount -Now $now)
    local_now = $script:fakeNow.ToString('yyyy-MM-ddTHH:mm:ss')
} | ConvertTo-Json -Compress
"""

HEARTBEAT_CASES = {
    # now (absolute) and fresh heartbeats 70-150 real seconds old, written
    # before the transition with the offset then in force.
    "fall_back_2026_11_01": (
        "2026-11-01T01:01:00-05:00",
        {
            "loop_status.json": "2026-11-01T01:58:30.000000-04:00",
            "clob_loop_status.json": "2026-11-01T01:59:50.000000-04:00",
            "observation_trigger_status.json": "2026-11-01T01:59:30.000000-04:00",
        },
    ),
    "spring_forward_2027_03_14": (
        "2027-03-14T03:01:00-04:00",
        {
            "loop_status.json": "2027-03-14T01:58:30.000000-05:00",
            "clob_loop_status.json": "2027-03-14T01:59:50.000000-05:00",
            "observation_trigger_status.json": "2027-03-14T01:59:30.000000-05:00",
        },
    ),
}


@WINDOWS_POWERSHELL
@pytest.mark.spawns
@pytest.mark.parametrize("case", sorted(HEARTBEAT_CASES))
def test_bounded_suite_counts_fresh_capture_workers_across_dst(tmp_path, case):
    now, heartbeats = HEARTBEAT_CASES[case]
    for value in heartbeats.values():
        age = (datetime.fromisoformat(now) - datetime.fromisoformat(value)).total_seconds()
        if not 0 <= age <= 180:
            raise RuntimeError(f"fixture heartbeat {value} is not fresh at {now}")
    (tmp_path / "data" / "snapshots").mkdir(parents=True)

    payload = _run(
        HEALTHY_WORKERS_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "bounded_worktree_test_suite.ps1"),
            "DST_REPO_ROOT": str(tmp_path),
            "DST_HEARTBEATS": json.dumps(heartbeats),
            "DST_NOW": now,
        },
    )

    # All three workers heartbeated within the last 150 real seconds. The
    # defect subtracts local wall times (negative age on fall-back, ~62 minutes
    # on spring-forward), counts 0, and Assert-HostAdmission aborts the suite.
    assert payload["healthy"] == 3, payload


GUARD_CREATION_PROBE = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'memory_commit_guard.ps1 does not parse' }
foreach ($name in @('Test-GovernedWeatherProcess', 'Test-AgentHeavyProcess', 'Get-AgentToolRoot',
        'Get-ProcessTreeRows', 'Stop-VerifiedProcessTree')) {
    $found = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true))
    if ($found.Count -ne 1) { throw "expected one function $name, found $($found.Count)" }
    Invoke-Expression $found[0].Extent.Text
}
$top = @($ast.EndBlock.Statements)
function Get-TopIndex([scriptblock]$Predicate) {
    $hits = @(for ($i = 0; $i -lt $top.Count; $i++) { if (& $Predicate $top[$i].Extent.Text) { $i } })
    if ($hits.Count -ne 1) { throw "expected one top-level statement, found $($hits.Count)" }
    return $hits[0]
}
function Get-TopRange([int]$From, [int]$To) {
    return ($top[$From..$To] | ForEach-Object { $_.Extent.Text }) -join "`n"
}
function Get-Assignment([string]$Variable) {
    $found = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left.Extent.Text -eq $Variable
    }, $true))
    if ($found.Count -ne 1) { throw "expected one assignment to $Variable, found $($found.Count)" }
    return $found[0].Extent.Text
}
Invoke-Expression (Get-Assignment '$agentRootNames')
Invoke-Expression (Get-Assignment '$agentShellNames')
# The clock statements: $localNow, and $utcNow where the script derives it.
$clockText = ($top | Where-Object { $_.Extent.Text -match '^\$(?:localNow|utcNow)\s*=' } |
    ForEach-Object { $_.Extent.Text }) -join "`n"
if (-not $clockText.Contains('$localNow = Get-Date')) { throw 'missing $localNow = Get-Date' }
$heavyText = Get-TopRange (Get-TopIndex { param($t) $t -eq '$heavyToolRoots = @{}' }) `
    (Get-TopIndex { param($t) $t.StartsWith('foreach') -and $t.Contains('$AgentWorkloadGraceSeconds') })
$sweepText = Get-TopRange (Get-TopIndex { param($t) $t -eq '$orphanActions = @()' }) `
    (Get-TopIndex { param($t) $t.StartsWith('foreach') -and $t.Contains('$OrphanGraceMinutes') })
$sortText = Get-Assignment '$orderedRoots'
$evidenceText = Get-Assignment '$orphanedEvidence'

# Rows carry CreationDate the way Get-CimInstance returns it: a local DateTime
# converted from the absolute instant (a fall-back-hour value keeps its
# ambiguity bit, so ToUniversalTime round-trips).
function ConvertTo-LocalBirth([string]$Iso) { return [datetimeoffset]::Parse($Iso).UtcDateTime.ToLocalTime() }
function New-Row($Spec) {
    return [pscustomobject]@{
        ProcessId = [uint32]$Spec.pid
        ParentProcessId = [uint32]$Spec.ppid
        Name = [string]$Spec.name
        CommandLine = [string]$Spec.cmd
        CreationDate = ConvertTo-LocalBirth $Spec.born
        ReadTransferCount = [uint64]0
    }
}
function Get-Date {
    param([string]$Format)
    if ($Format) { return $script:fakeNow.ToString($Format) }
    return $script:fakeNow
}
function Get-Process {
    param($Id, $ErrorAction)
    return [pscustomobject]@{ Id = [int]$Id; PrivateMemorySize64 = [long]64MB }
}
function Stop-Process { param($Id, [switch]$Force, $Confirm, $ErrorAction) $script:stopped.Add([int]$Id) }
function Write-GuardLog([string]$Level, [string]$Message) { }
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($Filter -match '^ProcessId = (\d+)$') {
        $wanted = [int]$Matches[1]
        return $script:liveRows | Where-Object { [int]$_.ProcessId -eq $wanted } | Select-Object -First 1
    }
    if ($Filter -eq "Name like 'python%'") { return $script:liveRows }
    throw "unexpected Win32_Process filter: $Filter"
}

$AgentWorkloadGraceSeconds = 15.0
$OrphanGraceMinutes = 30.0
$MaxConcurrentAgentHeavyWorkloads = 1
$escapedTaskName = 'WeatherEveningEvidenceRefresh'
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DST_CASES)) | ConvertFrom-Json
$results = [ordered]@{}
foreach ($case in @($cases)) {
    $script:fakeNow = ConvertTo-LocalBirth $case.now
    $script:stopped = New-Object System.Collections.Generic.List[int]
    $guardActions = New-Object System.Collections.Generic.List[string]
    $allProcesses = @($case.rows | ForEach-Object { New-Row $_ })
    $script:liveRows = @(if ($case.live) { $case.live | ForEach-Object { New-Row $_ } } else { $allProcesses })
    $processByPid = @{}
    foreach ($row in $allProcesses) { $processByPid[[uint32]$row.ProcessId] = $row }
    Invoke-Expression $clockText
    $site = [string]$case.site
    if ($site -eq 'heavy') {
        Invoke-Expression $heavyText
        $value = @($heavyToolRoots.Values | ForEach-Object { [int]$_.ProcessId } | Sort-Object)
    }
    elseif ($site -eq 'tree') {
        $value = @(Get-ProcessTreeRows $allProcesses[0] $allProcesses |
            ForEach-Object { [int]$_.ProcessId } | Sort-Object)
    }
    elseif ($site -eq 'order') {
        $heavyToolRoots = @{}
        foreach ($row in $allProcesses) { $heavyToolRoots["$($row.ProcessId)"] = $row }
        Invoke-Expression $sortText
        $value = @($orderedRoots | ForEach-Object { [int]$_.ProcessId })
    }
    elseif ($site -eq 'identity') {
        [void](Stop-VerifiedProcessTree $allProcesses[0] $allProcesses 'dst probe' $true)
        $value = @($script:stopped)
    }
    elseif ($site -eq 'sweep') {
        Invoke-Expression $sweepText
        $value = @($script:stopped)
    }
    elseif ($site -eq 'evidence') {
        Invoke-Expression $evidenceText
        $value = @($orphanedEvidence | ForEach-Object { [int]$_.AgeMinutes })
    }
    else { throw "unknown site $site" }
    $results[[string]$case.name] = [object[]]@($value)
}
$results | ConvertTo-Json -Compress -Depth 4
"""

_SHELL = "powershell.exe"
_PY = "python.exe"
_PYTEST = "python -m pytest -q"
_INLINE = "python -c pass"
_REFRESH = "python -m weather.operations.daily_refresh --scheduler-task-name WeatherEveningEvidenceRefresh"
_GONE = 7999999  # a parent PID absent from every table


def _row(pid, ppid, name, cmd, born):
    return {"pid": pid, "ppid": ppid, "name": name, "cmd": cmd, "born": born}


def _agent_tree(shell_born, child_born):
    # claude.exe -> tool shell -> heavy pytest child; the shell is the tool root.
    return [
        _row(7000001, _GONE, "claude.exe", "claude", "2026-10-01T00:00:00+00:00"),
        _row(7000003, 7000001, _SHELL, "powershell -NoProfile -Command run", shell_born),
        _row(7000005, 7000003, _PY, _PYTEST, child_born),
    ]


# (name, site, now, rows, expected, rows a re-read by PID returns, else None).
# Toronto falls back at 2026-11-01 06:00Z (01:59:59 EDT -> 01:00:00 EST) and
# springs forward at 2027-03-14 07:00Z (01:59:59 EST -> 03:00:00 EDT). Every
# expectation is the verdict on real (UTC) instants.
GUARD_CREATION_CASES = [
    # Ancestry: a 01:55 EDT shell is older than its 01:05 EST pytest child.
    ("heavy_ancestry_fall_back", "heavy", "2026-11-01T01:10:00-05:00",
     _agent_tree("2026-11-01T01:55:00-04:00", "2026-11-01T01:05:00-05:00"), [7000003], None),
    # Grace: 40 real seconds old (-59 minutes on the wall) is past the 15 s grace.
    ("heavy_grace_fall_back", "heavy", "2026-11-01T01:00:10-05:00",
     _agent_tree("2026-11-01T01:59:00-04:00", "2026-11-01T01:59:30-04:00"), [7000003], None),
    # Grace: 10 real seconds old (60 minutes on the wall) is inside it.
    ("heavy_grace_spring_forward", "heavy", "2027-03-14T03:00:05-04:00",
     _agent_tree("2027-03-14T01:59:50-05:00", "2027-03-14T01:59:55-05:00"), [], None),
    ("heavy_ordinary_counted", "heavy", "2026-10-20T01:10:00-04:00",
     _agent_tree("2026-10-20T01:00:00-04:00", "2026-10-20T01:05:00-04:00"), [7000003], None),
    ("heavy_ordinary_in_grace", "heavy", "2026-10-20T01:10:00-04:00",
     _agent_tree("2026-10-20T01:00:00-04:00", "2026-10-20T01:09:55-04:00"), [], None),
    # Ancestry PID reuse: a "parent" really younger than its child holds a reused
    # PID, so the child is not attributed to that tree.
    ("heavy_ordinary_reused_parent_pid", "heavy", "2026-10-20T03:10:00-04:00",
     _agent_tree("2026-10-20T02:00:00-04:00", "2026-10-20T01:00:00-04:00"), [], None),
    ("heavy_fall_back_reused_parent_pid", "heavy", "2026-11-01T01:40:00-05:00",
     _agent_tree("2026-11-01T01:10:00-05:00", "2026-11-01T01:30:00-04:00"), [], None),
    # Tree membership: descendants born after the root belong to its tree.
    ("tree_fall_back", "tree", "2026-11-01T01:20:00-05:00", [
        _row(7000003, 7000001, _SHELL, "powershell", "2026-11-01T01:55:00-04:00"),
        _row(7000005, 7000003, _PY, _PYTEST, "2026-11-01T01:05:00-05:00"),
        _row(7000007, 7000005, _PY, _INLINE, "2026-11-01T01:06:00-05:00"),
    ], [7000003, 7000005, 7000007], None),
    # A "child" really older than the root holds a reused parent PID: excluded.
    ("tree_fall_back_reused_pid", "tree", "2026-11-01T01:20:00-05:00", [
        _row(7000003, 7000001, _SHELL, "powershell", "2026-11-01T01:10:00-05:00"),
        _row(7000005, 7000003, _PY, _PYTEST, "2026-11-01T01:30:00-04:00"),
    ], [7000003], None),
    ("tree_ordinary", "tree", "2026-10-20T01:20:00-04:00", [
        _row(7000003, 7000001, _SHELL, "powershell", "2026-10-20T01:00:00-04:00"),
        _row(7000005, 7000003, _PY, _PYTEST, "2026-10-20T01:05:00-04:00"),
        _row(7000007, 7000005, _PY, _INLINE, "2026-10-20T00:59:00-04:00"),
    ], [7000003, 7000005], None),
    # Concurrency: roots are ordered oldest first (the oldest is retained).
    ("order_fall_back", "order", "2026-11-01T01:20:00-05:00", [
        _row(7000003, 7000001, _SHELL, "powershell", "2026-11-01T01:02:00-05:00"),
        _row(7000009, 7000001, _SHELL, "powershell", "2026-11-01T01:50:00-04:00"),
    ], [7000009, 7000003], None),
    ("order_ordinary", "order", "2026-10-20T01:20:00-04:00", [
        _row(7000003, 7000001, _SHELL, "powershell", "2026-10-20T01:10:00-04:00"),
        _row(7000009, 7000001, _SHELL, "powershell", "2026-10-20T01:05:00-04:00"),
    ], [7000009, 7000003], None),
    # Creation identity before a kill: 01:30 EDT and 01:30 EST are different processes.
    ("identity_fall_back_reused_pid", "identity", "2026-11-01T01:40:00-05:00",
     [_row(7000011, _GONE, _PY, _INLINE, "2026-11-01T01:30:00-04:00")], [],
     [_row(7000011, _GONE, _PY, _INLINE, "2026-11-01T01:30:00-05:00")]),
    ("identity_ordinary_same", "identity", "2026-10-20T01:40:00-04:00",
     [_row(7000011, _GONE, _PY, _INLINE, "2026-10-20T01:30:00-04:00")], [7000011], None),
    # Orphan sweep: a 01:05 EST child of a live 01:55 EDT parent is not orphaned.
    ("sweep_fall_back_live_parent", "sweep", "2026-11-01T01:40:00-05:00", [
        _row(7000013, _GONE, _SHELL, "powershell", "2026-11-01T01:55:00-04:00"),
        _row(7000015, 7000013, _PY, _INLINE, "2026-11-01T01:05:00-05:00"),
    ], [], None),
    # A parent PID really younger than its child was reused: the child is orphaned.
    ("sweep_ordinary_reused_parent_pid", "sweep", "2026-10-20T02:30:00-04:00", [
        _row(7000013, _GONE, _SHELL, "powershell", "2026-10-20T02:00:00-04:00"),
        _row(7000015, 7000013, _PY, _INLINE, "2026-10-20T01:30:00-04:00"),
    ], [7000015], None),
    # Parent gone: 50 real minutes old (-10 on the wall) is past the 30-minute grace.
    ("sweep_fall_back_grace", "sweep", "2026-11-01T01:10:00-05:00",
     [_row(7000017, _GONE, _PY, _INLINE, "2026-11-01T01:20:00-04:00")], [7000017], None),
    # Parent gone: 15 real minutes old (75 on the wall) is inside it.
    ("sweep_spring_forward_grace", "sweep", "2027-03-14T03:05:00-04:00",
     [_row(7000017, _GONE, _PY, _INLINE, "2027-03-14T01:50:00-05:00")], [], None),
    ("sweep_ordinary_past_grace", "sweep", "2026-10-20T02:31:00-04:00",
     [_row(7000017, _GONE, _PY, _INLINE, "2026-10-20T02:00:00-04:00")], [7000017], None),
    ("sweep_ordinary_in_grace", "sweep", "2026-10-20T02:29:00-04:00",
     [_row(7000017, _GONE, _PY, _INLINE, "2026-10-20T02:00:00-04:00")], [], None),
    # Orphaned evidence-refresh age (gated at 2 minutes and logged) is real elapsed time.
    ("evidence_fall_back_age", "evidence", "2026-11-01T12:00:00-05:00",
     [_row(7000019, _GONE, _PY, _REFRESH, "2026-11-01T01:30:00-04:00")], [690], None),
    ("evidence_ordinary_age", "evidence", "2026-10-20T12:00:00-04:00",
     [_row(7000019, _GONE, _PY, _REFRESH, "2026-10-20T11:50:00-04:00")], [10], None),
]


# ---------------------------------------------------------------------------
# DST-M5 / DST-M6: deadlines and bounded waits held as instants.
#
# The probes below drive the scripts' own statements with a logical clock: the
# clock is a UTC instant, Get-Date returns it as local time (ToLocalTime keeps
# .NET's repeated-hour flag, exactly as DateTime.Now does) and Start-Sleep
# advances it. Each case reports how many real seconds elapse before the
# script's own deadline fires.

LOGICAL_CLOCK = r"""
$script:fakeUtc = ([datetimeoffset]::Parse($env:DST_START)).UtcDateTime
$script:startUtc = $script:fakeUtc
function Get-Date {
    param([string]$Format)
    $local = $script:fakeUtc.ToLocalTime()
    if ($PSBoundParameters.ContainsKey('Format')) { return $local.ToString($Format) }
    return $local
}
function Start-Sleep {
    param([int]$Seconds, [int]$Milliseconds)
    $ms = if ($PSBoundParameters.ContainsKey('Milliseconds')) { $Milliseconds } else { $Seconds * 1000 }
    $script:fakeUtc = $script:fakeUtc.AddMilliseconds($ms)
}
function Get-ElapsedSeconds { return [int][Math]::Round(($script:fakeUtc - $script:startUtc).TotalSeconds) }
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw "$env:DST_AUDIT_SCRIPT does not parse" }
function Get-ScriptFunctionText([string]$Name, [switch]$Optional) {
    $found = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $Name
    }, $true))
    if ($found.Count -eq 0 -and $Optional) { return '' }
    if ($found.Count -ne 1) { throw "expected one function $Name, found $($found.Count)" }
    return $found[0].Extent.Text
}
function Get-AssignmentAst([string]$Left) {
    $found = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left.Extent.Text -eq $Left -and
            $node.Right.Extent.Text -ne '$null'
    }, $true))
    if ($found.Count -ne 1) { throw "expected one assignment to $Left, found $($found.Count)" }
    return $found[0]
}
# The statements of one block from the assignment to $FirstLeft through the
# first following statement that satisfies $IsLast.
function Get-StatementRunText([string]$FirstLeft, [scriptblock]$IsLast) {
    $first = Get-AssignmentAst $FirstLeft
    $statements = @($first.Parent.Statements)
    $index = [array]::IndexOf($statements, $first)
    for ($i = $index; $i -lt $statements.Count; $i++) {
        if (& $IsLast $statements[$i]) {
            return (@($statements[$index..$i] | ForEach-Object { $_.Extent.Text }) -join "`n")
        }
    }
    throw "no closing statement after $FirstLeft"
}
# Optional on master, where the instant helper does not exist yet.
$clockHelper = Get-ScriptFunctionText 'Get-QuietMergeClockInstant' -Optional
if ($clockHelper) { Invoke-Expression $clockHelper }
"""

WAIT_PROBE = LOGICAL_CLOCK + r"""
Invoke-Expression $env:DST_STUBS
$isLoop = { param($s) $s -is [System.Management.Automation.Language.LoopStatementAst] }
Invoke-Expression (Get-StatementRunText $env:DST_ANCHOR $isLoop)
[pscustomobject]@{ elapsed = (Get-ElapsedSeconds) } | ConvertTo-Json -Compress
"""

# Each M6 wait, with stubs that keep its readiness probe failing so the loop runs
# to its own deadline: (script, first statement, stubs, configured real seconds,
# the loop's sleep step = the most it may overshoot).
WAIT_SITES = {
    "quiet_merge_rollback": (
        "quiet_window_merge.ps1",
        "$rollbackDeadline",
        r"""
$RollbackRecoverySeconds = 1200
$executionTapeRecoveryRequired = $false
function Get-CaptureState { return [pscustomobject]@{ ok = $false; workers = @() } }
""",
        1200,
        15,
    ),
    "reconciliation_rollback": (
        "quiet_window_merge.ps1",
        "$rollbackNow",
        r"""
$RollbackRecoverySeconds = 1200
function Test-ReconciliationCaptureProof { return [pscustomobject]@{ ok = $false } }
""",
        1200,
        15,
    ),
    "suite_gate_running_wait": (
        "suite_gated_quiet_merge.ps1",
        "$suiteWaitDeadline",
        r"""
$SuiteRunningWaitMinutes = 20
$SuiteTaskName = 'dst-probe-suite'
$suiteTask = [pscustomobject]@{ State = 'Running' }
function Refuse-SuiteGate([string]$Reason) { throw "refused: $Reason" }
function Get-ScheduledTask { return [pscustomobject]@{ State = 'Running' } }
function Get-ScheduledTaskInfo { return [pscustomobject]@{ LastRunTime = [datetime]'2026-10-31T09:00:00' } }
""",
        1200,
        15,
    ),
    "adopt_first_ensure": (
        "adopt_execution_tape_after_merge.ps1",
        "$deadline",
        r"""
$SupervisorTaskName = 'dst-probe-supervisor'
$before = [pscustomobject]@{ LastRunTime = [datetime]'2026-10-31T09:00:00'; LastTaskResult = 0 }
function Get-ScheduledTask { return [pscustomobject]@{ State = 'Running' } }
function Get-ScheduledTaskInfo { return $before }
""",
        60,
        1,
    ),
}

# Start instants shortly before each transition (the 60-second adoption wait
# starts 30 seconds before it), and an ordinary night for unchanged semantics.
WAIT_STARTS = {
    "fall_back_2026_11_01": ("2026-11-01T01:50:00-04:00", "2026-11-01T01:59:30-04:00"),
    "spring_forward_2027_03_14": ("2027-03-14T01:50:00-05:00", "2027-03-14T01:59:30-05:00"),
    "ordinary_2026_10_20": ("2026-10-20T01:50:00-04:00", "2026-10-20T01:59:30-04:00"),
}


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_memory_guard_creation_ages_and_order_are_instants_across_dst():
    cases = [
        {"name": name, "site": site, "now": now, "rows": rows, "live": live}
        for name, site, now, rows, _, live in GUARD_CREATION_CASES
    ]

    payload = _run(
        GUARD_CREATION_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "memory_commit_guard.ps1"),
            "DST_CASES": base64.b64encode(json.dumps(cases).encode("utf-8")).decode("ascii"),
        },
    )

    # DST-M4: the S4U guard compared process CreationDate values as local wall
    # times. Across fall-back that broke agent ancestry (fail-open), dropped live
    # descendants from a tree, inverted the keep-oldest order, passed a reused PID
    # as the same process, and classed a live child as orphaned; across both
    # transitions it moved every grace period by an hour. Ordinary days keep their
    # verdicts.
    expected = {name: verdict for name, _, _, _, verdict, _ in GUARD_CREATION_CASES}
    assert payload == expected, payload


@WINDOWS_POWERSHELL
@pytest.mark.spawns
@pytest.mark.parametrize("start", sorted(WAIT_STARTS))
@pytest.mark.parametrize("site", sorted(WAIT_SITES))
def test_bounded_waits_last_their_configured_real_time_across_dst(site, start):
    script, anchor, stubs, budget, step = WAIT_SITES[site]
    long_start, short_start = WAIT_STARTS[start]

    payload = _run(
        WAIT_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / script),
            "DST_ANCHOR": anchor,
            "DST_STUBS": stubs,
            "DST_START": short_start if budget < 600 else long_start,
        },
    )

    # DST-M6: the defect computed these deadlines on the local wall clock, so a
    # wait straddling 02:00 ran an hour long on 2026-11-01 (holding the lease)
    # and ended at 03:00 EDT on 2027-03-14 (a false rollback_recovery_failed).
    assert budget <= payload["elapsed"] <= budget + step, payload


PUSH_CLOCK_SETUP = r"""
Invoke-Expression (Get-ScriptFunctionText 'Assert-ReconciliationPublicationTimeBudget')
Invoke-Expression (Get-AssignmentAst '$reconciliationPushRuntimeLimit').Extent.Text
Invoke-Expression (Get-AssignmentAst '$reconciliationPushTerminalReserve').Extent.Text
$isStopAt = {
    param($s)
    $s -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $s.Left.Extent.Text -eq '$pushContainmentStopAt'
}
# The armed containment clock: from the Start instant through the Stop reserve.
Invoke-Expression (Get-StatementRunText '$pushStartIssuedAt' $isStopAt)
"""

PUSH_CONTAINMENT_PROBE = LOGICAL_CLOCK + PUSH_CLOCK_SETUP + r"""
# The drain loop's own clock read and its two boundary conditions.
$pollRead = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -eq '$pushPollAt'
}, $true))[0].Extent.Text
$conditions = @($ast.FindAll({
    param($node) $node -is [System.Management.Automation.Language.IfStatementAst]
}, $true) | ForEach-Object { $_.Clauses[0].Item1.Extent.Text -replace '\s+', ' ' })
$deadlineCondition = '$pushPollAt -ge $pushContainmentDeadline'
$stopCondition = '$pushPollAt -ge $pushContainmentStopAt -and $pushPollAt -lt $pushContainmentDeadline'
foreach ($condition in @($deadlineCondition, $stopCondition)) {
    if (@($conditions | Where-Object { $_ -ceq $condition }).Count -lt 1) { throw "missing condition: $condition" }
}
$result = [ordered]@{ stop_opens = $null; deadline = $null }
for ($t = 0; $t -le 7200 -and $null -eq $result.deadline; $t += 10) {
    $script:fakeUtc = $script:startUtc.AddSeconds($t)
    Invoke-Expression $pollRead
    if ($null -eq $result.stop_opens -and [bool](Invoke-Expression $stopCondition)) { $result.stop_opens = $t }
    if ([bool](Invoke-Expression $deadlineCondition)) { $result.deadline = $t }
}
$result | ConvertTo-Json -Compress
"""

# Start instants: shortly before each transition, and an ordinary night.
PUSH_STARTS = {
    "fall_back_2026_11_01": "2026-11-01T01:50:00-04:00",
    "spring_forward_2027_03_14": "2027-03-14T01:50:00-05:00",
    "ordinary_2026_10_20": "2026-10-20T01:50:00-04:00",
}


@WINDOWS_POWERSHELL
@pytest.mark.spawns
@pytest.mark.parametrize("start", sorted(PUSH_STARTS))
def test_reconciliation_push_containment_is_pt15m_of_real_time(start):
    payload = _run(
        PUSH_CONTAINMENT_PROBE,
        {"DST_AUDIT_SCRIPT": str(OPS / "quiet_window_merge.ps1"), "DST_START": PUSH_STARTS[start]},
    )

    # DST-M5: the containment deadline is PT15M of elapsed time and the bounded
    # Stop opens 30 seconds before it. The defect added PT15M on the wall clock:
    # 75 minutes on 2026-11-01, and on 2027-03-14 a skipped 02:05 deadline that
    # fired after 10 minutes with the Stop window never open.
    assert payload == {"stop_opens": 870, "deadline": 900}, payload


RPC_BUDGET_PROBE = LOGICAL_CLOCK + PUSH_CLOCK_SETUP + r"""
Invoke-Expression (Get-ScriptFunctionText 'New-ReconciliationSchedulerRpcIdentity')
Invoke-Expression (Get-AssignmentAst '$reconciliationChildBoundaryReserveSeconds').Extent.Text
$result = [ordered]@{}
foreach ($t in @(0, 880, 905)) {
    $script:fakeUtc = $script:startUtc.AddSeconds($t)
    try {
        # The budget is computed on the logical clock, but the request deadline
        # is stamped on the real clock. Read the exact budget, then bracket the
        # real stamp instead of re-reading the real clock afterwards (#278:
        # a >0.5 s stall on a loaded runner rounded a 20 s budget to 19).
        $realBefore = [datetimeoffset]::UtcNow
        $identity = New-ReconciliationSchedulerRpcIdentity -LogicalBoundary $pushContainmentDeadline -MaximumSeconds 20
        $realAfter = [datetimeoffset]::UtcNow
        $deadline = [datetimeoffset]$identity.deadline
        $budget = [int]$identity.timeout_seconds
        if ($deadline -lt $realBefore.AddSeconds($budget) -or $deadline -gt $realAfter.AddSeconds($budget)) {
            throw "deadline $($deadline.ToString('o')) is not real-now + $budget s"
        }
        $result["t$t"] = $budget
    }
    catch {
        if ("$_" -notlike 'no Scheduler RPC budget remains*') { throw }
        $result["t$t"] = 'refused'
    }
}
$result | ConvertTo-Json -Compress
"""


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_reconciliation_rpc_budget_shrinks_to_the_real_containment_deadline():
    # Start at 01:55 EDT: the real PT15M deadline is 01:10 EST, after the
    # fall-back, while the wall-clock one was 02:10, an hour later.
    payload = _run(
        RPC_BUDGET_PROBE,
        {"DST_AUDIT_SCRIPT": str(OPS / "quiet_window_merge.ps1"), "DST_START": "2026-11-01T01:55:00-04:00"},
    )

    # Each Scheduler RPC is granted at most what remains before the containment
    # deadline less the 8-second child reserve; none is granted after it.
    assert payload == {"t0": 20, "t880": 12, "t905": "refused"}, payload
