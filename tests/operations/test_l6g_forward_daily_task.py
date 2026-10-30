"""Lane L2: the L6_G forward daily emission wrapper and its workstation task registrar (no Scheduler change).

Guards: the registrar's -WhatIf prints six local unzoned daily triggers (07:30..22:30), an Interactive / Limited
principal and the pinned-worktree action, and registers nothing; the wrapper refuses the whole run (logged, exit 0,
nothing else written) when a pinned module blob differs or the STOP file exists; a date whose vectors exist is a
no-op; a missing bundle before the receiver's deadline is a logged refusal that starts no Python and creates no
inbox; dates before D0 or not yet finished are refused; -WhatIf writes nothing. No test starts Python through the
wrapper (the interpreter path is a non-existent file) or touches the share, B's ledger or the Scheduler.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "tools" / "research" / "l6g_forward_daily.ps1"
REGISTRAR = ROOT / "tools" / "research" / "register_l6g_forward_daily_task.ps1"
PINNED = ("l6g_forward_emit.py", "l6g_forward_look.py", "l6g_forward_frame.py", "mg2_inputs.py", "mg2_composite.py")

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="requires Windows PowerShell"),
]


def _ps(script, *args, timeout=120):
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _worktree(tmp_path, *, tamper=None):
    wt = tmp_path / "wt"
    (wt / "src" / "weather" / "calibration").mkdir(parents=True)
    for name in PINNED:
        data = (ROOT / "src" / "weather" / "calibration" / name).read_bytes()
        if name == tamper:
            data += b"\n# tampered\n"
        (wt / "src" / "weather" / "calibration" / name).write_bytes(data)
    return wt


def _root(tmp_path, day):
    root = tmp_path / "forward"
    (root / "gefs" / day).mkdir(parents=True)
    (root / "gefs" / day / "manifest.json").write_text("{}")
    (root / "state").mkdir()
    (root / "state" / "l6g_state.json").write_text("{}")
    (root / "pins").mkdir()
    for name in ("l6.pkl", "coef.json"):
        (root / "pins" / name).write_text("x")
    return root


def _run(tmp_path, wt, root, *extra):
    share = tmp_path / "share"
    share.mkdir(exist_ok=True)
    return _ps(WRAPPER, "-Worktree", str(wt), "-Root", str(root), "-ShareRoot", str(share),
               "-Python", str(tmp_path / "no-such-python.exe"), "-L6State", str(root / "pins" / "l6.pkl"),
               "-Coefficients", str(root / "pins" / "coef.json"), "-FirstDate", "2026-01-01", *extra)


def _yesterday():
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


def _runs(root):
    path = root / "logs" / "runs.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def test_registrar_whatif_registers_nothing(tmp_path):
    wt = tmp_path / "pinned"
    (wt / "tools" / "research").mkdir(parents=True)
    shutil.copyfile(WRAPPER, wt / "tools" / "research" / WRAPPER.name)
    name = f"L2 test {uuid.uuid4().hex}"
    out = _ps(REGISTRAR, "-TaskName", name, "-Worktree", str(wt), "-WhatIf")
    assert out.returncode == 0, out.stderr
    text = out.stdout
    assert "nothing registered" in text
    assert text.count("MSFT_TaskDailyTrigger") == 6
    for at in ("07:30", "10:30", "13:30", "16:30", "19:30", "22:30"):
        assert f"T{at}:00" in text
    assert "LogonType Interactive, RunLevel Limited" in text
    assert "StartWhenAvailable True" in text
    assert str(wt / "tools" / "research" / WRAPPER.name) in text
    check = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"[bool](Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue)"],
                           capture_output=True, text=True, timeout=60, check=False)
    assert check.stdout.strip() == "False"


def test_wrapper_refuses_a_tampered_pinned_module(tmp_path):
    day = _yesterday()
    wt, root = _worktree(tmp_path, tamper="l6g_forward_emit.py"), _root(tmp_path, day)
    out = _run(tmp_path, wt, root, "-Date", day)
    assert out.returncode == 0, out.stderr
    assert "refused:" in out.stdout and "l6g_forward_emit.py blob" in out.stdout
    assert sorted(p.name for p in root.iterdir()) == ["gefs", "logs", "pins", "state"]
    assert not (root / "logs" / "runs.jsonl").exists()


def test_wrapper_stop_file_runs_nothing(tmp_path):
    day = _yesterday()
    wt, root = _worktree(tmp_path), _root(tmp_path, day)
    (root / "STOP").write_text("")
    out = _run(tmp_path, wt, root, "-Date", day)
    assert out.returncode == 0 and "STOP file present" in out.stdout


def test_emitted_date_is_a_noop(tmp_path):
    day = _yesterday()
    wt, root = _worktree(tmp_path), _root(tmp_path, day)
    (root / "vectors").mkdir()
    (root / "vectors" / f"{day}.parquet").write_bytes(b"emitted")
    out = _run(tmp_path, wt, root, "-Date", day)
    assert out.returncode == 0, out.stderr
    assert [(r["date"], r["outcome"]) for r in _runs(root)] == [(day, "noop")]
    assert (root / "vectors" / f"{day}.parquet").read_bytes() == b"emitted"


def test_missing_bundle_is_a_logged_refusal_without_a_partial_emit(tmp_path):
    day = _yesterday()
    wt, root = _worktree(tmp_path), _root(tmp_path, day)
    out = _run(tmp_path, wt, root, "-Date", day)
    assert out.returncode == 0, out.stderr
    rows = _runs(root)
    assert [(r["date"], r["outcome"]) for r in rows] == [(day, "refused")]
    assert "bundle missing" in rows[0]["detail"]
    for absent in ("inbox", "work", "frames", "vectors", "input_receipts.jsonl"):
        assert not (root / absent).exists(), absent
    log = next((root / "logs").glob("daily_*.log")).read_text(encoding="utf-8-sig")
    assert "bundle missing" in log and "done" in log


def test_missing_recorder_manifest_is_refused(tmp_path):
    day = _yesterday()
    wt, root = _worktree(tmp_path), _root(tmp_path, day)
    (root / "gefs" / day / "manifest.json").unlink()
    out = _run(tmp_path, wt, root, "-Date", day)
    assert out.returncode == 0, out.stderr
    assert "GEFS recorder manifest missing" in _runs(root)[0]["detail"]


def test_dates_before_d0_or_unfinished_are_refused(tmp_path):
    day = _yesterday()
    wt, root = _worktree(tmp_path), _root(tmp_path, day)
    today = dt.date.today().isoformat()
    out = _run(tmp_path, wt, root, "-Date", today)
    assert out.returncode == 0 and "not a finished local date" in out.stdout
    out = _ps(WRAPPER, "-Worktree", str(wt), "-Root", str(root), "-Python", str(tmp_path / "none.exe"),
              "-Date", "2026-10-30")
    assert out.returncode == 0 and "before the first emitted date 2026-10-31" in out.stdout


def test_wrapper_whatif_writes_nothing(tmp_path):
    day = _yesterday()
    wt, root = _worktree(tmp_path), _root(tmp_path, day)
    out = _run(tmp_path, wt, root, "-Date", day, "-WhatIf")
    assert out.returncode == 0, out.stderr
    assert "WhatIf:" in out.stdout
    assert not (root / "logs").exists()
