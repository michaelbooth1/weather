"""Bounded execution-tape probe: quiet-window binding, resource bounds and capture survival.

Guards: docs/ops/streak-soak.md "Bounded execution-tape proof", including the snapshot
iteration proof (SNAP-HB Defender finding 1: the snapshot heartbeat is liveness only once the
loop beats every 60 s of its idle sleep, so progress must come from
last_completed_iteration_at).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "bounded_execution_tape_probe.ps1"
WINDOWS_POWERSHELL = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="requires Windows PowerShell",
)

# Extracts the named functions from the real script with the PowerShell parser
# and evaluates every case in one child, so the tests execute the shipped
# functions rather than matching their text.
FUNCTION_LOADER = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:PROBE_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'bounded_execution_tape_probe.ps1 does not parse' }
foreach ($name in @($env:PROBE_FUNCTIONS -split ',')) {
    $function = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $function) { throw "missing $name" }
    Invoke-Expression $function.Extent.Text
}
"""

PROOF_HARNESS = FUNCTION_LOADER + r"""
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PROBE_CASES)) |
    ConvertFrom-Json
$results = [ordered]@{}
foreach ($case in @($cases)) {
    # Round-trip each status through JSON text exactly as the probe reads loop_status.json.
    $before = ($case.before | ConvertTo-Json -Depth 4) | ConvertFrom-Json
    $after = ($case.after | ConvertTo-Json -Depth 4) | ConvertFrom-Json
    $results[[string]$case.name] = Get-SnapshotIterationProof -Before $before -After $after `
        -BeforeReadUtc ([datetimeoffset]::Parse([string]$case.before_read)) `
        -AfterReadUtc ([datetimeoffset]::Parse([string]$case.after_read))
}
$results | ConvertTo-Json -Depth 5 -Compress
"""

T0 = datetime(2026, 7, 14, 6, 20, tzinfo=timezone.utc)  # 02:20 Toronto, inside 01:00-04:00
PROBE_SECONDS = 790  # default 780 s capture plus wrapper overhead
BOUND = 600 + 540 + 120  # interval + fleet budget + slack at production defaults


def _at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def _status(heartbeat, completed, *, interval=10.0, fleet_budget=540.0) -> dict:
    return {
        "pid": 4242,
        "interval_minutes": interval,
        "capture_execution": {"fleet_budget_seconds": fleet_budget},
        "last_heartbeat": heartbeat,
        "last_completed_iteration_at": completed,
    }


def _case(name, before, after, elapsed=PROBE_SECONDS) -> dict:
    return {
        "name": name,
        "before": before,
        "after": after,
        "before_read": _at(0),
        "after_read": _at(elapsed),
    }


