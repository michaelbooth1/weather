"""R20 forward input arrival: the host check, its registrar, the workstation receipts beacon and its registrar,
and the status.ps1 classification. Fixtures only: every share root, ledger and repository is under tmp_path, and
every Scheduler call reaches a stub.

Guards: master ruling R20 (2026-11-01) section 2 - WeatherForwardArrivalCheck slots and exit codes, the beacon's
ReadWrite,Delete ledger opens and tmp-then-rename writes, share roots as parameters (C19), registrars tested only
against scheduler stubs (C8), and status.ps1 FORWARD_ARRIVAL classification.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from tests.scheduler_stubs import GUARD_SCRIPT, assert_only_stubs_invoked, module_lookalike, prologue

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
RESEARCH = ROOT / "tools" / "research"
CHECK = OPS / "forward_input_arrival_check.ps1"
CHECK_REGISTRAR = OPS / "register_forward_input_arrival_check.ps1"
BEACON = RESEARCH / "ws_forward_receipts_beacon.ps1"
BEACON_REGISTRAR = RESEARCH / "register_ws_forward_receipts_beacon.ps1"
STATUS = OPS / "status.ps1"
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\WindowsPowerShell\v1.0\powershell.exe")
MARKER = "ab" * 32
OTHER = "cd" * 32

pytestmark = [
    pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 5.1 contract"),
    pytest.mark.spawns,
]


def _run(args: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", *args],
        capture_output=True, text=True, timeout=120, env={**os.environ, **(env or {})}, cwd=cwd, check=False,
    )


def _jsonl(path: Path, rows: list[dict | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [row if isinstance(row, str) else json.dumps(row) for row in rows]
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


# ---------------------------------------------------------------- host arrival check


def _b_row(day: str, status: str = "verified", sha: str = MARKER) -> dict:
    return {"schema": "mg2_input_receipt/1", "target_date": day, "status": status, "manifest_sha256": sha}


def _arrival_layout(tmp_path: Path, day: str, *, marker: str | None = MARKER, heartbeat_utc: str | None,
                    b: list | None = None, bundle: list | None = None, emit: list | None = None) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    receipts = tmp_path / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    if marker is not None:
        marker_path = repo / "data" / "exports" / "mg2-inputs" / day / "manifest.json.sha256"
        marker_path.parent.mkdir(parents=True)
        marker_path.write_text(marker + "\n", encoding="ascii")
    if heartbeat_utc is not None:
        (receipts / "heartbeat.json").write_text(
            json.dumps({"schema": "ws_forward_receipts_heartbeat/1", "generated_utc": heartbeat_utc}) + "\n",
            encoding="utf-8")
    for name, rows in (("mg2_input_receipts.jsonl", b), ("l6g_bundle_receipts.jsonl", bundle),
                       ("l6g_input_receipts.jsonl", emit)):
        if rows is not None:
            _jsonl(receipts / name, rows)
    return repo, receipts


def _check(repo: Path, receipts: Path, now: str) -> tuple[int, dict, subprocess.CompletedProcess]:
    result = _run(["-File", str(CHECK), "-RepoRoot", str(repo), "-ReceiptsRoot", str(receipts), "-Now", now])
    state_path = repo / "data" / "alerts" / "forward_arrival_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8-sig")) if state_path.exists() else {}
    return result.returncode, state, result


def test_morning_slot_needs_only_marker_and_fresh_heartbeat(tmp_path):
    # 2026-11-02 07:50 EST = 12:50Z; D = 2026-11-01.
    repo, receipts = _arrival_layout(tmp_path, "2026-11-01", heartbeat_utc="2026-11-02T12:30:00Z")
    code, state, result = _check(repo, receipts, "2026-11-02T07:50:00")
    assert code == 0, result.stdout + result.stderr
    assert state["status"] == "OK" and state["slot"] == "07:45" and state["target_date"] == "2026-11-01"
    assert state["schema"] == "forward_arrival_check/1" and state["failures"] == []
    ledger = (repo / "data" / "alerts" / "forward_arrival.jsonl").read_text(encoding="utf-8-sig").splitlines()
    assert [json.loads(line)["status"] for line in ledger] == ["OK"]


def test_evening_slot_ok_with_b_bundle_and_emit(tmp_path):
    day = "2026-11-01"
    repo, receipts = _arrival_layout(
        tmp_path, day, heartbeat_utc="2026-11-02T23:00:00Z",
        b=[_b_row("2026-10-31"), _b_row(day, "failed"), _b_row(day)],
        bundle=[_b_row(day, sha=OTHER)],
        emit=[{"schema": "l6g_forward_input_receipt/1", "date": day, "emitted_utc": "2026-11-02T15:00:00Z"}])
    code, state, result = _check(repo, receipts, "2026-11-02T18:10:00")
    assert code == 0, result.stdout + result.stderr
    assert state["slot"] == "18:05" and state["status"] == "OK"
    assert state["checks"] == {"host_marker": True, "heartbeat_age_minutes": 10.0, "b_verified": True,
                               "l6g_bundle_verified": True, "l6g_emitted": True}


def test_b_verified_for_another_bundle_is_an_alert_with_exit_2(tmp_path):
    day = "2026-11-01"
    repo, receipts = _arrival_layout(tmp_path, day, heartbeat_utc="2026-11-02T16:40:00Z",
                                     b=[_b_row(day, sha=OTHER)], bundle=[_b_row(day)])
    code, state, _ = _check(repo, receipts, "2026-11-02T11:50:00")
    assert code == 2
    assert state["status"] == "ALERT" and state["slot"] == "11:45"
    assert state["failures"] == [f"b_not_verified:{day} (verified)"]


def test_missing_marker_stale_heartbeat_and_missing_receipts_all_reported(tmp_path):
    day = "2026-11-01"
    repo, receipts = _arrival_layout(tmp_path, day, marker=None, heartbeat_utc="2026-11-02T20:00:00Z")
    code, state, _ = _check(repo, receipts, "2026-11-02T18:10:00")
    assert code == 2
    assert state["failures"] == [
        f"host_marker_missing:{day}", "heartbeat_stale:190min", f"b_not_verified:{day}",
        f"l6g_bundle_not_verified:{day}", f"l6g_not_emitted:{day}"]


def test_rows_for_other_dates_never_satisfy_d(tmp_path):
    """Regression: the rows were once passed to Where-Object as one array, so any matching date let every row
    through, and a verified row for another date satisfied D."""
    day = "2026-11-01"
    repo, receipts = _arrival_layout(
        tmp_path, day, heartbeat_utc="2026-11-02T23:00:00Z",
        b=[_b_row("2026-10-31"), _b_row(day, "failed")],
        bundle=[_b_row("2026-10-31"), _b_row(day, "failed")],
        emit=[{"schema": "l6g_forward_input_receipt/1", "date": "2026-10-31"}])
    code, state, _ = _check(repo, receipts, "2026-11-02T18:10:00")
    assert code == 2
    assert state["failures"] == [f"b_not_verified:{day} (failed)", f"l6g_bundle_not_verified:{day} (failed)",
                                 f"l6g_not_emitted:{day}"]


def test_a_repeated_key_never_counts_as_verified(tmp_path):
    day = "2026-11-01"
    ambiguous = (f'{{"target_date":"{day}","status":"failed","status":"verified",'
                 f'"manifest_sha256":"{MARKER}"}}')
    repo, receipts = _arrival_layout(tmp_path, day, heartbeat_utc="2026-11-02T16:40:00Z",
                                     b=[ambiguous], bundle=[_b_row(day)])
    code, state, _ = _check(repo, receipts, "2026-11-02T11:50:00")
    assert code == 2 and state["failures"] == [f"b_not_verified:{day}"]


def test_l6g_is_not_due_before_its_first_date(tmp_path):
    day = "2026-10-30"
    repo, receipts = _arrival_layout(tmp_path, day, heartbeat_utc="2026-10-31T22:00:00Z", b=[_b_row(day)])
    code, state, result = _check(repo, receipts, "2026-10-31T18:10:00")
    assert code == 0, result.stdout + result.stderr
    assert "l6g_emitted" not in state["checks"] and "l6g_bundle_verified" not in state["checks"]


def test_after_last_date_it_retires_and_checks_nothing(tmp_path):
    repo, receipts = _arrival_layout(tmp_path, "2026-12-17", marker=None, heartbeat_utc=None)
    code, state, result = _check(repo, receipts, "2026-12-18T11:50:00")
    assert code == 0, result.stdout + result.stderr
    assert state["status"] == "RETIRED" and state["failures"] == [] and state["checks"] == {}


# ---------------------------------------------------------------- workstation beacon


def _ledgers(tmp_path: Path) -> dict[str, Path]:
    base = tmp_path / "ws"
    mg2 = base / "mg2" / "input_receipts.jsonl"
    mg2.parent.mkdir(parents=True)
    full = _b_row("2026-11-01") | {"recorded_at": "2026-11-02T10:00:00Z", "checks": {"market_rows": 11},
                                    "path": r"C:\t\mg2\forward\incoming\2026-11-01"}
    # A torn last line (no LF) is not a complete line and must not be projected.
    mg2.write_bytes(("\ufeff" + json.dumps(full) + "\n" + "not json\n" + '{"target_date":"2026-11-0').encode("utf-8"))
    bundle = base / "l6g" / "bundle_receipts.jsonl"
    _jsonl(bundle, [_b_row("2026-11-01")])
    emit = base / "l6g" / "input_receipts.jsonl"
    _jsonl(emit, [{"schema": "l6g_forward_input_receipt/1", "date": "2026-11-01", "vectors_sha256": OTHER,
                   "emitted_utc": "2026-11-02T15:00:00Z", "vectors": [1, 2]}])
    return {"Mg2Ledger": mg2, "L6gBundleLedger": bundle, "L6gInputLedger": emit}


def _beacon(tmp_path: Path, share: Path | None, fallback: Path | None, ledgers: dict[str, Path]):
    args = ["-File", str(BEACON), "-ShareRoot", str(share), "-LogRoot", str(tmp_path / "log")]
    if fallback is not None:
        args += ["-FallbackShareRoot", str(fallback)]
    for name, path in ledgers.items():
        args += [f"-{name}", str(path)]
    return _run(args)


def test_beacon_projects_complete_lines_and_writes_heartbeat_last(tmp_path):
    ledgers = _ledgers(tmp_path)
    share = tmp_path / "share"
    (share / "in").mkdir(parents=True)
    result = _beacon(tmp_path, share, None, ledgers)
    assert result.returncode == 0, result.stdout + result.stderr
    out = share / "in" / "forward-receipts"
    assert sorted(p.name for p in out.iterdir()) == [
        "heartbeat.json", "l6g_bundle_receipts.jsonl", "l6g_input_receipts.jsonl", "mg2_input_receipts.jsonl"]
    mg2 = [json.loads(line) for line in (out / "mg2_input_receipts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert mg2 == [{"schema": "mg2_input_receipt/1", "target_date": "2026-11-01", "status": "verified",
                    "manifest_sha256": MARKER, "recorded_at": "2026-11-02T10:00:00Z"},
                   {"unparseable": True, "line": 2}]
    emit = json.loads((out / "l6g_input_receipts.jsonl").read_text(encoding="utf-8"))
    assert emit == {"schema": "l6g_forward_input_receipt/1", "date": "2026-11-01",
                    "emitted_utc": "2026-11-02T15:00:00Z", "vectors_sha256": OTHER}
    heartbeat = json.loads((out / "heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat["schema"] == "ws_forward_receipts_heartbeat/1" and heartbeat["written_via"] == "share_root"
    assert heartbeat["problems"] == []
    assert heartbeat["beacon_sha256"] == hashlib.sha256(BEACON.read_bytes()).hexdigest()
    assert heartbeat["ledgers"]["mg2_input_receipts.jsonl"]["rows"] == 2
    assert not list(out.glob("*.tmp"))
    # Source ledgers are untouched.
    assert ledgers["Mg2Ledger"].read_bytes().endswith(b'{"target_date":"2026-11-0')
    assert len((tmp_path / "log" / "runs.jsonl").read_text(encoding="utf-8-sig").splitlines()) == 1


def test_beacon_uses_the_fallback_root_and_fails_when_nothing_is_reachable(tmp_path):
    ledgers = _ledgers(tmp_path)
    fallback = tmp_path / "fallback"
    (fallback / "in").mkdir(parents=True)
    result = _beacon(tmp_path, tmp_path / "missing", fallback, ledgers)
    assert result.returncode == 0, result.stdout + result.stderr
    heartbeat = json.loads((fallback / "in" / "forward-receipts" / "heartbeat.json").read_text(encoding="utf-8"))
    assert heartbeat["written_via"] == "fallback_share_root"
    assert heartbeat["name_probe"]["reachable"] is False and heartbeat["ip_probe"]["reachable"] is True

    shutil.rmtree(fallback / "in")
    result = _beacon(tmp_path, tmp_path / "missing", fallback, ledgers)
    assert result.returncode == 1
    assert json.loads(result.stdout.strip().splitlines()[-1])["problems"] == ["no_share_reachable"]


def test_writers_can_append_and_rename_while_the_beacon_holds_a_ledger(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    _jsonl(ledger, [_b_row("2026-11-01")])
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{BEACON}' -DefineFunctionsOnly
$path = '{ledger}'
$result = [ordered]@{{}}
$stream = Open-WeatherLedgerForRead -Path $path
try {{
    $content = Read-WeatherLedgerCompleteLines -Stream $stream
    $result.lines_at_open = $content.lines.Count
    $writer = [IO.File]::Open($path, 'Append', 'Write', 'ReadWrite')
    $bytes = [Text.Encoding]::UTF8.GetBytes("{{`"target_date`":`"2026-11-02`"}}`n")
    $writer.Write($bytes, 0, $bytes.Length); $writer.Dispose()
    $result.append_while_open = 'ok'
    [IO.File]::Move($path, "$path.rotated")
    $result.rename_while_open = 'ok'
}} finally {{ $stream.Dispose() }}
# Control: a reader that denies write sharing does block the writer.
$blocking = [IO.File]::Open("$path.rotated", 'Open', 'Read', 'Read')
try {{
    try {{ $w = [IO.File]::Open("$path.rotated", 'Append', 'Write', 'ReadWrite'); $w.Dispose(); $result.control = 'not blocked' }}
    catch [IO.IOException] {{ $result.control = 'blocked' }}
}} finally {{ $blocking.Dispose() }}
$result.lines_after = @([IO.File]::ReadAllLines("$path.rotated")).Count
$result | ConvertTo-Json -Compress
"""
    runner = tmp_path / "runner.ps1"
    runner.write_text(script, encoding="utf-8-sig")
    result = _run(["-File", str(runner)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"lines_at_open": 1, "append_while_open": "ok", "rename_while_open": "ok",
                                         "control": "blocked", "lines_after": 2}


def test_beacon_never_copies_a_ledger_and_opens_ledgers_only_for_shared_read():
    code = "\n".join(line for line in BEACON.read_text(encoding="utf-8-sig").splitlines()
                     if not line.lstrip().startswith("#"))
    assert not re.search(r"Copy-Item|\[IO\.File\]::Copy|robocopy|xcopy", code, flags=re.IGNORECASE)
    opens = re.findall(r"\[IO\.File\]::Open\([^\n]*\n?[^\n]*", code)
    assert len(opens) == 1 and "[IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete" in opens[0]
    assert "192.168." not in BEACON.read_text(encoding="utf-8-sig")


def test_beacon_output_satisfies_the_host_check_end_to_end(tmp_path):
    now = _run(["-Command", "[TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, "
                "[TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')).ToString('yyyy-MM-ddTHH:mm:ss')"])
    local_now = now.stdout.strip()
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", local_now), now.stderr
    from datetime import date, timedelta
    day = (date.fromisoformat(local_now[:10]) - timedelta(days=1)).isoformat()
    ledgers = {"Mg2Ledger": tmp_path / "ws" / "b.jsonl", "L6gBundleLedger": tmp_path / "ws" / "g.jsonl",
               "L6gInputLedger": tmp_path / "ws" / "e.jsonl"}
    _jsonl(ledgers["Mg2Ledger"], [_b_row(day) | {"checks": {"a": 1}}])
    _jsonl(ledgers["L6gBundleLedger"], [_b_row(day, sha=OTHER)])
    _jsonl(ledgers["L6gInputLedger"], [{"schema": "l6g_forward_input_receipt/1", "date": day}])
    share = tmp_path / "share"
    (share / "in").mkdir(parents=True)
    assert _beacon(tmp_path, share, None, ledgers).returncode == 0
    repo, _ = _arrival_layout(tmp_path, day, heartbeat_utc=None)
    code, state, result = _check(repo, share / "in" / "forward-receipts", local_now)
    assert code == 0, result.stdout + result.stderr
    assert state["status"] == "OK" and state["target_date"] == day


# ---------------------------------------------------------------- host registrar (stubbed Scheduler)

CHECK_STUBS = r"""
$global:Registered = $null
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory)
    [pscustomobject]@{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory } }
function New-ScheduledTaskTrigger { param([switch]$Daily, $At)
    [pscustomobject]@{ RequestedAt = $At; StartBoundary = ('2026-11-01T' + $At + ':00Z'); DaysInterval = 1 } }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel)
    [pscustomobject]@{ LogonType = $LogonType; RunLevel = $RunLevel } }
function New-ScheduledTaskSettingsSet { param($ExecutionTimeLimit, $MultipleInstances)
    [pscustomobject]@{ StartWhenAvailable = $false; MultipleInstances = $MultipleInstances;
        ExecutionTimeLimit = [Xml.XmlConvert]::ToString([TimeSpan]$ExecutionTimeLimit) } }
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Principal, $Settings, [switch]$Force)
    $global:Registered = [pscustomobject]@{ Actions = @($Action); Triggers = @($Trigger);
        Principal = $Principal; Settings = $Settings }
    Set-Content -LiteralPath $env:REG_FIXTURE_OUT -Value ([pscustomobject]@{ task = $TaskName;
        at = @($Trigger | ForEach-Object { $_.RequestedAt }); boundaries = @($Trigger | ForEach-Object { $_.StartBoundary });
        arguments = $Action.Arguments; logon = $Principal.LogonType; run_level = $Principal.RunLevel;
        limit = $Settings.ExecutionTimeLimit } | ConvertTo-Json -Compress) }
function Get-ScheduledTask { param($TaskName)
    if ($env:REG_FIXTURE_READBACK_BOUNDARY) {
        $global:Registered.Triggers[1].StartBoundary = $env:REG_FIXTURE_READBACK_BOUNDARY }
    $global:Registered }
function Disable-ScheduledTask { param($TaskName)
    Set-Content -LiteralPath $env:REG_FIXTURE_DISABLED -Value $TaskName }
"""


@pytest.fixture
def check_registration(tmp_path):
    root = tmp_path / "src"
    scripts = root / "scripts" / "ops"
    scripts.mkdir(parents=True)
    for name in ("training_window_contract.ps1", "scheduled_task_local_trigger.ps1", GUARD_SCRIPT,
                 "register_forward_input_arrival_check.ps1", "forward_input_arrival_check.ps1"):
        shutil.copy2(OPS / name, scripts / name)
    (scripts / "workload_admission.ps1").write_text(
        "function Get-WeatherExecutionHostAssignment { param($RepoRoot) "
        "[pscustomobject]@{ dedicated_capture_execution_host_id = 'fixture-host' } }\n"
        "function Get-WeatherExecutionHostId { 'fixture-host' }\n", encoding="utf-8")
    git = ["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
           "-c", "commit.gpgSign=false", "-c", "core.autocrlf=false"]
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(git + args, check=True, capture_output=True, timeout=60)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True, timeout=60).stdout.strip()
    return root, head, tmp_path


