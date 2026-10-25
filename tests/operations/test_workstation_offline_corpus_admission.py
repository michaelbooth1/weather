"""Workstation allowlist admits the 2026-10-23 offline scorecard and corpus builders, and no fetcher.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; master ruling
2026-10-23 lane W; lane L5 pre-authorisation 2026-10-24) - dev_scorecard, new_city_corpus,
forecast_training_corpus and l5_subset_scores are admitted by
exact module name; network fetch modules and unknown modules stay refused by the real wrapper.
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.powershell_host import run_command as run_powershell_command

ROOT = Path(__file__).resolve().parents[2]
ADMISSION = ROOT / "scripts" / "ops" / "workload_admission.ps1"
ADDED = (
    "weather.calibration.l5_subset_scores",
    "weather.calibration.new_city_corpus",
    "weather.calibration.upstream_obs_screen",
    "weather.reporting.scorecards.dev_scorecard",
    "weather.sources.forecast_training_corpus",
)
# Network fetchers run directly, outside the wrapper (master ruling 2026-10-23); the venue-rule
# label module mixes a local `build` with a network `fetch` subcommand in one module name.
REFUSED = (
    "weather.sources.forecast_training_corpus_fetch",
    "weather.sources.metar_history",
    "weather.sources.forecast_history",
    "weather.backtesting.venue_rule_labels",
    "weather.sources.not_a_real_module",
    "weather.sources.free_screens.iem_upstream",
)


def _admission_verdicts(modules):
    """Evaluate the real admission functions (no process semantics under test)."""
    command_lines = ",".join("'python -m {} plan'".format(module) for module in modules)
    script = (
        f". '{ADMISSION}'\n"
        "$verdicts = [ordered]@{}\n"
        f"foreach ($line in @({command_lines})) {{\n"
        "    $verdicts[$line] = [bool](Test-WeatherWorkstationOfflineModuleCommandLine -CommandLine $line)\n"
        "}\n"
        "ConvertTo-Json -InputObject @{ listed = @(Get-WeatherWorkstationOfflineModule); verdicts = $verdicts } -Compress\n"
    )
    result = run_powershell_command(script, timeout=120)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    return set(payload["listed"]), {
        line.split()[2]: verdict for line, verdict in payload["verdicts"].items()
    }


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="runs workload_admission.ps1")
def test_admission_admits_added_modules_and_refuses_fetchers_and_unknown():
    listed, verdicts = _admission_verdicts(ADDED + REFUSED)
    for module in ADDED:
        assert module in listed
        assert verdicts[module] is True, module
    for module in REFUSED:
        assert module not in listed
        assert verdicts[module] is False, module
    assert not any(module.endswith("_fetch") for module in listed)
    spec = importlib.util.spec_from_file_location("ws_corpus_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert listed == hook._OFFLINE_WEATHER_MODULES


def test_forecast_training_corpus_cli_stays_local_only():
    """The allowlist matches the module name only, so this module may never grow a network
    subcommand: the collector must stay the separate forecast_training_corpus_fetch module."""
    from weather.sources import forecast_training_corpus as corpus

    parser = corpus.build_parser()
    subparsers = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
    assert len(subparsers) == 1
    assert set(subparsers[0].choices) == {"plan", "resume-status", "materialize"}
    source = Path(corpus.__file__).read_text(encoding="utf-8")
    for network_import in ("import urllib", "from urllib", "import requests", "import http", "import socket"):
        assert network_import not in source


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="Windows wrapper")
@pytest.mark.parametrize("module", REFUSED)
def test_real_wrapper_refuses_fetch_and_unknown_modules_before_any_lease(tmp_path, module):
    ops = tmp_path / "scripts" / "ops"
    ops.mkdir(parents=True)
    for name in ("workstation_heavy.ps1", "workload_admission.ps1", "windows_kill_on_close_job.ps1"):
        shutil.copyfile(ROOT / "scripts" / "ops" / name, ops / name)
    arguments = base64.b64encode(json.dumps(["-m", module, "fetch"]).encode("utf-8")).decode("ascii")
    result = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(ops / "workstation_heavy.ps1"),
            "-Kind", "weather_heavy",
            "-PythonPath", sys.executable,
            "-ArgumentsBase64", arguments,
            "-RepoRoot", str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode != 0
    assert "weather-heavy workload must be an offline training/replay module" in result.stderr
    assert not (tmp_path / "data" / "logs" / "heavy_workload.lock").exists()
