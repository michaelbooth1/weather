"""The workstation offline allowlist admits the L17 POOL-0006 replay harness exactly, in both mirrors.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; master
pre-authorisation 2026-10-24 for a lane's own offline research module) - workload_admission.ps1
and the Codex hook list the same modules (the ps1 mirror equality is asserted by
test_predawn_0006_admission's exec test), this module but no child or sibling.
"""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.pool0006_replay"


def _hook():
    spec = importlib.util.spec_from_file_location("l3_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_hook_admits_the_replay_module_exactly():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration", "weather.calibration.pool0006"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} score --markets atlanta'
    }}, constrained_capture_host=False) is not None
