"""DST execution tests for the LOW PowerShell findings of the 2026-10-07 DST audit.

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md findings DST-L6 (integration-attempt suite
teardown budget computed on the wall clock), DST-L7 (fixed storage-recovery ExecutionTimeLimit),
DST-L8 (wall-clock MaxRuntime deadline in the twin and WU orphan wrappers), DST-L11 (nightly
retrain RunAtLocal accepted an ambiguous or nonexistent local time) and DST-L15 (Scheduler
LastRunTime ordering in the execution-tape adoption and the suite gate). Each test was written
failing-first against the pre-fix scripts and passes with the fix.

The pattern is the one in test_dst_audit_powershell_20261007.py: every test runs the
repository's own statements or functions, extracted by the PowerShell parser, in a Windows
PowerShell child whose TimeZoneInfo.Local is pinned to Eastern, with instants in the
2026-11-01 fall-back hour, the 2027-03-14 spring-forward gap, and an ordinary night.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from tests.operations.test_dst_audit_powershell_20261007 import LOGICAL_CLOCK, OPS, WINDOWS_POWERSHELL, _run

TORONTO = ZoneInfo("America/Toronto")


def _b64(value) -> str:
    return base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")


PARSE_SCRIPT = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw "$env:DST_AUDIT_SCRIPT does not parse" }
function Get-FunctionAst([System.Management.Automation.Language.Ast]$Root, [string]$Name, [switch]$Optional) {
    $found = @($Root.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $Name
    }, $true))
    if ($found.Count -eq 0 -and $Optional) { return $null }
    if ($found.Count -ne 1) { throw "expected one function $Name, found $($found.Count)" }
    return $found[0]
}
# Defines a script function from its own file, so $PSScriptRoot inside it is the script's folder.
function Import-ScriptFunction([System.Management.Automation.Language.Ast]$Root, [string]$Name, [switch]$Optional) {
    $found = Get-FunctionAst $Root $Name -Optional:$Optional
    if ($null -ne $found) { $null = New-Item -Path "function:global:$Name" -Value $found.Body.GetScriptBlock() -Force }
}
# Top-level statements from the first whose text satisfies $IsFirst through the
# first following one that satisfies $IsLast.
function Get-TopRunText([scriptblock]$IsFirst, [scriptblock]$IsLast) {
    $top = @($ast.EndBlock.Statements)
    for ($i = 0; $i -lt $top.Count; $i++) {
        if (-not (& $IsFirst $top[$i].Extent.Text)) { continue }
        for ($j = $i; $j -lt $top.Count; $j++) {
            if (& $IsLast $top[$j].Extent.Text) {
                return (@($top[$i..$j] | ForEach-Object { $_.Extent.Text }) -join "`n")
            }
        }
    }
    throw 'statement run not found'
}
"""


# ---------------------------------------------------------------------------
# DST-L15: execution-tape adoption detects a new supervisor run by a changed
# LastRunTime, not a later one.

ADOPT_PROBE = PARSE_SCRIPT + r"""
$condition = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -eq '$completedThisRun'
}, $true))
if ($condition.Count -ne 1) { throw "expected one completedThisRun assignment, found $($condition.Count)" }
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DST_CASES)) | ConvertFrom-Json
$results = [ordered]@{}
foreach ($case in @($cases)) {
    # Get-ScheduledTaskInfo reports local wall time with no offset.
    $before = [pscustomobject]@{ LastRunTime = [datetime]::ParseExact($case.before, 'yyyy-MM-ddTHH:mm:ss', $null) }
    $after = [pscustomobject]@{ LastRunTime = [datetime]::ParseExact($case.after, 'yyyy-MM-ddTHH:mm:ss', $null) }
    Invoke-Expression $condition[0].Extent.Text
    $results[[string]$case.name] = [bool]$completedThisRun
}
$results | ConvertTo-Json -Compress
"""

