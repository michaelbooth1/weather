"""R11 Head 1 admission: mg1_layout on the workstation allowlist, and the host backfill wrapper's plan.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope) and master's 2026-11-01 option (d)
ruling: the mg1_layout admission line stays in R11 Head 1; the backfill runs on the host only through
scripts/ops/mg1_input_backfill.ps1 (never workstation-admitted), pinned to tools.research.mg1_input_backfill, writes
only data/exports/mg1-inputs, never passes a coverage flag, refuses dates outside 2026-10-15..2026-10-27, and its
-PlanOnly mode touches nothing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.mg1_layout"
REFUSED = (
    MODULE + ".child",
    MODULE + "_x",
    "weather.calibration.mg1",
    "weather.calibration.mg1_look",
    "weather.calibration.mg2_input_export",
    "tools.research.mg1_input_backfill",
)


def _hook():
    spec = importlib.util.spec_from_file_location("mg1_layout_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
def test_real_admission_lists_mg1_layout_once_matches_the_hook_and_admits_nothing_wider(tmp_path):
    lines = ",".join(f"'python -m {m} build'" for m in (MODULE,) + REFUSED)
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
    assert verdicts[MODULE] is True
    for module in REFUSED:
        assert module not in listed
        assert verdicts[module] is False, module


def test_hook_lists_mg1_layout_and_treats_a_direct_launch_as_heavy():
    hook = _hook()
    assert MODULE in hook._OFFLINE_WEATHER_MODULES
    for module in REFUSED:
        assert module not in hook._OFFLINE_WEATHER_MODULES
    result = hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} build --help'
    }}, constrained_capture_host=False)
    assert result is not None


WRAPPER = ROOT / "scripts" / "ops" / "mg1_input_backfill.ps1"


def _plan(tmp_path, *args):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER),
         "-ProductionRepoRoot", str(repo), "-PlanOnly", *args],
        capture_output=True, text=True, timeout=120, check=False, cwd=tmp_path,
    )
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == before  # touches nothing
    return result


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs the PS 5.1 wrapper")
def test_wrapper_plan_pins_the_backfill_tool_output_folder_and_default_dates(tmp_path):
    result = _plan(tmp_path)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    repo = str(tmp_path / "repo")
    assert plan["mode"] == "Export"
    assert plan["out_root"] == repo + r"\data\exports\mg1-inputs"
    assert plan["target_dates"] == [f"2026-10-{d}" for d in range(15, 28)]
    args = plan["child_arguments"]
    assert args[:5] == ["-P", "-B", "-m", "tools.research.mg1_input_backfill", "export"]
    assert args[-4:] == ["--data-root", repo + r"\data", "--out", plan["out_root"]]
    assert not any("coverage" in a for a in args)
    precheck = json.loads(_plan(tmp_path, "-Mode", "Precheck", "-Date", "2026-10-15,2026-10-27").stdout)
    assert precheck["child_arguments"][4:9] == ["precheck", "--date", "2026-10-15", "--date", "2026-10-27"]


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs the PS 5.1 wrapper")
def test_wrapper_refuses_dates_outside_the_backfill_span(tmp_path):
    for bad in ("2026-10-14", "2026-10-28", "2026-1015"):
        result = _plan(tmp_path, "-Date", bad)
        assert result.returncode != 0, bad
        assert "REFUSED" in result.stderr + result.stdout, bad
    ok = _plan(tmp_path, "-Date", "2026-10-15")
    assert ok.returncode == 0 and json.loads(ok.stdout)["target_dates"] == ["2026-10-15"]


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs the PS 5.1 wrapper")
def test_wrapper_names_no_host_address_and_carries_every_copied_guard(tmp_path):
    assert _plan(tmp_path).returncode == 0
    text = WRAPPER.read_text(encoding="utf-8")
    assert not re.search(r"(?<![\d.])\d{1,3}(\.\d{1,3}){3}(?![\d.])", text)
    for guard in ("Get-WeatherExecutionHostId", "dedicated_capture_execution_host_id", "-lt 30 -or $minute -ge 540",
                  "Enter-WeatherHeavyWorkloadLease", "if ($null -eq $lease)", "New-WeatherKillOnCloseJob",
                  "TerminateAndWait", "StartsWith($pinnedSrc", "-lt 5GB",
                  "Get-WeatherMemoryGuardStatusAgeMinutes -Read $memoryRead"):
        assert guard in text, guard
    assert "(Get-Date) - $memoryRead.last_write_time" not in text  # the local-time comparison is not used
