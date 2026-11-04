"""Lane L2: the MG-2 / Rule B-1 forward input pull+receive launcher and its workstation task registrar (draft).

Guards: binding plan section 9.7 (pull 06:30 on D+1 then hourly until 23:00, receive after each pull, build after
verified through workstation_heavy -Queue). The launcher refuses the whole run (logged, nothing started) when a B
binding blob (mg2_inputs, mg2_input_allowlist, mg2_composite) differs, the STOP file exists, or -Build's parser
worktree is not at 2e17ce0eb. A ledger-terminal date is never re-pulled. A past-deadline date gets receive only
(its late/missing line). A pull not_ready/unchanged_since_refusal/refused or a receive not_ready/quarantined/
refused result stops the run with no retry. The build stage runs only with -Build. -WhatIf writes nothing. The
registrar requires -ExpectedLauncherSha256, validates the task name, creates its working directory, refuses the
real ScheduledTasks module under WEATHER_TASK_TEST=1 and prints 18 unzoned local daily triggers. Both scripts parse
and carry no control characters. No test starts Python, touches the share, B's ledger or the real Scheduler: the
interpreter, git and workstation_heavy are fakes, and Windows paths are written with chr(92).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess

import pytest

from weather.paths import REPO_ROOT

BS = chr(92)
LAUNCHER = REPO_ROOT / "tools" / "research" / "mg2_forward_inputs_daily.ps1"
REGISTRAR = REPO_ROOT / "tools" / "research" / "register_mg2_forward_inputs_task.ps1"
PINNED = ("mg2_inputs.py", "mg2_input_allowlist.py", "mg2_composite.py")
PARSER_COMMIT = "2e17ce0eba891b028a968ac45895d3c203ea7dda"
NAME = "pytest-l2-fake-mg2-forward-inputs-do-not-create"

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="requires Windows PowerShell"),
]

FAKE_PYTHON = (
    "@echo off\r\n"
    'echo %*>>"%FAKE_ARGV%"\r\n'
    'if "%4"=="pull" echo %FAKE_PULL%\r\n'
    'if "%4"=="receive" echo %FAKE_RECEIVE%\r\n'
    "exit /b 0\r\n"
)
FAKE_GIT = "@echo off\r\necho %FAKE_GIT_HEAD%\r\n"
FAKE_HEAVY = """param([string]$Kind, [string]$PythonPath, [string]$ArgumentsBase64, [string]$RepoRoot, [switch]$Queue,
    [int]$QueueTimeoutSeconds, [double]$MinAvailableMemoryGB)
