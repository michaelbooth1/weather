"""Lane L13 recorder keepalive (tools/research/recorder_keepalive.ps1).

Runs the real keepalive in Windows PowerShell against a fixture registry of fake recorders under a temporary
directory; the real registry is refused under WEATHER_TASK_TEST=1, so no real recorder or launcher is touched.

Guards: an alive recorder (PID file plus CommandLine match) is left alone; a dead one gets its launcher run once; a
STOP file is never restarted; a check-only entry (HRRR) is logged but not started; a launcher whose sha256 differs from
the pin, or that is missing, is refused; a hung launcher is killed after the timeout; -CheckOnly starts nothing; the
keepalive STOP file stops every check; one JSON line per recorder; the pinned default registry (10 recorders, HRRR
check-only, sha256 pins matching the live launchers when present); and both scripts parse cleanly and are plain ASCII
with no control bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from weather.paths import REPO_ROOT

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell keepalive")

SCRIPT = REPO_ROOT / "tools/research/recorder_keepalive.ps1"
REGISTRAR = REPO_ROOT / "tools/research/register_recorder_keepalive_task.ps1"
B = chr(92)
MARKER = "pytest_l13_fake_keepalive_recorder"


def _launcher(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("ascii"))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry(tmp_path, name, *, body=None, restart=True, sha=None, launcher=True):
    wt = tmp_path / "wt" / name
    out = tmp_path / "out" / name
    out.mkdir(parents=True)
    rel = f"tools{B}research{B}{name}_launch.ps1"
    real = None
    if launcher:
        hit = tmp_path / f"{name}.launched"
        real = _launcher(wt / "tools" / "research" / f"{name}_launch.ps1",
                         body or f"Add-Content -LiteralPath '{hit}' -Value launched\nexit 0\n")
    return {"name": name, "worktree": str(wt), "launcher": rel, "outdir": str(out), "match": f"{MARKER}_{name}",
            "restart": restart, "sha256": sha or real or "0" * 64}


def run(tmp_path, entries, *extra, timeout=120):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps(entries), encoding="utf-8")
    logdir = tmp_path / "log"
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
           "-RegistryPath", str(reg), "-LogDir", str(logdir), *extra]
    r = subprocess.run(cmd, env={**os.environ, "WEATHER_TASK_TEST": "1"}, capture_output=True, text=True,
                       timeout=timeout)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = []
    for p in sorted(logdir.glob("keepalive_*.jsonl")):
        lines += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return {x["recorder"]: x for x in lines}, lines


@pytest.fixture
def live_fake(tmp_path):
    """A live process whose CommandLine carries the alive marker of entry 'alive'."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", f"{MARKER}_alive"])
    yield p
    p.kill()
    p.wait()


@pytest.mark.spawns
def test_alive_dead_stopped_checkonly_and_refusals_in_one_run(tmp_path, live_fake):
    alive = entry(tmp_path, "alive")
    Path(alive["outdir"], "recorder.pid").write_text(str(live_fake.pid), encoding="ascii")
    dead = entry(tmp_path, "dead")
    Path(dead["outdir"], "recorder.pid").write_text("999999", encoding="ascii")  # no such process
    stale = entry(tmp_path, "stale")  # a live PID whose CommandLine is not this recorder's
    Path(stale["outdir"], "recorder.pid").write_text(str(live_fake.pid), encoding="ascii")
    stopped = entry(tmp_path, "stopped")
    Path(stopped["outdir"], "STOP").write_text("", encoding="ascii")
    hrrr = entry(tmp_path, "hrrrlike", restart=False)
    badsha = entry(tmp_path, "badsha", sha="a" * 64)
    missing = entry(tmp_path, "missing", launcher=False)
    garbage = entry(tmp_path, "garbage")
    Path(garbage["outdir"], "recorder.pid").write_text("not-a-pid\x00", encoding="ascii")
    by, lines = run(tmp_path, [alive, dead, stale, stopped, hrrr, badsha, missing, garbage])
    assert len(lines) == 8
    assert by["alive"]["state"] == "alive" and by["alive"]["pid"] == live_fake.pid and by["alive"]["action"] == "none"
    for name in ("dead", "stale", "garbage"):
        assert by[name]["state"] == "dead" and by[name]["action"] == "launched", by[name]
        assert by[name]["state_after"] == "dead"  # the fixture launcher starts nothing
        assert (tmp_path / f"{name}.launched").read_text().count("launched") == 1
    assert by["stopped"]["state"] == "stopped" and by["stopped"]["action"] == "none"
    assert by["hrrrlike"]["state"] == "dead" and by["hrrrlike"]["action"] == "not_restarted"
    assert by["badsha"]["action"] == "refused" and "!= pinned" in by["badsha"]["detail"]
    assert by["missing"]["action"] == "refused" and "launcher missing" in by["missing"]["detail"]
    for name in ("alive", "stopped", "hrrrlike", "badsha"):
        assert not (tmp_path / f"{name}.launched").exists()
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", x["at_utc"]) for x in lines)


