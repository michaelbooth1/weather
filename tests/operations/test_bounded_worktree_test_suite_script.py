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
    assert "ls-files -- tests" in text
    assert "Get-ChildItem -LiteralPath $testRoot" not in text
    assert "$env:PYTHONPATH = Join-Path $WorktreeRoot \"src\"" in text
    assert "AdditionalPythonPath" in text
    assert "$additionalPythonRoots" in text
    assert "[IO.Path]::PathSeparator" in text
    assert "RequireLiveSdkContract" in text
    assert '$env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT = "1"' in text
    assert "$previousLiveSdkRequirement" in text
    for name, value in (
        ("WEATHER_INTEGRATION_TEST_OFFLINE", "1"),
        ("GIT_ALLOW_PROTOCOL", "file"),
        ("GIT_TERMINAL_PROMPT", "0"),
        ("PYTHONNOUSERSITE", "1"),
        ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1"),
        ("PYTHONDONTWRITEBYTECODE", "1"),
        ("PYTHONHASHSEED", "0"),
        ("PYTHONUTF8", "1"),
        ("PYTHONIOENCODING", "utf-8"),
    ):
        assert f'$env:{name} = "{value}"' in text
    assert "$previousIntegrationTestOffline" in text
    assert "[int]$MaxRuntimeSeconds = 5400" in text
    assert "$suiteDeadline" in text
    assert "$localNow.AddSeconds($MaxRuntimeSeconds)" in text
    assert "$suiteRuntimeStopwatch = [Diagnostics.Stopwatch]::StartNew()" in text
    assert "$suiteRuntimeStopwatch.Elapsed.TotalSeconds -ge $MaxRuntimeSeconds" in text
    assert "runtime or 09:00 hard teardown boundary" in text
    assert "Assert-SuiteDiskHeadroom" in text
    assert "[int64]53687091200" in text
    assert "requires at least 50 GiB free" in text
    assert "bounded suite refuses to append to or replace an existing log" in text
    assert "[IO.FileMode]::CreateNew" in text
    assert "[IO.FileShare]::Read" in text
    assert "$suiteLogWriter.WriteLine($line)" in text
    assert "$suiteLogStream.Flush($true)" in text
    assert "Add-Content -LiteralPath $LogPath" not in text
    assert "Invoke-SuiteCheckedLocalGit" in text
    assert "Get-SuiteGitExecutable" in text
    assert "GIT_NO_REPLACE_OBJECTS" in text
    assert "GIT_OPTIONAL_LOCKS" in text
    assert "GIT_CONFIG_GLOBAL" in text
    assert '"--end-of-options"' in text
    assert "& git -C" not in text
    assert "$previousIntegrationTestProductionRoot" in text
    assert "$previousIntegrationTestCandidateRoot" in text
    assert "$env:WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT = $WorktreeRoot" in text
    assert "suite exact-worktree import probe exceeded its bounded runtime" in text
    assert "$importProbeJob = New-WeatherKillOnCloseJob" in text
    assert "Start-WeatherProcessInJob" in text
    assert "$importProbeDeadline = [Diagnostics.Stopwatch]::StartNew()" in text
    assert "contained probe exit=" in text
    assert "weather-integration-junit-" in text
    assert '"--junitxml", $junitTempPath' in text
    assert "[IO.File]::Move($junitTempPath, $junitPath)" in text
    assert "JUnit temp/evidence paths must share one volume" in text
    assert "Remove-Item -LiteralPath $junitTempPath" in text
    assert "$previousIntegrationTestAllowedWriteRoot" in text
    assert "$env:WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT = $null" in text
    assert "Test-WeatherQualificationSensitiveEnvironmentName" in text
    assert '$env:WEATHER_INTEGRATION_TEST_SECRET_POLICY = "conservative_v1"' in text
    assert "$scrubbedSensitiveEnvironment" in text
    assert "POLYMARKET_" in text
    assert "CONNECTION_STRING" in text
    assert "URL|URI|DSN|AUTH|COOKIE|KEY|CERT" in text
    assert "SSH_AUTH_SOCK" in text
    assert "PIP_TRUSTED_HOST" in text
    assert "GIT_SSH_COMMAND" in text
    assert "$previousGitAllowProtocol" in text
    assert "$previousGitTerminalPrompt" in text
    assert "$previousPythonNoUserSite" in text
    assert "$previousPytestPluginAutoload" in text
    assert "$previousPythonDontWriteBytecode" in text
    assert "$previousPythonHashSeed" in text
    assert "$previousPythonUtf8" in text
    assert "$previousPythonIoEncoding" in text
    assert "$WorktreeRoot\n        $env:PYTHONPATH" in text
    lease = text.index("$workloadLease = Enter-WeatherHeavyWorkloadLease")
    offline = text.index('$env:WEATHER_INTEGRATION_TEST_OFFLINE = "1"')
    body = text.index("Set-Location -LiteralPath $WorktreeRoot", offline)
    cleanup = text.index("finally {", body)
    assert lease < offline < body < cleanup
    assert (
        text.index(
            "$env:WEATHER_INTEGRATION_TEST_OFFLINE = "
            "$previousIntegrationTestOffline",
            cleanup,
        )
        > cleanup
    )
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
    assert "[Globalization.CultureInfo]::InvariantCulture" in text
    assert "git merge" not in text
    assert "git push" not in text
    assert "git checkout" not in text
    assert "Start-ScheduledTask" not in text
    assert "Register-ScheduledTask" not in text


def test_bounded_suite_powershell_parses_and_emits_invariant_timestamps(
    tmp_path: Path,
):
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    env["WEATHER_BOUNDED_SUITE_LOG"] = str(tmp_path / "bounded-suite.log")
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Write-SuiteLog'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing Write-SuiteLog' }
Invoke-Expression $functionAst.Extent.Text
$culture = [Globalization.CultureInfo](Get-Culture).Clone()
$culture.DateTimeFormat.TimeSeparator = '.'
[Threading.Thread]::CurrentThread.CurrentCulture = $culture
$LogPath = $env:WEATHER_BOUNDED_SUITE_LOG
Write-SuiteLog 'VERDICT: culture probe' | Out-Null
[pscustomobject]@{
    errors = @($errors | ForEach-Object { $_.Message })
    line = (Get-Content -LiteralPath $LogPath -Raw).Trim()
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
    payload = json.loads(result.stdout)
    assert payload["errors"] == []
    assert payload["line"].endswith("  VERDICT: culture probe")
    assert payload["line"][13:21].count(":") == 2
    assert "." not in payload["line"][13:21]
