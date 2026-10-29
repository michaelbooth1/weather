"""ws_ping_watchdog.ps1 on simulated probes only: no network probe, no toast, no scheduled task."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "ws_ping_watchdog.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell")


def _run(state_dir: Path, probe: str, now: str) -> tuple[int, dict]:
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-StateDir", str(state_dir), "-SimulateProbe", probe, "-NowUtc", now, "-NoToast"],
        capture_output=True, text=True, timeout=60, check=False)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, proc.stdout + proc.stderr
    return proc.returncode, json.loads(lines[-1])


def test_alert_once_remind_then_recover(tmp_path: Path) -> None:
    seq = [("down", "2026-10-28T16:00:00Z", 0, None), ("down", "2026-10-28T16:05:00Z", 2, "ALERT"),
           ("down", "2026-10-28T16:10:00Z", 0, None), ("ws_offline", "2026-10-28T16:15:00Z", 0, None),
           ("down", "2026-10-28T17:05:00Z", 2, "REMINDER"), ("down", "2026-10-28T17:10:00Z", 0, None),
           ("up", "2026-10-28T17:15:00Z", 0, "RECOVERED"), ("up", "2026-10-28T17:20:00Z", 0, None)]
    for probe, now, code, event in seq:
        rc, rec = _run(tmp_path, probe, now)
        assert (rc, rec["event"]) == (code, event), (probe, now, rec)
    assert rec["consecutive_misses"] == 0 and rec["alerting"] is False
    log = (tmp_path / "ws_ping_watchdog.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == len(seq) and all(json.loads(x)["simulated"] for x in log)
    misses = [json.loads(x)["consecutive_misses"] for x in log]
    assert misses[:4] == [1, 2, 3, 3]  # ws_offline neither counts a miss nor resets the count


def test_single_miss_never_alerts_and_gaps_are_logged(tmp_path: Path) -> None:
    for probe, now in (("down", "2026-10-28T16:00:00Z"), ("up", "2026-10-28T16:05:00Z"),
                       ("down", "2026-10-28T16:10:00Z"), ("up", "2026-10-28T18:10:00Z")):
        rc, rec = _run(tmp_path, probe, now)
        assert rc == 0 and rec["event"] is None
    assert rec["watchdog_gap"] is True and rec["minutes_since_last_run"] == 120
