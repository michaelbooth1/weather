"""The workstation offline allowlist admits the S31 v2 cross-venue twin P0 exactly.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; master pre-authorisation
2026-10-24 for a lane's own offline research module; the coordinator's admit of 2026-10-31 for lane L14's S31
v2, ledger row 102). ``workload_admission.ps1`` is executed, not read: its listed set must equal the hook's and it must admit the
module but no sibling.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.s31_v2"


def _hook():
    spec = importlib.util.spec_from_file_location("s31_v2_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_hook_admits_the_s31_v2_exactly():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration", "weather.calibration.s31",
                 "weather.calibration.s31_v"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} --layout L --out O'
    }}, constrained_capture_host=False) is not None


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
def test_exec_admission_lists_and_admits_the_module_exactly(tmp_path):
    lister = tmp_path / "list_offline_modules.ps1"
    lister.write_text(
        f". '{ROOT / 'scripts' / 'ops' / 'workload_admission.ps1'}'\n"
        "ConvertTo-Json -InputObject @(Get-WeatherWorkstationOfflineModule) -Compress\n"
        f"if (Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine 'python.exe -m {MODULE} --layout L') "
        "{ 'ADMITTED' } else { 'REFUSED' }\n"
        f"if (Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine 'python.exe -m {MODULE}_x') "
        "{ 'ADMITTED' } else { 'REFUSED' }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(lister)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    listing, exact, sibling = result.stdout.strip().splitlines()[-3:]
    modules = json.loads(listing)
    assert modules.count(MODULE) == 1 and set(modules) == _hook()._OFFLINE_WEATHER_MODULES
    assert (exact, sibling) == ("ADMITTED", "REFUSED")
