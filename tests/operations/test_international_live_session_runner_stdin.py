"""The real live launcher runner must shut down cooperatively when its caller's stdin is open.

Windows PowerShell answers Ctrl+Break inside a running script by entering its
debugger and reading a command from stdin. If the launcher child inherited an
open stdin (an operator console, or a pipe the caller holds) that read blocks,
the script never reaches its own exit, and every interrupted live session ends
as a forced Job teardown after the cleanup reserve. The runner therefore starts
the child with stdin on the null device, so the debugger reads EOF and resumes.

This test drives the production ``_default_launcher_runner`` in a helper
process whose stdin is a pipe the test keeps open for the whole run, so the
launcher's caller has exactly the open-stdin shape that blocked. The child is a
stub script: no orders, credentials, wallet or network.

Guards: cooperative Ctrl+Break shutdown of the live launcher child
(docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md) regardless of caller stdin.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from weather.operations import international_live_session_runner as runner

# Timing contract (same shape as the cooperative Ctrl+Break test beside it):
# - STARTUP_ALLOWANCE: runner call to deadline; must exceed PowerShell start-up
#   so the break lands while the script runs.
# - TAIL: the script exits 3 on its own this long after the deadline.
# - GRACE: the runner's cleanup grace (production reserve is 20 s). A forced
#   teardown cannot report before the deadline plus GRACE; a cooperative exit
#   must arrive within TAIL + MARGIN of the deadline, which leaves GAP seconds
#   of separation below GRACE. MARGIN absorbs slow CI runners: a cooperative
#   run on windows-latest was observed returning 4.9 s after the deadline.
STARTUP_ALLOWANCE_SECONDS = 3.0
TAIL_SECONDS = 0.5
GRACE_SECONDS = 12.0
MARGIN_SECONDS = 7.5
GAP_SECONDS = 4.0
COOPERATIVE_EXIT_CODE = 3

HELPER = r"""
import json, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from weather.operations import international_live_session_runner as runner
script, marker = Path(sys.argv[1]), Path(sys.argv[2])
allowance, tail, grace = (float(value) for value in sys.argv[3:6])
deadline = datetime.now().astimezone() + timedelta(seconds=allowance)
deadline_ms = int(deadline.timestamp() * 1000)
release_ms = deadline_ms + int(tail * 1000)
marker_literal = str(marker).replace("'", "''")
script.write_text(
    f"[IO.File]::WriteAllText('{marker_literal}', "
    "[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds().ToString())\n"
    f"$release = [DateTimeOffset]::FromUnixTimeMilliseconds({release_ms})\n"
    "while ([DateTimeOffset]::UtcNow -lt $release) { Start-Sleep -Milliseconds 50 }\n"
    "exit 3\n",
    encoding="utf-8",
)
outcome = {"deadline_ms": deadline_ms, "raised": False}
try:
    runner._default_launcher_runner(
        script,
        timeout_seconds=allowance + grace,
        absolute_deadline=deadline,
        cleanup_grace_seconds=grace,
    )
except runner.LauncherControlError as exc:
    outcome.update(
        raised=True,
        cooperative=exc.cooperative,
        forced=exc.forced,
        exit_code=exc.exit_code,
    )
outcome["returned_ms"] = int(time.time() * 1000)
outcome["runner_file"] = runner.__file__
print("OUTCOME " + json.dumps(outcome), flush=True)
"""


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt", reason="Windows Job containment is Windows-only")
def test_default_runner_shuts_down_cooperatively_with_caller_stdin_open(tmp_path):
    src_root = Path(runner.__file__).resolve().parents[2]
    script = tmp_path / "cooperative.ps1"
    marker = tmp_path / "script-started.txt"
    output = tmp_path / "helper-output.txt"
    # The helper imports the same runner module this test imported.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(src_root), env.get("PYTHONPATH", "")) if part
    )

    with output.open("wb") as sink:
        helper = subprocess.Popen(
            [
                sys.executable, "-c", HELPER, str(script), str(marker),
                str(STARTUP_ALLOWANCE_SECONDS), str(TAIL_SECONDS), str(GRACE_SECONDS),
            ],
            stdin=subprocess.PIPE,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            # The caller's stdin stays open (never written, never closed) until
            # the runner has returned, as in an operator console run.
            helper.wait(timeout=STARTUP_ALLOWANCE_SECONDS + GRACE_SECONDS + 60)
        finally:
            if helper.poll() is None:
                helper.kill()
                helper.wait(timeout=10)
            helper.stdin.close()

    text = output.read_text(encoding="utf-8", errors="replace")
    # A parked debugger prompt has no trailing newline, so the outcome can
    # share its line; match the marker anywhere.
    outcomes = re.findall(r"OUTCOME (\{.*\})", text)
    assert helper.returncode == 0, text
    assert len(outcomes) == 1, text
    outcome = json.loads(outcomes[0])
    assert Path(outcome["runner_file"]).resolve() == Path(runner.__file__).resolve()

    # The break landed while the script ran and PowerShell entered its debugger,
    # so this run exercised the stdin-dependent path.
    assert int(marker.read_text(encoding="utf-8")) < outcome["deadline_ms"], text
    assert "debug mode" in text, text
    assert outcome["raised"] is True, text
    assert outcome["cooperative"] is True, text
    assert outcome["forced"] is False, text
    assert outcome["exit_code"] == COOPERATIVE_EXIT_CODE, text
    cleanup_seconds = (outcome["returned_ms"] - outcome["deadline_ms"]) / 1000
    assert TAIL_SECONDS + MARGIN_SECONDS <= GRACE_SECONDS - GAP_SECONDS
    assert cleanup_seconds < TAIL_SECONDS + MARGIN_SECONDS, text
