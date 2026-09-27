import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "nt", reason="Windows native admission parser")
def test_shadow_launcher_parses_and_profile_fails_before_state_access(tmp_path):
    script = f"""
$ErrorActionPreference = 'Stop'
$tokens=$null; $errors=$null
[void][Management.Automation.Language.Parser]::ParseFile('{ROOT / 'scripts/ops/workstation_shadow.ps1'}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw 'launcher parse failed' }}
. '{ROOT / 'scripts/ops/workload_admission.ps1'}'
function Get-WeatherExecutionHostId {{ 'capture' }}
function Get-WeatherExecutionPrincipalId {{ 'fixture' }}
function Get-WeatherExecutionHostAssignment {{ [pscustomobject]@{{dedicated_capture_execution_host_id='capture'}} }}
function Get-WeatherHeavyWorkloadPoisonPath {{ throw 'STATE_PATH_MUST_NOT_BE_REACHED' }}
try {{
    Enter-WeatherHeavyWorkloadLease -RepoRoot '{tmp_path}' -Workload 'WorkstationPublicShadow-fixture' -ExecutionHostProfile 'workstation_public_shadow'
    throw 'unexpected admission'
}} catch {{
    if ($_.Exception.Message -notlike '*forbidden on the dedicated*') {{ throw }}
}}
$rows = @([pscustomobject]@{{ProcessId=123456;Name='python.exe';CommandLine='python.exe -m weather.market.maker_shadow public';ParentProcessId=0}})
if (@(Get-WeatherActiveWorkstationHeavyProcess -ProcessSnapshot $rows).Count -ne 1) {{ throw 'shadow residual not detected' }}
Write-Output 'PASS'
"""
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_shadow_does_not_expand_offline_module_permission():
    from tests.operations.test_workload_admission_script import LEASE_SCRIPT
    text = LEASE_SCRIPT.read_text(encoding="utf-8")
    allowlist = text.split("function Get-WeatherWorkstationOfflineModule", 1)[1].split("function ", 1)[0]
    assert "maker_shadow" not in allowlist