PROOF_CASES = [
    # Healthy default probe: a cycle completed during the run, heartbeat fresh.
    _case(
        "healthy_advanced",
        _status(_at(-30), _at(-200)),
        _status(_at(PROBE_SECONDS - 40), _at(PROBE_SECONDS - 500)),
    ),
    # Healthy loop whose completions are > 780 s apart (short batch, then a long
    # one still running): no advance inside the default window, yet healthy.
    _case(
        "healthy_no_advance_inside_short_probe",
        _status(_at(-20), _at(-160)),
        _status(_at(PROBE_SECONDS - 3), _at(-160)),
    ),
    # Defender finding 1: probe starts 10 s into a 288 s sleep, the loop wedges
    # at the next iteration start; sleep beats at +50..+230 advanced the old
    # heartbeat proof. Heartbeat age is now 560 s > 300 s.
    _case(
        "wedged_after_sleep_beats",
        _status(_at(-10), _at(-10)),
        _status(_at(230), _at(-10)),
    ),
    # A batch that keeps emitting progress beats but never completes.
    _case(
        "masked_batch_never_completes",
        _status(_at(-5), _at(PROBE_SECONDS - BOUND - 1)),
        _status(_at(PROBE_SECONDS - 3), _at(PROBE_SECONDS - BOUND - 1)),
    ),
    _case(
        "completion_age_exactly_at_bound",
        _status(_at(-5), _at(PROBE_SECONDS - BOUND)),
        _status(_at(PROBE_SECONDS - 3), _at(PROBE_SECONDS - BOUND)),
    ),
    _case(
        "heartbeat_age_exactly_at_limit",
        _status(_at(-5), _at(-100)),
        _status(_at(PROBE_SECONDS - 300), _at(PROBE_SECONDS - 400)),
    ),
    _case(
        "heartbeat_age_just_over_limit",
        _status(_at(-5), _at(-100)),
        _status(_at(PROBE_SECONDS - 300.5), _at(PROBE_SECONDS - 400)),
    ),
    # A probe run at least the bound long must see an advance explicitly.
    _case(
        "long_probe_advanced",
        _status(_at(-5), _at(-100)),
        _status(_at(BOUND + 10 - 20), _at(BOUND + 10 - 300)),
        elapsed=BOUND + 10,
    ),
    _case(
        "long_probe_not_advanced",
        _status(_at(-5), _at(-1)),
        _status(_at(BOUND + 10 - 20), _at(-1)),
        elapsed=BOUND + 10,
    ),
    _case(
        "never_completed",
        _status(_at(-5), None),
        _status(_at(PROBE_SECONDS - 3), None),
    ),
    _case(
        "future_completion",
        _status(_at(-5), _at(-100)),
        _status(_at(PROBE_SECONDS - 3), _at(PROBE_SECONDS + 30)),
    ),
    # N1: a heartbeat newer than the probe's final read (clock skew or a
    # future-dated write) is not liveness evidence and must fail closed.
    _case(
        "future_heartbeat",
        _status(_at(-5), _at(-100)),
        _status(_at(PROBE_SECONDS + 30), _at(PROBE_SECONDS - 100)),
    ),
    _case(
        "missing_cycle_parameters",
        _status(_at(-5), _at(-100)),
        _status(_at(PROBE_SECONDS - 3), _at(PROBE_SECONDS - 100), interval=None, fleet_budget=None),
    ),
    # Offsets other than UTC (the loop writes isoformat with its offset) compare as instants.
    _case(
        "offset_timestamps_compare_as_instants",
        _status((T0 - timedelta(seconds=30)).astimezone(timezone(timedelta(hours=-4))).isoformat(),
                _at(-200)),
        _status(
            (T0 + timedelta(seconds=PROBE_SECONDS - 40)).astimezone(
                timezone(timedelta(hours=-4))
            ).isoformat(),
            (T0 + timedelta(seconds=PROBE_SECONDS - 500)).astimezone(
                timezone(timedelta(hours=-5))
            ).isoformat(),
        ),
    ),
]


def _run_harness(harness: str, functions: str, cases: list, **extra_env: str) -> dict:
    payload = base64.b64encode(json.dumps(cases).encode("utf-8")).decode("ascii")
    env = {
        **os.environ,
        "PROBE_SCRIPT": str(SCRIPT),
        "PROBE_FUNCTIONS": functions,
        "PROBE_CASES": payload,
        **extra_env,
    }
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", harness],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PowerShell harness failed: {result.stderr.strip() or result.stdout.strip()}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


@pytest.fixture(scope="module")
def proofs() -> dict:
    return _run_harness(PROOF_HARNESS, "ConvertTo-StatusInstant,Get-SnapshotIterationProof", PROOF_CASES)


