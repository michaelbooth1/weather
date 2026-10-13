"""Maker replay v2 W0/W1: one exact offline fixture-measurement module admitted, no guard relaxation."""
import importlib.util
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.research.maker_replay_v2.run"


def test_exact_module_and_guarded_launch():
    text = (ROOT / "scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    body = re.search(r"function Get-WeatherWorkstationOfflineModule\s*\{.*?@\((.*?)\)\s*\}", text, re.S)[1]
    modules = re.findall(r'"([A-Za-z0-9_.-]+)"', body)
    spec = importlib.util.spec_from_file_location("mrv2_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert set(modules) == hook._OFFLINE_WEATHER_MODULES
    assert modules.count(MODULE) == 1
    assert MODULE + ".child" not in modules and "tools.research.maker_replay_v2" not in modules
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} s1 --out x'
    }}, constrained_capture_host=False) is not None


def test_allow_list_is_the_union_with_master():
    """Both research modules admitted on master and on the v2 build line are listed here (T1, 2026-10-13).

    Master admits ``tools.research.guidance_all_hours.run`` where the build line admits this module; the union means
    every allow-list conflict of a build-line merge resolves to the build-line side without dropping either."""
    text = (ROOT / "scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    body = re.search(r"function Get-WeatherWorkstationOfflineModule\s*\{.*?@\((.*?)\)\s*\}", text, re.S)[1]
    modules = re.findall(r'"([A-Za-z0-9_.-]+)"', body)
    research = [m for m in modules if m.startswith("tools.")]
    assert research == sorted(research)
    assert {"tools.research.guidance_all_hours.run", MODULE} <= set(research)
