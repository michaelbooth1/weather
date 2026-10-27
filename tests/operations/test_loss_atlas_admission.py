"""The loss atlas is admitted to the workstation wrapper by exact name, in both allowlist mirrors.

Guards: master pre-authorisation 2026-10-24 (each lane may allowlist its own offline research module
in Get-WeatherWorkstationOfflineModule and the Codex hook mirror, with a test that pins the list);
the pre-registration checker is light and stays off the list; no child or parent module is admitted.
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
MODULE = "weather.reporting.scorecards.loss_atlas"
# Every scorecards module either mirror may admit (pinned; a new one needs its own reviewed line).
SCORECARD_MODULES = {
    "weather.reporting.scorecards.dev_scorecard",
    MODULE,
    "weather.reporting.scorecards.train_serve_feature_parity",
}
REFUSED = (MODULE + ".child", "weather.reporting.scorecards", "weather.reporting.scorecards.prereg_check")


def _hook():
    spec = importlib.util.spec_from_file_location("loss_atlas_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
def test_real_admission_lists_loss_atlas_once_matches_the_hook_and_admits_nothing_wider(tmp_path):
    lines = ",".join(f"'python -m {m} atlas'" for m in (MODULE,) + REFUSED)
    script = tmp_path / "admission_verdicts.ps1"
    script.write_text(
        f". '{ROOT / 'scripts' / 'ops' / 'workload_admission.ps1'}'\n"
        "$verdicts = [ordered]@{}\n"
        f"foreach ($line in @({lines})) {{\n"
        "    $verdicts[$line] = [bool](Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine $line)\n"
        "}\n"
        "ConvertTo-Json -InputObject @{ listed = @(Get-WeatherWorkstationOfflineModule); verdicts = $verdicts } "
        "-Compress\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    listed = payload["listed"]
    verdicts = {line.split()[2]: v for line, v in payload["verdicts"].items()}
    assert listed.count(MODULE) == 1
    assert set(listed) == _hook()._OFFLINE_WEATHER_MODULES
    assert {m for m in listed if m.startswith("weather.reporting.")} <= SCORECARD_MODULES
    assert verdicts[MODULE] is True
    for module in REFUSED:
        assert module not in listed
        assert verdicts[module] is False, module


def test_hook_lists_loss_atlas_and_treats_a_direct_launch_as_heavy():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    assert {m for m in hook._OFFLINE_WEATHER_MODULES if m.startswith("weather.reporting.")} <= SCORECARD_MODULES
    for module in REFUSED:
        assert module not in hook._OFFLINE_WEATHER_MODULES
    result = hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} atlas --help'
    }}, constrained_capture_host=False)
    assert result is not None
