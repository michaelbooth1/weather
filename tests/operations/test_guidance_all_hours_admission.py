"""111h Part 2 adds only one exact offline module, with no guard relaxation.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; item 111h Part 2) -
  workload_admission.ps1 and the Codex hook admit exactly the same modules, no child module.
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
MODULE = "tools.research.guidance_all_hours.run"


def test_wrapper_and_hook_exact_allowlist():
    text = (ROOT / "scripts/ops/workload_admission.ps1").read_text(encoding="utf-8-sig")
    body = re.search(r"function Get-WeatherWorkstationOfflineModule\s*\{.*?@\((.*?)\)\s*\}", text, re.S).group(1)
    modules = re.findall(r'"([A-Za-z0-9_.-]+)"', body)
    spec = importlib.util.spec_from_file_location("gah_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert set(modules) == hook._OFFLINE_WEATHER_MODULES
    assert MODULE in modules
    assert MODULE + ".child" not in modules
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} score'
    }}, constrained_capture_host=False) is not None


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
def test_exec_admission_lists_exactly_the_hook_modules(tmp_path):
    """Execution twin of the text asserts above: the real admission function, not its source text, lists
    the same modules as the Codex hook, including MODULE and no child of it."""
    lister = tmp_path / "list_offline_modules.ps1"
    lister.write_text(
        f". '{ROOT / 'scripts' / 'ops' / 'workload_admission.ps1'}'\n"
        "ConvertTo-Json -InputObject @(Get-WeatherWorkstationOfflineModule) -Compress\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(lister)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    listed = set(json.loads(result.stdout))
    spec = importlib.util.spec_from_file_location("gah_hook_exec", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert listed == hook._OFFLINE_WEATHER_MODULES
    assert MODULE in listed
    assert MODULE + ".child" not in listed
