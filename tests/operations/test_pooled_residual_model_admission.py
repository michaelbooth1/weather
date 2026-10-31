"""The L2 pooled residual research module is admitted exactly, and only offline.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; master
pre-authorisation 2026-10-24 for lane L2) - workload_admission.ps1 and the Codex hook admit exactly
the same modules, this module but no child or sibling; no src module imports it, except the one reviewed
entry in ``LOADS_PINNED_SOURCE`` (L8 ratchet fix, 2026-10-27, master re-reviews each entry).
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.pooled_residual_model"
LOADS_PINNED_SOURCE = {
    # MG-2's P3d_N parity proof loads the L2 source FILE at a pinned sha256 (``_load_upstream``), never the
    # installed module; it is WS-only and refuses to import on the capture host (mg2_composite's guard).
    "src/weather/calibration/mg2_p3d_n.py": "MG-2 P3d_N: pinned-sha upstream source load for its parity proof",
}


def _hook():
    spec = importlib.util.spec_from_file_location("prm_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def _ps_modules():
    text = (ROOT / "scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    body = re.search(r"function Get-WeatherWorkstationOfflineModule\s*\{.*?@\((.*?)\)\s*\}", text, re.S).group(1)
    return re.findall(r'"([A-Za-z0-9_.-]+)"', body)


def test_both_lists_admit_the_module_exactly_once_and_agree():
    modules = _ps_modules()
    assert modules.count(MODULE) == 1
    assert set(modules) == set(_hook()._OFFLINE_WEATHER_MODULES)
    for near in (MODULE + ".child", MODULE + "_report", "weather.calibration.pooled_residual"):
        assert near not in modules


def test_hook_treats_a_direct_launch_as_heavy():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} report --help'
    }}, constrained_capture_host=False) is not None


def test_no_src_module_imports_it():
    pattern = re.compile(r"pooled_residual_model")
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if path.name not in RESEARCH_IMPORTERS and pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert sorted(offenders) == sorted(path.replace("/", os.sep) for path in LOADS_PINNED_SOURCE)


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
def test_exec_admission_lists_the_module_and_matches_the_hook(tmp_path):
    lister = tmp_path / "list_offline_modules.ps1"
    lister.write_text(
        f". '{ROOT / 'scripts' / 'ops' / 'workload_admission.ps1'}'\n"
        "ConvertTo-Json -InputObject @(Get-WeatherWorkstationOfflineModule) -Compress\n"
        f"if (Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine 'python.exe -m {MODULE} report') "
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
    assert set(json.loads(listing)) == _hook()._OFFLINE_WEATHER_MODULES
    assert (exact, sibling) == ("ADMITTED", "REFUSED")
