"""C3 step 7 (v3): operator Ctrl+C. The driver ignores Ctrl+C itself. A sentinel child records
the console SIGINT. The verdict comes from a separate judge run that reads helper-output.txt,
markers.txt, sentinel.txt and this run's own ledger line. It is binary: PASS or FAIL."""
import signal
signal.signal(signal.SIGINT, signal.SIG_IGN)   # FIRST: never consume the operator's Ctrl+C (not inherited by children)

import json, re, subprocess, sys, tempfile, time
from pathlib import Path

ALLOWANCE, TAIL, GRACE, MARGIN = 20.0, 0.5, 12.0, 7.5
PREFIX = "c3-s7-ctrlc-"
HERE = Path(__file__).resolve().parent                 # C:\c3\20261008
LEDGER = HERE / "launch-ledger.txt"
SENTINEL_WINDOW_S = ALLOWANCE + GRACE
# The sentinel: same console, same process group, inside the C3 Job (a child of this driver).
# It records READY, then every console SIGINT with a wall-clock ms stamp, then DONE, and exits on
# its own. time.sleep is interruptible on Windows, so the stamp is taken at the keypress.
SENTINEL = (
    "import signal,sys,time\n"
    "p=sys.argv[1]\n"
    "def rec(kind):\n"
    "    with open(p,'a',encoding='ascii') as h: h.write('%s %d\\n'%(kind,int(time.time()*1000)))\n"
    "signal.signal(signal.SIGINT,lambda s,f:rec('SIGINT'))\n"
    "rec('READY')\n"
    "end=time.monotonic()+float(sys.argv[2])\n"
    "while time.monotonic()<end: time.sleep(0.1)\n"
    "rec('DONE')\n")


def runner_file(tree: Path) -> Path:
    return tree / "src" / "weather" / "operations" / "international_live_session_runner.py"


def read_stamps(path: Path) -> list:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition(" ")
            rows.append((name, int(value)))
    return rows


def ledger_row(label: str):
    lines = [line for line in LEDGER.read_text(encoding="utf-8-sig").splitlines() if f" label={label} " in line]
    if len(lines) != 1:
        return None, len(lines)
    return dict(re.findall(r"(\w+)=(\[[^\]]*\]|\S+)", lines[0])), 1


def judge(tree: Path, work: Path, label: str, mode: str) -> int:
    sys.path.insert(0, str(tree))
    from tests.operations.live_launcher_break_harness import assert_cooperative_break
    work = work.resolve()
    control = mode == "control"
    want = PREFIX + ("control-" if control else "")
    if (mode not in ("operator", "control") or not work.name.startswith(want)
            or (not control and work.name.startswith(PREFIX + "control-")) or work.parent.parent != HERE):
        print(f"C3 STEP 7 FAIL refusing {work} for mode {mode!r}: not this step's work folder")
        return 2
    failures, timing = [], []
    output = work / "helper-output.txt"
    text = output.read_text(encoding="utf-8", errors="replace") if output.exists() else ""
    found = re.findall(r"OUTCOME (\{.*\})", text)
    outcome = json.loads(found[0]) if len(found) == 1 else None
    events = read_stamps(work / "markers.txt")
    rc_file = work / "helper-rc.txt"
    rc = int(rc_file.read_text(encoding="ascii").strip()) if rc_file.exists() else -1
    stamps = dict(events)
    try:
        assert_cooperative_break(rc, text, outcome, events, runner_file=str(runner_file(tree)),
                                 max_return_after_deadline_s=TAIL + MARGIN, max_elapsed_s=ALLOWANCE + GRACE)
    except (AssertionError, KeyError, TypeError) as exc:
        failures.append("step-5 asserts: " + (str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__))
    sentinel = read_stamps(work / "sentinel.txt")
    ready = [t for k, t in sentinel if k == "READY"]
    done = [t for k, t in sentinel if k == "DONE"]
    sigint = [t for k, t in sentinel if k == "SIGINT"]
    if len(ready) != 1:
        failures.append(f"sentinel READY count {len(ready)} (exactly 1 required)")
    if len(done) != 1:
        failures.append(f"sentinel DONE count {len(done)} (exactly 1 required)")
    start, deadline = stamps.get("START"), (outcome or {}).get("deadline_ms")
    in_window = (len(sigint) == 1 and len(ready) == 1 and start is not None and deadline is not None
                 and ready[0] < sigint[0] and start < sigint[0] < deadline)
    if control:
        if sigint:
            failures.append(f"control: sentinel recorded {len(sigint)} SIGINT with no keypress (spurious)")
    elif not in_window:
        timing.append(f"sentinel SIGINT {sigint} is not exactly one stamp between START/READY and the deadline")
    row, count = ledger_row(label)
    if row is None:
        failures.append(f"ledger has {count} lines for {label} (exactly 1 required)")
    else:
        for key, value in (("rc", "0"), ("timedOut", "False"), ("interrupted", "False"), ("verify", "OK"),
                           ("escaped", "0"), ("memberMismatch", "0"), ("consoleForeign", "0")):
            if row.get(key) != value:
                failures.append(f"ledger {key}={row.get(key)} (want {value})")
        want_ctrl = ("False", "0") if control else ("True", "1")
        got_ctrl = (row.get("ctrlC"), row.get("ctrlCCount"))
        if got_ctrl != want_ctrl:
            message = f"ledger ctrlC/ctrlCCount={got_ctrl} (want {want_ctrl})"
            (timing if (not control and not in_window) else failures).append(message)
    hardstop = row is not None and (row.get("verify") == "HARDSTOP" or row.get("escaped") != "0"
                                    or row.get("memberMismatch") != "0" or row.get("consoleForeign") != "0")
    honoured = None
    if outcome is not None and "elapsed_s" in outcome:
        honoured = "at_keypress" if outcome["elapsed_s"] < ALLOWANCE - 1.0 else "at_wait_return"
    passed = not failures and not timing
    print(json.dumps({"step": "s7", "mode": mode, "label": label, "work": str(work), "rc": rc, "outcome": outcome,
                      "events": events, "sentinel": sentinel,
                      "sigint_after_start_ms": (sigint[0] - start) if sigint and start else None,
                      "sigint_before_deadline_ms": (deadline - sigint[0]) if sigint and deadline else None,
                      "break_lag_ms": (stamps["BREAK"] - deadline) if deadline and "BREAK" in stamps else None,
                      "honoured_info_only": honoured, "ledger": row,
                      "failures": failures, "timing_failures": timing,
                      "operator_timing_only": (not passed and not failures and bool(timing))}, indent=1))
    if hardstop:
        print("C3 STEP 7 HARD STOP: the run's ledger line shows escaped, memberMismatch or consoleForeign")
        return 3
    name = "C3 STEP 7 CONTROL" if control else "C3 STEP 7"
    print(f"{name} PASS" if passed else f"{name} FAIL")
    return 0 if passed else 1


