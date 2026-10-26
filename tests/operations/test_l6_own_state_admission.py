"""The workstation offline allowlist admits the frozen L6 own-state fitter exactly.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; master pre-authorisation
2026-10-24 for a lane's own offline research module) and master ruling D2 (i) of 2026-10-26 (the fit runs
once, through the wrapper). The two mirrors are compared by the exec-admission tests in
``test_mg2_composite_admission.py``, which assert that ``workload_admission.ps1`` lists exactly the hook's set.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.l6_own_state"


def _hook():
    spec = importlib.util.spec_from_file_location("l6s_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_hook_admits_the_l6_own_state_fitter_exactly():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration", "weather.calibration.l6_own"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} fit --research-root r --out-dir o --commit c'
    }}, constrained_capture_host=False) is not None


def test_ps1_mirror_lists_the_module():
    text = (ROOT / "scripts" / "ops" / "workload_admission.ps1").read_text(encoding="utf-8")
    assert f'"{MODULE}",' in text
