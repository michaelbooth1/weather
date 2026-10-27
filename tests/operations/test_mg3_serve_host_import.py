"""weather.model.mg3_serve imports on the capture host, names no research module, and no capture loop imports it.

Guards: MG-3 serve series (coordinator brief 2026-10-27): nothing may become reachable from a capture loop; no
research import in a serving module; L2's MG-3 design prerequisite b.0 (a host serve path never needs a research
module that refuses the capture host).

1. Host import: a child interpreter emulates the capture host, imports the module and runs its pure serve math; no
   ``weather.calibration`` or ``weather.reporting`` module may load.
2. Import allowlist: every import in the module, top-level or lazy, is pinned here.
3. Text ratchet: the module text names no research module, so the repository's text-based no-importer ratchets
   stay exact.
4. Loop reachability: no module under ``src``, ``app`` or ``scripts`` other than the module itself names it, so
   no capture supervisor's import closure can reach it. A new importer must be reviewed here first.
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
MODULE = REPO_ROOT / "src" / "weather" / "model" / "mg3_serve.py"

ALLOWED_IMPORTS = {
    "datetime", "hashlib", "json", "math", "pathlib", "pickle", "zoneinfo",
    "numpy", "pandas", "scipy.special",
    "weather.model",  # ``from weather.model import mg3_arms`` / ``mg_serve_core`` (pinned below)
}
ALLOWED_WEATHER_NAMES = {"mg3_arms", "mg_serve_core"}
RESEARCH_TOKENS = ("weather.calibration", "weather.reporting", "pooled_residual_model", "r0_ols_floor",
                   "season_matched_l6", "cool_season_audit", "rz_hrrr_spread", "mg2_composite", "mg2_p3d_n",
                   "b_scorer", "upstream_obs_screen", "feature_model")

CHILD = r"""
import json, sys
from datetime import date
from weather import execution_host
capture_id = str(execution_host.load_execution_host_assignment()["dedicated_capture_execution_host_id"])
assert capture_id
execution_host.current_execution_host_id = lambda: capture_id
from weather.model import mg3_serve as ms
e = ms.hrrr_raw_path(None, [], icao="KATL", tz="America/New_York", local_date="2026-08-10", hour=10)
ms.hrrr_extra_columns(e, 80.0)
ms.l6_band_distribution(80.0, 2.0, 75.0)
ms.serve_arm({"schema": ms.BINDING_SCHEMA, "states": {"SM-H 13-15": {"hours": [13, 14, 15], "excluded_markets": ["san-francisco"]}}},
             "san-francisco", 14)
loaded = sorted(m for m in sys.modules if m.startswith(("weather.calibration", "weather.reporting")))
print(json.dumps({"loaded": loaded}))
"""


@pytest.mark.spawns
def test_mg3_serve_imports_under_capture_host_emulation_without_research_modules():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)])
    proc = subprocess.run([sys.executable, "-c", CHILD], cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)
    assert proc.returncode == 0, proc.stderr[-4000:]
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"loaded": []}


def test_mg3_serve_imports_are_allowlisted():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    found, weather_names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in a serving module"
            found.add(node.module)
            if node.module == "weather.model":
                weather_names |= {alias.name for alias in node.names}
    found -= {"__future__"}
    assert found <= ALLOWED_IMPORTS, sorted(found - ALLOWED_IMPORTS)
    assert weather_names == ALLOWED_WEATHER_NAMES


def test_mg3_serve_text_names_no_research_module():
    text = MODULE.read_text(encoding="utf-8")
    assert [t for t in RESEARCH_TOKENS if t in text] == []


def _imports_mg3_serve(path):
    """True when ``path`` imports mg3_serve or names its dotted module path (an importlib or -m target).

    A prose mention (L2's builder and schema-family docstrings name "the shape mg3_serve reads") is not an import."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if "mg3_serve" not in text:
        return False
    if "weather.model.mg3_serve" in text or "weather/model/mg3_serve" in text:
        return True
    if path.suffix != ".py":
        return True  # a script naming it at all is reviewed here first
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import) and any(a.name.split(".")[-1] == "mg3_serve" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (
                (node.module or "").split(".")[-1] == "mg3_serve" or any(a.name == "mg3_serve" for a in node.names)):
            return True
    return False


def test_no_capture_loop_can_reach_mg3_serve():
    importers = []
    for top in ("src", "app", "scripts"):
        for path in (REPO_ROOT / top).rglob("*"):
            if path.suffix not in {".py", ".ps1"} or path == MODULE:
                continue
            if _imports_mg3_serve(path):
                importers.append(path.relative_to(REPO_ROOT).as_posix())
    assert importers == []


def test_the_importer_ratchet_sees_imports_not_prose(tmp_path):
    cases = {"a.py": ("from weather.model import mg3_serve\n", True),
             "b.py": ("import weather.model.mg3_serve as m\n", True),
             "c.py": ("importlib.import_module('weather.model.mg3_serve')\n", True),
             "d.py": ('"""the shape mg3_serve reads"""\n', False),
             "e.ps1": ("python -m weather.model.mg3_serve\n", True)}
    for name, (text, expected) in cases.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
        assert _imports_mg3_serve(tmp_path / name) is expected, name
