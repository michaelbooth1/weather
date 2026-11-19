"""Guards: T115 capture-integrity escalation and early metadata warnings."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.powershell_host import run_command


ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.spawns, pytest.mark.skipif(os.name != "nt", reason="Windows host health")]


def signal_function():
    script = ROOT / "scripts/ops/status.ps1"
    return f"""
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw ($errors | Out-String) }}
$fn=@($ast.FindAll({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-WeatherCaptureHealthSignals'}}, $true))[0]
Invoke-Expression $fn.Extent.Text
"""


@pytest.mark.parametrize("age,result,warn_count", [(24, 0, 0), (24.01, 0, 1), (12, 1, 1), (25, 1, 2)])
def test_metadata_warning_boundaries(age, result, warn_count):
    body = signal_function() + f"""
$now=[datetimeoffset]'2026-11-15T14:00:00-05:00'
$metadata=@{{generated_at_utc=$now.AddHours(-{age}).ToString('o')}}
Get-WeatherCaptureHealthSignals -LoopStatus @{{}} -EventMetadata $metadata -RefreshLastResult {result} -Now $now | ConvertTo-Json -Depth 6
"""
    completed = run_command(body)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["flags"] == []
    assert len(payload["warns"]) == warn_count


@pytest.mark.parametrize("as_of,severity", [("2026-11-15T11:59:00", "HIGH"),
                                          ("2026-11-15T12:00:00", "CRITICAL"),
                                          ("2026-11-15T17:59:00", "CRITICAL"),
                                          ("2026-11-15T18:00:00", "HIGH")])
def test_blocked_liveness_reaches_host_health_alert(tmp_path, as_of, severity):
    ops = tmp_path / "scripts/ops"
    ops.mkdir(parents=True)
    watchdog = ops / "health_watchdog.ps1"
    watchdog.write_bytes((ROOT / "scripts/ops/health_watchdog.ps1").read_bytes())
    # Run the real status interpretation inside the watchdog's subprocess;
    # gathering is fixture-only, with no production files or Scheduler access.
    (ops / "status.ps1").write_text(
        "param([string]$RepoRoot, [switch]$Json)\n" + signal_function() + """
$loop=@{fleet_collection=@{summary=@{capture_liveness=@{status='STALE'; reason='toronto BLOCK: generated location_market_events metadata is 60 hours old'; blocked_market_count=1}}}}
$signals=Get-WeatherCaptureHealthSignals -LoopStatus $loop -EventMetadata @{generated_at_utc='2026-11-14T13:00:00Z'} -RefreshLastResult 1 -Now ([datetimeoffset]'2026-11-15T14:00:00Z')
@{verdict='ATTENTION'; flags=@($signals.flags); warns=@($signals.warns); capture_health=$signals} | ConvertTo-Json -Depth 8
""", encoding="utf-8")
    completed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(watchdog),
                                "-RepoRoot", str(tmp_path), "-AsOf", as_of],
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == (2 if severity == "CRITICAL" else 0), completed.stderr
    latest = json.loads((tmp_path / "data/alerts/host_health_latest.json").read_text(encoding="utf-8-sig"))
    integrity = [a for a in latest["alerts"] if a["class"] == "capture_integrity"]
    assert len(integrity) == 1 and integrity[0]["severity"] == severity
    assert "60 hours old" in integrity[0]["flag"]
    warnings = [a for a in latest["alerts"] if a["class"] == "event_metadata"]
    assert len(warnings) == 2 and all(a["severity"] == "WARN" for a in warnings)
    assert latest["capture_health"]["capture_liveness"]["blocked_market_count"] == 1


def test_status_gathers_liveness_metadata_and_refresh_result(tmp_path):
    snapshots = tmp_path / "data/snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / "loop_status.json").write_text(json.dumps({"fleet_collection": {"summary": {
        "capture_liveness": {"status": "STALE", "reason": "toronto: no snapshots written"}}}}))
    config = tmp_path / "config"
    config.mkdir()
    (config / "location_market_events.json").write_text('{"generated_at_utc":"2000-01-01T00:00:00Z"}')
    source = (ROOT / "scripts/ops/status.ps1").read_text()
    gathering = source.split("# Inspect data flow independently of the process/heartbeat checks above.\n", 1)[1].split("foreach ($c in $caps.Keys)", 1)[0]
    completed = run_command(signal_function() + f"""
$repo='{tmp_path}'; $captureRoot='{snapshots}'
$flags=New-Object System.Collections.Generic.List[string]
$warns=New-Object System.Collections.Generic.List[string]
function Get-ScheduledTaskInfo {{ param($TaskName, $ErrorAction) if ($TaskName -ne 'WeatherLocationConfigRefresh') {{ throw 'unexpected task' }}; @{{LastTaskResult=1}} }}
""" + gathering + "\n@{flags=@($flags); warns=@($warns)} | ConvertTo-Json -Depth 6")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert len(payload["flags"]) == 1 and "no snapshots written" in payload["flags"][0]
    assert len(payload["warns"]) == 2
