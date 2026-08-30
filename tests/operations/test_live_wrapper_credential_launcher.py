from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

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


def test_launcher_job_contains_the_complete_live_child_tree():
    source = TEMPLATE.read_text(encoding="utf-8")

    assert '$jobScript = Join-Path $repo "scripts\\ops\\windows_kill_on_close_job.ps1"' in source
    assert "__SEAL_WINDOWS_JOB_HELPER_SHA256__" in source
    assert '"PSModulePath"' in source
    assert '"System32\\WindowsPowerShell\\v1.0\\Modules"' in source
    assert "Add-SealedReadLock -Path $jobScript" in source
    assert source.index(". $jobScript") < source.index("New-WeatherKillOnCloseJob")
    assert source.index("New-WeatherKillOnCloseJob") < source.index(
        "Start-WeatherInteractiveProcessInJob"
    )
    assert source.index("$child.WaitForExit()") < source.index(
        "$job.TerminateAndWait(5000)"
    )
    assert source.index(
        "Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease"
    ) < source.index("$job.TerminateAndWait(5000)")
    assert source.index("$job.TerminateAndWait(5000)") < source.index(
        "Exit-WeatherHeavyWorkloadLease"
    )
    assert "Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease" in source
    assert "& $python" not in source


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.skipif(
    os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") == "1",
    reason="outer workstation lease owns the shared mutex",
)
def test_forced_launcher_exit_kills_the_live_child_tree_before_mutex_reuse(tmp_path):
    repo = tmp_path / "production"
    ops = repo / "scripts/ops"
    ops.mkdir(parents=True)
    job_script = ops / "windows_kill_on_close_job.ps1"
    shutil.copyfile(
        REPO_ROOT / "scripts/ops/windows_kill_on_close_job.ps1",
        job_script,
    )
    lease_script = ops / "workload_admission.ps1"
    lease_script.write_text(
        "function Enter-WeatherHeavyWorkloadLease {\n"
        "  param($RepoRoot,$Workload,$ExecutionHostProfile,$ExpectedExecutionHostId)\n"
        "  $mutex=[Threading.Mutex]::new($false,'Global\\WeatherProjectHeavyWorkloadV1')\n"
        "  if(-not $mutex.WaitOne(0,$false)){$mutex.Dispose();return $null}\n"
        "  [pscustomobject]@{Mutex=$mutex;MutexOwned=$true}\n"
        "}\n"
        "function Exit-WeatherHeavyWorkloadLease {\n"
        "  param($Lease)\n"
        "  if($Lease.MutexOwned){$Lease.Mutex.ReleaseMutex()}\n"
        "  $Lease.Mutex.Dispose()\n"
        "}\n",
        encoding="utf-8",
    )
    python = Path(sys.executable).resolve()
    site_packages = python.parent.parent / "Lib/site-packages"
    if not site_packages.is_dir():
        pytest.skip("test interpreter does not use the required Windows venv layout")
    ready = tmp_path / "live-child-ready.txt"
    survived = tmp_path / "live-grandchild-survived.txt"
    wrapper = tmp_path / "stage0.py"
    wrapper.write_text(
        "import os, pathlib, subprocess, sys, time\n"
        "code = (\"import os,pathlib,time;time.sleep(2.5);\"\n"
        "        \"pathlib.Path(os.environ['WEATHER_JOB_SURVIVED']).write_text('survived')\")\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', code])\n"
        "pathlib.Path(os.environ['WEATHER_JOB_READY']).write_text(str(grandchild.pid))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    references = manifest(tmp_path / "references.json")
    replacements = {
        "__SEAL_PRODUCTION_ROOT__": str(repo.resolve()),
        "__SEAL_PRODUCTION_PYTHON__": str(python),
        "__SEAL_WRAPPER_PATH__": str(wrapper.resolve()),
        "__SEAL_WRAPPER_SHA256__": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
        "__SEAL_WORKLOAD__": "InternationalLive-stage0-job-test",
        "__SEAL_EXECUTION_HOST_PROFILE__": "portable_execution_v1",
        "__SEAL_EXECUTION_HOST_ID__": "a" * 64,
        "__SEAL_WORKLOAD_ADMISSION_SHA256__": hashlib.sha256(
            lease_script.read_bytes()
        ).hexdigest(),
        "__SEAL_WINDOWS_JOB_HELPER_SHA256__": hashlib.sha256(
            job_script.read_bytes()
        ).hexdigest(),
        "__SEAL_CREDENTIAL_MANIFEST_PATH__": str(references.resolve()),
        "__SEAL_CREDENTIAL_MANIFEST_SHA256__": hashlib.sha256(
            references.read_bytes()
        ).hexdigest(),
    }
    source = TEMPLATE.read_text(encoding="utf-8")
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    assert "__SEAL_" not in source
    launcher_path = tmp_path / "fixed-scope-launcher.ps1"
    launcher_path.write_text(source, encoding="utf-8-sig")

    env = {
        **os.environ,
        "WEATHER_JOB_READY": str(ready),
        "WEATHER_JOB_SURVIVED": str(survived),
    }
    launcher = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launcher_path),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            if launcher.poll() is not None:
                stdout, stderr = launcher.communicate()
                pytest.fail(f"launcher exited before readiness: {stdout} {stderr}")
            time.sleep(0.05)
        assert ready.is_file(), "contained live child did not reach readiness"
        launcher.terminate()
        launcher.wait(timeout=10)
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait(timeout=10)

    mutex_probe = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "$m=[Threading.Mutex]::new($false,'Global\\WeatherProjectHeavyWorkloadV1');"
            "$owned=$false;try{try{$owned=$m.WaitOne(0,$false)}"
            "catch [Threading.AbandonedMutexException]{$owned=$true};"
            "if(-not $owned){exit 2};$m.ReleaseMutex()}finally{$m.Dispose()}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert mutex_probe.returncode == 0, mutex_probe.stderr
    time.sleep(3)
    assert not survived.exists()
