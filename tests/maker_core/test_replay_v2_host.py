"""CONSOLIDATED row 13 (binding, DECISION_LOG 2026-10-15): ``v2/host.py`` is the single memory probe on v2 paths, and
the frozen ``maker_core/replay/ceilings.py`` stays untouched. No production data; the probe reads this process only.
"""
from __future__ import annotations

import ast
import ctypes
import gc
import hashlib
import os
from pathlib import Path
import sys
import tracemalloc

import pytest

from maker_core.replay.v2 import host

ROOT = Path(__file__).resolve().parents[2]
V2_PATHS = (ROOT / "src" / "maker_core" / "replay" / "v2", ROOT / "tools" / "research" / "maker_replay_v2")
HOST = ROOT / "src" / "maker_core" / "replay" / "v2" / "host.py"
FROZEN = ROOT / "src" / "maker_core" / "replay" / "ceilings.py"
# git blob id of maker_core/replay/ceilings.py on the build line codex/maker-replay-v2-build-20261003 (and every v2
# head since): ``git rev-parse origin/codex/maker-replay-v2-build-20261003:src/maker_core/replay/ceilings.py``.
FROZEN_CEILINGS_BLOB = "c87fd24538987b4baad7a050c856936805441d87"

PROBE_MODULES = frozenset({"psutil", "resource", "ctypes"})
PROBE_NAMES = frozenset({"process_memory", "commit_percent", "_windows_process_memory"})
PROBE_TEXT = ("GetProcessMemoryInfo", "K32GetProcessMemoryInfo", "ru_maxrss", "getrusage", "/proc/self/statm",
              "WorkingSetSize", "PagefileUsage", "memory_info(", "GlobalMemoryStatus")


def probes(source):
    """Every way ``source`` reads process memory other than through ``v2.host`` (empty when it reads none)."""
    found = [token for token in PROBE_TEXT if token in source]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] in PROBE_MODULES]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in PROBE_MODULES:
                found.append(module)
            elif module != "maker_core.replay.v2.host" and any(a.name in PROBE_NAMES for a in node.names):
                found.append(f"{module}:{','.join(a.name for a in node.names)}")
            elif module == "maker_core.replay" and any(a.name == "ceilings" for a in node.names):
                found.append("maker_core.replay.ceilings")
        elif isinstance(node, ast.Attribute) and node.attr in PROBE_NAMES and not (
                isinstance(node.value, ast.Name) and node.value.id == "host"):
            found.append("." + node.attr)
    return found


def v2_sources():
    for folder in V2_PATHS:
        for path in sorted(folder.rglob("*.py")):
            if path != HOST:
                yield path


def test_host_is_the_only_memory_probe_on_v2_paths():
    offenders = {str(p.relative_to(ROOT)): probes(p.read_text(encoding="utf-8")) for p in v2_sources()}
    assert len(offenders) > 20  # the scan really covers both trees
    assert {p: f for p, f in offenders.items() if f} == {}


@pytest.mark.parametrize("snippet", [
    "from maker_core.replay.ceilings import process_memory\n",
    "from maker_core.replay import ceilings\nceilings.process_memory()\n",
    "import psutil\n",
    "import ctypes\n",
    "def f():\n    import resource\n",
    "x = obj.process_memory()\n",
    "k.K32GetProcessMemoryInfo\n",
])
def test_the_ratchet_catches_each_probe(snippet):
    assert probes(snippet)


def test_the_ratchet_allows_the_host_module():
    assert probes("from maker_core.replay.v2.host import process_memory\nfrom maker_core.replay.v2 import host\n"
                  "host.process_memory()\nhost.counters()\n") == []
    assert probes(HOST.read_text(encoding="utf-8"))  # the probe itself would be flagged, so it is excluded by path


def test_the_frozen_v01_ceilings_file_is_byte_identical_to_the_build_line():
    data = FROZEN.read_bytes()
    blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    assert blob == FROZEN_CEILINGS_BLOB


def test_process_memory_reads_two_non_negative_ints():
    current, peak = host.process_memory()
    assert type(current) is int and type(peak) is int and 0 < current <= peak


def _cache_size():
    cache = getattr(ctypes, "_pointer_type_cache", None)
    return None if cache is None else len(cache)


@pytest.mark.skipif(os.name != "nt", reason="the leak and the shared windll are Windows ctypes paths")
def test_the_host_probe_does_not_grow_the_process():
    for _ in range(10):
        host.process_memory()
    gc.collect()
    cache = _cache_size()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for _ in range(5_000):
            host.process_memory()
        gc.collect()
        grown = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    assert grown < 64 * 1024
    assert _cache_size() == cache


@pytest.mark.skipif(os.name != "nt" or sys.version_info >= (3, 14),
                    reason="negative control: the frozen probe's per-call POINTER cache (CPython < 3.14, Windows)")
def test_negative_control_the_frozen_probe_does_grow_the_pointer_cache():
    from maker_core.replay import ceilings as frozen
    before = _cache_size()
    for _ in range(500):
        frozen.process_memory()
    assert _cache_size() - before >= 500  # the detector above is sensitive to the defect it guards


@pytest.mark.skipif(os.name != "nt", reason="ctypes.windll is Windows only")
def test_the_host_probe_never_touches_the_shared_windll():
    shared = ctypes.windll.psapi.GetProcessMemoryInfo
    argtypes = shared.argtypes
    host.process_memory()
    host.counters()
    assert ctypes.windll.psapi.GetProcessMemoryInfo.argtypes == argtypes
    state = host._windows()
    assert state["psapi"] is not ctypes.windll.psapi and state["kernel32"] is not ctypes.windll.kernel32
