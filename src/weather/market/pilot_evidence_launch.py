"""Independent evidence-only process ownership; never start, wait for or stop F0."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from weather.paths import REPO_ROOT
from weather.schema_families import schema_version
from weather.market.pilot_evidence_contract import strict_json
from weather.market.pilot_evidence_supervisor import validate_output


def capture_arguments(args):
    result = ["-B", "-m", "weather.market.pilot_validation_evidence", "public-capture"]
    for market in args.market:
        result += ["--market", market]
    for day in args.event_date:
        result += ["--event-date", day.isoformat()]
    result += ["--all-bands", "--both-tokens", "--raw-market-stream", "--end-utc", args.end_utc.isoformat()]
    if args.start_utc:
        result += ["--start-utc", args.start_utc.isoformat()]
    for field in ("rest_book_seconds", "terms_seconds", "fee_seconds", "fee_rate_seconds", "metadata_seconds",
                  "time_sample_seconds", "max_age_seconds", "max_mark_delay_seconds", "max_rest_rps",
                  "max_rss_mib", "max_output_mib", "min_free_gib", "output"):
        result += ["--" + field.replace("_", "-"), str(getattr(args, field))]
    return result


def source_tip():
    def git(*args):
        return subprocess.run(["git", "-C", str(REPO_ROOT), *args], check=True, capture_output=True,
                              text=True, timeout=5).stdout.strip()
    tip = git("rev-parse", "HEAD")
    if git("status", "--porcelain"):
        raise ValueError("independent launch requires a clean pinned worktree")
    return tip


def launch(args, *, popen=subprocess.Popen, tip_reader=source_tip):
    root = validate_output(args.output)
    if args.end_utc <= datetime.now(timezone.utc):
        raise ValueError("absolute end has passed; a late launch never extends it")
    if args.start_utc and args.end_utc <= args.start_utc:
        raise ValueError("end must follow planned start")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_tip) or tip_reader() != args.expected_tip:
        raise ValueError("launch tip differs from the reviewed pin")
    # No live/heavy mutex, F0 path, F0 PID or shared cleanup callback exists here.
    command = [sys.executable, *capture_arguments(args)]
    root.parent.mkdir(parents=True, exist_ok=True)
    handle = root.with_name(root.name + ".launch.json")
    receipt = {"kind": "pilot_public_evidence_handle", "schema_version": schema_version("pilot_public_evidence_handle"), "output": str(root),
               "expected_tip": args.expected_tip, "end_utc": args.end_utc.isoformat(),
               "created_utc": datetime.now(timezone.utc).isoformat(), "command": command,
               "automatic_restart": False, "phase": "launching"}
    with handle.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream)
    child = None
    try:
        with root.with_name(root.name + ".stdout.log").open("xb") as out, root.with_name(root.name + ".stderr.log").open("xb") as err:
            options = {"cwd": str(REPO_ROOT), "stdin": subprocess.DEVNULL, "stdout": out, "stderr": err,
                       "close_fds": True}
            if os.name == "nt":
                # Own process group, detached from its caller's console
                # and Job. A caller Job that forbids breakaway refuses launch.
                # Never weaken the caller Job or move F0 into this process tree.
                options["creationflags"] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP |
                                             subprocess.CREATE_BREAKAWAY_FROM_JOB)
            else:
                options["start_new_session"] = True
            child = popen(command, **options)
        receipt.update(phase="launched", supervisor_pid=child.pid, launcher_pid=os.getpid())
        with handle.open("w", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
    except Exception as exc:
        if child is not None and child.poll() is None:
            child.terminate()  # This exact newly created handle only, never a PID tree.
            child.wait(timeout=5)
        receipt.update(phase="launch_failed", error_type=type(exc).__name__, evidence_gap=True)
        with handle.open("w", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
        raise
    return receipt  # No wait, readiness gate, retry or automatic restart.


def stop(output):
    root = validate_output(output, new=False)
    handle = root.with_name(root.name + ".launch.json")
    if handle.is_symlink() or getattr(handle.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("redirected evidence handle refused")
    with handle.open("rb") as stream:
        receipt = strict_json(stream.read(65537), max_bytes=65536)
    if (receipt.get("kind") != "pilot_public_evidence_handle" or
            receipt.get("schema_version") != schema_version("pilot_public_evidence_handle") or
            Path(receipt.get("output", "")) != root):
        raise ValueError("handle does not own this evidence directory")
    path = root / "STOP"
    try:
        with path.open("xb") as stream:
            stream.write(b"owner requested evidence-only stop\n")
    except FileExistsError:
        pass
    # No OpenProcess/kill/PID reuse hazard. Only this supervisor watches this file.
    return {"stop_requested": True, "output": str(root), "handle": str(handle),
            "end_utc": receipt["end_utc"], "f0_controlled": False}
