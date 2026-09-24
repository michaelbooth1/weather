"""Exercise monitor helpers against synthetic evidence, never the live host scripts."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell contract")
NOW = "2026-09-24T14:00:00Z"


def ps(script, functions, body, tmp_path):
    source = ROOT / "scripts" / "ops" / script
    runner = tmp_path / "runner.ps1"
    names = ",".join("'" + name + "'" for name in functions)
    runner.write_text(
        "$ErrorActionPreference='Stop'\n"
        "$tokens=$null; $errors=$null\n"
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{source}',[ref]$tokens,[ref]$errors)\n"
        "if($errors.Count){throw ($errors | Out-String)}\n"
        f"$names=@({names})\n"
        "$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in $names},$true) | ForEach-Object {Invoke-Expression $_.Extent.Text}\n"
        f"$root='{tmp_path}'\n" + body,
        encoding="utf-8-sig",
    )
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(runner)],
        capture_output=True, text=True, timeout=20,
    )


@pytest.mark.parametrize("case", ["critical", "warn", "clean", "missing", "malformed", "count", "stale"])
def test_sweep_rows_drive_verdict(case, tmp_path):
    critical = case in {"critical", "count"}
    content = (
        "# Staleness sweep\nGenerated 2026-09-24 09:00. Regenerated every run; do not edit.\n"
        f"**Verdict: {'CRITICAL' if critical else 'WARN' if case == 'warn' else 'OK'}** - {1 if critical else 0} critical, 0 warn, 1 checks.\n"
    )
    if case in {"critical", "warn"}:
        content += f"| **{'CRITICAL' if critical else 'WARN'}** | `learning/daily_learning` | stale for 42 days | cannot learn |\n"
    if case == "malformed":
        content = "truncated snapshot"
    if case == "stale":
        content = content.replace("2026-09-24", "2026-09-20")
    if case != "missing":
        (tmp_path / "sweep.md").write_text(content, encoding="utf-8")
    result = ps("status.ps1", ["Get-WeatherSweepFlags"], """
$flags=@(Get-WeatherSweepFlags -Path (Join-Path $root 'sweep.md') -Now ([datetime]'2026-09-24T10:00:00'))
$flags | ConvertTo-Json -Compress
if($flags.Count){exit 2}else{exit 0}
""", tmp_path)
    assert result.returncode == (0 if case in {"clean", "warn"} else 2), result.stderr
    if critical and case != "count":
        assert "learning/daily_learning" in result.stdout
    source = (ROOT / "scripts/ops/status.ps1").read_text()
    assert "$flags.Add($sweepFlag)" in source
    assert '$exitCode = if ($flags.Count -gt 0) { 2 } else { 0 }' in source


def retirement_fixture(tmp_path, case):
    marker = dict(schema="quiet_window_merge_in_progress_v0.1", updated_at="2026-09-24T04:45:29Z",
                  repo_root="C:/production", phase="prepared", operation_mode="ordinary_synchronized_merge_v0.1",
                  branch="origin/codex/example", expected_tip="a" * 40, expected_baseline="b" * 40,
                  baseline_commit="b" * 40, pre_merge_commit="c" * 40, merge_commit=None)
    report = {**marker, "schema": "quiet_window_merge_report_v0.2", "ts": "2026-09-24T04:45:30Z", "stage": "rollback_recovery_failed"}
    if case == "other_attempt":
        report["pre_merge_commit"] = "d" * 40
    if case == "incident":
        marker["operation_mode"] = "production_baseline_reconciliation_v0.1"
    if case == "merged":
        marker["merge_commit"] = "d" * 40
    raw = json.dumps(marker)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    receipt = dict(schema="owner_approved_marker_retirement_v0", at="2026-09-24T13:14:12Z",
                   approval="owner approved", head="b" * 40, merge_head_present=False, dirty_tracked=["config/locations.json"],
                   marker_sha256=digest, marker_bytes={"value": raw}, conditions_ok=True)
    if case.startswith("agent"):
        receipt.update(schema="agent_marker_retirement_v0", origin_master="b" * 40, capture_healthy=True, marker_bytes=raw)
    if case == "agent_unhealthy":
        receipt["capture_healthy"] = False
    if case == "wrong_hash":
        receipt["marker_sha256"] = "0" * 64
    if case == "report_hash":
        report["marker_sha256"] = "0" * 64
    if case == "new_hash":
        report["marker_sha256"] = digest
    if case == "old":
        receipt["at"] = "2026-09-23T13:14:12Z"
    if case == "future":
        receipt["at"] = "2026-09-25T13:14:12Z"
    if case == "distant":
        report["ts"] = "2026-09-24T06:45:30Z"
    if case == "unapproved":
        receipt["approval"] = ""
    if case == "string_bool":
        receipt["conditions_ok"] = "true"
    if case == "dry":
        receipt["dry_run"] = True
    if case == "active":
        (tmp_path / "active.json").write_text(raw)
    (tmp_path / "report.json").write_text(json.dumps(report))
    prefix = "agent" if case.startswith("agent") else "owner-approved"
    (tmp_path / f"{prefix}-retire-example.json").write_text(json.dumps(receipt))


@pytest.mark.parametrize("case", ["owner", "agent", "new_hash", "wrong_hash", "report_hash", "other_attempt", "incident", "merged", "agent_unhealthy", "old", "future", "distant", "unapproved", "string_bool", "dry", "active"])
def test_retirement_exact_bytes_and_attempt(case, tmp_path):
    retirement_fixture(tmp_path, case)
    result = ps("status.ps1", ["Find-WeatherQuietMergeRetirement"], f"""
