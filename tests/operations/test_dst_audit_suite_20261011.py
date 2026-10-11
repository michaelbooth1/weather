"""Failing-first DST execution tests for the bounded worktree suite (DST audit 2026-10-07).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md findings DST-M7 (the suite deadline took the
earlier of 09:00 and a wall-clock ``start + MaxRuntimeSeconds``, so a 01:30 EST start on
2027-03-14 was killed after 30 real minutes instead of 90) and DST-L13 (the per-run tag that names
the chunk JUnit evidence and pytest basetemps was a local ``yyyyMMddTHHmmss`` wall time, which
repeats inside the 2026-11-01 fall-back hour and trips the "already exists" guards).

Every test executes the repository's own PowerShell (statements and functions extracted from
scripts/ops/bounded_worktree_test_suite.ps1 and scripts/ops/workstation_pregate.ps1 by the
PowerShell parser) in a real Windows PowerShell child whose local time zone is pinned to Eastern,
so the result does not depend on the runner's zone. Clock-dependent cases use fixed instants in the
2027-03-14 spring-forward gap, the 2026-11-01 repeated hour, and ordinary days. Both tests failed
against the unfixed script; a broken harness raises ``RuntimeError`` instead of an assertion.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
SUITE = OPS / "bounded_worktree_test_suite.ps1"
PREGATE = OPS / "workstation_pregate.ps1"
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
# A pinned wall clock: Get-Date resolves to the local reading of $script:fakeUtc.
$script:fakeUtc = [datetime]::SpecifyKind([datetime]'2000-01-01', [DateTimeKind]::Utc)
function Get-Date {
    param([string]$Format)
    $local = [TimeZoneInfo]::ConvertTimeFromUtc($script:fakeUtc, [TimeZoneInfo]::Local)
    if ($Format) { return $local.ToString($Format, [Globalization.CultureInfo]::InvariantCulture) }
    return $local
}
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
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell harness failed: {result.stderr.strip() or result.stdout.strip()}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("PowerShell harness printed nothing")
    return json.loads(lines[-1])


def _b64(value: object) -> str:
    return base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")


DEADLINE_PROBE = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'bounded_worktree_test_suite.ps1 does not parse' }
# The real deadline setup: every top-level statement from the start-time read
# up to (not including) the runtime Stopwatch.
$top = @($ast.EndBlock.Statements)
$first = @(for ($i = 0; $i -lt $top.Count; $i++) { if ($top[$i].Extent.Text -ceq '$localNow = Get-Date') { $i } })
$last = @(for ($i = 0; $i -lt $top.Count; $i++) {
    if ($top[$i].Extent.Text -clike '$suiteRuntimeStopwatch = *') { $i } })
if ($first.Count -ne 1 -or $last.Count -ne 1 -or $last[0] -le $first[0]) { throw 'deadline setup not found' }
$setup = ($top[$first[0]..($last[0] - 1)] | ForEach-Object { $_.Extent.Text }) -join "`n"
# Every in-run teardown check: the if-conditions that consult $suiteDeadline.
$conditions = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text.Contains('$suiteDeadline')
}, $true) | ForEach-Object { $_.Clauses[0].Item1.Extent.Text })
if ($conditions.Count -lt 3) { throw "expected the three suite deadline checks, found $($conditions.Count)" }
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DST_CASES)) | ConvertFrom-Json
$results = [ordered]@{}
foreach ($case in @($cases)) {
    $startUtc = ([datetimeoffset]::Parse([string]$case.start)).UtcDateTime
    $MaxRuntimeSeconds = [int]$case.max_runtime
    $script:fakeUtc = $startUtc
    Invoke-Expression $setup
    $kills = @()
    foreach ($condition in $conditions) {
        $killed = $null
        # Real time advances in 60-second steps; the Stopwatch reports the same
        # elapsed real time and Get-Date the local wall reading at that instant.
        for ($elapsed = 0; $elapsed -le 43200; $elapsed += 60) {
            $script:fakeUtc = $startUtc.AddSeconds($elapsed)
            $suiteRuntimeStopwatch = [pscustomobject]@{ Elapsed = [timespan]::FromSeconds($elapsed) }
            $importProbeDeadline = [pscustomobject]@{ Elapsed = [timespan]::Zero }
            if ([bool](Invoke-Expression $condition)) { $killed = $elapsed; break }
        }
        $kills += $killed
    }
    $distinct = @($kills | Sort-Object -Unique)
    $results[[string]$case.name] = if ($distinct.Count -eq 1) { $distinct[0] } else { 'disagree' }
}
[pscustomobject]@{ checks = $conditions.Count; kills = $results } | ConvertTo-Json -Compress -Depth 4
"""