def _register_check(fixture, stubs=CHECK_STUBS, readback_boundary=None, tip=None):
    root, head, tmp = fixture
    (tmp / "stubs.ps1").write_text(prologue(tmp / "ledger.jsonl") + stubs, encoding="utf-8")
    env = {"REG_FIXTURE_OUT": str(tmp / "registered.json"), "REG_FIXTURE_DISABLED": str(tmp / "disabled.txt"),
           "REG_FIXTURE_READBACK_BOUNDARY": readback_boundary or ""}
    command = (f". '{tmp / 'stubs.ps1'}'; & '{root / 'scripts/ops/register_forward_input_arrival_check.ps1'}' "
               f"-ExpectedSourceTip {tip or head} -ReceiptsRoot 'C:\\xfer\\in\\forward-receipts'")
    result = _run(["-Command", command], env=env, cwd=root)
    out = tmp / "registered.json"
    return result, (json.loads(out.read_text(encoding="utf-8-sig")) if out.exists() else None)


def test_check_registrar_whatif_prints_the_definition_and_touches_nothing(tmp_path):
    result = _run(["-File", str(CHECK_REGISTRAR), "-ExpectedSourceTip", "a" * 40,
                   "-ReceiptsRoot", r"C:\xfer\in\forward-receipts", "-WhatIf"])
    assert result.returncode == 0, result.stdout + result.stderr
    spec = json.loads(result.stdout.strip().splitlines()[-1])
    assert spec["task_name"] == "WeatherForwardArrivalCheck" and spec["registered"] is False
    assert spec["triggers_local_daily"] == ["07:45", "11:45", "18:05"]
    assert spec["principal"].endswith(" S4U Limited") and spec["execution_time_limit"] == "PT5M"
    assert spec["arguments"][-4:] == ["-ReceiptsRoot", r"C:\xfer\in\forward-receipts", "-LastDate", "2026-12-16"]
    assert Path(spec["arguments"][5]).name == "forward_input_arrival_check.ps1"


