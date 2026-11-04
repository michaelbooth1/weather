"""Exercise monitor helpers against synthetic evidence, never the live host scripts."""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
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


# (manifest status or None/"malformed", manifest age h, report text or None, report age h, severity, source)
STAGE_A_CASES = {
    "completed_fresh": ("COMPLETED", 22, "Status: **ok**", 22, "OK", "manifest"),
    "completed_old": ("COMPLETED", 36, "Status: **ok**", 36, "WARN", "manifest"),
    "completed_stale": ("COMPLETED", 60, "Status: **ok**", 60, "CRITICAL", "manifest"),
    # The defect: killed at 11:55 after per-step checkpoints, so the report is fresh.
    "killed_with_fresh_report": ("RUNNING", 20, "Status: **running**", 20, "CRITICAL", "manifest"),
    "killed_report_says_ok": ("RUNNING", 20, "Status: **ok**", 1, "CRITICAL", "manifest"),
    "running_now": ("RUNNING", 0.5, "Status: **running**", 0.5, "WARN", "manifest"),
    "error_status": ("ERROR", 20, "Status: **error**", 20, "CRITICAL", "manifest"),
    "missing_manifest_running_report": (None, 0, "Status: **running**", 1, "CRITICAL", "report"),
    "missing_manifest_finished_report": (None, 0, "Status: **ok**", 20, "OK", "report"),
    "malformed_manifest_running_report": ("malformed", 1, "Status: **running**", 1, "CRITICAL", "report"),
    "missing_both": (None, 0, None, 0, "CRITICAL", "none"),
}


@pytest.mark.spawns
@pytest.mark.parametrize("case", sorted(STAGE_A_CASES))
def test_stage_a_chain_completion_uses_manifest_not_report_mtime(case, tmp_path):
    status, manifest_age, report, report_age, severity, source = STAGE_A_CASES[case]
    now = datetime(2026, 9, 24, 8, 10)
    manifest_path = tmp_path / "stage_a.json"
    report_path = tmp_path / "daily_refresh_report.md"
    if status == "malformed":
        manifest_path.write_text("{truncated", encoding="utf-8")
    elif status is not None:
        manifest_path.write_text(json.dumps(dict(
            status=status, started_at_utc="2026-09-23T13:30:00+00:00",
            completed_at_utc="2026-09-23T15:40:00+00:00" if status == "COMPLETED" else None,
        )), encoding="utf-8")
    if status is not None:
        stamp = (now - timedelta(hours=manifest_age)).timestamp()
        os.utime(manifest_path, (stamp, stamp))
    if report is not None:
        report_path.write_text(f"# Daily Refresh\n\n{report}\n", encoding="utf-8")
        stamp = (now - timedelta(hours=report_age)).timestamp()
        os.utime(report_path, (stamp, stamp))
    result = ps("staleness_sweep.ps1", ["Get-WeatherStageAChainFinding"],
                "Get-WeatherStageAChainFinding -ManifestPath (Join-Path $root 'stage_a.json') "
                "-ReportPath (Join-Path $root 'daily_refresh_report.md') "
                f"-Now ([datetime]'{now.isoformat()}') | ConvertTo-Json -Compress", tmp_path)
    assert result.returncode == 0, result.stderr
    finding = json.loads(result.stdout)
    assert (finding["severity"], finding["source"]) == (severity, source), finding
    source_text = (ROOT / "scripts/ops/staleness_sweep.ps1").read_text(encoding="utf-8-sig")
    assert 'Test-FileAge "chain/daily_refresh_report"' not in source_text
    assert "daily_refresh_settlement_truth_manifest.json" in source_text


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


def test_maker_evidence_age_is_utc_not_local(tmp_path):
    # 2026-09-25: [datetime] parsed "+00:00" as local time, so a fresh status read 14,404 s old.
    line = next(
        row.strip()
        for row in (ROOT / "scripts" / "ops" / "status.ps1").read_text(encoding="utf-8-sig").splitlines()
        if row.strip().startswith("$makerAge = ")
    )
    runner = tmp_path / "age.ps1"
    runner.write_text(
        "$makerEvidence=[pscustomobject]@{updated_at_utc=(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffff+00:00')}\n"
        + line
        + "\n[Console]::Out.Write([int]$makerAge)\n",
        encoding="utf-8-sig",
    )
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(runner)],
        capture_output=True, text=True, check=True,
    ).stdout
    assert abs(int(out)) < 60