$report=Get-Content (Join-Path $root 'report.json') -Raw | ConvertFrom-Json
$found=Find-WeatherQuietMergeRetirement -Directory $root -Report $report -ActiveMarkerPath (Join-Path $root 'active.json') -Now ([datetimeoffset]'{NOW}')
if($found){{$found | ConvertTo-Json -Compress;exit 0}}else{{exit 2}}
""", tmp_path)
    assert result.returncode == (0 if case in {"owner", "agent", "new_hash"} else 2), result.stderr


@pytest.mark.parametrize("case", ["unregistered", "disabled", "empty", "fresh", "warn", "critical", "error", "future", "heartbeat"])
def test_reward_records_not_heartbeat(case, tmp_path):
    task = "$null" if case == "unregistered" else "([pscustomobject]@{State='" + ("Disabled" if case == "disabled" else "Running") + "'})"
    folder = tmp_path / "2026-09-24" / "13-0123456789ab"
    folder.mkdir(parents=True)
    if case not in {"empty", "heartbeat"}:
        at = {"warn": "13:50:00", "critical": "13:30:00", "future": "14:01:00"}.get(case, "13:59:00")
        row = dict(kind="rewards", http_status=500 if case == "error" else 200,
                   captured_at_utc=f"2026-09-24T{at}Z", content_sha256="e" * 64)
        # A large prior body and malformed final line must not hide a complete fresh record.
        (folder / "reward-example.jsonl").write_text("x" * 40000 + "\n" + json.dumps(row) + "\n{partial")
    (tmp_path / "status.json").write_text(json.dumps(dict(updated_at_utc=NOW, state="RUNNING")))
    result = ps("staleness_sweep.ps1", ["Get-WeatherRewardCaptureFinding"],
                f"Get-WeatherRewardCaptureFinding -Root $root -Task {task} -Now ([datetimeoffset]'{NOW}') | ConvertTo-Json -Compress", tmp_path)
    assert result.returncode == 0, result.stderr
    finding = json.loads(result.stdout)
    assert finding["severity"] == {"fresh": "OK", "warn": "WARN"}.get(case, "CRITICAL")
    if case == "unregistered":
        assert "no producer registered" in finding["detail"]


def test_watchdog_rotates_without_rewriting_and_reads_archive_tail(tmp_path):
    log = tmp_path / "host_health_alerts.jsonl"
    old = b'x' * 2048 + b'\n{"ts":"2026-09-24T13:00:00Z","top_severity":"CRITICAL"}\n'
    log.write_bytes(old)
    result = ps("health_watchdog.ps1", ["Add-WeatherWatchdogLog", "Read-WeatherWatchdogTail"], f"""
$path=Join-Path $root 'host_health_alerts.jsonl'
Add-WeatherWatchdogLog -Path $path -Line '{{"top_severity":"OK"}}' -MaxBytes 512 -Now ([datetimeoffset]'{NOW}')
$archive=Get-ChildItem -LiteralPath $root -Filter 'host_health_alerts.*.jsonl'
Read-WeatherWatchdogTail -Path $archive.FullName -MaxBytes 256
Add-WeatherWatchdogLog -Path $path -Line '{{"top_severity":"HIGH"}}' -MaxBytes 512 -Now ([datetimeoffset]'{NOW}')
""", tmp_path)
    assert result.returncode == 0, result.stderr
    archives = list(tmp_path.glob("host_health_alerts.*.jsonl"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == old
    assert [json.loads(s)["top_severity"] for s in log.read_text().splitlines()] == ["OK", "HIGH"]
    assert "CRITICAL" in result.stdout and "xxx" not in result.stdout


def test_watchdog_failed_rotation_never_appends_oversized_file(tmp_path):
    log = tmp_path / "host_health_alerts.jsonl"
    log.write_bytes(b"x" * 1024)
    result = ps("health_watchdog.ps1", ["Add-WeatherWatchdogLog"], """
$path=Join-Path $root 'host_health_alerts.jsonl'
$held=[IO.File]::Open($path,'Open','Read','Read')
try { Add-WeatherWatchdogLog -Path $path -Line '{}' -MaxBytes 512 } finally { $held.Dispose() }
""", tmp_path)
    assert result.returncode != 0
    assert log.read_bytes() == b"x" * 1024
