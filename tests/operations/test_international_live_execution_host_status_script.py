from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from weather.operations.live_path_security import current_execution_host_id


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "ops"
    / "international_live_execution_host_status.ps1"
)


def test_portable_status_is_repo_relative_and_execution_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "[string]$RepoRoot" in text
    assert 'Join-Path $PSScriptRoot "..\\.."' in text
    assert "international_live_execution_host_status_v0.3" in text
    assert 'status = $(if ($flags.Count -eq 0)' in text
    assert "international_live_execution_host_v2`0$machineGuid" in text
    assert "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography" in text
    assert "international_live_execution_principal_v1" in text
    assert "international_live_execution_host_assignment_v0.1" in text
    assert "pre_tool_use_host_load.py" not in text
    assert "[IO.DriveType]::Fixed" in text
    assert "[IO.FileAttributes]::ReparsePoint" in text
    assert "dedicated capture host forbids" in text
    assert "Component Based Servicing" in text
    assert "PendingFileRenameOperations" in text
    assert "HTTP_PROXY" in text
    assert "WEATHER_MARKET_REGISTRY" in text
    assert "WinHttpGetIEProxyConfigForCurrentUser" in text
    assert "WinHttpGetDefaultProxyConfiguration" in text
    assert "winhttp_direct" in text
    assert "credential_access = $false" in text
    assert "exchange_contact = $false" in text
    assert "scheduler_mutation = $false" in text
    assert "capture_mutation = $false" in text
    assert "Get-ScheduledTask" not in text
    assert "CredRead" not in text
    assert "polymarket.com" not in text
    assert "capture_runtime" not in text
    assert "execution_tape" not in text
    assert "C:\\Users\\micha" not in text


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows execution-host identity",
)
def test_powershell_and_python_execution_host_ids_match() -> None:
    command = (
        f". '{REPO_ROOT / 'scripts/ops/workload_admission.ps1'}'; "
        "Get-WeatherExecutionHostId"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == current_execution_host_id()


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="PowerShell parser",
)
def test_portable_status_script_parses() -> None:
    command = (
        "$tokens=$null;$errors=$null;"
        "[void][Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT}',[ref]$tokens,[ref]$errors);"
        "if(@($errors).Count){$errors|% Message;exit 1}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(
    os.name != "nt" or shutil.which("powershell") is None,
    reason="Windows execution-host status",
)
def test_portable_status_serializes_one_redirect_environment_name() -> None:
    redirect_names = {
        "ALL_PROXY",
        "CURL_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "WEATHER_MARKET_REGISTRY",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in redirect_names
    }
    environment["HTTP_PROXY"] = "http://127.0.0.1:9"

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RepoRoot",
            str(REPO_ROOT),
            "-Json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "BLOCKED"
    assert payload["network"]["ambient_redirect_environment_names"] == [
        "HTTP_PROXY"
    ]
