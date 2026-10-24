"""The workstation offline allowlist admits the L3 challenger module exactly, in both mirrors.

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
MODULE = "weather.calibration.r0_ols_floor_challenger"


def _hook():
    spec = importlib.util.spec_from_file_location("l3_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_hook_admits_the_challenger_exactly():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration", "weather.calibration.r0_ols_floor"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} score --markets atlanta'
    }}, constrained_capture_host=False) is not None


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
def test_exec_admission_lists_the_challenger_and_matches_the_hook(tmp_path):
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
