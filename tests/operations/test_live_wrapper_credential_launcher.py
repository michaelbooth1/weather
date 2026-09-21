from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import venv

import pytest

from weather.operations.international_live_wrapper_sealer import _render_launcher


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
def test_forced_launcher_exit_kills_the_live_child_tree_before_mutex_reuse(tmp_path):
    mutex_name = f"Local\\WeatherLauncherFixture-{uuid.uuid4().hex}"
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
        f"  $mutex=[Threading.Mutex]::new($false,'{mutex_name}')\n"
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
    fixture_venv = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(fixture_venv)
    python = (fixture_venv / "Scripts/python.exe").resolve()
    pyvenv_config = (fixture_venv / "pyvenv.cfg").resolve()
    runtime_python = Path(sys._base_executable).resolve()
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
    source = _render_launcher(
        TEMPLATE.read_text(encoding="utf-8"),
        production_root=repo.resolve(),
        production_python=python,
        production_python_sha256=hashlib.sha256(python.read_bytes()).hexdigest(),
        production_pyvenv_config=pyvenv_config,
        production_pyvenv_config_sha256=hashlib.sha256(pyvenv_config.read_bytes()).hexdigest(),
        production_runtime_python=runtime_python,
        production_runtime_python_sha256=hashlib.sha256(runtime_python.read_bytes()).hexdigest(),
        wrapper_path=wrapper.resolve(),
        wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest(),
        workload="InternationalLive-stage0-job-test",
        execution_host_profile="portable_execution_v1",
        execution_host_id="a" * 64,
        workload_sha256=hashlib.sha256(lease_script.read_bytes()).hexdigest(),
        job_helper_sha256=hashlib.sha256(job_script.read_bytes()).hexdigest(),
        credential_manifest_path=references.resolve(),
        credential_manifest_sha256=hashlib.sha256(references.read_bytes()).hexdigest(),
    )
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
            f"$m=[Threading.Mutex]::new($false,'{mutex_name}');"
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
