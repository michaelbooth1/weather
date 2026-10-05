"""Untracked probe: the real launcher runner with its production cleanup grace, Ctrl+Break at several
points from PowerShell start-up onwards. Records every outcome; asserts nothing."""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from weather.operations import international_live_session_runner as runner

OUT = Path(os.environ.get("PROBE_OUT", r"C:\wt\workstation-chat\l-data\flake\probe.jsonl"))
TAIL = 1.5


@pytest.mark.parametrize("rep", range(int(os.environ.get("PROBE_REPS", "15"))))
@pytest.mark.parametrize("allowance", [0.0, 0.3, 1.0, 5.0])
def test_probe(tmp_path, allowance, rep):
    grace = runner.COOPERATIVE_CLEANUP_GRACE_SECONDS
    marker = tmp_path / "m.txt"
    deadline = datetime.now().astimezone() + timedelta(seconds=allowance)
    deadline_ms = int(deadline.timestamp() * 1000)
    release_ms = deadline_ms + int(TAIL * 1000)
    lit = str(marker).replace("'", "''")
    script = tmp_path / "s.ps1"
    script.write_text(
        f"[IO.File]::WriteAllText('{lit}', [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds().ToString())\n"
        f"$release = [DateTimeOffset]::FromUnixTimeMilliseconds({release_ms})\n"
        "while ([DateTimeOffset]::UtcNow -lt $release) { Start-Sleep -Milliseconds 50 }\n"
        "exit 3\n",
        encoding="utf-8",
    )
    t0 = time.monotonic()
    rec = {"allowance": allowance, "rep": rep, "grace": grace}
    try:
        runner._default_launcher_runner(
            script, timeout_seconds=allowance + grace, absolute_deadline=deadline,
            cleanup_grace_seconds=grace,
        )
        rec["raised"] = False
    except runner.LauncherControlError as exc:
        rec.update(raised=True, cooperative=exc.cooperative, forced=exc.forced, exit_code=exc.exit_code)
    except Exception as exc:  # noqa: BLE001
        rec.update(raised=True, other=repr(exc)[:200])
    rec["elapsed"] = round(time.monotonic() - t0, 3)
    rec["marker_minus_deadline_ms"] = (
        int(marker.read_text(encoding="utf-8")) - deadline_ms if marker.exists() else None
    )
    with open(OUT, "a", encoding="utf-8") as h:
        h.write(json.dumps(rec) + "\n")