def _capture_family_block(tmp_path, tasks, payload, exit_code=0):
    source = (ROOT / "scripts" / "ops" / "status.ps1").read_text(encoding="utf-8-sig")
    start = source.index("$captureFamilies = @()")
    end = source.index('catch { $flags.Add("CAPTURE_FAMILY status check failed to run") }')
    block = source[start:end] + 'catch { $flags.Add("CAPTURE_FAMILY status check failed to run") }'
    (tmp_path / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    task_rows = "".join(f"[pscustomobject]@{{TaskName='{name}';State='{state}'}};" for name, state in tasks)
    runner = tmp_path / "families.ps1"
    runner.write_text(
        "$ErrorActionPreference='Stop'\n"
        "$flags=New-Object System.Collections.Generic.List[string]; $warns=New-Object System.Collections.Generic.List[string]\n"
        f"function Get-ScheduledTask {{ param($TaskName,$ErrorAction) @({task_rows}) | Where-Object {{ $_.TaskName -like $TaskName }} }}\n"
        f"function fakepy {{ $global:seen=$args; Get-Content -Raw '{tmp_path / 'payload.json'}'; $global:LASTEXITCODE={exit_code} }}\n"
        "$py='fakepy'\n" + block + "\n"
        "[Console]::Out.Write((@{flags=@($flags);warns=@($warns);seen=@($global:seen);rows=@($captureFamilies).Count} | ConvertTo-Json -Compress))\n",
        encoding="utf-8-sig",
    )
    out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(runner)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.spawns
def test_status_capture_family_block_forwards_task_states_and_alarm_levels(tmp_path):
    payload = {"families": [{"family": "lowest_temperature", "line": "x"}],
               "flags": ["CAPTURE_FAMILY a: state DEGRADED"],
               "warns": ["CAPTURE_FAMILY b: stopped at its own 70 GiB free-space floor"]}
    result = _capture_family_block(
        tmp_path, [("WeatherMakerEvidenceCapture", "Ready"), ("WeatherMakerEvidenceLowestTemperature", "Disabled"),
                   ("WeatherOther", "Ready"), ("Unrelated", "Ready")], payload)

    assert result["seen"] == ["-m", "weather.reporting.market.capture_family_status",
                              "--task-state", "WeatherMakerEvidenceCapture=Ready",
                              "--task-state", "WeatherMakerEvidenceLowestTemperature=Disabled",
                              "--task-state", "WeatherOther=Ready"]
    # A disk-floor stop arrives as a WARN and stays a note; it never becomes a FLAG.
    assert result["flags"] == payload["flags"] and result["warns"] == payload["warns"] and result["rows"] == 1


@pytest.mark.spawns
def test_status_capture_family_block_flags_when_the_reader_fails(tmp_path):
    result = _capture_family_block(tmp_path, [], {"families": []}, exit_code=1)

    assert result["flags"] == ["CAPTURE_FAMILY status check failed to run"] and result["warns"] == []


# ---- R18: dated known-criticals table in staleness_sweep.ps1 ----
SWEEP = ROOT / "scripts" / "ops" / "staleness_sweep.ps1"
LOAD_KNOWN_TABLE = (
    "$ast.FindAll({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and "
    "$n.Left.Extent.Text -in @('$knownCriticals','$knownCriticalMaxDays')},$false) | ForEach-Object {Invoke-Expression $_.Extent.Text}\n"
)
HELD = {"WeatherEveningEvidenceRefresh": "Disabled", "WeatherTrainingWindow": "Disabled"}
GOOD_ROW = dict(check="learning/daily_learning", producers=list(HELD), recorded="2026-11-04",
                expires="2026-12-31", decision="DL R18")
# id: (row overrides, finding severity or None, producer states, now, disposition)
DISPOSITION_CASES = {
    "held": ({}, "CRITICAL", HELD, "2026-11-20T08:10:00", "KNOWN"),
    "expiry_day": ({}, "CRITICAL", HELD, "2026-12-31T23:59:00", "KNOWN"),
    "expired": ({}, "CRITICAL", HELD, "2027-01-01T08:10:00", "LAPSED"),
    "producer_ready": ({}, "CRITICAL", {**HELD, "WeatherTrainingWindow": "Ready"}, "2026-11-20T08:10:00", "LAPSED"),
    "producer_running": ({}, "CRITICAL", {**HELD, "WeatherEveningEvidenceRefresh": "Running"}, "2026-11-20T08:10:00", "LAPSED"),
    "producer_missing": ({}, "CRITICAL", {"WeatherEveningEvidenceRefresh": "Disabled"}, "2026-11-20T08:10:00", "LAPSED"),
    "state_not_exact": ({}, "CRITICAL", {**HELD, "WeatherTrainingWindow": "disabled"}, "2026-11-20T08:10:00", "LAPSED"),
    "finding_warn": ({}, "WARN", HELD, "2026-11-20T08:10:00", "NONE"),
    "finding_ok": ({}, "OK", HELD, "2026-11-20T08:10:00", "NONE"),
    "no_finding": ({}, None, HELD, "2026-11-20T08:10:00", "NONE"),
    "over_cap": ({"recorded": "2026-10-31"}, "CRITICAL", HELD, "2026-11-20T08:10:00", "MALFORMED"),
    "cap_exact": ({"recorded": "2026-11-01"}, "CRITICAL", HELD, "2026-11-20T08:10:00", "KNOWN"),
    "bad_date": ({"expires": "31/12/2026"}, "CRITICAL", HELD, "2026-11-20T08:10:00", "MALFORMED"),
    "inverted": ({"expires": "2026-11-01"}, "CRITICAL", HELD, "2026-11-20T08:10:00", "MALFORMED"),
    "no_producers": ({"producers": []}, "CRITICAL", HELD, "2026-11-20T08:10:00", "MALFORMED"),
    "no_decision": ({"decision": ""}, "CRITICAL", HELD, "2026-11-20T08:10:00", "MALFORMED"),
    "malformed_even_if_ok": ({"recorded": "2026-01-01"}, "OK", HELD, "2026-11-20T08:10:00", "MALFORMED"),
}


@pytest.mark.spawns
def test_known_critical_disposition_matrix(tmp_path):
    cases = []
    for case_id, (overrides, severity, states, now, _expected) in DISPOSITION_CASES.items():
        cases.append(dict(id=case_id, row={**GOOD_ROW, **overrides}, severity=severity, states=states, now=now))
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    result = ps("staleness_sweep.ps1", ["Get-WeatherKnownCriticalDisposition"], LOAD_KNOWN_TABLE + """
$out=@{}
foreach($c in (Get-Content (Join-Path $root 'cases.json') -Raw | ConvertFrom-Json)){
  $states=@{}; foreach($p in $c.states.PSObject.Properties){$states[$p.Name]=[string]$p.Value}
  $finding=if($c.severity){[pscustomobject]@{check=$c.row.check;severity=[string]$c.severity}}else{$null}
  $out[$c.id]=(Get-WeatherKnownCriticalDisposition -Row $c.row -Finding $finding -ProducerStates $states -Now ([datetime]$c.now) -MaxDays $knownCriticalMaxDays).disposition
}
$shipped=@($knownCriticals | ForEach-Object {
  $f=[pscustomobject]@{check=$_.check;severity='CRITICAL'}
  $s=@{}; foreach($p in $_.producers){$s[$p]='Disabled'}
  [pscustomobject]@{check=$_.check;producers=@($_.producers);decision=$_.decision;expires=$_.expires
    disposition=(Get-WeatherKnownCriticalDisposition -Row $_ -Finding $f -ProducerStates $s -Now ([datetime]$_.recorded) -MaxDays $knownCriticalMaxDays).disposition}
})
@{cases=$out;shipped=$shipped;cap=$knownCriticalMaxDays} | ConvertTo-Json -Depth 5 -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cap"] == 60
    for case_id, spec in DISPOSITION_CASES.items():
        assert payload["cases"][case_id] == spec[4], case_id
    shipped = {row["check"]: row for row in payload["shipped"]}
    assert set(shipped) == {"learning/daily_learning", "learning/market_beating_scoreboard"}
    assert shipped["learning/daily_learning"]["producers"] == ["WeatherEveningEvidenceRefresh", "WeatherTrainingWindow"]
    assert shipped["learning/market_beating_scoreboard"]["producers"] == ["WeatherEveningEvidenceRefresh"]
    for row in shipped.values():
        assert (row["disposition"], row["expires"], row["decision"]) == ("KNOWN", "2026-12-31", "DL R18")


TASK_STUBS = """
function Get-ScheduledTask {
  [CmdletBinding()] param()
  if($env:R18_LIST_FAILS){ throw [System.UnauthorizedAccessException]'access denied' }
  [pscustomobject]@{TaskName='TaskReady';State='Ready'}
  [pscustomobject]@{TaskName='TaskNever';State='Disabled'}
  [pscustomobject]@{TaskName='TaskDenied';State='Ready'}
  [pscustomobject]@{TaskName='Unrelated';State='Ready'}
}
function Get-ScheduledTaskInfo {
  [CmdletBinding()] param([Parameter(ValueFromPipeline=$true)]$InputObject)
  process {
    if($InputObject.TaskName -eq 'TaskDenied'){ throw [System.UnauthorizedAccessException]'access denied' }
    if($InputObject.TaskName -eq 'TaskNever'){ [pscustomobject]@{LastRunTime=[datetime]'1999-11-30';LastTaskResult=267011} }
    else { [pscustomobject]@{LastRunTime=[datetime]::SpecifyKind([datetime]'2026-08-13T01:00:00',[DateTimeKind]::Utc);LastTaskResult=-2147024891} }
  }
}
"""


@pytest.mark.spawns
@pytest.mark.parametrize("case", ["tasks", "unreadable", "list_fails"])
def test_task_results_snapshot_never_aborts(case, tmp_path):
    config = {"tasks": [{"name": n} for n in ["TaskReady", "TaskNever", "TaskAbsent", "TaskDenied"]]}
    (tmp_path / "tasks.json").write_text(json.dumps(config) if case != "unreadable" else "{truncated", encoding="utf-8")
    result = ps("staleness_sweep.ps1", ["Get-WeatherTaskResults"], TASK_STUBS + f"""
$env:R18_LIST_FAILS='{'1' if case == 'list_fails' else ''}'
Get-WeatherTaskResults -ConfigPath (Join-Path $root 'tasks.json') -ExtraNames @('TaskReady','TaskExtra') | ConvertTo-Json -Depth 4 -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    rows = {row["name"]: row for row in payload["rows"]}
    if case == "unreadable":
        assert len(payload["failures"]) == 1 and "scheduled_tasks.json unreadable" in payload["failures"][0]
        assert list(rows) == ["TaskReady", "TaskExtra"]
        return
    assert list(rows) == ["TaskReady", "TaskNever", "TaskAbsent", "TaskDenied", "TaskExtra"]
    if case == "list_fails":
        assert payload["failures"] == ["task list unreadable: access denied"]
        assert all(row["state"] is None and row["last_run_utc"] is None for row in rows.values())
        return
    assert rows["TaskReady"] == {"name": "TaskReady", "last_run_utc": "2026-08-13T01:00:00.0000000Z",
                                 "result_hex": "0x80070005", "state": "Ready"}
    assert rows["TaskNever"]["last_run_utc"] is None and rows["TaskNever"]["result_hex"] == "0x41303"
    assert rows["TaskAbsent"]["state"] == "NotRegistered" and rows["TaskExtra"]["state"] == "NotRegistered"
    assert rows["TaskDenied"]["state"] == "Ready" and rows["TaskDenied"]["result_hex"] is None
    assert len(payload["failures"]) == 1 and payload["failures"][0].startswith("TaskDenied:")
    text = SWEEP.read_text(encoding="utf-8-sig")
    assert "Get-WinEvent" not in text and "Get-EventLog" not in text


def _sweep_report(tmp_path, states, failures=()):
    """Run the shipped post-pass and report block on synthetic findings; parse it with status.ps1."""
    text = SWEEP.read_text(encoding="utf-8-sig")
    (tmp_path / "block.ps1").write_text(text[text.index("# ---- 12. task last-run snapshot"):], encoding="utf-8")
    rows = "".join(
        f"[pscustomobject]@{{name='{n}';last_run_utc='2026-08-13T05:00:00.0000000Z';result_hex='0x0';state='{s}'}};"
        for n, s in states.items())
    fails = ",".join(f"'{f}'" for f in failures)
    body = LOAD_KNOWN_TABLE + f"""
function Get-WeatherTaskResults {{ param($ConfigPath,$ExtraNames) [pscustomobject]@{{rows=@({rows});failures=@({fails})}} }}
$findings=@()
Add-Finding 'learning/daily_learning' 'CRITICAL' 'data\\backtest\\daily_learning.json is 80.0d old' 'rollup why' 80.0 2
Add-Finding 'learning/market_beating_scoreboard' 'CRITICAL' 'data\\backtest\\market_beating_objective_scoreboard.json is 80.0d old' 'scoreboard why' 80.0 2
Add-Finding 'docs/unreachable' 'WARN' '1 of 9 unreachable' 'why' $null $null
Add-Finding 'settlement/latest' 'OK' 'fresh' 'why' 1 2
$repo=$root; $now=[datetime]'2026-11-10T08:10:00'
$JsonOut=Join-Path $root 'sweep.jsonl'; $MarkdownOut=Join-Path $root 'sweep.md'
$ErrorActionPreference='Continue'
. ([scriptblock]::Create([IO.File]::ReadAllText((Join-Path $root 'block.ps1'))))
"""
    result = ps("staleness_sweep.ps1", ["Add-Finding", "Get-WeatherKnownCriticalDisposition"], body, tmp_path)
    md = (tmp_path / "sweep.md").read_text(encoding="utf-8-sig")
    record = json.loads((tmp_path / "sweep.jsonl").read_text(encoding="utf-8-sig").splitlines()[-1])
    flags = ps("status.ps1", ["Get-WeatherSweepFlags"], """
@(Get-WeatherSweepFlags -Path (Join-Path $root 'sweep.md') -Now ([datetime]'2026-11-10T09:00:00')) | ConvertTo-Json -Compress
""", tmp_path)
    assert flags.returncode == 0, flags.stderr
    parsed = json.loads(flags.stdout) if flags.stdout.strip() else []
    return result, md, record, parsed if isinstance(parsed, list) else [parsed]


@pytest.mark.spawns
def test_held_known_criticals_leave_the_critical_table_and_status_flags(tmp_path):
    result, md, record, flags = _sweep_report(tmp_path, HELD)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "**Verdict: WARN** - 0 critical, 1 warn, 2 known, 4 checks." in md
    known = md[md.index("## Known"):md.index("## All checks")]
    assert ("| `learning/daily_learning` | 80.0d | WeatherEveningEvidenceRefresh Disabled, last run "
            "2026-08-13T05:00:00.0000000Z; WeatherTrainingWindow Disabled") in known
    assert "| 2026-12-31 | DL R18 |" in known
    assert "| **CRITICAL** |" not in md and "| **KNOWN** |" not in md
    assert flags == []
    assert (record["verdict"], record["critical_count"], record["warn_count"], record["known_count"]) == ("WARN", 0, 1, 2)
    assert {f["check"]: f["severity"] for f in record["findings"]} == {
        "learning/daily_learning": "KNOWN", "learning/market_beating_scoreboard": "KNOWN", "docs/unreachable": "WARN"}
    assert {t["name"] for t in record["task_results"]} == set(HELD)
    # The console lists only CRITICAL and WARN rows.
    assert [line.strip() for line in result.stdout.splitlines() if line.startswith("  [")] == [
        "[WARN] docs/unreachable: 1 of 9 unreachable"]


@pytest.mark.spawns
def test_an_unheld_known_critical_stays_critical_and_adds_a_lapsed_row(tmp_path):
    states = {**HELD, "WeatherTrainingWindow": "Ready"}
    result, md, record, flags = _sweep_report(tmp_path, states, failures=["TaskDenied: access denied"])
    assert result.returncode == 2, result.stdout + result.stderr
    assert "**Verdict: CRITICAL** - 2 critical, 2 warn, 1 known, 6 checks." in md
    assert sorted(f.split("]")[0] for f in flags) == [
        "STALENESS_SWEEP CRITICAL [known/lapsed", "STALENESS_SWEEP CRITICAL [learning/daily_learning"]
    assert any("learning/daily_learning: producer WeatherTrainingWindow is Ready, not Disabled" in f for f in flags)
    assert (record["critical_count"], record["warn_count"], record["known_count"]) == (2, 2, 1)
    assert {f["check"]: f["severity"] for f in record["findings"]}["tasks/task_results"] == "WARN"


def test_learning_why_texts_name_stage_b_and_carry_no_dates():
    text = SWEEP.read_text(encoding="utf-8-sig")
    whys = text[text.index('Test-FileAge "learning/daily_learning"'):text.index("$stageA = Get-WeatherStageAChainFinding")]
    assert whys.count("Stage-B output (after promotion_refresh)") == 2
    assert "nightly_retrain under WeatherTrainingWindow" in whys
    assert whys.count("settlement-gated") == 2
    assert "27 days" not in whys and "21 steps" not in whys
    assert not re.search(r"20\d\d-\d\d-\d\d|\d+ days", whys)
