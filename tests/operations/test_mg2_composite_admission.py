"""The workstation offline allowlist admits the MG-2 binding and its input receiver exactly, in both mirrors.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; master
pre-authorisation 2026-10-24 for a lane's own offline research module) - workload_admission.ps1
and the Codex hook list the same modules, this module but no child or sibling.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("weather.calibration.mg2_composite", "weather.calibration.mg2_inputs", "weather.calibration.mg2_p3d_n")


def _hook():
    spec = importlib.util.spec_from_file_location("mg2_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


@pytest.mark.parametrize("MODULE", MODULES)
def test_hook_admits_the_mg2_modules_exactly(MODULE):
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration", "weather.calibration.mg2"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} emit --market atlanta'
    }}, constrained_capture_host=False) is not None
    assert "weather.calibration.mg2_input_allowlist" not in hook._OFFLINE_WEATHER_MODULES


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
@pytest.mark.parametrize("MODULE", MODULES)
def test_exec_admission_lists_the_mg2_modules_and_matches_the_hook(tmp_path, MODULE):
    lister = tmp_path / "list_offline_modules.ps1"
    lister.write_text(
        f". '{ROOT / 'scripts' / 'ops' / 'workload_admission.ps1'}'\n"
        "ConvertTo-Json -InputObject @(Get-WeatherWorkstationOfflineModule) -Compress\n"
        f"if (Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine 'python.exe -m {MODULE} score') "
        "{ 'ADMITTED' } else { 'REFUSED' }\n"
        f"if (Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine 'python.exe -m {MODULE}_x') "
        "{ 'ADMITTED' } else { 'REFUSED' }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(lister)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    listing, exact, sibling = result.stdout.strip().splitlines()[-3:]
    listed = set(json.loads(listing))
    assert listed == _hook()._OFFLINE_WEATHER_MODULES
    assert MODULE in listed
    assert (exact, sibling) == ("ADMITTED", "REFUSED")
