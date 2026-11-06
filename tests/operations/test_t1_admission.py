"""Guards: exact offline T1 admission in wrapper/hook; no live flags or sibling modules."""
import base64
import importlib.util
import json
import os
from pathlib import Path

import pytest

from tests.powershell_host import run_command

ROOT = Path(__file__).resolve().parents[2]
MODULE = 'weather.backtesting.t1_cli'


def test_t1_hook_admits_only_exact_offline_module():
    spec = importlib.util.spec_from_file_location('t1_load_hook', ROOT / '.codex/hooks/pre_tool_use_host_load.py')
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    def encoded(module, *args):
        return base64.b64encode(json.dumps(['-m', module, *args]).encode()).decode()

    assert hook._approved_workstation_arguments('weather_heavy', encoded(MODULE, 'simulate'))
    assert hook._approved_workstation_arguments('weather_heavy', encoded(MODULE, 'accuracy'))
    assert not hook._approved_workstation_arguments('weather_heavy', encoded(MODULE + '.child', 'simulate'))
    for flag in ('--live', '--execute', '--place', '--cancel', '--promote'):
        assert not hook._approved_workstation_arguments('weather_heavy', encoded(MODULE, 'simulate', flag))


@pytest.mark.spawns
@pytest.mark.skipif(os.name != 'nt', reason='PowerShell admission mirror')
def test_t1_powershell_admission_lists_exact_module(tmp_path):
    # Pure function/list evaluation; no lease, Scheduler, host identity or admission mutation.
    result = run_command(
        f". '{ROOT / 'scripts/ops/workload_admission.ps1'}'\n"
        "ConvertTo-Json -InputObject @(Get-WeatherWorkstationOfflineModule) -Compress\n",
        cwd=ROOT, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    modules = json.loads(result.stdout.strip().splitlines()[-1])
    assert modules.count(MODULE) == 1
    assert MODULE + '.child' not in modules
