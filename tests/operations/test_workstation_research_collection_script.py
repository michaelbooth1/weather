from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts" / "ops" / "workstation_research_collection.ps1"
ADMISSION = REPO_ROOT / "scripts" / "ops" / "workload_admission.ps1"


def test_research_collection_wrapper_is_exactly_plan_and_endpoint_bound() -> None:
    text = WRAPPER.read_text(encoding="utf-8-sig")

    assert "previous-runs-multiyear-collection-plan-2026-09-87a.json" in text
    assert "924ddd2f1ca5a85def80dcee1296752df3df167f8a37d9ae7566a8c5f7ec303a" in text
    assert "20b45f3c0d98a57170a66a237de865374309da67371805fc15204d00f354b09e" in text
    assert "https://previous-runs-api.open-meteo.com/v1/forecast" in text
    assert '"weather.sources.previous_runs_research_collection"' in text
    assert '"collect"' in text
    assert '"--plan"' in text
    assert "Get-FileHash -Algorithm SHA256" in text
    assert "international_live_execution_host.json" in text
    assert "assignment_sha256" in text
    assert "$outputRoot -isnot [IO.DirectoryInfo]" in text
    assert "$existingChildren.Count -ne 0" in text
    assert "exact empty, ACL-verified root" in text


def test_research_collection_has_distinct_host_bound_lease_and_containment() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8-sig")
    admission = ADMISSION.read_text(encoding="utf-8-sig")

    assert '"workstation_research_collection_v1"' in wrapper
    assert "Enter-WeatherHeavyWorkloadLease" in wrapper
    assert "WorkstationResearchCollection-" in wrapper
    assert "New-WeatherKillOnCloseJob" in wrapper
    assert "Start-WeatherInteractiveProcessInJob" in wrapper
    assert "$child.WaitForExit()" in wrapper
    assert "$job.TerminateAndWait(5000)" in wrapper
    assert "Set-WeatherHeavyWorkloadLeaseTeardownPending" in wrapper
    assert "Set-WeatherHeavyWorkloadLeasePoisoned" in wrapper
    assert "Exit-WeatherHeavyWorkloadLease" in wrapper
    assert "WEATHER_RESEARCH_COLLECTION_WRAPPER_ACTIVE" in wrapper

    profile = admission.index(
        'elseif ($ExecutionHostProfile -ceq "workstation_research_collection_v1")'
    )
    profile_end = admission.index(
        'elseif ($ExecutionHostProfile -ceq "capture_colocated_v1")', profile
    )
    profile_body = admission[profile:profile_end]
    assert "Get-WeatherExecutionHostAssignment" in profile_body
    assert "Get-WeatherExecutionPrincipalId" in profile_body
    assert "dedicated capture host" in profile_body
    assert "active_portable_execution_host_id" in profile_body
    assert "active_portable_execution_principal_id" in profile_body
    assert "WorkstationResearchCollection-[0-9a-f]{12}" in profile_body
    assert "$policyWindow = \"workstation_research_collection\"" in profile_body
    assert '"Global\\WeatherProjectHeavyWorkloadV1"' in admission
    assert admission.count('"workstation_research_collection_v1"') >= 5


def test_external_root_acl_is_protected_and_explicitly_denies_offline_writer() -> None:
    text = WRAPPER.read_text(encoding="utf-8-sig")

    assert "$security.SetAccessRuleProtection($true, $false)" in text
    assert "$security.SetOwner($currentSid)" in text
    assert '"S-1-5-18"' in text
    assert '"S-1-5-32-544"' in text
    assert '"CodexSandboxOffline"' in text
    assert "FileSystemAccessRule" in text
    assert "AccessControlType]::Deny" in text
    for right in ("Write", "Delete", "DeleteSubdirectoriesAndFiles"):
        assert f"FileSystemRights]::{right}" in text
    assert "matching_rule_count" in text
    assert "$exitCode -in @(0, 2)" in text
    assert "final-verification.json" in text


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell parser",
)
@pytest.mark.parametrize("path", (WRAPPER, ADMISSION))
def test_research_collection_powershell_is_syntactically_valid(path: Path) -> None:
    environment = {**os.environ, "WEATHER_PARSE_PATH": str(path)}
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$ErrorActionPreference='Stop'; "
                "$tokens=$null; "
                "$errors=$null; "
                "[void][Management.Automation.Language.Parser]::ParseFile("
                "$env:WEATHER_PARSE_PATH,[ref]$tokens,[ref]$errors); "
                "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows PowerShell classifier",
)
def test_only_exact_collector_module_is_classified() -> None:
    environment = {**os.environ, "WEATHER_ADMISSION_PATH": str(ADMISSION)}
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_ADMISSION_PATH
$exact = Test-WeatherWorkstationResearchCollectionModuleCommandLine `
    -CommandLine 'python.exe -m weather.sources.previous_runs_research_collection collect'
$other = Test-WeatherWorkstationResearchCollectionModuleCommandLine `
    -CommandLine 'python.exe -m weather.sources.previous_runs_research_collection_extra collect'
if (-not $exact -or $other) { exit 1 }
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