def _reasons(proof: dict) -> list[str]:
    reasons = proof["reasons"]
    if reasons is None:
        return []
    return [reasons] if isinstance(reasons, str) else list(reasons)


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_snapshot_proof_passes_healthy_loops_without_requiring_advance_in_a_short_probe(proofs):
    advanced = proofs["healthy_advanced"]
    assert advanced["ok"] is True, advanced
    assert advanced["advanced"] is True
    assert advanced["advance_required"] is False
    assert advanced["completion_bound_seconds"] == BOUND
    assert advanced["heartbeat_age_seconds"] == pytest.approx(40.0)
    assert advanced["completed_iteration_age_seconds"] == pytest.approx(500.0)

    waiting = proofs["healthy_no_advance_inside_short_probe"]
    assert waiting["ok"] is True, waiting
    assert waiting["advanced"] is False
    assert waiting["advance_required"] is False


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_snapshot_proof_rejects_a_wedge_masked_by_idle_sleep_beats(proofs):
    proof = proofs["wedged_after_sleep_beats"]
    assert proof["ok"] is False
    assert proof["heartbeat_age_seconds"] == pytest.approx(560.0)
    assert any("heartbeat age 560.0s" in reason for reason in _reasons(proof)), proof
    # The completion is only 800 s old, inside the bound: the heartbeat guard alone fires.
    assert len(_reasons(proof)) == 1


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_snapshot_proof_rejects_progress_beats_without_a_completed_iteration(proofs):
    masked = proofs["masked_batch_never_completes"]
    assert masked["ok"] is False
    assert _reasons(masked) == [
        f"snapshot last completed iteration age {BOUND + 1:.1f}s is outside 0..{BOUND}s"
    ]
    edge = proofs["completion_age_exactly_at_bound"]
    assert edge["ok"] is True, edge


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_snapshot_proof_heartbeat_limit_is_300_seconds_inclusive(proofs):
    assert proofs["heartbeat_age_exactly_at_limit"]["ok"] is True
    over = proofs["heartbeat_age_just_over_limit"]
    assert over["ok"] is False
    assert len(_reasons(over)) == 1
    assert over["heartbeat_max_age_seconds"] == 300


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_snapshot_proof_requires_advance_once_the_probe_spans_the_completion_bound(proofs):
    advanced = proofs["long_probe_advanced"]
    assert advanced["ok"] is True, advanced
    assert advanced["advance_required"] is True
    assert advanced["advanced"] is True
    stuck = proofs["long_probe_not_advanced"]
    assert stuck["ok"] is False
    assert stuck["advance_required"] is True
    assert "snapshot last_completed_iteration_at did not advance during probe" in _reasons(stuck)


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_snapshot_proof_fails_closed_on_missing_or_future_evidence(proofs):
    assert _reasons(proofs["never_completed"]) == [
        "snapshot last_completed_iteration_at is missing or unparseable"
    ]
    assert proofs["future_completion"]["ok"] is False
    assert proofs["future_completion"]["completed_iteration_age_seconds"] == pytest.approx(-30.0)
    # N1: an unknown completion bound must fail closed, not merely explain itself.
    # With the bound unknown the completion-age check is skipped, so ok is the only guard.
    missing_proof = proofs["missing_cycle_parameters"]
    assert missing_proof["ok"] is False, missing_proof
    assert missing_proof["advance_required"] is False
    missing = _reasons(missing_proof)
    assert "snapshot status has no positive interval_minutes" in missing
    assert "snapshot status has no positive capture_execution.fleet_budget_seconds" in missing
    # The completion itself is fresh: the missing parameters are the only failure.
    assert len(missing) == 2, missing


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_snapshot_proof_rejects_a_heartbeat_newer_than_the_final_read(proofs):
    proof = proofs["future_heartbeat"]
    assert proof["ok"] is False, proof
    assert proof["heartbeat_age_seconds"] == pytest.approx(-30.0)
    assert _reasons(proof) == ["snapshot heartbeat age -30.0s is outside 0..300s"]


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_snapshot_proof_compares_offset_timestamps_as_instants(proofs):
    proof = proofs["offset_timestamps_compare_as_instants"]
    assert proof["ok"] is True, proof
    assert proof["heartbeat_age_seconds"] == pytest.approx(40.0)
    assert proof["completed_iteration_age_seconds"] == pytest.approx(500.0)
    assert proof["advanced"] is True


# Get-HealthyCaptureWorkerCount run end to end against a temporary data\snapshots
# tree whose loop_status.json and writer lock name this PowerShell process, so
# only the heartbeat age decides. Timestamps are written as JSON strings and read
# back through Get-Content | ConvertFrom-Json exactly as on the host (Windows
# PowerShell 5.1 leaves them as strings).
WORKER_HARNESS = FUNCTION_LOADER + r"""
$RepoRoot = $env:PROBE_REPO_ROOT
$snapshotRoot = Join-Path $RepoRoot 'data\snapshots'
New-Item -ItemType Directory -Force -Path $snapshotRoot | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $snapshotRoot '.loop_status.json.writer.lock'),
    (@{ pid = $PID } | ConvertTo-Json -Compress), $utf8)
$cases = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($env:PROBE_CASES)) |
    ConvertFrom-Json
$results = [ordered]@{}
foreach ($case in @($cases)) {
    $status = '{"pid": ' + $PID + ', "last_heartbeat": "' + [string]$case.heartbeat + '"}'
    [IO.File]::WriteAllText((Join-Path $snapshotRoot 'loop_status.json'), $status, $utf8)
    $results[[string]$case.name] = Get-HealthyCaptureWorkerCount `
        -Now ([datetimeoffset]::Parse([string]$case.now, [Globalization.CultureInfo]::InvariantCulture))
}
$results | ConvertTo-Json -Compress
"""

