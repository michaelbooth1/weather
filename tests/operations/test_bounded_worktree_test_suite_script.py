import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "bounded_worktree_test_suite.ps1"


def test_bounded_suite_is_fail_closed_and_non_mutating():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "00:30-09:00 heavy-work window" in text
    assert "$localMinute -lt 30" in text
    assert "$localMinute -ge (9 * 60)" in text
    assert "$hardStop = $localNow.Date.AddHours(9)" in text
    assert "killing its complete child tree" in text
    assert "ExpectedTip" in text
    assert "worktree list --porcelain" in text
    assert "status --porcelain" in text
    assert "suite worktree is dirty" in text
    assert "$env:PYTHONPATH = Join-Path $WorktreeRoot \"src\"" in text
    assert "AdditionalPythonPath" in text
    assert "$additionalPythonRoots" in text
    assert "[IO.Path]::PathSeparator" in text
    assert "RequireLiveSdkContract" in text
    assert '$env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT = "1"' in text
    assert "$previousLiveSdkRequirement" in text
    assert "Set-Location -LiteralPath $WorktreeRoot" in text
    assert "Set-Location -LiteralPath $previousLocation" in text
    assert "Get-HealthyCaptureWorkerCount" in text
    assert 'Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720' in text
    assert text.count("MaxAge = 180") == 2
    assert "Get-CommitPercent" in text
    assert "Start-WeatherProcessInJob" in text
    assert "New-WeatherKillOnCloseJob" in text
    assert "--junitxml" in text
    assert "VERDICT: ALL CHUNKS PASSED" in text
    assert "IntegrationPreflight" in text
    assert "test_schema_registry.py" in text
    assert "VERDICT: INTEGRATION PREFLIGHT PASSED" in text
    assert "git merge" not in text
    assert "git push" not in text
    assert "git checkout" not in text
    assert "Start-ScheduledTask" not in text
    assert "Register-ScheduledTask" not in text


def test_bounded_suite_powershell_parses_without_execution():
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
[pscustomobject]@{
    errors = @($errors | ForEach-Object { $_.Message })
} | ConvertTo-Json -Compress
"""
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
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["errors"] == []