ADOPT_CASES = [
    # 01:55 EDT run, then the adoption's run at 01:05 EST: new, but earlier on the wall.
    ("fall_back_new_run", "2026-11-01T01:55:00", "2026-11-01T01:05:00", True),
    ("spring_forward_new_run", "2027-03-14T01:59:00", "2027-03-14T03:00:30", True),
    ("ordinary_new_run", "2026-10-20T01:30:00", "2026-10-20T01:31:00", True),
    ("ordinary_no_new_run", "2026-10-20T01:30:00", "2026-10-20T01:30:00", False),
]


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_adoption_detects_new_supervisor_run_across_fall_back():
    payload = _run(
        ADOPT_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "adopt_execution_tape_after_merge.ps1"),
            "DST_CASES": _b64([{"name": n, "before": b, "after": a} for n, b, a, _ in ADOPT_CASES]),
        },
    )

    # DST-L15: "-gt" read the 01:05 EST run as older than the 01:55 EDT one and
    # refused a successful adoption; an unchanged LastRunTime is still no run.
    assert payload == {name: verdict for name, _, _, verdict in ADOPT_CASES}, payload


# ---------------------------------------------------------------------------
# DST-L15: the suite gate's log-versus-LastRunTime ordering and correlation.

SUITE_GATE_PROBE = PARSE_SCRIPT + r"""
Import-ScriptFunction $ast 'Get-SuiteGateLocalInstants' -Optional
function Refuse-SuiteGate([string]$Reason) { throw "refused: $Reason" }
$checks = Get-TopRunText { param($t) $t.StartsWith('$logItem = Get-Item') } `
    { param($t) $t.StartsWith('if') -and $t.Contains('does not correlate to LastRunTime') }
$SuiteLogPath = $env:DST_SUITE_LOG
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DST_CASES)) | ConvertFrom-Json
$results = [ordered]@{}
foreach ($case in @($cases)) {
    [IO.File]::WriteAllLines($SuiteLogPath, [string[]]@(
        "$($case.log_start)  === bounded worktree suite starting ===",
        "$($case.log_start)  worktree=x branch=b expected_tip=t"))
    [IO.File]::SetLastWriteTimeUtc($SuiteLogPath, [datetimeoffset]::Parse($case.log_written).UtcDateTime)
    $suiteInfo = [pscustomobject]@{ LastRunTime = [datetime]::ParseExact($case.last_run, 'yyyy-MM-ddTHH:mm:ss', $null) }
    try {
        Invoke-Expression $checks
        $results[[string]$case.name] = 'ok'
    }
    catch { $results[[string]$case.name] = $_.Exception.Message }
}
$results | ConvertTo-Json -Compress
"""

_PREDATES = "refused: suite log predates the task run"
_UNCORRELATED = "refused: suite log run boundary does not correlate to LastRunTime"

# (name, task LastRunTime wall, log run-boundary wall, log last write instant, verdict).
SUITE_GATE_CASES = [
    # Task started 01:59:50 EDT; the log boundary was written 15 s later at 01:00:05 EST.
    ("fall_back_correlated", "2026-11-01T01:59:50", "2026-11-01 01:00:05", "2026-11-01T03:10:00-05:00", "ok"),
    # Task started 01:30 EDT; the log was last written at 01:20 EST, 50 real minutes later.
    ("fall_back_written_after_run", "2026-11-01T01:30:00", "2026-11-01 01:30:05", "2026-11-01T01:20:00-05:00",
     "ok"),
    # 01:10 EDT and 01:40 EST are 90 minutes apart under every reading: still refused.
    ("fall_back_uncorrelated", "2026-11-01T01:10:00", "2026-11-01 01:40:00", "2026-11-01T03:10:00-05:00",
     _UNCORRELATED),
    # Task started 01:59:50 EST; the log boundary was written 15 s later at 03:00:05 EDT.
    ("spring_forward_correlated", "2027-03-14T01:59:50", "2027-03-14 03:00:05", "2027-03-14T03:30:00-04:00", "ok"),
    ("ordinary_correlated", "2026-10-20T01:30:00", "2026-10-20 01:30:20", "2026-10-20T02:00:00-04:00", "ok"),
    ("ordinary_uncorrelated", "2026-10-20T01:30:00", "2026-10-20 01:40:00", "2026-10-20T02:00:00-04:00",
     _UNCORRELATED),
    ("ordinary_log_predates", "2026-10-20T01:30:00", "2026-10-20 01:30:20", "2026-10-20T01:20:00-04:00",
     _PREDATES),
]


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_suite_gate_orders_log_and_last_run_as_instants_across_dst(tmp_path):
    cases = [
        {"name": n, "last_run": r, "log_start": s, "log_written": w}
        for n, r, s, w, _ in SUITE_GATE_CASES
    ]
    payload = _run(
        SUITE_GATE_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "suite_gated_quiet_merge.ps1"),
            "DST_SUITE_LOG": str(tmp_path / "suite.log"),
            "DST_CASES": _b64(cases),
        },
    )

    # DST-L15: both checks compared offsetless local wall times, so a run whose
    # log boundary or last write fell after the fall-back (or past the
    # spring-forward gap) read as 60 minutes off and the merge was refused.
    assert payload == {name: verdict for name, *_, verdict in SUITE_GATE_CASES}, payload


