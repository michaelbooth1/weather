"""C3 steps 5/6 driver: the #230 harness on this console. Kills nothing itself."""
import json, sys, tempfile
from pathlib import Path

tree, run_dir, step, mode = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), sys.argv[3], sys.argv[4]
# mode: positive | positive-stdin-closed | no_break | sitecustomize
assert mode in ("positive", "positive-stdin-closed", "no_break", "sitecustomize"), mode
assert run_dir.is_dir() and not any(run_dir.iterdir()), f"run folder must be new and empty: {run_dir}"
# F1: -S skipped site.venv(), so sys.prefix is the BASE install and the harness's sysconfig purelib would be
# the base site-packages (ModuleNotFoundError: requests). Do what site.venv() does, BEFORE the first import
# of sysconfig (it copies sys.prefix at import time), then cross-check against step 3's value. Fail closed.
assert "sysconfig" not in sys.modules, "sysconfig was imported before the venv prefix reset"
_venv = Path(sys.executable).parent.parent                      # ...\venv\Scripts\python.exe -> ...\venv
assert (_venv / "pyvenv.cfg").is_file(), f"not a venv interpreter: {sys.executable}"
sys.prefix = sys.exec_prefix = str(_venv)
import os, sysconfig
_pl = os.path.normcase(os.path.normpath(sysconfig.get_paths()["purelib"]))
_want = os.environ.get("WEATHER_FIXED_SESSION_SITE_PACKAGES", "")
assert _want and _pl == os.path.normcase(os.path.normpath(_want)), f"purelib {_pl} != step-3 site-packages {_want!r}"
sys.path.insert(0, str(tree))                  # the tests package; -S means no site, no sitecustomize
from tests.operations.live_launcher_break_harness import assert_cooperative_break, run_break_case
assert "sitecustomize" not in sys.modules
runner = tree / "src" / "weather" / "operations" / "international_live_session_runner.py"
work = Path(tempfile.mkdtemp(prefix=f"c3-{step}-{mode}-", dir=run_dir))
ALLOWANCE, TAIL, GRACE, MARGIN = 3.0, 0.5, 12.0, 7.5
positive = mode.startswith("positive")
rc, text, outcome, events = run_break_case(
    work, str(runner), allowance=ALLOWANCE, tail=TAIL, grace=GRACE,
    caller_stdin_open=(mode != "positive-stdin-closed"),       # R6: the stdin-lane shape by default
    mutant=None if positive else mode)
(work / "helper-rc.txt").write_text(str(rc), encoding="ascii")
stamps = dict(events)
lag = stamps["BREAK"] - outcome["deadline_ms"] if outcome and "BREAK" in stamps else None
print(json.dumps({"step": step, "mode": mode, "rc": rc, "outcome": outcome, "events": events,
                  "break_lag_ms": lag, "work": str(work)}, indent=1))
if positive:
    assert_cooperative_break(rc, text, outcome, events, runner_file=str(runner),
                             max_return_after_deadline_s=TAIL + MARGIN, max_elapsed_s=ALLOWANCE + GRACE)
    print("C3 STEP 5 PASS")
