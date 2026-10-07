"""Failing-first DST execution tests for the Windows ops scripts (DST audit 2026-10-07).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md findings DST-H3 (quiet-window merge heartbeat
advancement compared on the wall clock) and DST-H4 (bounded suite capture-worker heartbeat age computed
on the wall clock). DST-C1 (daily Scheduler triggers stored with a fixed UTC offset) is fixed by the
local-trigger helper and guarded by tests/operations/test_scheduled_task_local_daily_triggers.py; its
xfail here was retired with that fix.

Every test executes the repository's own PowerShell (a statement or function
extracted from the script by the PowerShell parser) in a real Windows
PowerShell child whose local time zone is pinned to Eastern, so the result
does not depend on the runner's zone. The clock-dependent cases use fixed
instants inside the 2026-11-01 fall-back hour (and the 2027-03-14 spring-forward
gap). Each test is ``xfail(strict=True, raises=AssertionError)`` while the defect is
on master: a broken harness raises ``RuntimeError`` and fails loudly instead of
counting as the expected failure. The fixing change must remove the marker.
"""

from __future__ import annotations

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
$comparisons = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.BinaryExpressionAst] -and
        $node.Operator -eq 'Ile' -and
        $node.Left.Extent.Text -match '\$afterWorker\.last_heartbeat' -and
        $node.Right.Extent.Text -match '\$beforeWorker\.last_heartbeat'
}, $true))
if ($comparisons.Count -ne 1) { throw "expected one heartbeat comparison, found $($comparisons.Count)" }
$beforeWorker = [pscustomobject]@{ last_heartbeat = $env:DST_BEFORE }
$afterWorker = [pscustomobject]@{ last_heartbeat = $env:DST_AFTER }
$notAdvanced = [bool](Invoke-Expression $comparisons[0].Extent.Text)
[pscustomobject]@{
    line = $comparisons[0].Extent.StartLineNumber
    not_advanced = $notAdvanced
} | ConvertTo-Json -Compress
"""


@WINDOWS_POWERSHELL
@pytest.mark.spawns
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DST audit 2026-10-07: DST-H3")
def test_quiet_merge_heartbeat_advancement_survives_fall_back():
    # Supervisor heartbeats are written with their offset (datetime.isoformat()).
    before = "2026-11-01T01:58:40.250000-04:00"  # 05:58:40Z, first 01:xx (EDT)
    after = "2026-11-01T01:03:12.500000-05:00"  # 06:03:12Z, second 01:xx (EST)
    if not datetime.fromisoformat(after) > datetime.fromisoformat(before):
        raise RuntimeError("fixture heartbeats are not in real-time order")

    payload = _run(
        MERGE_HEARTBEAT_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "quiet_window_merge.ps1"),
            "DST_BEFORE": before,
            "DST_AFTER": after,
        },
    )

    # The readopted worker heartbeated 4.5 real minutes later. The defect casts
    # both to local [datetime] (01:58 vs 01:03 wall) and rolls the merge back.
    assert payload["not_advanced"] is False, payload


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
# The pinned clock: Get-Date resolves to this function inside the extracted one.
$script:fakeNow = [datetimeoffset]::Parse($env:DST_NOW).UtcDateTime.ToLocalTime()
function Get-Date { return $script:fakeNow }
Invoke-Expression $functionAst.Extent.Text
[pscustomobject]@{
    healthy = [int](Get-HealthyCaptureWorkerCount)
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
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DST audit 2026-10-07: DST-H4")
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