# ---------------------------------------------------------------------------
# DST-L6: the integration-attempt suite's remaining budget is real time to 09:00.

ATTEMPT_SUITE_PROBE = LOGICAL_CLOCK + r"""
$setup = (@($ast.EndBlock.Statements) | Where-Object {
    $_.Extent.Text -match '^\$(localNow|localMinute|hardStop|suiteDeadlineBudgetMilliseconds|suiteDeadlineClock)\s*='
} | ForEach-Object { $_.Extent.Text }) -join "`n"
Invoke-Expression $setup
Invoke-Expression (Get-AssignmentAst '$remainingMilliseconds').Extent.Text
$results = [ordered]@{}
foreach ($t in @($env:DST_OFFSETS -split ',')) {
    $script:fakeUtc = $script:startUtc.AddSeconds([int]$t)
    $results["t$t"] = [int][Math]::Round((& $remainingMilliseconds) / 1000.0)
}
$results | ConvertTo-Json -Compress
"""

# Start instant -> real seconds from it to 09:00 local that morning.
ATTEMPT_SUITE_STARTS = {
    "fall_back_2026_11_01": "2026-11-01T01:30:00-04:00",
    "spring_forward_2027_03_14": "2027-03-14T01:30:00-05:00",
    "ordinary_2026_10_20": "2026-10-20T01:30:00-04:00",
}


@WINDOWS_POWERSHELL
@pytest.mark.spawns
@pytest.mark.parametrize("start", sorted(ATTEMPT_SUITE_STARTS))
def test_attempt_suite_budget_is_real_time_to_nine_across_dst(start):
    started = datetime.fromisoformat(ATTEMPT_SUITE_STARTS[start])
    nine = datetime.combine(started.date(), time(9), TORONTO)
    total = int((nine - started).total_seconds())
    offsets = [0, 3600, total - 60]

    payload = _run(
        ATTEMPT_SUITE_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "integration_attempt_suite.ps1"),
            "DST_START": ATTEMPT_SUITE_STARTS[start],
            "DST_OFFSETS": ",".join(str(t) for t in offsets),
        },
    )

    # DST-L6: the budget and the poll subtracted local wall times, so a 01:30
    # EDT start on 2026-11-01 tore down at 08:00 EST and a 01:30 EST start on
    # 2027-03-14 read an hour more budget than remained before 09:00 EDT.
    expected = {f"t{t}": total - t for t in offsets}
    assert set(payload) == set(expected), payload
    assert all(abs(payload[key] - expected[key]) <= 2 for key in expected), (payload, expected)


# ---------------------------------------------------------------------------
# DST-L7: the storage-recovery segment ExecutionTimeLimit follows the UTC span.

STORAGE_PROBE = PARSE_SCRIPT + r"""
$contract = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_CONTRACT_SCRIPT, [ref]$tokens, [ref]$errors)
Import-ScriptFunction $contract 'Get-WeatherNightTimes'
Import-ScriptFunction $ast 'Get-WeatherNightSegmentRuntimeMinutes' -Optional
$top = @($ast.EndBlock.Statements)
$loop = @($top | Where-Object {
    $_ -is [System.Management.Automation.Language.ForEachStatementAst] -and $_.Extent.Text.Contains('$runtimeMinutes')
})
if ($loop.Count -ne 1) { throw "expected one registration loop, found $($loop.Count)" }
$segmentText = (@($loop[0].Body.Statements) | Where-Object {
    $_.Extent.Text -match '^(\$(runtimeMinutes|at|argumentSegment)\s*=|if \(\$segment -eq)'
} | ForEach-Object { $_.Extent.Text }) -join "`n"
$results = [ordered]@{}
foreach ($night in @($env:DST_NIGHTS -split ',')) {
    $plan = [pscustomobject]@{ night_date = $night }
    # The registrar's own $early statement.
    Invoke-Expression (@($top | Where-Object { $_.Extent.Text -match '^\$early\s*=' })[0].Extent.Text)
    foreach ($segment in @('early', 'late')) {
        $runtimeMinutes = $null
        Invoke-Expression $segmentText
        $results["$night/$segment"] = [int]$runtimeMinutes
    }
}
$results | ConvertTo-Json -Compress
"""

