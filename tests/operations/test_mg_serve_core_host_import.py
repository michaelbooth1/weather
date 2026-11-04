"""C4: ``weather.model.mg_serve_core`` imports on the capture host and stays the only serve copy.

Guards: plan C:\\t\\l3\\neutral\\plan.md (sha 83707862...) section (c) C4, and L2's MG-3 design prerequisite b.0.
A host serve path must never need a research module that refuses the capture host. Three ratchets:

1. Host import: a child interpreter emulates the capture host (the tracked capture-host id) and imports the core.
   It runs the lazily-imported numpy, scipy and pandas paths, and asserts that no ``weather.calibration`` or
   ``weather.reporting`` module was loaded. As a positive control, a refusing research module still refuses in
   the same child.
2. Import allowlist: every ``import`` in the core, top-level or lazy, is in a pinned set.
3. No new copies: the core's distinctive serve names may not be defined anywhere else under ``src/weather``
   except in the pinned research sources. Stage A does not rewire them (master ruling D1, 2026-10-26), so the
   pinned map records today's duplicates. It may only shrink: Stage B removes entries as it rewires each
   source. Names too generic to ratchet (``parse_time``, ``iso``, ``finite``, ``availability``, ``cycle_time``,
   ``pool``, ``compose``) are pinned by C1 parity instead.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE = REPO_ROOT / "src" / "weather" / "model" / "mg_serve_core.py"

ALLOWED_IMPORTS = {
    "collections", "datetime", "fractions", "hashlib", "json", "math", "pathlib", "pickle", "re",
    "numpy", "pandas", "scipy.special",
    "weather.paths", "weather.units",
}

GENERIC = {"parse_time", "iso", "finite", "availability", "cycle_time", "pool", "compose"}

# Known duplicates at Stage A: {module under src/weather: names}. Shrink-only.
KNOWN_COPIES = {
    "calibration/feature_model.py": {"smoothed_dist"},
    "calibration/high_so_far_parity_shadow.py": {"event_folders", "mg1_band_probs"},
    "calibration/intraday_calibration.py": {"smoothed_dist"},
    "calibration/mg2_composite.py": {"distribution_band_frame", "floor_B"},
    "calibration/mg2_inputs.py": {"select_v2"},
    "calibration/mg2_p3d_n.py": {"nearest_centre", "predictive_distribution", "smoothed_dist"},
    "calibration/ols_floor_ladder.py": {"season_of"},
    "calibration/pooled_residual_model.py": {"exact_tgroup_f", "nearest_centre", "predictive_distribution",
                                             "round_candidate", "season_of", "state_distribution", "state_features",
                                             "station_coordinates", "wu_whole_f"},
    "calibration/r0_ols_floor_challenger.py": {"l6_captured_features", "metar_observation_instant",
                                               "observations_at_cutoff", "parse_captured_metar", "routine_dmax"},
    "calibration/r0_ols_floor_devfit.py": {"usable_v2_mean"},
    "reporting/research/guidance_extract.py": {"select_v2"},
}

CHILD = r"""
import json, sys
from datetime import date
from weather import execution_host
capture_id = str(execution_host.load_execution_host_assignment()["dedicated_capture_execution_host_id"])
assert capture_id
execution_host.current_execution_host_id = lambda: capture_id
import numpy as np
import pandas as pd
from weather.model import mg_serve_core as core
core.station_coordinates()
core.wu_whole_f(32 + 9 * 1234 / 50)
z = np.linspace(-2, 2, 41)
core.predictive_distribution(80.2, 2.0, 77.0, z, list(range(60, 101)), core.smoothed_dist([79, 80, 81], range(60, 101)))
core.mg1_band_probs(np.array(["eq"]), [80], [81], np.array([77.0]), np.array([80.0]), np.array([2.0]))
core.usable_v2_mean(pd.DataFrame({"v2_available_at": ["2026-09-26T08:00:00Z"],
                                  "captured_at_utc": ["2026-09-26T09:00:00Z"], "v2_mean": [80.0], "v2_stddev": [2.0]}))
loaded = sorted(m for m in sys.modules if m.startswith(("weather.calibration", "weather.reporting")))
refused = None
try:
    import weather.calibration.r0_ols_floor_challenger  # noqa: F401
except ImportError as exc:
    refused = type(exc).__name__
print(json.dumps({"loaded": loaded, "refused": refused}))
"""


@pytest.mark.spawns
def test_core_imports_under_capture_host_emulation_without_research_modules():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)])
    proc = subprocess.run([sys.executable, "-c", CHILD], cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stderr[-4000:]
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["loaded"] == [], result
    if os.name == "nt":  # the research guards only refuse on Windows (the capture host is a Windows install)
        assert result["refused"] is not None, "positive control: the research module should refuse the host"


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in the serve core"
            yield node.module


def test_core_imports_are_allowlisted():
    found = set(_imports(ast.parse(CORE.read_text(encoding="utf-8")))) - {"__future__"}
    assert found <= ALLOWED_IMPORTS, sorted(found - ALLOWED_IMPORTS)
    assert not any(m.startswith(("weather.calibration", "weather.reporting")) for m in found)


def test_no_new_copies_of_serve_core_functions():
    core_tree = ast.parse(CORE.read_text(encoding="utf-8"))
    names = {n.name for n in core_tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))} - GENERIC
    src = REPO_ROOT / "src" / "weather"
    found = {}
    for path in sorted(src.rglob("*.py")):
        if path == CORE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        dup = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names}
        if dup:
            found[path.relative_to(src).as_posix()] = dup
    new = {m: sorted(d - KNOWN_COPIES.get(m, set())) for m, d in found.items() if d - KNOWN_COPIES.get(m, set())}
    assert not new, f"new copies of serve-core functions; import them from weather.model.mg_serve_core: {new}"
    gone = {m: sorted(d - found.get(m, set())) for m, d in KNOWN_COPIES.items() if d - found.get(m, set())}
    assert not gone, f"a known copy was removed; shrink KNOWN_COPIES to match: {gone}"