def test_check_registrar_registers_local_daily_triggers_against_stubs(check_registration):
    result, registered = _register_check(check_registration)
    assert result.returncode == 0, result.stdout + result.stderr
    assert registered["task"] == "WeatherForwardArrivalCheck"
    assert registered["at"] == ["07:45", "11:45", "18:05"]
    assert all(not b.endswith("Z") for b in registered["boundaries"])
    assert registered["logon"] == "S4U" and registered["run_level"] == "Limited" and registered["limit"] == "PT5M"
    assert "-LastDate 2026-12-16" in registered["arguments"]
    assert_only_stubs_invoked(check_registration[2] / "ledger.jsonl", {"Register-ScheduledTask", "Get-ScheduledTask"})


def test_check_registrar_disables_on_a_zoned_readback(check_registration):
    result, _ = _register_check(check_registration, readback_boundary="2026-11-01T11:45:00-05:00")
    assert result.returncode != 0 and "readback mismatch" in result.stdout + result.stderr
    assert (check_registration[2] / "disabled.txt").read_text(encoding="utf-8-sig").strip() == "WeatherForwardArrivalCheck"
    assert_only_stubs_invoked(check_registration[2] / "ledger.jsonl",
                              {"Register-ScheduledTask", "Get-ScheduledTask", "Disable-ScheduledTask"})


