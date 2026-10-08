"""The exchange-economics refresh task leaves a diagnosable status file (Swarm P audit F1).

Guards: docs/operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md (scheduled task and status
file). WeatherExchangeEconomicsSnapshotRefresh returned 1 on 2026-10-06 and 2026-10-07 with
no output to read. The registrar must bind 06:50 local, -File and S4U/Limited, and the
helper must write data\\logs\\exchange_economics_refresh_status.json on every exit path.
The Windows cases run the real helper against a scratch repository root; nothing is
registered and no network or production data is touched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
REGISTRAR = OPS / "register_exchange_economics_refresh.ps1"
HELPER = OPS / "refresh_exchange_economics_snapshot.ps1"

WINDOWS_POWERSHELL = pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="requires Windows PowerShell",
)


def test_registrar_binds_0650_local_file_action_and_limited_principal():
    text = REGISTRAR.read_text(encoding="utf-8-sig")
    assert '[ValidateSet("06:50")][string]$At = "06:50"' in text
    assert "$trigger = New-WeatherLocalDailyTrigger -At $At" in text
    assert '-File `"$script`"' in text
    assert "-Command" not in text.split("$arguments =", 1)[1].split("\n", 1)[0]
    assert "-LogonType S4U" in text
    assert "-RunLevel Limited" in text
    assert "Highest" not in text
    assert "Test-WeatherLocalDailyStartBoundary" in text
    assert '[string]$registered[0].Principal.RunLevel -ne "Limited"' in text


def _scratch_root(tmp_path: Path, *, with_venv: bool) -> Path:
    root = tmp_path / "repo"
    (root / "scripts" / "ops").mkdir(parents=True)
    shutil.copy2(HELPER, root / "scripts" / "ops" / HELPER.name)
    if with_venv:
        # A real venv launcher without the project installed: the collector import
        # fails, which stands in for any nonzero collector exit.
        if sys.prefix == sys.base_prefix:
            pytest.skip("needs a virtual-environment interpreter to clone")
        scripts = root / "venv" / "Scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(Path(sys.prefix) / "pyvenv.cfg", root / "venv" / "pyvenv.cfg")
        shutil.copy2(Path(sys.executable), scripts / "python.exe")
    return root


def _run_helper(root: Path, *extra: str) -> tuple[int, dict]:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(root / "scripts" / "ops" / HELPER.name), "-RepoRoot", str(root), "-TargetDate", "2026-10-07", *extra],
        capture_output=True, text=True, timeout=120, env=env, cwd=root,
    )
    status_path = root / "data" / "logs" / "exchange_economics_refresh_status.json"
    assert status_path.is_file(), result.stdout + result.stderr
    status = json.loads(status_path.read_text(encoding="utf-8"))
    history = (root / "data" / "logs" / "exchange_economics_refresh_history.jsonl").read_text(encoding="utf-8")
    assert json.loads(history.splitlines()[-1]) == status
    return result.returncode, status


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_missing_interpreter_is_refused_with_a_status_file(tmp_path):
    code, status = _run_helper(_scratch_root(tmp_path, with_venv=False))
    assert code == 3
    assert status["status"] == "REFUSED" and status["exit_code"] == 3
    assert "venv python not found" in status["reason"]
    assert status["task"] == "WeatherExchangeEconomicsSnapshotRefresh"


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_wrong_platform_is_refused_with_a_status_file(tmp_path):
    code, status = _run_helper(_scratch_root(tmp_path, with_venv=False), "-Platform", "polymarket_us")
    assert code == 2
    assert status["status"] == "REFUSED" and "polymarket_global" in status["reason"]


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_collector_failure_records_exit_code_and_output_tail(tmp_path):
    code, status = _run_helper(_scratch_root(tmp_path, with_venv=True))
    assert code == 1
    assert status["status"] == "FAIL" and status["exit_code"] == 1
    assert status["reason"] == "collector exited 1"
    assert any("weather" in line for line in status["output_tail"]), status
    assert status["target_date"] == "2026-10-07"


FAKE_COLLECTOR = '''
import os, sys, time
from pathlib import Path
Path(os.environ["FAKE_COLLECTOR_MARK"]).write_text("started", encoding="utf-8")
print("fake collector running")
time.sleep(float(os.environ.get("FAKE_COLLECTOR_SLEEP", "0")))
sys.exit(int(os.environ.get("FAKE_COLLECTOR_EXIT", "0")))
'''


def _fake_collector_env(tmp_path: Path, *, sleep: float, exit_code: int) -> dict:
    package = tmp_path / "fakepkg" / "weather" / "market"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "exchange_economics.py").write_text(FAKE_COLLECTOR, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update(
        PYTHONPATH=str(tmp_path / "fakepkg"),
        FAKE_COLLECTOR_MARK=str(tmp_path / "collector.started"),
        FAKE_COLLECTOR_SLEEP=str(sleep),
        FAKE_COLLECTOR_EXIT=str(exit_code),
    )
    return env


def _helper_command(root: Path) -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(root / "scripts" / "ops" / HELPER.name), "-RepoRoot", str(root), "-TargetDate", "2026-10-07"]


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_successful_collection_records_pass(tmp_path):
    root = _scratch_root(tmp_path, with_venv=True)
    result = subprocess.run(_helper_command(root), capture_output=True, text=True, timeout=120,
                            env=_fake_collector_env(tmp_path, sleep=0, exit_code=0), cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    status = json.loads((root / "data" / "logs" / "exchange_economics_refresh_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "PASS" and status["exit_code"] == 0
    assert "fake collector running" in status["output_tail"]
    history = (root / "data" / "logs" / "exchange_economics_refresh_history.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["status"] for line in history] == ["PASS"]  # RUNNING never reaches history


@WINDOWS_POWERSHELL
@pytest.mark.spawns
def test_a_killed_run_leaves_a_running_marker_not_the_previous_result(tmp_path):
    root = _scratch_root(tmp_path, with_venv=True)
    logs = root / "data" / "logs"
    logs.mkdir(parents=True)
    status_path = logs / "exchange_economics_refresh_status.json"
    status_path.write_text(json.dumps({"status": "PASS", "started_at_utc": "2026-10-06T10:50:00Z"}), encoding="utf-8")

    process = subprocess.Popen(_helper_command(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env=_fake_collector_env(tmp_path, sleep=60, exit_code=0), cwd=root)
    try:
        deadline = time.monotonic() + 60
        while not (tmp_path / "collector.started").exists():
            assert process.poll() is None, "helper exited before the collector started"
            assert time.monotonic() < deadline, "collector never started"
            time.sleep(0.2)
        running = json.loads(status_path.read_text(encoding="utf-8"))
        assert running["status"] == "RUNNING" and running["exit_code"] == -1
        assert running["pid"] == process.pid
    finally:
        # Same effect as the Scheduler's execution-limit kill: the whole tree, no cleanup.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
        process.wait(timeout=60)

    after = json.loads(status_path.read_text(encoding="utf-8"))
    assert after["status"] == "RUNNING"  # stale RUNNING is the kill signal
    assert not (logs / "exchange_economics_refresh_history.jsonl").exists()
