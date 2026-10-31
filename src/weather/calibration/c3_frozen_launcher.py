r"""C3 frozen-tool launcher: the fixed 13 x 2 bundle builds and 2 scorer runs for the C3 kill tier (lane L16).

Master ruling (d), 2026-10-31: one allowlisted launcher, run as ONE ``workstation_heavy.ps1 -Queue`` job, so the frozen
``d937b34`` builder and scorer run under the wrapper's mutex and child-tree contract. The command list is FIXED here;
the only argument is ``--out``. Every child runs serially from the clean detached worktree ``SCORER_TREE`` at
``FROZEN_COMMIT`` (so the scorer stamps ``code_tip`` = d937b34 and the C3 driver's R5 passes unchanged), with
``-E -s``, cwd = ``SCORER_TREE\src`` and an explicit environment without PYTHONPATH and PYTHONHOME.

Why ``-E -s`` and not ``-I`` (approved by master as option (i)): under ``-I`` the venv's ``__editable__`` .pth
resolves ``weather`` to the MAIN checkout's ``src`` and drops the cwd, so the frozen modules cannot be imported
from the frozen tree. ``-E -s`` keeps the cwd as ``sys.path[0]``. The cwd is the frozen tree's ``src`` (not its root):
from the root, the ``weather`` shim resolves to the frozen tree but ``maker_core`` still comes from the main checkout
through the editable .pth (sitecustomize is not imported, because the cwd joins sys.path only after site runs).
Before EVERY child a pre-flight
child under the identical interpreter, flags, cwd and environment asserts that ``weather.__file__``,
``maker_core.__file__``, ``maker_core.replay.bundle``'s origin, the target module's spec origin and
``weather.paths.REPO_ROOT`` all resolve inside
``SCORER_TREE``; the frozen tree's HEAD and an empty ``git status --porcelain`` are re-checked too.

    python -m weather.calibration.c3_frozen_launcher --out <new dir>

Writes only under ``--out``: ``passA/<day>``, ``passB/<day>`` (bundles), ``report1``, ``report2`` (scorer),
``children/`` (pre-flight and child stdout/stderr) and ``launcher_receipt.json``. Exit 0 = all 28 children
succeeded; 2 = refused (nothing run past the refusal); 3 = a child exited non-zero or timed out (stopped there,
never retried). Kill-only research tooling: no network import, no live, order or credential path.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "c3_frozen_launcher/1"
FROZEN_COMMIT = "d937b34ab1d50cd4b8e35e80901184f7f0f82a9f"
SCORER_TREE = Path(r"C:\wt\l16-c3scorer")
DATA_ROOT = Path(r"C:\t\ex2b1\data")
DAYS = tuple(f"2026-09-{d:02d}" for d in range(25, 31)) + tuple(f"2026-10-{d:02d}" for d in range(1, 8))
ABSENT_DAYS = ("2026-09-23", "2026-09-24")
ABSENT_NOTE = ("UTC days 2026-09-23 and 2026-09-24 are absent (never captured on the host). Lead-1/2 conditions for "
               "targets 09-25/26 that need those quote days are missing, not filled; C3's frozen coverage floor "
               "decides, INCONCLUSIVE as frozen.")
# DRAFT section 6: --markets <all 12>, the built-in ids at d937b34 (weather.market.market_registry.BUILTIN_SPECS).
MARKETS = ("toronto", "nyc", "atlanta", "austin", "chicago", "dallas", "denver", "houston", "los-angeles", "miami",
           "san-francisco", "seattle")
BUILDER = "weather.market.maker_replay_bundle"
SCORER = "weather.market.maker_fair_value_score"
FLAGS = ("-E", "-s")
BUILD_TIMEOUT_S = 360
SCORE_TIMEOUT_S = 1800
PREFLIGHT_TIMEOUT_S = 120
SCRUBBED_ENV_KEYS = ("PYTHONPATH", "PYTHONHOME")
PTH_TRAP_NOTE = ("Under -I the venv's __editable__ .pth resolves weather to the main checkout's src (and drops the "
                 "cwd), so -E -s with cwd = the frozen tree's src is used (from the tree root, maker_core still "
                 "resolved to the main checkout); a per-child pre-flight proves the import origin.")
PREFLIGHT_CODE = (
    "import importlib.util, json, sys\n"
    "import weather, maker_core, weather.paths\n"
    "spec = importlib.util.find_spec(sys.argv[1])\n"
    "print(json.dumps({'weather': weather.__file__, 'maker_core': maker_core.__file__,\n"
    "    'module_origin': spec.origin if spec else None, 'repo_root': str(weather.paths.REPO_ROOT),\n"
    "    'maker_core_replay_bundle': importlib.util.find_spec('maker_core.replay.bundle').origin,\n"
    "    'sys_path0': sys.path[0], 'executable': sys.executable,\n"
    "    'flags': {'ignore_environment': sys.flags.ignore_environment, 'no_user_site': sys.flags.no_user_site,\n"
    "              'isolated': sys.flags.isolated}}, sort_keys=True))\n"
)
PREFLIGHT_PATH_KEYS = ("weather", "maker_core", "maker_core_replay_bundle", "module_origin", "repo_root")


def child_cwd():
    return SCORER_TREE / "src"

EXIT_OK, EXIT_REFUSED, EXIT_CHILD_FAILED = 0, 2, 3


class Refused(Exception):
    """A refusal: exit 2; no further child runs."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan(out):
    """The fixed command list: 13 days x passes A and B of the builder, then the scorer twice on pass A."""
    out = Path(out)
    steps = []
    for p in ("A", "B"):
        for day in DAYS:
            target = out / f"pass{p}" / day
            steps.append(dict(name=f"build_{p}_{day}", module=BUILDER, timeout_s=BUILD_TIMEOUT_S, output=target,
                              args=["bundle", "--date", day, "--data-root", str(DATA_ROOT), "--markets", *MARKETS,
                                    "--out", str(target)]))
    bundles = [str(out / "passA" / day) for day in DAYS]
    for k in (1, 2):
        target = out / f"report{k}"
        steps.append(dict(name=f"score_{k}", module=SCORER, timeout_s=SCORE_TIMEOUT_S, output=target,
                          args=[*(a for b in bundles for a in ("--bundle", b)), "--out", str(target)]))
    return steps