def run(tree: Path, run_dir: Path, mode: str) -> int:
    assert mode in ("operator", "control"), mode
    run_dir = run_dir.resolve()
    assert run_dir.parent == HERE, f"run folder must be directly under {HERE}: {run_dir}"
    assert run_dir.is_dir() and not any(run_dir.iterdir()), f"run folder must be new and empty: {run_dir}"
    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
    # F1: -S skipped site.venv(), so sys.prefix is the BASE install and the harness's sysconfig purelib would be
    # the base site-packages. Do what site.venv() does, BEFORE the first import of sysconfig (it copies
    # sys.prefix at import time), then cross-check against step 3's value. Fail closed.
    assert "sysconfig" not in sys.modules, "sysconfig was imported before the venv prefix reset"
    venv = Path(sys.executable).parent.parent                   # ...\venv\Scripts\python.exe -> ...\venv
    assert (venv / "pyvenv.cfg").is_file(), f"not a venv interpreter: {sys.executable}"
    sys.prefix = sys.exec_prefix = str(venv)
    import os, sysconfig
    purelib = os.path.normcase(os.path.normpath(sysconfig.get_paths()["purelib"]))
    want = os.environ.get("WEATHER_FIXED_SESSION_SITE_PACKAGES", "")
    assert want and purelib == os.path.normcase(os.path.normpath(want)), f"purelib {purelib} != step-3 site-packages {want!r}"
    sys.path.insert(0, str(tree))
    from tests.operations.live_launcher_break_harness import run_break_case
    assert "sitecustomize" not in sys.modules
    work = Path(tempfile.mkdtemp(prefix=PREFIX + ("control-" if mode == "control" else ""), dir=run_dir))
    sentinel_file = work / "sentinel.txt"
    sentinel = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", SENTINEL, str(sentinel_file),
                                 str(SENTINEL_WINDOW_S)], stdin=subprocess.DEVNULL)
    ready_by = time.monotonic() + 15
    while time.monotonic() < ready_by:
        if sentinel_file.exists() and "READY " in sentinel_file.read_text(encoding="ascii"):
            break
        time.sleep(0.05)
    else:
        print("C3 STEP 7: sentinel not READY within 15 s; not running the case (the judge will FAIL)", flush=True)
        return 3                                     # no kill path: the C3 Job ends the sentinel at close
    print("C3 STEP 7 WORK " + str(work), flush=True)
    if mode == "operator":
        print("C3 STEP 7: wait for the wrapper's 'START and sentinel READY' line, press Ctrl+C ONCE, then wait.", flush=True)
    else:
        print("C3 STEP 7 CONTROL: press NOTHING.", flush=True)
    rc, _text, _outcome, _events = run_break_case(
        work, str(runner_file(tree)), allowance=ALLOWANCE, tail=TAIL, grace=GRACE,
        caller_stdin_open=True, mutant=None)
    (work / "helper-rc.txt").write_text(str(rc), encoding="ascii")
    try:
        sentinel.wait(timeout=SENTINEL_WINDOW_S + 30)    # it exits on its own; no kill path
    except subprocess.TimeoutExpired:
        print("C3 STEP 7: sentinel still running; the C3 Job ends it at close (the judge will FAIL: no DONE)", flush=True)
        return 3
    print("C3 STEP 7 RUN DONE: judge it with the separate 'judge' run (the verdict needs this run's ledger line)", flush=True)
    return 0


if __name__ == "__main__":
    verb = sys.argv[1]
    if verb == "run":
        sys.exit(run(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]))
    if verb == "judge":
        sys.exit(judge(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]))
    sys.exit(f"unknown verb {verb!r}")
