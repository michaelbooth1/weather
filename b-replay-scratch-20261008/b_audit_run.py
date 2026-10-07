"""Audit-hook wrapper for the B replay (weather.backtesting.metar_v4_lockin_replay).

Usage:
  python b_audit_run.py [--audit-dir DIR] [--no-abort-on-write] [--dump-modules FILE]
                        [--module MOD] -- <replay args...>

Installs sys.addaudithook BEFORE anything from `weather` is imported, then runs the
module with runpy as __main__. Every write-capable event whose target is OUTSIDE
--audit-dir is appended to <audit-dir>/audit-writes.jsonl (one JSON object per line:
event, path, mode/flags, temp, stack[3]). With --abort-on-write (default ON) the first
non-temp such event is logged, flushed, and the process ends with os._exit(4).
Writes under %TEMP%/%TMP% are logged with "temp": true and never abort.
Exit codes of the wrapped module pass through (SystemExit propagates).

Limits: audit hooks see Python-level opens and os/shutil calls, and sqlite3.connect.
Native-library writes that bypass Python (e.g. pyarrow/C++ file sinks) are invisible.
"""
import json
import os
import sys
import threading

DEFAULT_AUDIT_DIR = r"C:\tmp\b-replay-20261008"
DEFAULT_MODULE = "weather.backtesting.metar_v4_lockin_replay"

_WRITE_FLAGS = 0
for _name in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"):
    _WRITE_FLAGS |= getattr(os, _name, 0)

_PATH_EVENTS = {
    "os.rename", "os.remove", "os.rmdir", "os.mkdir", "os.truncate", "os.symlink",
    "os.link", "os.chmod", "os.utime", "sqlite3.connect",
}
# os.replace raises "os.rename"; os.unlink raises "os.remove" (CPython audit table).


def _parse(argv):
    opts = {"audit_dir": DEFAULT_AUDIT_DIR, "abort": True, "dump": None, "module": DEFAULT_MODULE}
    if "--" not in argv:
        sys.stderr.write("b_audit_run: missing '--' before replay args\n")
        os._exit(2)
    split = argv.index("--")
    head, rest = argv[:split], argv[split + 1:]
    i = 0
    while i < len(head):
        a = head[i]
        if a == "--audit-dir":
            opts["audit_dir"] = head[i + 1]; i += 2
        elif a == "--abort-on-write":
            opts["abort"] = True; i += 1
        elif a == "--no-abort-on-write":
            opts["abort"] = False; i += 1
        elif a == "--dump-modules":
            opts["dump"] = head[i + 1]; i += 2
        elif a == "--module":
            opts["module"] = head[i + 1]; i += 2
        else:
            sys.stderr.write(f"b_audit_run: unknown option {a}\n")
            os._exit(2)
    return opts, rest


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def main():
    opts, replay_args = _parse(sys.argv[1:])
    audit_dir = _norm(opts["audit_dir"])
    os.makedirs(audit_dir, exist_ok=True)
    log_path = os.path.join(audit_dir, "audit-writes.jsonl")
    log = open(log_path, "a", encoding="utf-8")  # opened before the hook: never audited
    temp_dirs = tuple(sorted({
        form
        for k in ("TEMP", "TMP") if os.environ.get(k)
        for form in (_norm(os.environ[k]), os.path.normcase(os.path.realpath(os.environ[k])))
    }))  # both spellings, so an 8.3 short-name TEMP still matches
    abort = opts["abort"]
    state = threading.local()
    counts = {"logged": 0}

    def inside(p, root):
        return p == root or p.startswith(root.rstrip("\\/") + os.sep)

    def record(event, raw_path, extra):
        if isinstance(raw_path, int):
            # write through an already-open descriptor; the os-level open was audited
            return
        try:
            path = _norm(os.fsdecode(raw_path))
        except Exception:
            path = repr(raw_path)
        if inside(path, audit_dir):
            return
        is_temp = any(inside(path, t) for t in temp_dirs)
        frames = []
        try:
            f = sys._getframe(2)
            while f is not None and len(frames) < 3:
                frames.append(f"{f.f_code.co_filename}:{f.f_lineno}:{f.f_code.co_name}")
                f = f.f_back
        except Exception:
            pass
        line = {"event": event, "path": path, "temp": is_temp, "stack": frames}
        line.update(extra)
        log.write(json.dumps(line, default=str) + "\n")
        log.flush()
        counts["logged"] += 1
        if abort and not is_temp:
            sys.stderr.write(f"b_audit_run: ABORT on write event {event} {path}\n")
            sys.stderr.flush()
            os._exit(4)

    def hook(event, args):
        if getattr(state, "busy", False):
            return
        if event == "open":
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and flags & _WRITE_FLAGS
            )
            if not writes:
                return
            extra = {"mode": mode, "flags": flags}
            targets = [path]
        elif event in _PATH_EVENTS:
            if event == "sqlite3.connect" and str(args[0]) in (":memory:", ""):
                return
            extra = {"args": [a for a in args if not isinstance(a, (str, bytes, os.PathLike))][:3]}
            targets = [args[0]] if event != "os.rename" else [args[0], args[1]]
            if event in ("os.symlink", "os.link"):
                targets = [args[1]]
        elif event.startswith("shutil."):
            extra = {"args": [str(a) for a in args][:4]}
            targets = [a for a in args[:2] if isinstance(a, (str, bytes, os.PathLike))] or ["<shutil>"]
        else:
            return
        state.busy = True
        try:
            for t in targets:
                record(event, t, extra)
        finally:
            state.busy = False

    sys.addaudithook(hook)

    # Nothing from `weather` is imported before this point.
    import runpy

    sys.argv = [opts["module"]] + replay_args
    try:
        runpy.run_module(opts["module"], run_name="__main__", alter_sys=True)
    finally:
        if opts["dump"]:
            state.busy = True
            mods = sorted(
                f"{name}\t{getattr(m, '__file__', None)}" for name, m in list(sys.modules.items())
            )
            with open(opts["dump"], "w", encoding="utf-8") as fh:
                fh.write("\n".join(mods) + "\n")
            state.busy = False
        sys.stderr.write(f"b_audit_run: {counts['logged']} write event(s) logged to {log_path}\n")
        log.flush()


if __name__ == "__main__":
    main()
