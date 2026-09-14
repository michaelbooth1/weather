"""Actual Windows token/argv reads; production S4U acceptance remains separate."""

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="actual Windows token APIs")


def native(tmp_path, body):
    script = tmp_path / "identity-fixture.ps1"
    helper = str(ROOT / "scripts/ops/qualification_host_identity.ps1").replace("'", "''")
    script.write_text("$ErrorActionPreference = 'Stop'\n. '" + helper + "'\n" + body, encoding="utf-8")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(script)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_current_token_logon_and_process_identity_are_read_natively(tmp_path):
    value = json.loads(native(tmp_path, "Get-WeatherQualificationCurrentLogon | ConvertTo-Json -Compress\n"))
    assert value["pid"] > 0 and value["creation_utc_ticks"] > 0
    assert value["image"].lower().endswith("powershell.exe")
    assert value["sid"].startswith("S-1-") and len(value["authentication_id"]) == 16
    assert type(value["logon_type"]) is int and value["logon_type"] > 0
    assert value["token_type"] == 1 and type(value["elevated"]) is bool


def test_native_command_line_parser_keeps_literal_spaces_and_quotes(tmp_path):
    value = json.loads(native(tmp_path, r'''
Initialize-WeatherQualificationLogonReader
[Weather.Operations.QualificationLogonReader]::Arguments('powershell.exe -File "C:\path with spaces\entry.ps1" -Value "literal \"quoted\" text"') | ConvertTo-Json -Compress
'''))
    assert value == ["powershell.exe", "-File", r"C:\path with spaces\entry.ps1", "-Value", 'literal "quoted" text']


def test_other_host_refuses_before_scheduler_lookup(tmp_path):
    native(tmp_path, r'''
function Get-WeatherExecutionHostId { return ('b' * 64) }
function Get-WeatherExecutionPrincipalId { return ('c' * 64) }
function Assert-WeatherIntegrationAttemptTaskBinding { throw 'Scheduler must not be queried for another host' }
$observed = ''
try {
    Assert-WeatherQualificationS4UInvocation -AttemptContract ([pscustomobject]@{}) -Role host -ExpectedHostId ('a' * 64) -ExpectedPrincipalId ('c' * 64)
} catch { $observed = $_.Exception.Message }
if ($observed -cne 'S4U invocation is on the wrong host or principal') { throw "Wrong refusal boundary: $observed" }
''')