def child_argv(python, step):
    return [str(python), *FLAGS, "-m", step["module"], *step["args"]]


def preflight_argv(python, module):
    return [str(python), *FLAGS, "-c", PREFLIGHT_CODE, module]


def child_env(base=None):
    """A copy of the environment without PYTHONPATH / PYTHONHOME (any case); returns (env, removed keys)."""
    base = dict(os.environ if base is None else base)
    drop = {k.upper() for k in SCRUBBED_ENV_KEYS}
    removed = sorted(k for k in base if k.upper() in drop)
    return {k: v for k, v in base.items() if k.upper() not in drop}, removed


def _inside(path, root):
    if not path:
        return False
    p = os.path.normcase(str(Path(path).resolve()))
    r = os.path.normcase(str(Path(root).resolve()))
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


# ----------------------------------------------------------------------------- process control (Windows)

_PROCESS_QUERY_LIMITED_INFORMATION, _SYNCHRONIZE, _WAIT_TIMEOUT = 0x1000, 0x00100000, 0x102


class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    k.CloseHandle.argtypes = (ctypes.c_void_p,)
    k.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    k.K32GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.POINTER(_PMC), ctypes.c_ulong)
    return k


def open_handle(pid):
    """Cache a query handle right after spawn so the exit state and peak RSS stay readable."""
    if os.name != "nt":
        return None
    return _kernel32().OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid) or None


def peak_working_set(handle):
    if not handle:
        return None
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    return int(pmc.PeakWorkingSetSize) if _kernel32().K32GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb) else None


def close_handle(handle):
    if handle:
        _kernel32().CloseHandle(handle)


def pid_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k = _kernel32()
    h = k.OpenProcess(_SYNCHRONIZE, False, pid)
    if not h:
        return False
    try:
        return k.WaitForSingleObject(h, 0) == _WAIT_TIMEOUT
    finally:
        k.CloseHandle(h)


def kill_tree(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
    else:
        os.kill(pid, 9)


class Runner:
    """Real git checks and child processes; tests substitute a fake with the same two methods."""

    def git(self, *args):
        return subprocess.run(["git", "-C", str(SCORER_TREE), *args], capture_output=True, text=True,
                              check=True).stdout

    def run(self, argv, cwd, env, timeout_s, stdout_path, stderr_path):
        return run_child(argv, cwd, env, timeout_s, stdout_path, stderr_path)


def run_child(argv, cwd, env, timeout_s, stdout_path, stderr_path):
    """Run one child; on timeout kill its whole tree. Returns exit code, runtime, timeout flag and peak RSS."""
    t0 = time.monotonic()
    with open(stdout_path, "xb") as so, open(stderr_path, "xb") as se:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=so, stderr=se, stdin=subprocess.DEVNULL)
        handle = open_handle(proc.pid)
        timed_out = False
        try:
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_tree(proc.pid)
                proc.wait()
            peak = peak_working_set(handle)
        finally:
            close_handle(handle)
    return dict(pid=proc.pid, exit_code=proc.returncode, timed_out=timed_out,
                runtime_s=round(time.monotonic() - t0, 3), peak_working_set_bytes=peak)


# ----------------------------------------------------------------------------- checks

def check_tree(runner):
    try:
        head = runner.git("rev-parse", "HEAD").strip()
        porcelain = runner.git("status", "--porcelain", "--untracked-files=all").strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Refused(f"git failed in {SCORER_TREE}: {exc}") from exc
    if head != FROZEN_COMMIT:
        raise Refused(f"{SCORER_TREE} HEAD is {head}, not {FROZEN_COMMIT}")
    if porcelain:
        raise Refused(f"{SCORER_TREE} is dirty: {porcelain.splitlines()[:5]}")
    return dict(head=head, porcelain_empty=True)


