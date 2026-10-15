"""Opt-in per-step diagnostics; never changes a runner's result or exception."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
import warnings

from weather.io import write_json_atomic
from weather.paths import data_path


def current_private_bytes():
    if os.name != "nt":
        return None  # RSS/VmData are not equivalent to Windows PrivateUsage.
    from weather.operations.windows_process_metrics import windows_process_memory_metrics
    row = windows_process_memory_metrics(os.getpid())
    return row.get("private_bytes") if row else None


def run_profiled(name, runner, args, *, scope="orchestrator"):
    if not getattr(args, "profile_steps", False):
        return runner(args)
    import tracemalloc

    started = time.perf_counter()
    report = {"step": name, "scope": scope, "pid": os.getpid(), "status": "ok",
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "private_memory_sample_seconds": 0.1, "peak_private_bytes": None,
              "private_memory_basis": "sampled process PrivateUsage; excludes descendants",
              "pyinstrument": "unavailable", "errors": []}
    profiler, owns_trace, thread = None, False, None
    stop = threading.Event()
    peak = [None]

    def sample():
        try:
            value = current_private_bytes()
            if value is not None:
                peak[0] = max(peak[0] or 0, int(value))
        except Exception:
            pass

    def sampling_loop():
        while not stop.wait(0.1):
            sample()

    def record_error(label, error):
        report["errors"].append(f"{label}: {type(error).__name__}: {error}"[:500])

    try:
        sample()
        thread = threading.Thread(target=sampling_loop, name="refresh-profile-memory", daemon=True)
        thread.start()
        if not tracemalloc.is_tracing():
            tracemalloc.start(1)
            owns_trace = True
        report["tracemalloc_scope"] = "step" if owns_trace else "existing process tracer"
    except Exception as exc:
        record_error("measurement setup", exc)
    try:
        from pyinstrument import Profiler
        profiler = Profiler(interval=0.01)
        profiler.start()
        report["pyinstrument"] = "capturing"
    except Exception as exc:
        record_error("pyinstrument setup", exc)
        profiler = None
    try:
        return runner(args)
    except BaseException:
        report["status"] = "error"
        raise
    finally:
        report["wall_seconds"] = time.perf_counter() - started
        stop.set()
        if thread is not None and thread.ident is not None:
            thread.join(timeout=1)
        sample()
        report["peak_private_bytes"] = peak[0]
        report["private_memory_available"] = peak[0] is not None
        profile_text = None
        if profiler is not None:
            try:
                profiler.stop()
                text = profiler.output_text(unicode=False, color=False)
                profile_text = text[:131072]
                report["pyinstrument"] = "captured"
                report["pyinstrument_text_truncated"] = len(text) > len(profile_text)
            except Exception as exc:
                record_error("pyinstrument finish", exc)
        try:
            if tracemalloc.is_tracing():
                current, traced_peak = tracemalloc.get_traced_memory()
                report["traced_current_bytes"] = current
                report["traced_peak_bytes"] = traced_peak
                report["top_allocations"] = [
                    {"file": item.traceback[0].filename, "line": item.traceback[0].lineno,
                     "size_bytes": item.size, "count": item.count}
                    for item in tracemalloc.take_snapshot().statistics("lineno")[:20]
                ]
        except Exception as exc:
            record_error("tracemalloc finish", exc)
        finally:
            if owns_trace:
                tracemalloc.stop()
        try:
            root = Path(getattr(args, "profile_out", None) or
                        Path(getattr(args, "backtest_root", data_path() / "backtest")) / "step_profiles")
            root.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(name))
            stem = f"{safe_name}.{scope}.{os.getpid()}.{time.time_ns()}"
            if profile_text is not None:
                text_path = root / f"{stem}.pyinstrument.txt"
                text_path.write_text(profile_text, encoding="utf-8")
                report["pyinstrument_path"] = str(text_path)
            write_json_atomic(root / f"{stem}.json", report, trailing_newline=True)
        except Exception as exc:
            # Diagnostics must neither mask a step exception nor turn a
            # successful settlement/report step into a pipeline failure.
            try:
                warnings.warn(f"step profile could not be written: {exc}", RuntimeWarning)
            except Exception:
                pass  # even warnings-as-errors cannot mask the step outcome