$argv = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($ArgumentsBase64)) | ConvertFrom-Json
Add-Content -LiteralPath $env:FAKE_HEAVY_LOG -Value (@{ kind = $Kind; queue = [bool]$Queue; mem = $MinAvailableMemoryGB; argv = @($argv) } | ConvertTo-Json -Compress)
$out = $argv[[array]::IndexOf($argv, '--out') + 1]
New-Item -ItemType Directory -Force $out | Out-Null
Set-Content -LiteralPath (Join-Path $out 'manifest.json') -Value '{}'
exit 0
"""


def _ps_file(script, *args, env=None, timeout=120):
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env)


class Rig:
    def __init__(self, tmp_path, *, tamper=None):
        self.tmp = tmp_path
        self.wt = tmp_path / "wt"
        cal = self.wt / "src" / "weather" / "calibration"
        cal.mkdir(parents=True)
        for name in PINNED:
            data = (REPO_ROOT / "src" / "weather" / "calibration" / name).read_bytes()
            (cal / name).write_bytes(data + (b"\n# tampered\n" if name == tamper else b""))
        (self.wt / "scripts" / "ops").mkdir(parents=True)
        (self.wt / "scripts" / "ops" / "workstation_heavy.ps1").write_text(FAKE_HEAVY, encoding="utf-8")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        (self.bin / "python.cmd").write_text(FAKE_PYTHON, encoding="ascii", newline="")
        (self.bin / "git.cmd").write_text(FAKE_GIT, encoding="ascii", newline="")
        self.share, self.inbox, self.log_root = tmp_path / "share", tmp_path / "inbox", tmp_path / "task"
        self.ledger, self.layouts = tmp_path / "ledger" / "input_receipts.jsonl", tmp_path / "layout"
        self.argv, self.heavy = tmp_path / "argv.txt", tmp_path / "heavy.jsonl"
        self.share.mkdir()

    def run(self, *extra, pull="pulled", receive="verified", git_head=PARSER_COMMIT, first=None):
        env = {**os.environ, "FAKE_ARGV": str(self.argv), "FAKE_HEAVY_LOG": str(self.heavy),
               "FAKE_PULL": json.dumps({"status": pull}), "FAKE_RECEIVE": json.dumps({"status": receive}),
               "FAKE_GIT_HEAD": git_head, "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "")}
        args = ["-Worktree", str(self.wt), "-ShareRoot", str(self.share), "-Inbox", str(self.inbox),
                "-Ledger", str(self.ledger), "-LogRoot", str(self.log_root), "-Python", str(self.bin / "python.cmd"),
                "-LayoutRoot", str(self.layouts), "-ParserWorktree", str(self.tmp / "parser"),
                "-FirstDate", first or _day(1), *extra]
        out = _ps_file(LAUNCHER, *args, env=env)
        assert out.returncode == 0, out.stdout + out.stderr
        return out

    def calls(self):
        if not self.argv.exists():
            return []
        return [line.split()[3:5] for line in self.argv.read_text(encoding="mbcs").splitlines() if line.strip()]

    def runs(self):
        path = self.log_root / "logs" / "runs.jsonl"
        if not path.exists():
            return []
        return [(r["date"], r["step"], r["outcome"]) for r in
                (json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip())]

    def ledger_rows(self, *rows):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _day(back):
    return (dt.date.today() - dt.timedelta(days=back)).isoformat()


def test_tampered_binding_blob_refuses_the_whole_run(tmp_path):
    rig = Rig(tmp_path, tamper="mg2_input_allowlist.py")
    out = rig.run()
    assert "refused:" in out.stdout and f"src{BS}weather{BS}calibration{BS}mg2_input_allowlist.py blob" in out.stdout
    assert rig.calls() == [] and rig.runs() == []


def test_stop_file_runs_nothing(tmp_path):
    rig = Rig(tmp_path)
    (rig.log_root).mkdir()
    (rig.log_root / "STOP").write_text("")
    out = rig.run()
    assert "STOP file present" in out.stdout and rig.calls() == []


def test_pull_then_receive_verified_without_build(tmp_path):
    rig = Rig(tmp_path)
    rig.run()
    day = _day(1)
    assert rig.calls() == [["pull", "--share-root"], ["receive", "--inbox"]]
    assert rig.runs() == [(day, "pull", "pulled"), (day, "receive", "verified")]
    argv = rig.argv.read_text(encoding="mbcs")
    assert f"--date {day} --ledger {rig.ledger}" in argv and f"--inbox {rig.inbox}" in argv
    assert not rig.heavy.exists()


@pytest.mark.parametrize("status", ["not_ready", "unchanged_since_refusal", "refused", ""])
def test_pull_stop_statuses_stop_the_run_before_receive(tmp_path, status):
    rig = Rig(tmp_path)
    rig.run(pull=status)
    assert rig.calls() == [["pull", "--share-root"]]
    assert rig.runs() == [(_day(1), "pull", "stop")]


@pytest.mark.parametrize("status", ["not_ready", "quarantined", "refused:files_match"])
def test_receive_stop_statuses_stop_the_run_and_later_dates(tmp_path, status):
    # Two days back is past its deadline (receive only); the stop leaves yesterday untouched.
    rig = Rig(tmp_path)
    rig.run(receive=status, first=_day(2))
    assert rig.calls() == [["receive", "--inbox"]]
    assert rig.runs() == [(_day(2), "receive", "stop")]


def test_past_deadline_date_gets_receive_only_then_the_next_date_runs(tmp_path):
    rig = Rig(tmp_path)
    rig.run(receive="missing", first=_day(2))
    assert rig.calls() == [["receive", "--inbox"], ["pull", "--share-root"], ["receive", "--inbox"]]
    assert [r[:2] for r in rig.runs()] == [(_day(2), "receive"), (_day(1), "pull"), (_day(1), "receive")]


def test_ledger_terminal_dates_are_never_pulled(tmp_path):
    rig = Rig(tmp_path)
    rig.ledger_rows({"target_date": _day(3), "status": "verified"},
                    {"target_date": _day(2), "status": "refused:schema", "attempt": 1},
                    {"target_date": _day(2), "status": "quarantined", "attempt": 2},
                    {"target_date": _day(1), "status": "late"})
    out = rig.run(first=_day(3))
    assert rig.calls() == [] and rig.runs() == [] and "done" in out.stdout


def test_build_stage_runs_only_with_build_through_the_queue(tmp_path):
    rig = Rig(tmp_path)
    day = _day(1)
    rig.ledger_rows({"target_date": day, "status": "verified"})
    (rig.inbox / day / "verified").mkdir(parents=True)
    rig.run()
    assert not rig.heavy.exists()
    rig.run("-Build")
    (heavy,) = [json.loads(x) for x in rig.heavy.read_text(encoding="utf-8-sig").splitlines()]
    assert heavy["kind"] == "weather_heavy" and heavy["queue"] is True and heavy["mem"] == 3
    argv = heavy["argv"]
    assert argv[:3] == ["-m", "weather.calibration.mg2_inputs", "build"]
    assert argv[argv.index("--bundle") + 1] == str(rig.inbox / day / "verified")
    assert argv[argv.index("--out") + 1] == str(rig.layouts / day)
    assert argv[argv.index("--parser-worktree") + 1] == str(tmp_path / "parser")
    assert (day, "build", "built") in rig.runs() and rig.calls() == []
    rig.run("-Build")  # a built layout is not rebuilt
    assert len(rig.heavy.read_text(encoding="utf-8-sig").splitlines()) == 1


def test_build_refuses_a_parser_worktree_off_the_pinned_commit(tmp_path):
    rig = Rig(tmp_path)
    out = rig.run("-Build", git_head="0" * 40)
    assert "refused: -Build parser worktree" in out.stdout
    assert rig.calls() == [] and not rig.heavy.exists()


def test_whatif_writes_nothing(tmp_path):
    rig = Rig(tmp_path)
    out = rig.run("-WhatIf", first=_day(2))
    assert "WhatIf:" in out.stdout and "receive only (records late/missing)" in out.stdout
    assert "pull + receive" in out.stdout
    assert rig.calls() == [] and not rig.log_root.exists() and not rig.ledger.exists()


def test_unfinished_or_pre_d0_dates_are_refused(tmp_path):
    rig = Rig(tmp_path)
    out = rig.run("-Date", dt.date.today().isoformat())
    assert "not a finished local date" in out.stdout and rig.calls() == []
    out = rig.run("-Date", "2026-10-28", first="2026-10-29")
    assert "before the first date 2026-10-29" in out.stdout and rig.calls() == []


# ----------------------------------------------------------------------------- registrar (stubbed Scheduler)

# ScheduledTasks is a CDXML module whose commands are functions: importing it first, then defining the stubs over
# it and forcing any autoload, keeps a later autoload from replacing them (the 2026-10-30 incident). The harness
# refuses to run the registrar unless every Scheduler mutator still resolves to a harness function; the task name
# is fake as a second guard and the registrar's own WEATHER_TASK_TEST refusal is a third.
HARNESS = r"""
$ErrorActionPreference = 'Stop'
Import-Module ScheduledTasks
$global:mutations = @()
function Get-ScheduledTask {
    param($TaskName, $ErrorAction)
    if ($TaskName -eq $env:NEW_NAME -and ($env:NEW_EXISTS -eq '1' -or $global:mutations.Count -gt 0)) {
        return [pscustomobject]@{ TaskName = $TaskName; State = 'Ready' }
    }
    $null
}
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Principal, $Settings, $Description) $global:mutations += "register:$TaskName" }
function Unregister-ScheduledTask { param($TaskName, $Confirm) $global:mutations += "unregister:$TaskName" }
function Disable-ScheduledTask { $global:mutations += 'disable' }
function Enable-ScheduledTask { $global:mutations += 'enable' }
function Set-ScheduledTask { $global:mutations += 'set' }
function Start-ScheduledTask { $global:mutations += 'start' }
$null = New-ScheduledTaskAction -Execute 'harness.exe'
$null = New-ScheduledTaskSettingsSet
$null = New-ScheduledTaskTrigger -Daily -At '06:30'
foreach ($name in 'Get-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask', 'Disable-ScheduledTask',
                  'Enable-ScheduledTask', 'Set-ScheduledTask', 'Start-ScheduledTask') {
    $c = Get-Command $name
    if ($c.CommandType -ne 'Function' -or $c.Source) { throw "HARNESS UNSAFE: $name resolves to $($c.Source)" }
}
$params = $env:REGISTRAR_PARAMS | ConvertFrom-Json
$splat = @{}
foreach ($p in $params.PSObject.Properties) { $splat[$p.Name] = $p.Value }
if ($env:WHATIF -eq '1') { $splat['WhatIf'] = $true }
if ($env:BUILD -eq '1') { $splat['Build'] = $true }
$env:WEATHER_TASK_TEST = '1'
$out, $err = @(), ''
try { $out = @(& $env:REGISTRAR @splat 6>$null) } catch { $err = $_.Exception.Message }
foreach ($name in 'Register-ScheduledTask', 'Unregister-ScheduledTask') {
    if ((Get-Command $name).Source) { throw "HARNESS UNSAFE after run: $name resolves to $((Get-Command $name).Source)" }
}
[pscustomobject]@{ error = $err; mutations = @($global:mutations); output = ($out -join "`n") } | ConvertTo-Json -Compress
"""


def _pinned_worktree(tmp_path):
    launcher = tmp_path / "pinned" / "tools" / "research" / LAUNCHER.name
    launcher.parent.mkdir(parents=True)
    shutil.copyfile(LAUNCHER, launcher)
    return tmp_path / "pinned", hashlib.sha256(launcher.read_bytes()).hexdigest()


def register(tmp_path, *, whatif=True, build=False, new_exists=False, sha=None, name=NAME):
    wt, real_sha = _pinned_worktree(tmp_path)
    params = {"Worktree": str(wt), "WorkingDirectory": str(tmp_path / "work"), "TaskName": name,
              "ExpectedLauncherSha256": real_sha if sha is None else sha}
    env = {**os.environ, "REGISTRAR": str(REGISTRAR), "REGISTRAR_PARAMS": json.dumps(params),
           "WHATIF": "1" if whatif else "0", "BUILD": "1" if build else "0", "NEW_NAME": NAME,
           "NEW_EXISTS": "1" if new_exists else "0"}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", HARNESS], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    mutations = payload["mutations"] or []
    payload["mutations"] = [mutations] if isinstance(mutations, str) else mutations
    return payload, real_sha, wt


def test_registrar_whatif_prints_the_schedule_and_registers_nothing(tmp_path):
    payload, sha, wt = register(tmp_path)
    assert payload["error"] == "" and payload["mutations"] == []
    out = payload["output"]
    times = ["06:30"] + [f"{h:02d}:30" for h in range(7, 23)] + ["23:00"]
    assert f"daily (local, unzoned) at {', '.join(times)}" in out
    assert out.count("MSFT_TaskDailyTrigger") == 18
    for at in times:
        assert f"T{at}:00" in out
    assert "LogonType Interactive, RunLevel Limited" in out
    assert "MultipleInstances IgnoreNew, StartWhenAvailable True, ExecutionTimeLimit PT4H" in out
    launcher = BS.join(["tools", "research", LAUNCHER.name])
    assert f'-File "{wt}{BS}{launcher}" -Worktree "{wt}" -LogRoot "{tmp_path / "work"}"' in out
    assert "-Build" not in out and "Build stage      : False" in out
    assert f"Launcher sha256  : {sha}" in out
    assert "nothing registered" in out and not (tmp_path / "work").exists()


def test_registrar_build_switch_adds_the_stage_to_the_action(tmp_path):
    payload, _, _ = register(tmp_path, build=True)
    assert payload["error"] == "" and payload["mutations"] == []
    assert f'-LogRoot "{tmp_path / "work"}" -Build' in payload["output"] and "Build stage      : True" in payload["output"]


def test_registrar_without_whatif_registers_once_and_creates_the_working_directory(tmp_path):
    payload, _, _ = register(tmp_path, whatif=False)
    assert payload["error"] == "" and payload["mutations"] == [f"register:{NAME}"]
    assert (tmp_path / "work").is_dir()
    assert f"Working directory: {tmp_path / 'work'} (exists)" in payload["output"]


@pytest.mark.parametrize("case,message", [
    ("exists", "task already exists"),
    ("sha_mismatch", "!= expected"),
    ("no_sha", "pass -ExpectedLauncherSha256"),
])
def test_registrar_refuses_and_changes_nothing(tmp_path, case, message):
    kwargs = {"whatif": False}
    if case == "exists":
        kwargs["new_exists"] = True
    elif case == "sha_mismatch":
        kwargs["sha"] = "0" * 64
    else:
        kwargs["sha"] = " "
    payload, _, _ = register(tmp_path, **kwargs)
    assert message in payload["error"] and payload["mutations"] == []
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize("bad", ["a/b", "a" + BS + "b", "x:y", "w*", "q?", 'd"q', "l<t", "g>t", "p|p", " lead",
                                 "trail ", " "])
def test_registrar_refuses_invalid_task_names(tmp_path, bad):
    payload, _, _ = register(tmp_path, whatif=False, name=bad)
    assert "invalid task name" in payload["error"] and payload["mutations"] == []


def test_registrar_refuses_the_real_scheduler_under_weather_task_test(tmp_path):
    # No stubs: the registrar must refuse before anything else. -WhatIf and the fake name are belt and braces.
    wt, sha = _pinned_worktree(tmp_path)
    cmd = (f"$env:WEATHER_TASK_TEST = '1'; try {{ & '{REGISTRAR}' -WhatIf -Worktree '{wt}' "
           f"-WorkingDirectory '{tmp_path / 'work'}' -ExpectedLauncherSha256 {sha} -TaskName '{NAME}' }} "
           "catch { 'REFUSED: ' + $_.Exception.Message }")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert "REFUSED: WEATHER_TASK_TEST=1" in result.stdout, result.stdout + result.stderr


# ----------------------------------------------------------------------------- parse and bytes

@pytest.mark.parametrize("script", [LAUNCHER, REGISTRAR], ids=lambda p: p.name)
def test_scripts_parse_with_the_powershell_parser(script):
    cmd = ("$t = $null; $e = $null; "
           f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$t, [ref]$e); "
           "'ERRORS=' + @($e).Count; foreach ($x in $e) { $x.Message }")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "ERRORS=0" in result.stdout, f"{script}: {result.stdout}"


@pytest.mark.parametrize("path", [LAUNCHER, REGISTRAR, REPO_ROOT / "tests" / "operations" / "test_mg2_forward_inputs_task.py"],
                         ids=lambda p: p.name)
def test_no_control_characters_other_than_line_endings_and_tab(path):
    data = path.read_bytes()
    bad = sorted({b for b in data if (b < 0x20 and b not in (0x09, 0x0A, 0x0D)) or b == 0x7F})
    assert not bad, f"{path.name}: control bytes {bad}"
    assert data.replace(b"\r\n", b"").count(b"\r") == 0, f"{path.name}: lone CR"
    assert b"\t" not in data, f"{path.name}: a TAB where a backslash-t path was meant?"


def test_launcher_pins_are_the_b_binding_blobs():
    text = LAUNCHER.read_text(encoding="utf-8")
    for name in PINNED:
        blob = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", f"HEAD:src/weather/calibration/{name}"],
                              capture_output=True, text=True, check=True, timeout=60).stdout.strip()
        assert f"'src{BS}weather{BS}calibration{BS}{name}'" in text and f"'{blob}'" in text, name
    assert f"'{PARSER_COMMIT}'" in text