STORAGE_NIGHTS = ["2026-10-20", "2026-11-01", "2027-03-14"]


def _segment_limit(night: str, start_minute: int, end_minute: int, margin: int) -> int:
    midnight = datetime.fromisoformat(night)
    start = (midnight + timedelta(minutes=start_minute)).replace(tzinfo=TORONTO)
    end = (midnight + timedelta(minutes=end_minute)).replace(tzinfo=TORONTO)
    return int((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds() // 60) + margin


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_storage_recovery_limit_follows_the_real_segment_span():
    payload = _run(
        STORAGE_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "register_storage_recovery_night.ps1"),
            "DST_CONTRACT_SCRIPT": str(OPS / "storage_recovery_night_contract.ps1"),
            "DST_NIGHTS": ",".join(STORAGE_NIGHTS),
        },
    )

    # Early 00:30-04:42 local plus 2 minutes, late 06:45-08:55 plus 4, measured
    # in real time: 314 minutes across the 2026-11-01 fall-back (the fixed 254
    # killed the segment at about 03:44 EST) and 194 across the spring-forward.
    expected = {}
    for night in STORAGE_NIGHTS:
        expected[f"{night}/early"] = _segment_limit(night, 30, 282, 2)
        expected[f"{night}/late"] = _segment_limit(night, 405, 535, 4)
    assert expected["2026-10-20/early"] == 254 and expected["2026-10-20/late"] == 134
    assert expected["2026-11-01/early"] == 314 and expected["2027-03-14/early"] == 194
    assert payload == expected, payload


# ---------------------------------------------------------------------------
# DST-L8: the twin and WU orphan wrappers bound MaxRuntimeSeconds in real time.

RUNTIME_PROBE = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:DST_AUDIT_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw "$env:DST_AUDIT_SCRIPT does not parse" }
$top = @($ast.EndBlock.Statements)
$clockText = (@($top | Where-Object { $_.Extent.Text -match '^\$(now|runtimeClock)\s*=' }) |
    ForEach-Object { $_.Extent.Text }) -join "`n"
