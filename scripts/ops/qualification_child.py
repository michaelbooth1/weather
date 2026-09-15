"""Fixed child modes, invoked with -I -S by an independently trusted launcher.

The launcher pins this file and its guard/observer before each native launch.
Only reviewed paths are added; no candidate sitecustomize or .pth is executed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys


def load(name, path, expected):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("trusted child dependency changed")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Execute the bytes just hashed, not a second path open or stale pyc.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def main():
    request_path, expected = sys.argv[1:]
    raw = Path(request_path).read_bytes()
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("child request differs")
    request = json.loads(raw)
    # These are trusted-parent-produced bytes, not a candidate request API.
    candidate = Path(request["candidate"])
    if Path.cwd() != candidate or not candidate.is_absolute():
        raise ValueError("child candidate directory differs")
    guard = load("qualification_offline_guard", request["guard"]["path"], request["guard"]["sha256"])
    guard.install(writable_roots=request["writable_roots"], forbidden_roots=request["forbidden_roots"],
                  executable_paths=request["executable_paths"])
    sys.path[:] = [str(candidate), str(candidate / "src"), *request["site_roots"],
                   *(p for p in sys.path if p and Path(p).is_absolute())]
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    mode = request["mode"]
    if mode in {"collect", "tests"}:
        import pytest

        observer = load("qualification_observer", request["observer"]["path"], request["observer"]["sha256"])
        arguments = [*(request["nodes"] if mode == "tests" else ["tests"]), "--strict-config", "--strict-markers",
                     "-o", "addopts=", "-o", "cache_dir=" + request["cache"], "--basetemp=" + request["basetemp"], "-q"]
        if mode == "collect":
            arguments.append("--collect-only")
        else:
            arguments.append("--junitxml=" + request["junit"])
        raise SystemExit(pytest.main(arguments, plugins=[observer]))
    if mode == "imports":
        import weather
        import weather.paths

        identities = []
        for module in (weather, weather.paths):
            path = Path(module.__file__).absolute()
            relative = path.relative_to(candidate).as_posix()
            identities.append({"module": module.__name__, "root": "candidate", "path": relative,
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        with open(request["imports"], "x", encoding="utf-8") as handle:
            json.dump({"imports": identities}, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        return
    if mode == "compile":
        # compileall's cache is redirected by the parent; it never writes S.
        import compileall

        sys.pycache_prefix = request["cache"]
        if not all(compileall.compile_dir(str(candidate / name), quiet=1) for name in ("app", "src", "tests")):
            raise SystemExit(1)
        return
    modules = {"agent_docs_audit": "weather.operations.agent_docs_audit",
               "roadmap_lint": "weather.reporting.roadmap.roadmap_backlog"}
    if mode not in modules:
        raise ValueError("unsupported fixed child mode")
    sys.argv = [modules[mode], *(["--fail-on-lint", "--check"] if mode == "roadmap_lint" else [])]
    runpy.run_module(modules[mode], run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