def test_check_registrar_refuses_a_wrong_tip_and_a_non_stub(check_registration):
    result, registered = _register_check(check_registration, tip="0" * 40)
    assert result.returncode != 0 and "tip mismatch" in result.stdout + result.stderr and registered is None
    stubs = CHECK_STUBS.replace("function Register-ScheduledTask {", "function Unused-WeatherFixtureStub {")
    result, registered = _register_check(check_registration, stubs=stubs + module_lookalike("Register-ScheduledTask"))
    assert result.returncode != 0 and "Register-ScheduledTask is not a test stub" in result.stdout + result.stderr
    assert registered is None
    assert_only_stubs_invoked(check_registration[2] / "ledger.jsonl", set())


# ---------------------------------------------------------------- workstation beacon registrar (stubbed Scheduler)

BEACON_STUBS = r"""
$global:Registered = $null
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory)
    [pscustomobject]@{ Execute = $Execute; Arguments = $Argument; WorkingDirectory = $WorkingDirectory } }
function New-ScheduledTaskTrigger { param([switch]$Once, $At, $RepetitionInterval, [switch]$AtLogOn, $User)
    if ($AtLogOn) { return [pscustomobject]@{ Kind = 'logon'; User = $User; Repetition = $null
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskLogonTrigger' } } }
    [pscustomobject]@{ Kind = 'once'; At = $At; CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskTimeTrigger' }
        Repetition = [pscustomobject]@{ Interval = [Xml.XmlConvert]::ToString([TimeSpan]$RepetitionInterval); Duration = '' } } }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel)
    [pscustomobject]@{ UserId = $UserId; LogonType = $LogonType; RunLevel = $RunLevel } }
function New-ScheduledTaskSettingsSet { param($MultipleInstances, $ExecutionTimeLimit, [switch]$AllowStartIfOnBatteries,
        [switch]$DontStopIfGoingOnBatteries)
    [pscustomobject]@{ StartWhenAvailable = $false; MultipleInstances = $MultipleInstances
        ExecutionTimeLimit = [Xml.XmlConvert]::ToString([TimeSpan]$ExecutionTimeLimit) } }
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Principal, $Settings, $Description)
    $global:Registered = [pscustomobject]@{ Actions = @($Action); Triggers = @($Trigger); Principal = $Principal
        Settings = $Settings; State = 'Ready' }
    if ($env:REG_FIXTURE_LOGON) { $global:Registered.Principal.LogonType = $env:REG_FIXTURE_LOGON }
    Set-Content -LiteralPath $env:REG_FIXTURE_OUT -Value ([pscustomobject]@{ task = $TaskName
        arguments = $Action.Arguments; working_directory = $Action.WorkingDirectory
        kinds = @($Trigger | ForEach-Object { $_.Kind }); logon = $Principal.LogonType; run_level = $Principal.RunLevel
        limit = $Settings.ExecutionTimeLimit; instances = $Settings.MultipleInstances } | ConvertTo-Json -Compress) }
function Get-ScheduledTask { param($TaskName)
    if ($env:REG_FIXTURE_EXISTS) { return [pscustomobject]@{ TaskName = $TaskName } }
    $global:Registered }
function Disable-ScheduledTask { param($TaskName)
    Set-Content -LiteralPath $env:REG_FIXTURE_DISABLED -Value $TaskName }
"""

