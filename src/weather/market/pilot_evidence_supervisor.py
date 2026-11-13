"""Own one cancellable worker process; no live/heavy mutex or Scheduler."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import signal
import threading
import time

from weather.market.pilot_evidence_contract import ClockPlan, MIB, strict_json
from weather.market.pilot_evidence_health import BANK_BYTES, HealthFile
from weather.market.pilot_evidence_store import process_memory, stamp


def available_snapshots(connection):
    while True:
        try:
            if not connection.poll(0):
                return
            yield strict_json(connection.recv_bytes(BANK_BYTES))
        except (EOFError, OSError):
            return


class WorkerLifeline:
    """Terminate the entire worker if its supervisor is forcibly killed.

    Windows SIGTERM/TerminateProcess cannot run a Python signal handler. This
    independent worker thread detects the parent sentinel and writes the already
    reserved health bytes before os._exit ends even a blocked resolver thread.
    """
    def __init__(self, root, send, cancel):
        self.root, self.send, self.cancel = root, send, cancel
        self.latest = {"final": False, "phase": "worker_starting", "counts": {}, "gaps": {}}
        self.done = threading.Event()
        self.last_full = 0.0
        self.thread = threading.Thread(target=self.run, name="public-worker-lifeline", daemon=True)
        self.thread.start()

    def publish(self, snapshot):
        snapshot = {**snapshot, "lifeline_ready": True, "worker_pid": os.getpid()}
        now = time.monotonic()
        payload = snapshot
        if now - self.last_full < 1 and not snapshot.get("final") and not snapshot.get("stop_reason"):
            fields = ("operations", "counts", "gaps", "secondary_errors", "storage_failed",
                      "receipt_utc", "receipt_monotonic_ns", "lifeline_ready", "worker_pid")
            payload = {key: snapshot[key] for key in fields if key in snapshot}
            payload["_delta"] = True
        else:
            self.last_full = now
        raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) >= BANK_BYTES - 16384:
            raise ValueError("health snapshot exceeds reserved capacity")
        if not payload.get("_delta"):
            # Keep only a validated full receipt for parent-loss recovery.
            # Leave room for supervisor/terminal failure fields in both banks.
            self.latest = snapshot
        self.send.send_bytes(raw)

    def run(self):
        parent = multiprocessing.parent_process()
        while not self.done.wait(0.1):
            if parent is not None and not parent.is_alive():
                self.cancel.value = 2
                receipt = dict(self.latest)
                receipt.update(final=True, phase="supervisor_lost", stop_reason="supervisor_lost",
                               success=False, worker_pid=os.getpid(), exit_requested=True, **stamp())
                receipt["gaps"] = {**receipt.get("gaps", {}), "supervisor_lost": 1}
                try:
                    reserved = HealthFile.existing(self.root)
                    reserved.write(receipt)
                    reserved.close()
                finally:
                    os._exit(1)

    def close(self):
        self.done.set()
        self.thread.join(timeout=0.5)


def validate_output(root, *, new=True):
    root = Path(root)
    if (not root.is_absolute() or ".." in root.parts or
            (new and root.exists()) or (not new and not root.is_dir())):
        raise ValueError("output must be a new normalized absolute directory")
    if os.name == "nt":
        allowed = (Path("C:/t/codex/T017"), Path("C:/t/pilot1109"))
        if not any(root.is_relative_to(parent) for parent in allowed):
            raise ValueError("output outside the task/pilot evidence roots")
    for parent in (root, *root.parents):
        if parent.exists():
            stat = parent.lstat()
            if parent.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("redirected evidence path refused")
    return root


def supervise(args, worker, *, grace_seconds=3, heartbeat_seconds=15, free_space=None, memory_reader=process_memory):
    root = validate_output(args.output)
    root.mkdir(parents=True, exist_ok=False)
    health = HealthFile(root)
    plan = ClockPlan(start=getattr(args, "start_utc", None), end=getattr(args, "end_utc", None))
    context = multiprocessing.get_context("spawn")
    cancel = context.RawValue("b", 0)
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(args, send, cancel), name="public-evidence-worker")
    last = {"final": True, "success": False, "coverage_ready": False, "phase": "starting",
            "stop_reason": "startup_incomplete", "counts": {}, "gaps": {},
            "clock_anchors": plan.anchors(), "supervisor_pid": os.getpid(), **stamp()}
    health.write(last)
    previous, signaled = {}, []

    def signal_stop(signum, frame):
        signaled.append(signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, signal_stop)
    reason, stop_at, forced = None, None, False
    last_message, last_write = time.monotonic(), 0.0
    combined_peak = 0
    parent_peak = child_peak = 0
    disk = Path("C:/") if os.name == "nt" else root
    free_space = free_space or (lambda: shutil.disk_usage(disk).free)
    try:
        free = free_space()
        if free < args.min_free_gib * 1024 ** 3:
            reason = "free_space_floor"
        else:
            process.start()
            send.close()
        while process.pid is not None and process.is_alive():
            now = time.monotonic()
            # Drain complete bounded snapshots, never trust an unbounded IPC body.
            for snapshot in available_snapshots(receive):
                if not isinstance(snapshot, dict):
                    reason = reason or "invalid_worker_health"
                    break
                last = {**last, **snapshot} if snapshot.pop("_delta", False) else snapshot
                last_message = now
            if reason is None:
                if health.failed:
                    reason = "health_bank_failure"
                elif signaled:
                    reason = "operator_signal"
                elif (root / "STOP").exists():
                    reason = "operator_stop_file"
                elif plan.check_clock() is not None:
                    reason = "clock_discontinuity"
                    last["clock_discontinuity_seconds"] = plan.check_clock()
                elif plan.end_at is not None and now >= plan.end_at:
                    reason = "end_utc"
                elif any(now > op["deadline_monotonic"] for op in last.get("operations", {}).values()):
                    reason = "transport_watchdog"
                elif now - last_message > heartbeat_seconds:
                    reason = "worker_watchdog"
                elif free_space() < args.min_free_gib * 1024 ** 3:
                    reason = "free_space_floor"
                else:
                    try:
                        parent_rss, parent_high = memory_reader()
                        child_rss, child_high = memory_reader(process.pid)
                        parent_peak, child_peak = max(parent_peak, parent_high), max(child_peak, child_high)
                        combined_peak = max(combined_peak, parent_rss + child_rss)
                        if combined_peak >= args.max_rss_mib * MIB:
                            reason = "rss_cap"
                    except OSError:
                        if process.is_alive():
                            reason = "memory_measurement_failed"
            if reason and stop_at is None:
                cancel.value = 1 if reason == "end_utc" else 2
                stop_at = now
                last.update(final=False, phase="stopping", stop_reason=reason, **stamp())
                health.write(last)  # First, before cancellation/kill/final chunk work.
            if stop_at is not None and now - stop_at >= grace_seconds:
                process.kill()
                process.join(timeout=1)
                forced = True
                break
            if now - last_write >= 10 and last.get("lifeline_ready"):
                receipt = dict(last)
                receipt.update(final=False, worker_pid=process.pid,
                               supervisor_pid=os.getpid(), phase="stopping" if stop_at is not None else "running",
                               combined_sampled_peak_rss_bytes=combined_peak,
                               parent_os_peak_rss_bytes=parent_peak, worker_os_peak_rss_bytes=child_peak,
                               clock_anchors=plan.anchors(), **stamp())
                health.write(receipt)
                last_write = now
            time.sleep(0.05)
        if process.pid is not None:
            process.join(timeout=1)
            if os.name == "nt":
                try:
                    _, peak = process_memory(handle=process.sentinel)
                    child_peak = max(child_peak, peak)
                except OSError:
                    pass
            for snapshot in available_snapshots(receive):
                last = {**last, **snapshot} if snapshot.pop("_delta", False) else snapshot
        joined = process.pid is None or not process.is_alive()
        reason = reason or last.get("stop_reason") or "worker_exit_without_receipt"
        worker_final = last.get("final") is True and last.get("lifeline_ready") is True
        if forced:
            last.setdefault("gaps", {})["forced_worker_exit"] = 1
        if reason != "end_utc" and reason != "account_export_complete" and reason != "readiness_complete":
            last.setdefault("gaps", {})[reason] = max(1, last.get("gaps", {}).get(reason, 0))
        clean_exit = (joined and worker_final and not forced and process.exitcode == 0 and
                      not last.get("storage_failed") and not last.get("secondary_errors") and
                      last.get("worker_threads_joined", False))
        success = reason in ("end_utc", "account_export_complete", "readiness_complete") and clean_exit
        if reason == "venue_congestion":
            last.setdefault("coverage", {})["coverage_ready"] = False
        last.update(final=True, phase="terminated", stop_reason=reason, worker_exited=joined,
                    worker_final_receipt=worker_final, forced_worker_exit=forced,
                    worker_exit_code=process.exitcode if process.pid else None,
                    success=success, clean_exit=clean_exit, supervisor_pid=os.getpid(), worker_pid=process.pid,
                    combined_sampled_peak_rss_bytes=combined_peak, clock_anchors=plan.anchors(), **stamp())
        last.update(parent_os_peak_rss_bytes=parent_peak, worker_os_peak_rss_bytes=child_peak,
                    sum_process_os_peak_upper_bound_bytes=parent_peak + child_peak,
                    rss_peak_measurement="Windows PeakWorkingSetSize; non-Windows fallback sampled")
        health.write(last)
        return 0 if (success or reason == "venue_congestion" and clean_exit) and not health.failed else 1, last
    except Exception as exc:
        cancel.value = 2
        if process.pid is not None and process.is_alive():
            process.kill()
            process.join(timeout=1)
        last = dict(last) if isinstance(last, dict) else {"counts": {}, "gaps": {}}
        last.setdefault("gaps", {})["supervisor_failure"] = 1
        last.update(final=True, success=False, phase="failed", stop_reason="supervisor_failure",
                    error_type=type(exc).__name__, worker_pid=process.pid,
                    worker_exited=process.pid is None or not process.is_alive(), **stamp())
        try:
            health.write(last)
        except OSError:
            print("Reserved health unavailable; capture is incomplete", flush=True)
        return 1, last
    finally:
        if process.pid is not None and process.is_alive():
            process.kill()
            process.join(timeout=1)
        receive.close()
        send.close()
        health.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