@pytest.mark.spawns
def test_check_only_starts_nothing(tmp_path):
    dead = entry(tmp_path, "dead")
    by, _ = run(tmp_path, [dead], "-CheckOnly")
    assert by["dead"]["action"] == "would_launch" and not (tmp_path / "dead.launched").exists()


@pytest.mark.spawns
def test_hung_launcher_is_killed_after_the_timeout(tmp_path):
    hung = entry(tmp_path, "hung", body="Start-Sleep -Seconds 60\nexit 0\n")
    by, _ = run(tmp_path, [hung], "-LauncherTimeoutSeconds", "2")
    assert by["hung"]["action"] == "launcher_timeout" and by["hung"]["state_after"] == "dead"


@pytest.mark.spawns
def test_keepalive_stop_file_stops_every_check(tmp_path):
    dead = entry(tmp_path, "dead")
    (tmp_path / "log").mkdir()
    (tmp_path / "log" / "STOP").write_text("", encoding="ascii")
    by, lines = run(tmp_path, [dead])
    assert [x["recorder"] for x in lines] == ["_keepalive"] and by["_keepalive"]["state"] == "stopped"
    assert not (tmp_path / "dead.launched").exists()


@pytest.mark.spawns
def test_real_registry_is_refused_under_the_test_guard(tmp_path):
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
           "-LogDir", str(tmp_path / "log"), "-CheckOnly"]
    r = subprocess.run(cmd, env={**os.environ, "WEATHER_TASK_TEST": "1"}, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "refusing the real registry" in (r.stdout + r.stderr)
    assert not (tmp_path / "log").exists()


def default_registry():
    text = SCRIPT.read_text(encoding="ascii")
    block = text[text.index("$DefaultRegistry = @("):text.index("\n)\n", text.index("$DefaultRegistry = @("))]
    out = []
    for m in re.finditer(r"@\{(.*?)\}(?:,|\s*$)", block, re.S):
        body = m.group(1)
        fields = dict(re.findall(r"(\w+) = '([^']*)'", body))
        fields["restart"] = re.search(r"restart = \$(true|false)", body).group(1) == "true"
        out.append(fields)
    return out


def test_default_registry_pins_the_ten_recorders():
    reg = default_registry()
    assert [r["name"] for r in reg] == ["ecmwf_ens", "eccc_gem", "gefs_00_12_18z", "gefs_06z", "hrrr", "mosmix",
                                        "nbm_text", "l3_t1_price", "l8_om_prev_runs", "iem_mos"]
    assert [r["name"] for r in reg if not r["restart"]] == ["hrrr"]
    assert len({r["outdir"] for r in reg}) == 10 and len({r["match"] for r in reg}) == 10
    for r in reg:
        assert re.fullmatch(r"[0-9a-f]{64}", r["sha256"]), r
        assert r["launcher"] == f"tools{B}research{B}{r['match']}_launch.ps1", r
        assert r["worktree"].startswith(f"C:{B}wt{B}") and r["outdir"].startswith(f"C:{B}t{B}"), r
        live = Path(r["worktree"]) / r["launcher"]
        if live.exists():  # on the workstation the pins must match the launchers in the live worktrees
            assert hashlib.sha256(live.read_bytes()).hexdigest() == r["sha256"], r["name"]


@pytest.mark.spawns
@pytest.mark.parametrize("path", [SCRIPT, REGISTRAR], ids=["keepalive", "registrar"])
def test_scripts_parse_cleanly(path):
    cmd = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
           f"'{path}', [ref]$null, [ref]$e); 'ERRORS=' + $e.Count; $e | ForEach-Object {{ $_.Message }}")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                       text=True, timeout=120)
    assert "ERRORS=0" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("path", [SCRIPT, REGISTRAR], ids=["keepalive", "registrar"])
def test_scripts_are_ascii_without_control_bytes(path):
    data = path.read_bytes()
    bad = sorted({b for b in data if b > 0x7E or (b < 0x20 and b != 0x0A)})
    assert bad == [], bad
    assert b"\r" not in data
    # the backslashes the scripts depend on survived (the escaping trap that once ate one)
    text = data.decode("ascii")
    assert f"System32{B}WindowsPowerShell{B}v1.0{B}powershell.exe" in text or path == REGISTRAR
    if path == REGISTRAR:
        assert "'[" + B + B + "/:*?" in text