SHARE = r"\\FIXTUREHOST\xfer"
FALLBACK = r"\\fixture-fallback\xfer"


@pytest.fixture
def beacon_registration(tmp_path):
    worktree = tmp_path / "wt"
    (worktree / "tools" / "research").mkdir(parents=True)
    (worktree / "scripts" / "ops").mkdir(parents=True)
    shutil.copy2(BEACON, worktree / "tools" / "research" / BEACON.name)
    shutil.copy2(BEACON_REGISTRAR, worktree / "tools" / "research" / BEACON_REGISTRAR.name)
    shutil.copy2(OPS / GUARD_SCRIPT, worktree / "scripts" / "ops" / GUARD_SCRIPT)
    return worktree, tmp_path


def _register_beacon(fixture, *, stubs=BEACON_STUBS, sha=None, whatif=False, **env_extra):
    worktree, tmp = fixture
    (tmp / "stubs.ps1").write_text(prologue(tmp / "ledger.jsonl") + stubs, encoding="utf-8")
    env = {"REG_FIXTURE_OUT": str(tmp / "registered.json"), "REG_FIXTURE_DISABLED": str(tmp / "disabled.txt"),
           "REG_FIXTURE_LOGON": "", "REG_FIXTURE_EXISTS": "", **env_extra}
    beacon_sha = sha if sha is not None else hashlib.sha256(BEACON.read_bytes()).hexdigest()
    command = (f". '{tmp / 'stubs.ps1'}'; & '{worktree / 'tools/research' / BEACON_REGISTRAR.name}' "
               f"-ShareRoot '{SHARE}' -FallbackShareRoot '{FALLBACK}' -WorkingDirectory '{tmp / 'beacon-wd'}' "
               f"-ExpectedBeaconSha256 {beacon_sha}" + (" -WhatIf" if whatif else ""))
    result = _run(["-Command", command], env=env)
    out = tmp / "registered.json"
    return result, (json.loads(out.read_text(encoding="utf-8-sig")) if out.exists() else None)