# name -> (start instant, MaxRuntimeSeconds, real seconds until the teardown).
# Toronto springs forward at 2027-03-14 07:00Z (02:00 EST -> 03:00 EDT) and
# falls back at 2026-11-01 06:00Z (02:00 EDT -> 01:00 EST).
DEADLINE_CASES = {
    # The audit case: 01:30 EST + 90 minutes reads 03:00 on the wall after only
    # 30 real minutes. The defect killed the run at 1800 s.
    "spring_forward_0130_est": ("2027-03-14T01:30:00-05:00", 5400, 5400),
    # Wall-clock 02:15 does not exist; the defect waited for 03:00 EDT (4500 s).
    "spring_forward_0045_est": ("2027-03-14T00:45:00-05:00", 5400, 5400),
    "spring_forward_0800_edt": ("2027-03-14T08:00:00-04:00", 5400, 3600),
    "fall_back_0130_edt_first": ("2026-11-01T01:30:00-04:00", 5400, 5400),
    "fall_back_0130_est_second": ("2026-11-01T01:30:00-05:00", 5400, 5400),
    "fall_back_0800_est": ("2026-11-01T08:00:00-05:00", 5400, 3600),
    # Ordinary days: the Stopwatch cap and the 09:00 wall boundary, each binding.
    "ordinary_0130": ("2026-10-20T01:30:00-04:00", 5400, 5400),
    "ordinary_0130_short_cap": ("2026-10-20T01:30:00-04:00", 600, 600),
    "ordinary_0800": ("2026-10-20T08:00:00-04:00", 5400, 3600),
    "ordinary_0830_long_cap": ("2026-10-20T08:30:00-04:00", 7200, 1800),
}


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_suite_teardown_is_the_stopwatch_cap_or_the_0900_wall_edge_across_dst():
    cases = [
        {"name": name, "start": start, "max_runtime": cap}
        for name, (start, cap, _) in DEADLINE_CASES.items()
    ]

    payload = _run(DEADLINE_PROBE, {"DST_AUDIT_SCRIPT": str(SUITE), "DST_CASES": _b64(cases)})

    # Every in-run check (import probe, chunk admission, running chunk) kills at
    # min(MaxRuntimeSeconds of real time, the next 09:00 local wall reading).
    expected = {name: kill for name, (_, _, kill) in DEADLINE_CASES.items()}
    assert payload["checks"] == 3, payload
    assert payload["kills"] == expected, payload