# Toronto falls back at 2026-11-01 06:00Z: 01:59:59 EDT (-04:00) is followed by
# 01:00:00 EST (-05:00), so 01:00-02:00 local repeats inside the 01:00-04:00 probe
# window. "now" is given in the host's local offset, as Get-Date would show it.
WORKER_CASES = [
    # 150 s real age; a wall-clock difference reads -57.5 min (spurious unhealthy).
    {"name": "fresh_across_fall_back", "heartbeat": "2026-11-01T01:58:00-04:00",
     "now": "2026-11-01T01:00:30-05:00"},
    # 62 min real age; a wall-clock difference reads 120 s (falsely healthy).
    {"name": "stale_hour_hidden_by_fall_back", "heartbeat": "2026-11-01T01:10:00-04:00",
     "now": "2026-11-01T01:12:00-05:00"},
    {"name": "exactly_300_across_fall_back", "heartbeat": "2026-11-01T01:57:00-04:00",
     "now": "2026-11-01T01:02:00-05:00"},
    {"name": "just_over_300_across_fall_back", "heartbeat": "2026-11-01T01:56:59-04:00",
     "now": "2026-11-01T01:02:00-05:00"},
    # Written after fall-back, read "before" it on the clock face: 6 min in the future.
    {"name": "future_heartbeat", "heartbeat": "2026-11-01T01:05:00-05:00",
     "now": "2026-11-01T01:59:00-04:00"},
    {"name": "utc_heartbeat", "heartbeat": "2026-11-01T05:59:00+00:00",
     "now": "2026-11-01T01:01:00-05:00"},
    {"name": "unparseable_heartbeat", "heartbeat": "not-a-time",
     "now": "2026-11-01T01:01:00-05:00"},
]


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_worker_count_ages_snapshot_heartbeat_on_utc_instants_across_fall_back(tmp_path):
    counts = _run_harness(
        WORKER_HARNESS,
        "ConvertTo-StatusInstant,Get-HealthyCaptureWorkerCount",
        WORKER_CASES,
        PROBE_REPO_ROOT=str(tmp_path),
    )
    # Only the snapshot worker's files exist, so a healthy snapshot worker counts 1.
    assert counts == {
        "fresh_across_fall_back": 1,
        "stale_hour_hidden_by_fall_back": 0,
        "exactly_300_across_fall_back": 1,
        "just_over_300_across_fall_back": 0,
        "future_heartbeat": 0,
        "utc_heartbeat": 1,
        "unparseable_heartbeat": 0,
    }


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_probe_is_exact_commit_and_quiet_window_bound() -> None:
    script = _text()

    assert '[ValidatePattern("^[0-9a-fA-F]{40}$")]' in script
    assert "[int]$DurationSeconds = 780" in script
    assert "production HEAD must equal origin/master before the probe" in script
    assert "merge-base --is-ancestor $RequiredAncestor $head" in script
    assert "probe must start inside the 01:00-04:00 quiet window" in script


def test_probe_owns_child_and_enforces_resource_bounds() -> None:
    script = _text()

    assert "windows_kill_on_close_job.ps1" in script
    assert "Start-WeatherProcessInJob" in script
    assert '@{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 300 }' in script
    assert '@{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180 }' in script
    assert '@{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180 }' in script
    assert "working set $workingSetMB MB exceeds" in script
    assert "host commit $commit% exceeds abort ceiling" in script


def test_probe_requires_new_rows_connected_seed_set_and_clean_integrity() -> None:
    script = _text()

    assert '[string]$Status.state -ne "CONNECTED"' in script
    assert "$activeRows.Count -ne $expectedCount" in script
    assert '[string]$row.connection_state -ne "CONNECTED"' in script
    assert "connected_seed_set_proved" in script
    assert "evidence_integrity" not in script
    assert "bounded capture produced no new execution observations" in script
    assert 'foreach ($name in @("parse_rejections", "unrouted_trades", "ambiguous_routes"))' in script


def test_probe_requires_clean_stop_and_capture_survival() -> None:
    script = _text()

    assert '[string]$final.state -ne "STOPPED"' in script
    assert "capture worker health degraded during probe" in script
    assert "snapshot heartbeat did not advance during probe" not in script
    assert "Get-SnapshotIterationProof -Before $snapshotBefore -After $snapshotAfter" in script
    assert "snapshot iteration proof failed during probe" in script


def test_probe_persists_latest_and_append_only_history() -> None:
    script = _text()

    assert "execution_tape_probe_last.json" in script
    assert "execution_tape_probe_history.jsonl" in script
    assert "Set-Content -LiteralPath $ReportPath" in script
    assert "Add-Content -LiteralPath $HistoryPath" in script
