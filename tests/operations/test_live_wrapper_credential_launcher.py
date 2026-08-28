from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (
    REPO_ROOT
    / "scripts"
    / "ops"
    / "international_live_templates"
    / "fixed_scope_launcher.ps1.tmpl"
)
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows PowerShell",
)
REFERENCE_NAMES = (
    "POLYMARKET_API_KEY_STORAGE_REF",
    "POLYMARKET_API_SECRET_STORAGE_REF",
    "POLYMARKET_API_PASSPHRASE_STORAGE_REF",
    "POLYMARKET_PRIVATE_KEY_STORAGE_REF",
)
REFERENCE_TARGETS = {
    "POLYMARKET_API_KEY_STORAGE_REF": "wincred://Weather/Polymarket/InternationalPilot/ApiKey",
    "POLYMARKET_API_SECRET_STORAGE_REF": "wincred://Weather/Polymarket/InternationalPilot/ApiSecret",
    "POLYMARKET_API_PASSPHRASE_STORAGE_REF": "wincred://Weather/Polymarket/InternationalPilot/Passphrase",
    "POLYMARKET_PRIVATE_KEY_STORAGE_REF": "wincred://Weather/Polymarket/InternationalPilot/PrivateKey",
}
DIRECT_NAMES = (
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_API_PASSPHRASE",
    "POLYMARKET_PRIVATE_KEY",
    "POLYMARKET_US_SECRET_KEY",
)


def manifest(path: Path) -> Path:
    references = dict(REFERENCE_TARGETS)
    payload = {
        "schema_version": "mm_live_credential_reference_manifest_v0.1",
        "platform": "polymarket_global",
        "wallet_type": "gnosis_safe",
        "signature_type": "POLY_GNOSIS_SAFE",
        "signature_type_id": 2,
        "wallet_address": "0x" + "2" * 40,
        "funder_address": "0x" + "3" * 40,
        "credential_references": references,
        "public_environment": {
            "POLYMARKET_FUNDER_ADDRESS": "0x" + "3" * 40,
        },
        "secret_values_retained": False,
        "ignored_relayers_rpc_and_self_assertions": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def run_functions(script: str, env: dict[str, str]):
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=REPO_ROOT,
        env={**os.environ, **env},
        check=False,
        capture_output=True,
        text=True,
    )
    return result


def function_bootstrap() -> str:
    return r"""
$ErrorActionPreference = 'Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(
  $env:LAUNCHER_TEMPLATE,[ref]$tokens,[ref]$errors)
if($errors.Count -ne 0){throw 'template parse failed'}
foreach($name in @('Get-SealedCredentialEnvironment','Enter-SealedCredentialEnvironment','Exit-SealedCredentialEnvironment')){
  $fn=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true))[0]
  if($null -eq $fn){throw "missing $name"}
  Invoke-Expression $fn.Extent.Text
}
"""


@WINDOWS_POWERSHELL_REQUIRED
def test_launcher_contains_public_refs_clears_poison_and_restores_parent(tmp_path):
    path = manifest(tmp_path / "references.json")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    script = function_bootstrap() + r"""
$required=@('POLYMARKET_API_KEY_STORAGE_REF','POLYMARKET_API_SECRET_STORAGE_REF','POLYMARKET_API_PASSPHRASE_STORAGE_REF','POLYMARKET_PRIVATE_KEY_STORAGE_REF','POLYMARKET_FUNDER_ADDRESS')
$direct=@('POLYMARKET_API_KEY','POLYMARKET_API_SECRET','POLYMARKET_API_PASSPHRASE','POLYMARKET_PRIVATE_KEY','POLYMARKET_US_SECRET_KEY')
foreach($name in $required){[Environment]::SetEnvironmentVariable($name,'AMBIENT-POISON','Process')}
foreach($name in $direct){[Environment]::SetEnvironmentVariable($name,'DIRECT-POISON','Process')}
$public=Get-SealedCredentialEnvironment -ManifestPath $env:REFERENCE_MANIFEST -ExpectedSha256 $env:REFERENCE_SHA
$prior=Enter-SealedCredentialEnvironment -PublicEnvironment $public
try{
  $duringRequired=@($required|Where-Object{[Environment]::GetEnvironmentVariable($_,'Process') -eq 'AMBIENT-POISON'}).Count
  $duringDirect=@($direct|Where-Object{[Environment]::GetEnvironmentVariable($_,'Process')}).Count
}finally{Exit-SealedCredentialEnvironment -PriorEnvironment $prior}
$restoredRequired=@($required|Where-Object{[Environment]::GetEnvironmentVariable($_,'Process') -eq 'AMBIENT-POISON'}).Count
$restoredDirect=@($direct|Where-Object{[Environment]::GetEnvironmentVariable($_,'Process') -eq 'DIRECT-POISON'}).Count
[pscustomobject]@{public_count=$public.Count;during_required_poison=$duringRequired;during_direct=$duringDirect;restored_required=$restoredRequired;restored_direct=$restoredDirect}|ConvertTo-Json -Compress
"""
    result = run_functions(
        script,
        {
            "LAUNCHER_TEMPLATE": str(TEMPLATE),
            "REFERENCE_MANIFEST": str(path),
            "REFERENCE_SHA": digest,
        },
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "public_count": 5,
        "during_required_poison": 0,
        "during_direct": 0,
        "restored_required": 5,
        "restored_direct": 5,
    }


@WINDOWS_POWERSHELL_REQUIRED
def test_launcher_rejects_missing_or_tampered_reference_manifest(tmp_path):
    path = manifest(tmp_path / "references.json")
    wrong_hash = "0" * 64
    for candidate in (tmp_path / "missing.json", path):
        script = function_bootstrap() + r"""
$rejected=$false
try{Get-SealedCredentialEnvironment -ManifestPath $env:REFERENCE_MANIFEST -ExpectedSha256 $env:REFERENCE_SHA|Out-Null}catch{$rejected=$true}
if(-not $rejected){throw 'invalid manifest was accepted'}
"""
        result = run_functions(
            script,
            {
                "LAUNCHER_TEMPLATE": str(TEMPLATE),
                "REFERENCE_MANIFEST": str(candidate),
                "REFERENCE_SHA": wrong_hash,
            },
        )
        assert result.returncode == 0, result.stderr


@WINDOWS_POWERSHELL_REQUIRED
def test_launcher_no_argument_entry_does_not_trip_strict_mode_args_variable(tmp_path):
    script_path = tmp_path / "fixed_scope_launcher.ps1"
    script_path.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "fixed-scope launcher dependency is absent" in (
        result.stdout + result.stderr
    )
    assert "VariableIsUndefined" not in result.stderr