if (-not $clockText.Contains('$now = Get-Date')) { throw 'missing $now = Get-Date' }
$handle = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Extent.Text -eq '$null = $child.Handle'
}, $true))
if ($handle.Count -ne 1) { throw 'missing child handle statement' }
$block = @($handle[0].Parent.Statements)
$index = [array]::IndexOf($block, $handle[0])
$waitText = $null
for ($i = $index + 1; $i -lt $block.Count; $i++) {
    if ($block[$i] -is [System.Management.Automation.Language.WhileStatementAst]) {
        $waitText = (@($block[($index + 1)..$i]) | ForEach-Object { $_.Extent.Text }) -join "`n"
        break
    }
}
if (-not $waitText) { throw 'missing wait loop' }
# Logical clock = start instant + real elapsed time, so the script's Stopwatch
# and its Get-Date agree. The fake child polls every 100 ms and exits on its own
# after the 8-second cap (reported as not stopped).
function Get-Date { return $script:fakeUtc.ToLocalTime() }
$child = [pscustomobject]@{}
$child | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {
    param($ms)
    [Threading.Thread]::Sleep(100)
    $script:fakeUtc = $script:startUtc.Add($script:real.Elapsed)
    return ($script:real.Elapsed.TotalSeconds -ge 8)
}
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:DST_CASES)) | ConvertFrom-Json
$results = [ordered]@{}
foreach ($case in @($cases)) {
    $MaxRuntimeSeconds = [int]$case.max_runtime
    $script:startUtc = [datetimeoffset]::Parse($case.start).UtcDateTime
    $script:fakeUtc = $script:startUtc
    $script:real = [Diagnostics.Stopwatch]::StartNew()
    Invoke-Expression $clockText
    try {
        Invoke-Expression $waitText
        $results[[string]$case.name] = 'not_stopped'
    }
    catch { $results[[string]$case.name] = [Math]::Round($script:real.Elapsed.TotalSeconds, 1) }
}
$results | ConvertTo-Json -Compress
"""

# (name, start instant, MaxRuntimeSeconds, real seconds until the deadline fires).
RUNTIME_CASES = [
    # One second before 02:00 EDT: the defect's 02:00:02 deadline was an hour away.
    ("fall_back", "2026-11-01T01:59:59-04:00", 3, 3.0),
    # One second before 02:00 EST: the defect's 02:00:02 deadline fired at 03:00 EDT.
    ("spring_forward", "2027-03-14T01:59:59-05:00", 3, 3.0),
    ("ordinary", "2026-10-20T01:59:59-04:00", 3, 3.0),
    # The 09:00 wall boundary still ends the run first.
    ("nine_boundary", "2026-10-20T08:59:58-04:00", 1800, 2.0),
]


@WINDOWS_POWERSHELL
@pytest.mark.spawns
@pytest.mark.parametrize("script", ["closed_day_projection_twins_run.ps1", "wu_orphan_cleanup_run.ps1"])
def test_wrapper_max_runtime_is_real_time_across_dst(script):
    payload = _run(
        RUNTIME_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / script),
            "DST_CASES": _b64([{"name": n, "start": s, "max_runtime": m} for n, s, m, _ in RUNTIME_CASES]),
        },
    )

    # DST-L8: min(09:00, now + MaxRuntime) on the wall clock ran an hour long
    # across the fall-back and ended early across the spring-forward.
    for name, _, _, seconds in RUNTIME_CASES:
        value = payload[name]
        assert value != "not_stopped" and seconds <= value <= seconds + 1.0, (name, payload)


# ---------------------------------------------------------------------------
# DST-L11: the direct nightly retrain registrar refuses a RunAtLocal that does
# not name exactly one instant.

NIGHTLY_PROBE = PARSE_SCRIPT + r"""
Import-ScriptFunction $ast 'Assert-NightlyRetrainRunAtLocal' -Optional
$checks = Get-TopRunText { param($t) $t -eq '$runAt = [datetime]::MinValue' } `
    { param($t) $t.StartsWith('$RunAtLocal = $runAt.ToString(') }
function Get-Date { return [datetime]'2026-10-11T12:00:00' }
$results = [ordered]@{}
foreach ($value in @($env:DST_RUN_AT -split ',')) {
    $RunAtLocal = $value
    try {
        Invoke-Expression $checks
        $results[$value] = 'accepted'
    }
    catch { $results[$value] = 'refused' }
}
$results | ConvertTo-Json -Compress
"""

NIGHTLY_RUN_AT = {
    "2026-11-01T00:59:59": "accepted",
    "2026-11-01T01:00:00": "refused",  # first of the repeated hour
    "2026-11-01T01:30:00": "refused",
    "2026-11-01T01:59:59": "refused",
    "2026-11-01T02:00:00": "accepted",
    "2027-03-14T01:59:59": "accepted",
    "2027-03-14T02:30:00": "refused",  # skipped by the spring-forward
    "2027-03-14T03:00:00": "accepted",
    "2026-10-20T01:30:00": "accepted",
}


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_nightly_retrain_refuses_ambiguous_and_nonexistent_run_times():
    payload = _run(
        NIGHTLY_PROBE,
        {
            "DST_AUDIT_SCRIPT": str(OPS / "register_nightly_retrain.ps1"),
            "DST_RUN_AT": ",".join(NIGHTLY_RUN_AT),
        },
    )

    # DST-L11: AssumeLocal parsing accepted 01:30 on 2026-11-01 (two instants)
    # and 02:30 on 2027-03-14 (none) for a one-shot with no late catch-up.
    assert payload == NIGHTLY_RUN_AT, payload


def test_fixture_instants_match_their_stated_real_order():
    # The suite-gate fixtures' "ok" verdicts rest on these real orders.
    run = datetime(2026, 11, 1, 1, 59, 50, tzinfo=TORONTO)
    log = datetime(2026, 11, 1, 1, 0, 5, tzinfo=TORONTO, fold=1)
    assert (log.astimezone(timezone.utc) - run.astimezone(timezone.utc)).total_seconds() == 15