def test_beacon_registrar_whatif_prints_the_owner_bundle_definition(beacon_registration):
    worktree, tmp = beacon_registration
    result, registered = _register_beacon(beacon_registration, whatif=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert registered is None
    spec = json.loads(result.stdout.strip().splitlines()[-1])
    beacon = worktree / "tools" / "research" / BEACON.name
    assert spec["task_name"] == "R20 forward receipts beacon" and spec["registered"] is False
    assert spec["arguments"] == (
        f'-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{beacon}" '
        f'-ShareRoot "{SHARE}" -LogRoot "{tmp / "beacon-wd"}" -FallbackShareRoot "{FALLBACK}"')
    once, logon = spec["triggers"]
    assert once["type"] == "Once" and once["repetition_interval"] == "PT30M" and once["start_local"][14:16] in ("10", "40")
    assert logon["type"] == "AtLogOn"
    assert spec["principal"].endswith(" Interactive Limited")
    assert spec["execution_time_limit"] == "PT5M" and spec["multiple_instances"] == "IgnoreNew"
    assert spec["beacon_sha256"] == hashlib.sha256(BEACON.read_bytes()).hexdigest()
    assert_only_stubs_invoked(tmp / "ledger.jsonl", set())


def test_beacon_registrar_registers_against_stubs_and_reads_back(beacon_registration):
    result, registered = _register_beacon(beacon_registration)
    assert result.returncode == 0, result.stdout + result.stderr
    assert registered["task"] == "R20 forward receipts beacon"
    assert registered["kinds"] == ["once", "logon"]
    assert registered["logon"] == "Interactive" and registered["run_level"] == "Limited"
    assert registered["limit"] == "PT5M" and registered["instances"] == "IgnoreNew"
    assert "registered R20 forward receipts beacon" in result.stdout
    assert_only_stubs_invoked(beacon_registration[1] / "ledger.jsonl", {"Register-ScheduledTask", "Get-ScheduledTask"})


def test_beacon_registrar_disables_a_mismatched_readback(beacon_registration):
    result, _ = _register_beacon(beacon_registration, REG_FIXTURE_LOGON="S4U")
    assert result.returncode != 0 and "the task was disabled" in result.stdout + result.stderr
    assert (beacon_registration[1] / "disabled.txt").read_text(encoding="utf-8-sig").strip() == "R20 forward receipts beacon"
    assert_only_stubs_invoked(beacon_registration[1] / "ledger.jsonl",
                              {"Register-ScheduledTask", "Get-ScheduledTask", "Disable-ScheduledTask"})


def test_beacon_registrar_refuses_wrong_sha_existing_task_and_non_stub(beacon_registration):
    tmp = beacon_registration[1]
    result, registered = _register_beacon(beacon_registration, sha="0" * 64)
    assert result.returncode != 0 and "!= expected" in result.stdout + result.stderr and registered is None
    result, registered = _register_beacon(beacon_registration, REG_FIXTURE_EXISTS="1")
    assert result.returncode != 0 and "task already exists" in result.stdout + result.stderr and registered is None
    assert_only_stubs_invoked(tmp / "ledger.jsonl", {"Get-ScheduledTask"})
    (tmp / "ledger.jsonl").unlink()
    stubs = BEACON_STUBS.replace("function Get-ScheduledTask {", "function Unused-WeatherFixtureStub {")
    result, registered = _register_beacon(beacon_registration, stubs=stubs + module_lookalike("Get-ScheduledTask"))
    assert result.returncode != 0 and "Get-ScheduledTask is not a test stub" in result.stdout + result.stderr
    assert registered is None
    assert_only_stubs_invoked(tmp / "ledger.jsonl", set())


def test_beacon_registrar_rejects_a_share_root_that_is_not_a_unc_root(beacon_registration):
    worktree, tmp = beacon_registration
    result = _run(["-File", str(worktree / "tools" / "research" / BEACON_REGISTRAR.name),
                   "-ShareRoot", r"\\host\xfer\in", "-WhatIf"])
    assert result.returncode != 0 and "share root of the form" in result.stdout + result.stderr


# ---------------------------------------------------------------- status.ps1 classification


def _status_state(tmp_path: Path, state: dict | str | None, utc_now: str) -> dict:
    path = tmp_path / "forward_arrival_state.json"
    if state is not None:
        path.write_text(state if isinstance(state, str) else json.dumps(state), encoding="utf-8")
    runner = tmp_path / "status_runner.ps1"
    runner.write_text(
        "$ErrorActionPreference='Stop'\n"
        "$tokens=$null; $errors=$null\n"
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{STATUS}',[ref]$tokens,[ref]$errors)\n"
        "if($errors.Count){throw ($errors | Out-String)}\n"
        "$f=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and"
        " $n.Name -eq 'Get-WeatherForwardArrivalState'},$true))\n"
        "if($f.Count -ne 1){throw 'missing function'}\n"
        "Invoke-Expression $f[0].Extent.Text\n"
        f"Get-WeatherForwardArrivalState -Path '{path}' -UtcNow ([datetime]::Parse('{utc_now}',"
        " [cultureinfo]::InvariantCulture, [Globalization.DateTimeStyles]'AdjustToUniversal,AssumeUniversal'))"
        " | ConvertTo-Json -Compress -Depth 3\n",
        encoding="utf-8-sig")
    result = _run(["-File", str(runner)])
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _state(status: str, checked_utc: str = "2026-11-02T16:50:00Z", failures=()) -> dict:
    return {"schema": "forward_arrival_check/1", "status": status, "target_date": "2026-11-01", "slot": "11:45",
            "checked_utc": checked_utc, "failures": list(failures), "checks": {}}


@pytest.mark.parametrize(
    "state, now, status, flag, warn",
    [
        (None, "2026-11-02T17:00:00Z", "ABSENT", None, None),
        (_state("OK"), "2026-11-02T17:00:00Z", "OK", None, None),
        (_state("ALERT", failures=["b_not_verified:2026-11-01", "heartbeat_stale:120min"]), "2026-11-02T17:00:00Z",
         "ALERT", "FORWARD_ARRIVAL ALERT for 2026-11-01 at 11:45: b_not_verified:2026-11-01; heartbeat_stale:120min",
         None),
        (_state("OK"), "2026-11-03T08:00:00Z", "OK", None,
         "FORWARD_ARRIVAL: last check 2026-11-02T16:50:00Z is 15.2h old (task not running?)"),
        (_state("RETIRED"), "2026-12-30T08:00:00Z", "RETIRED", None, None),
        ("{not json", "2026-11-02T17:00:00Z", "UNREADABLE", None, "FORWARD_ARRIVAL: state file is unreadable"),
    ],
    ids=["absent", "ok", "alert", "stale", "retired", "unreadable"],
)
def test_status_classifies_the_arrival_state(tmp_path, state, now, status, flag, warn):
    got = _status_state(tmp_path, state, now)
    assert got["status"] == status
    assert got["flag"] == flag
    if warn is None:
        assert got["warn"] is None
    else:
        assert got["warn"].startswith(warn)


def test_status_wires_the_state_into_flags_json_and_the_exit_2_exemption():
    source = STATUS.read_text(encoding="utf-8-sig")
    assert 'Get-WeatherForwardArrivalState -Path (Join-Path $repo "data\\alerts\\forward_arrival_state.json")' in source
    assert ('$name -eq "WeatherForwardArrivalCheck" -and $res -eq "0x2" -and $forwardArrival.status -eq "ALERT"'
            in source)
    assert "forward_arrival = $forwardArrival" in source