def preflight(runner, python, module, env, children, index):
    tree = check_tree(runner)
    so, se = children / f"{index:02d}_preflight.stdout.txt", children / f"{index:02d}_preflight.stderr.txt"
    run = runner.run(preflight_argv(python, module), child_cwd(), env, PREFLIGHT_TIMEOUT_S, so, se)
    record = dict(tree=tree, module=module, exit_code=run["exit_code"], timed_out=run["timed_out"])
    if run["exit_code"] != 0 or run["timed_out"]:
        raise Refused(f"pre-flight for {module} failed: exit {run['exit_code']}, timed_out {run['timed_out']}")
    try:
        found = json.loads(Path(so).read_text(encoding="utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise Refused(f"pre-flight for {module} printed no JSON") from exc
    record["imports"] = found
    outside = [k for k in PREFLIGHT_PATH_KEYS if not _inside(found.get(k), SCORER_TREE)]
    if outside:
        raise Refused(f"pre-flight for {module}: {outside} resolve outside {SCORER_TREE}: "
                      + json.dumps({k: found.get(k) for k in outside}))
    flags = found.get("flags", {})
    if not (flags.get("ignore_environment") and flags.get("no_user_site")):
        raise Refused(f"pre-flight for {module}: interpreter flags are not -E -s: {flags}")
    return record


def check_out(out):
    out = Path(out).resolve()
    if out.exists() or not out.parent.is_dir():
        raise Refused("a new --out directory is required (it must not exist; its parent must)")
    for other in (SCORER_TREE, DATA_ROOT):
        other = Path(other).resolve()
        if out == other or out.is_relative_to(other) or other.is_relative_to(out):
            raise Refused(f"--out overlaps {other}")
    return out


def _outputs(path):
    path = Path(path)
    if not path.exists():
        return []
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    return [dict(path=str(p), bytes=p.stat().st_size, sha256=sha256_file(p)) for p in files]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write_receipt(out, receipt):
    tmp = out / "launcher_receipt.json.tmp"
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, out / "launcher_receipt.json")


# ----------------------------------------------------------------------------- main

def main(argv=None, runner=None, python=None):
    ap = argparse.ArgumentParser(prog="python -m weather.calibration.c3_frozen_launcher", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="new directory; every write goes under it")
    args = ap.parse_args(argv)
    runner = runner or Runner()
    python = Path(python or sys.executable)
    try:
        out = check_out(args.out)
        start_tree = check_tree(runner)
    except Refused as exc:
        print(f"c3 frozen launcher refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    env, removed = child_env()
    steps = plan(out)
    receipt = dict(schema=SCHEMA, status="RUNNING", started_utc=_now(), launcher=__name__,
                   launcher_sha256=sha256_file(__file__), frozen_commit=FROZEN_COMMIT, scorer_tree=str(SCORER_TREE),
                   child_cwd=str(child_cwd()),
                   data_root=str(DATA_ROOT), python=str(python), flags=list(FLAGS), env_keys_removed=removed,
                   scrubbed_env_keys=list(SCRUBBED_ENV_KEYS), pth_trap_note=PTH_TRAP_NOTE, days=list(DAYS),
                   absent_days=list(ABSENT_DAYS), absent_note=ABSENT_NOTE, markets=list(MARKETS),
                   timeouts_s=dict(build=BUILD_TIMEOUT_S, score=SCORE_TIMEOUT_S, preflight=PREFLIGHT_TIMEOUT_S),
                   wrapper=dict(active=os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE"),
                                slot=os.environ.get("WEATHER_WORKSTATION_WRAPPER_SLOT")),
                   start_tree=start_tree, plan=[child_argv(python, s) for s in steps], steps=[])
    out.mkdir()
    for sub in ("passA", "passB", "children"):
        (out / sub).mkdir()
    children = out / "children"
    _write_receipt(out, receipt)
    code = EXIT_OK
    for i, step in enumerate(steps, 1):
        rec = dict(index=i, name=step["name"], argv=child_argv(python, step), cwd=str(child_cwd()),
                   timeout_s=step["timeout_s"])
        receipt["steps"].append(rec)
        try:
            rec["preflight"] = preflight(runner, python, step["module"], env, children, i)
        except Refused as exc:
            rec["refused"] = str(exc)
            receipt.update(status="REFUSED", refusal=str(exc))
            code = EXIT_REFUSED
            break
        so, se = children / f"{i:02d}_{step['name']}.stdout.txt", children / f"{i:02d}_{step['name']}.stderr.txt"
        rec["started_utc"] = _now()
        rec.update(runner.run(rec["argv"], child_cwd(), env, step["timeout_s"], so, se))
        rec["outputs"] = _outputs(step["output"])
        rec["stdout"], rec["stderr"] = _outputs(so), _outputs(se)
        _write_receipt(out, receipt)
        if rec["exit_code"] != 0 or rec["timed_out"]:
            receipt.update(status="STOPPED", stopped_at=step["name"])
            code = EXIT_CHILD_FAILED
            break
    else:
        receipt["status"] = "COMPLETE"
    receipt["finished_utc"] = _now()
    _write_receipt(out, receipt)
    print(json.dumps({"status": receipt["status"], "steps_run": len(receipt["steps"]), "of": len(steps)}))
    return code


if __name__ == "__main__":
    sys.exit(main())