RUN_TAG_PROBE = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'bounded_worktree_test_suite.ps1 does not parse' }
function Get-Assignment([string]$Variable, [string]$Uses = '') {
    $found = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
            $node.Left.VariablePath.UserPath -ceq $Variable -and
            $node.Right.Extent.Text.Contains($Uses)
    }, $true))
    if ($found.Count -ne 1) { throw "expected one assignment to `$$Variable, found $($found.Count)" }
    return $found[0].Extent.Text
}
$tagStatement = Get-Assignment 'runTag'
$junitStatement = Get-Assignment 'junitPath' '$runTag'
$baseTempStatement = Get-Assignment 'chunkBaseTemp' '$runTag'
foreach ($functionAst in @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Get-SuiteRunTag'
}, $true))) { Invoke-Expression $functionAst.Extent.Text }
$LogPath = 'C:\evidence\full-suite.log'
$chunkBaseTempParent = 'C:\pt'
$ordinal = 1
$instants = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DST_INSTANTS)) | ConvertFrom-Json
$runs = [ordered]@{}
foreach ($instant in @($instants)) {
    # The suite's own tag statement, run while the wall clock reads this instant.
    $script:fakeUtc = ([datetimeoffset]::Parse([string]$instant)).UtcDateTime
    $realBefore = [datetime]::UtcNow
    Invoke-Expression $tagStatement
    $realAfter = [datetime]::UtcNow
    $statementTag = $runTag
    $helperTag = $null
    if (Get-Command Get-SuiteRunTag -CommandType Function -ErrorAction SilentlyContinue) {
        $runTag = Get-SuiteRunTag -Now ([datetimeoffset]::Parse([string]$instant))
        $helperTag = $runTag
    }
    Invoke-Expression $junitStatement
    Invoke-Expression $baseTempStatement
    $runs[[string]$instant] = [ordered]@{
        statement_tag = $statementTag
        real_before = $realBefore.ToString("yyyyMMdd'T'HHmmss'Z'", [Globalization.CultureInfo]::InvariantCulture)
        real_after = $realAfter.ToString("yyyyMMdd'T'HHmmss'Z'", [Globalization.CultureInfo]::InvariantCulture)
        helper_tag = $helperTag
        junit = $junitPath
        basetemp = $chunkBaseTemp
    }
}
$runs | ConvertTo-Json -Compress -Depth 4
"""

# The first and second 01:30 of 2026-11-01 (one real hour apart), the
# spring-forward edge, and an ordinary afternoon.
RUN_TAG_INSTANTS = {
    "2026-11-01T01:30:00-04:00": "20261101T053000Z",
    "2026-11-01T01:30:00-05:00": "20261101T063000Z",
    "2027-03-14T03:00:00-04:00": "20270314T070000Z",
    "2026-10-20T14:05:09-04:00": "20261020T180509Z",
}


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_suite_run_tag_names_are_utc_instants_unique_across_fall_back():
    payload = _run(RUN_TAG_PROBE, {"DST_AUDIT_SCRIPT": str(SUITE), "DST_INSTANTS": _b64(list(RUN_TAG_INSTANTS))})

    for instant, expected_tag in RUN_TAG_INSTANTS.items():
        run = payload[instant]
        # The live statement ignores the local wall clock and reads UTC now; the
        # defect returned the pinned wall reading (20261101T013000 twice).
        assert re.fullmatch(r"\d{8}T\d{6}Z", run["statement_tag"] or ""), run
        assert run["real_before"] <= run["statement_tag"] <= run["real_after"], run
        # The tag helper maps an instant to its UTC name.
        assert run["helper_tag"] == expected_tag, run
        assert run["junit"] == f"C:\\evidence\\full-suite.log.{expected_tag}.chunk-001.xml", run
        assert run["basetemp"] == f"C:\\pt\\bs-{expected_tag}-001", run
    # Two runs one real hour apart inside the repeated hour get distinct names,
    # so neither trips the "already exists" guards.
    first, second = (payload[i] for i in list(RUN_TAG_INSTANTS)[:2])
    assert first["junit"] != second["junit"] and first["basetemp"] != second["basetemp"]
    assert datetime.strptime(first["helper_tag"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) == datetime.fromisoformat(
        "2026-11-01T01:30:00-04:00"
    )


PREGATE_LOG_PROBE = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'workstation_pregate.ps1 does not parse' }
$found = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq 'Read-WorkstationPregateSuiteLog'
}, $true))
if ($found.Count -ne 1) { throw 'missing Read-WorkstationPregateSuiteLog' }
Invoke-Expression $found[0].Extent.Text
$tags = [ordered]@{}
foreach ($path in @($env:DST_LOGS -split ';')) {
    $tags[[IO.Path]::GetFileName($path)] = (Read-WorkstationPregateSuiteLog -Path $path).run_tag
}
$tags | ConvertTo-Json -Compress
"""


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_workstation_pregate_reads_utc_and_legacy_run_tags(tmp_path):
    logs = {
        "utc.log": "20261101T063000Z",
        "legacy.log": "20261101T013000",
    }
    paths = []
    for name, tag in logs.items():
        path = tmp_path / name
        path.write_text(
            f"2026-11-01 01:30:05  chunk 1/2 starting files=25 junit=C:\\pg\\suite.log.{tag}.chunk-001.xml\n",
            encoding="utf-8",
        )
        paths.append(str(path))

    payload = _run(PREGATE_LOG_PROBE, {"DST_AUDIT_SCRIPT": str(PREGATE), "DST_LOGS": ";".join(paths)})

    # The pre-gate removes C:\pt\bs-<run_tag>-* after the host suite; a tag it
    # cannot read would leave the chunk basetemps behind.
    assert payload == logs, payload
