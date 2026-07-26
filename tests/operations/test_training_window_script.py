import json
import os
import subprocess
from pathlib import Path

from weather.operations.producer_provenance import (
    _windows_argv,
    decode_scheduler_action_arguments,
)


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "training_window.ps1"
REGISTER = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "register_training_window.ps1"
)
CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ops"
    / "training_window_contract.ps1"
)


def test_training_window_uses_verified_no_live_capture_admission():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Wait-CaptureStopped" in text
    assert "--capture-mode no_live_capture" in text
    assert "--capture-resource-mode\", \"no_live_capture" in text
    assert "--capture-resource-min-free-memory-bytes\", \"0" in text
    assert "if (-not (Wait-CaptureStopped $CaptureStopTimeoutSeconds))" in text


def test_training_window_restores_before_propagating_nightly_failure():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "} finally {" in text
    assert "Restore-Capture" in text.split("} finally {", 1)[1]
    assert '$nightlyStatus -in @(\"blocked\", \"error\", \"missing\", \"unreadable\")' in text
    assert text.rstrip().endswith("exit $childExit")


def test_training_window_carries_exact_delegated_scheduler_contract():
    registration = REGISTER.read_text(encoding="utf-8-sig")
    window = SCRIPT.read_text(encoding="utf-8-sig")
    contract = CONTRACT.read_text(encoding="utf-8-sig")

    assert "Get-TrainingWindowTaskActionTokens" in contract
    assert "ConvertTo-ScheduledTaskArgumentString" in contract
    assert "ConvertTo-SchedulerArgumentContract" in contract
    assert "$windowActionTokens = @(Get-TrainingWindowTaskActionTokens" in registration
    assert "-Argument $windowActionArguments" in registration
    assert "-Execute $PowerShellExecutable" in registration
    assert "$scheduledActionTokens = @(Get-TrainingWindowTaskActionTokens" in window
    assert '"--scheduler-invocation-topology", "delegated_child"' in window
    assert '"--scheduler-task-name", $WindowTaskName' in window
    assert '"--scheduler-task-executable", $SchedulerTaskExecutable' in window
    assert '"--scheduler-task-action-arguments-b64", $schedulerActionArgumentsB64' in window
    assert '"--scheduler-process-executable", $python' in window
    assert '"--producer-sla-seconds", ([string]$producerSlaSeconds)' in window


def test_training_window_refuses_hardcoded_staged_source_without_matching_receipt():
    window = SCRIPT.read_text(encoding="utf-8-sig")

    assert "production_source_2026-07-16" in window
    assert '$pitReceipt = Join-Path $pitSourceRoot "staging-receipt.json"' in window
    assert "weather.operations.point_in_time_staging_receipt verify" in window
    assert "$pitReceiptValid = ($LASTEXITCODE -eq 0)" in window
    assert "if ($pitReceiptValid -and" in window
    assert '"--point-in-time-source-receipt", $pitReceipt' in window
    assert "incomplete or unreceipted; production bootstrap refused" in window


def test_training_window_action_tokens_round_trip_with_windows_semantics():
    if os.name != "nt":
        return
    env = os.environ.copy()
    env["WEATHER_CONTRACT_SCRIPT"] = str(CONTRACT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_CONTRACT_SCRIPT
$tokens = @(
  '-NoProfile',
  '-NonInteractive',
  '-ExecutionPolicy', 'Bypass',
  '-File', 'C:\Repo Root\scripts\ops\training_window.ps1',
  '-RepoRoot', 'C:\Repo Root',
  '-WindowTaskName', 'WeatherTrainingWindow',
  '-SchedulerTaskExecutable', 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
)
[pscustomobject]@{
  arguments = ConvertTo-ScheduledTaskArgumentString -Tokens $tokens
  contract = ConvertTo-SchedulerArgumentContract -Tokens $tokens
  tokens = $tokens
} | ConvertTo-Json -Depth 4 -Compress
"""
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert _windows_argv(payload["arguments"]) == payload["tokens"]
    assert decode_scheduler_action_arguments(payload["contract"]) == payload["tokens"]
