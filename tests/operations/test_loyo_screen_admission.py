"""The workstation offline allowlist admits the generic nested-LOYO history screen exactly.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; master pre-authorisation
2026-10-24 for a lane's own offline research module; master YES of 2026-10-30 for lane L3's screen harness). ``workload_admission.ps1`` is executed, not read: its listed set must equal the hook's
and it must admit the module but no sibling.
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
MODULE = "weather.calibration.loyo_screen"


def _hook():
    spec = importlib.util.spec_from_file_location("loyo_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_hook_admits_the_loyo_screen_exactly():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration", "weather.calibration.loyo"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} run --column c.parquet --name C --out o'
    }}, constrained_capture_host=False) is not None


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
def test_exec_admission_lists_and_admits_the_module_exactly(tmp_path):
    lister = tmp_path / "list_offline_modules.ps1"
    lister.write_text(
        f". '{ROOT / 'scripts' / 'ops' / 'workload_admission.ps1'}'\n"
        "ConvertTo-Json -InputObject @(Get-WeatherWorkstationOfflineModule) -Compress\n"
        f"if (Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine 'python.exe -m {MODULE} run') "
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
