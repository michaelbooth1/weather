"""81a adds only one exact offline module, with no guard relaxation."""
import importlib.util
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.research.morning_guidance.run"


def test_wrapper_and_hook_exact_allowlist():
    text = (ROOT / "scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    body = re.search(r"function Get-WeatherWorkstationOfflineModule\s*\{.*?@\((.*?)\)\s*\}", text, re.S).group(1)
    modules = re.findall(r'"([A-Za-z0-9_.-]+)"', body)
    spec = importlib.util.spec_from_file_location("morning_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert set(modules) == hook._OFFLINE_WEATHER_MODULES
    assert MODULE in modules
    assert MODULE + ".child" not in modules
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} coverage'
    }}, constrained_capture_host=False) is not None
