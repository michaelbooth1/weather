"""Shared harness for the live launcher's cooperative Ctrl+Break tests.

Guards: cooperative Ctrl+Break shutdown of the live launcher child
(docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md), proved without console text, in the
interpreter configuration production uses.

The production ``_default_launcher_runner`` runs in a helper process started EXACTLY as
scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl starts the
live runner: ``python -I -S -B -c`` with ``src`` inserted first and site-packages
appended from ``WEATHER_FIXED_SESSION_SRC`` / ``WEATHER_FIXED_SESSION_SITE_PACKAGES``,
in the repository working directory. The helper shares whatever console its parent
has (under the bounded suite, pytest's own hidden console); the runner and its
PowerShell child then share the helper's. Isolated mode never loads the repository
``sitecustomize.py``, and ``tests/operations/test_live_runner_console_guards.py``
binds these flags and this bootstrap to the template.

Root cause of the 2026-10-06 host failures (chunks 16 and 18): when the repository
root is on sys.path at start-up, ``sitecustomize.py`` (and
``weather.operations.windows_silent``) wrap ``subprocess.Popen`` to add
CREATE_NO_WINDOW. The runner's PowerShell child then gets its own windowless console,
Ctrl+Break (a console event for the sender's console) never reaches it, and the stub
simply exits on its own: the runner still reports "cooperative". The live runner is
started with ``-I -S`` and never loads either patch.

The stub proves delivery itself: a ``DebuggerStop`` handler on its runspace debugger
appends ``BREAK <ms>`` to a marker file when PowerShell answers Ctrl+Break. It writes
``START <ms>`` first and ``EXIT <ms>`` before exiting 3 at its release time.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

COOPERATIVE_EXIT_CODE = 3

# The template's runner bootstrap, verbatim apart from running the helper body instead of runpy.
PRODUCTION_FLAGS = ("-I", "-S", "-B")
BOOTSTRAP = (
    "import os,runpy,sys;sys.dont_write_bytecode=True;"
    "sys.path.insert(0,os.environ['WEATHER_FIXED_SESSION_SRC']);"
    "sys.path.append(os.environ['WEATHER_FIXED_SESSION_SITE_PACKAGES']);"
)

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
stamp = "$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
script.write_text("\n".join([
    "$onStop = [EventHandler[System.Management.Automation.DebuggerStopEventArgs]]{ param($s, $e) "
    + "[IO.File]::AppendAllText('" + lit + "', \"BREAK " + stamp + "`n\") }",
    "$Host.Runspace.Debugger.add_DebuggerStop($onStop)",
    "[IO.File]::AppendAllText('" + lit + "', \"START " + stamp + "`n\")",
    "$release = [DateTimeOffset]::FromUnixTimeMilliseconds(" + str(release_ms) + ")",
    "while ([DateTimeOffset]::UtcNow -lt $release) { Start-Sleep -Milliseconds 50 }",
    "[IO.File]::AppendAllText('" + lit + "', \"EXIT " + stamp + "`n\")",
    "exit 3",
]) + "\n", encoding="utf-8")
outcome = {"deadline_ms": deadline_ms, "release_ms": release_ms, "raised": False,
           "popen_silenced": bool(getattr(real_popen, "_weather_silent_windows_children", False)),
           "sitecustomize_loaded": "sitecustomize" in sys.modules}
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
                   caller_stdin_open: bool, mutant: str | None = None,
                   ) -> tuple[int, str, dict | None, list[tuple[str, int]]]:
    """Run the real runner once in a helper started like production; return (rc, output, outcome, markers).

    ``mutant="no_break"`` makes the runner send no Ctrl+Break. ``mutant="sitecustomize"``
    starts the helper the way the failing test contexts did (no isolation, repository root
    on PYTHONPATH), so the repository ``sitecustomize.py`` silences console children.
    """

    src_root = Path(runner_file).resolve().parents[2]
    repo_root = src_root.parent
    script = tmp_path / "cooperative.ps1"
    marker = tmp_path / "markers.txt"
    output = tmp_path / "helper-output.txt"
    env = {k: v for k, v in os.environ.items()
           if k not in ("BREAK_HARNESS_MUTANT", "WEATHER_ALLOW_CONSOLE_CHILDREN", "PYTHONPATH")}
    env["WEATHER_FIXED_SESSION_SRC"] = str(src_root)
    env["WEATHER_FIXED_SESSION_SITE_PACKAGES"] = sysconfig.get_paths()["purelib"]
    args = [str(script), str(marker), str(allowance), str(tail), str(grace)]
    if mutant == "sitecustomize":
        env["PYTHONPATH"] = os.pathsep.join([str(repo_root), str(src_root)])
        command = [sys.executable, "-c", HELPER, *args]
    else:
        if mutant:
            env["BREAK_HARNESS_MUTANT"] = mutant
        command = [sys.executable, *PRODUCTION_FLAGS, "-c", BOOTSTRAP + HELPER, *args]
    with output.open("wb") as sink:
        helper = subprocess.Popen(
            command, stdin=subprocess.PIPE if caller_stdin_open else subprocess.DEVNULL,
            stdout=sink, stderr=subprocess.STDOUT, env=env, cwd=str(repo_root))
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
    if outcome is not None and mutant != "sitecustomize":
        # A production-shaped run must load neither console-silencing Popen patch.
        assert outcome["sitecustomize_loaded"] is False and outcome["popen_silenced"] is False, text
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
