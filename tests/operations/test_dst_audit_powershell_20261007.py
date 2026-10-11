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
workers and execution tape) across the fall-back hour and on ordinary days.

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
