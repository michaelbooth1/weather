"""C3 step 8 driver (v3.1). Runs the real _default_launcher_runner ONLY on the pinned stub, and
passes the stub, its child and the tree's Job helper as protected_files (deny-write + re-hash)."""
import hashlib, json, os, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path
from weather.operations import international_live_session_runner as runner
from weather.operations.live_path_security import LivePathSecurityError

assert "sitecustomize" not in sys.modules and not getattr(subprocess.Popen, "_weather_silent_windows_children", False)
HERE = Path(__file__).resolve().parent                    # C:\c3\20261008
EXPECTED_NAME = "c3_prompt_launcher.ps1"
CHILD = (HERE / "c3_prompt_child.py").resolve()
TREE = Path(os.environ["WEATHER_FIXED_SESSION_SRC"]).resolve().parent
JOB_HELPER = (TREE / "scripts" / "ops" / "windows_kill_on_close_job.ps1").resolve()
FORBIDDEN = ("international_live", "fixed_scope", "fixed_session", "session_manifest", "manifest", "seal",
             "credential", "wallet", "clob", "polymarket", "stage0", "stage1", "data\\")

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

stub = Path(sys.argv[1])
want_launcher, want_child, want_helper = (value.strip().lower() for value in sys.argv[2:5])
resolved = stub.resolve(strict=True)
text = resolved.read_text(encoding="utf-8").lower()
checks = {
    "in_scratch_folder": resolved.parent == HERE,
    "exact_name": resolved.name == EXPECTED_NAME,
    "not_a_link": not stub.is_symlink() and stub.absolute() == resolved,
    "launcher_sha256_pinned": sha256(resolved) == want_launcher,
    "child_sha256_pinned": CHILD.is_file() and sha256(CHILD) == want_child,
    "job_helper_sha256_pinned": JOB_HELPER.is_file() and sha256(JOB_HELPER) == want_helper,
    "names_the_child": str(CHILD).lower() in text,
    "no_live_reference": not any(token in text for token in FORBIDDEN),
}
print(json.dumps({"stub": str(resolved), "checks": checks}), flush=True)
if not all(checks.values()):
    print("C3 STEP 8 REFUSED: stub pin failed; the launcher control was not called", flush=True)
    sys.exit(9)

# N4: the runner itself takes deny-write handles on these files, re-hashes them, and holds the
# handles until it returns (the same mechanism that guards sealed artifacts).
protected = {resolved: want_launcher, CHILD: want_child, JOB_HELPER: want_helper}
deadline = datetime.now().astimezone() + timedelta(seconds=120)
try:
    done = runner._default_launcher_runner(resolved, timeout_seconds=130, absolute_deadline=deadline,
                                           protected_files=protected, cleanup_grace_seconds=12)
    print(json.dumps({"returncode": done.returncode, "raised": False}), flush=True)
except runner.LauncherControlError as exc:
    print(json.dumps({"raised": True, "cooperative": exc.cooperative, "forced": exc.forced,
                      "exit_code": exc.exit_code}), flush=True)
except (runner.SessionCompositionError, LivePathSecurityError) as exc:
    print(json.dumps({"refused_by_runner": type(exc).__name__, "detail": str(exc)[:200]}), flush=True)
    # v3.1 N8: the runner can also raise this AFTER launch (e.g. "launcher child-tree termination was not proved").
    print("C3 STEP 8 ABORT: the runner refused or failed; see detail (exit 9)", flush=True)
    sys.exit(9)
