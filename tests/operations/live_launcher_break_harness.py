"""Shared harness for the live launcher's cooperative Ctrl+Break tests.

Guards: cooperative Ctrl+Break shutdown of the live launcher child
(docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md), proved without console text.

The production ``_default_launcher_runner`` runs in a helper process that gets
its OWN hidden console (CREATE_NEW_CONSOLE with SW_HIDE). Ctrl+Break is a
console event: it reaches only processes on the sender's console. Under the
production bounded suite (pytest started with CREATE_NO_WINDOW, 2026-10-06
host chunks 16 and 18) the launcher child landed on no shared console, the
break was never delivered, and the stub simply reached its own exit; the old
"debug mode" console-text precondition failed there. With a console of its own
the helper delivers the break on every host.

The stub script proves delivery itself: a ``DebuggerStop`` handler on its
runspace debugger appends ``BREAK <ms>`` to a marker file when PowerShell
answers Ctrl+Break, so the precondition needs no console text. The stub writes
``START <ms>`` first and ``EXIT <ms>`` before exiting 3 at its release time.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

COOPERATIVE_EXIT_CODE = 3

HELPER = r"""
import json, os, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from weather.operations import international_live_session_runner as runner
script, marker = Path(sys.argv[1]), Path(sys.argv[2])
allowance, tail, grace = (float(value) for value in sys.argv[3:6])
child_stdin = []
real_popen = runner.subprocess.Popen
def popen_spy(*args, **kwargs):
    child_stdin.append(repr(kwargs.get("stdin")))
    process = real_popen(*args, **kwargs)
    if os.environ.get("BREAK_HARNESS_MUTANT") == "no_break":
        process.send_signal = lambda sig: None  # mutant: the runner sends no Ctrl+Break
    return process
runner.subprocess.Popen = popen_spy
deadline = datetime.now().astimezone() + timedelta(seconds=allowance)
deadline_ms = int(deadline.timestamp() * 1000)
release_ms = deadline_ms + int(tail * 1000)
lit = str(marker).replace("'", "''")
script.write_text(
    "$onStop = [EventHandler[System.Management.Automation.DebuggerStopEventArgs]]{ param($s, $e) "
    f"[IO.File]::AppendAllText('{lit}', \"BREAK $([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())`n\") }}\n"
    "$Host.Runspace.Debugger.add_DebuggerStop($onStop)\n"
    f"[IO.File]::AppendAllText('{lit}', \"START $([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())`n\")\n"
    f"$release = [DateTimeOffset]::FromUnixTimeMilliseconds({release_ms})\n"
    "while ([DateTimeOffset]::UtcNow -lt $release) { Start-Sleep -Milliseconds 50 }\n"
    f"[IO.File]::AppendAllText('{lit}', \"EXIT $([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())`n\")\n"
    "exit 3\n",
    encoding="utf-8",
)
outcome = {"deadline_ms": deadline_ms, "release_ms": release_ms, "raised": False}
started = time.monotonic()
try:
    runner._default_launcher_runner(
        script, timeout_seconds=allowance + grace, absolute_deadline=deadline, cleanup_grace_seconds=grace)
except runner.LauncherControlError as exc:
    outcome.update(raised=True, cooperative=exc.cooperative, forced=exc.forced, exit_code=exc.exit_code)
outcome["elapsed_s"] = time.monotonic() - started
outcome["returned_ms"] = int(time.time() * 1000)
outcome["runner_file"] = runner.__file__
outcome["child_stdin"] = child_stdin
print("OUTCOME " + json.dumps(outcome), flush=True)
"""


def run_break_case(tmp_path: Path, runner_file: str, *, allowance: float, tail: float, grace: float,
                   caller_stdin_open: bool, mutant: str | None = None) -> tuple[int, str, dict | None, list[tuple[str, int]]]:
    """Run the real runner once in a hidden-console helper; return (rc, output, outcome, marker events)."""

    src_root = Path(runner_file).resolve().parents[2]
    script = tmp_path / "cooperative.ps1"
    marker = tmp_path / "markers.txt"
    output = tmp_path / "helper-output.txt"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(part for part in (str(src_root), env.get("PYTHONPATH", "")) if part)
    env.pop("BREAK_HARNESS_MUTANT", None)
    if mutant:
        env["BREAK_HARNESS_MUTANT"] = mutant
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # SW_HIDE
    with output.open("wb") as sink:
        helper = subprocess.Popen(
            [sys.executable, "-c", HELPER, str(script), str(marker), str(allowance), str(tail), str(grace)],
            stdin=subprocess.PIPE if caller_stdin_open else subprocess.DEVNULL,
            stdout=sink, stderr=subprocess.STDOUT, env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup,
        )
        try:
            # An open caller stdin stays open (never written, never closed) until the runner returns.
            helper.wait(timeout=allowance + grace + 60)
        finally:
            if helper.poll() is None:
                helper.kill()
                helper.wait(timeout=10)
            if helper.stdin:
                helper.stdin.close()
    text = output.read_text(encoding="utf-8", errors="replace")
    found = re.findall(r"OUTCOME (\{.*\})", text)
    outcome = json.loads(found[0]) if len(found) == 1 else None
    events = []
    if marker.exists():
        for line in marker.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition(" ")
            events.append((name, int(value)))
    return helper.returncode, text, outcome, events


def assert_cooperative_break(rc: int, text: str, outcome: dict | None, events: list[tuple[str, int]], *,
                             runner_file: str, max_return_after_deadline_s: float, max_elapsed_s: float) -> None:
    """Precondition (the break landed while the stub ran) plus the hard outcome asserts."""

    assert rc == 0 and outcome is not None, text
    assert Path(outcome["runner_file"]).resolve() == Path(runner_file).resolve()
    assert outcome["child_stdin"] == [repr(subprocess.DEVNULL)], outcome
    names = [name for name, _ in events]
    stamps = dict(events)
    # Precondition, console-independent: the stub was running at the deadline and its own
    # DebuggerStop handler recorded the break before the stub's release.
    assert names[:1] == ["START"] and stamps["START"] < outcome["deadline_ms"], (events, outcome)
    assert "BREAK" in stamps, f"Ctrl+Break never reached the stub ({events}); {text}"
    assert stamps["START"] < stamps["BREAK"] < outcome["release_ms"], (events, outcome)
    # Outcome: hard asserts, never tolerated.
    assert outcome["raised"] is True, text
    assert outcome["cooperative"] is True, text
    assert outcome["forced"] is False, text
    assert outcome["exit_code"] == COOPERATIVE_EXIT_CODE, text
    assert "EXIT" in stamps, (events, outcome)
    assert (outcome["returned_ms"] - outcome["deadline_ms"]) / 1000 < max_return_after_deadline_s, outcome
    assert outcome["elapsed_s"] < max_elapsed_s, outcome
