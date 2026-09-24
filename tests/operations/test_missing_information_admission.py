"""The sole new offline entrypoint uses the ordinary guarded launch contract."""
import importlib.util
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.research.missing_information.run"


def test_only_exact_research_module_added_to_admission():
    text = (ROOT / "scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    body = re.search(r"function Get-WeatherWorkstationOfflineModule\s*\{.*?@\((.*?)\)\s*\}", text, re.S).group(1)
    modules = re.findall(r'"([A-Za-z0-9_.-]+)"', body)
    assert [m for m in modules if not m.startswith("weather.")] == [
        MODULE, "tools.research.morning_guidance.run", "tools.research.nbm_target_trace.run",
        "tools.cross_band_fill_clustering_20260924", "tools.timing_shadow_20260924"]


@pytest.mark.parametrize("module", [MODULE, "tools.cross_band_fill_clustering_20260924", "tools.timing_shadow_20260924"])
def test_hook_recognizes_research_work_as_heavy_and_rejects_direct_launch(module):
    spec = importlib.util.spec_from_file_location("mi_host_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert module in hook._OFFLINE_WEATHER_MODULES
    assert module + ".child" not in hook._OFFLINE_WEATHER_MODULES
    result = hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {module} --help'
    }}, constrained_capture_host=False)
    assert result is not None
