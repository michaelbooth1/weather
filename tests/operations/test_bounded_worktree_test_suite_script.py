import json
import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "bounded_worktree_test_suite.ps1"
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows PowerShell",
)


def test_bounded_suite_is_fail_closed_and_non_mutating():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "00:30-09:00 heavy-work window" in text
    assert "$localMinute -lt 30" in text
    assert "$localMinute -ge (9 * 60)" in text
    assert "$hardStop = $localNow.Date.AddHours(9)" in text
    assert "killing its complete child tree" in text
    assert "ExpectedTip" in text
    assert '-Arguments @("worktree", "list", "--porcelain")' in text
    assert '-Arguments @("status", "--porcelain")' in text
    assert "suite worktree is dirty" in text
    assert '-Arguments @("ls-files", "--", "tests")' in text
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
    # Per-chunk basetemp on a short path, removed without following junctions.
    assert '@("--basetemp", $chunkBaseTemp)' in text
    assert 'Join-Path $env:SystemDrive "pt"' in text
    assert 'rmdir /s /q' in text
    assert "refusing unsafe pytest basetemp cleanup" in text
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


@WINDOWS_POWERSHELL_REQUIRED
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
$suiteLogStream = $null
$suiteLogWriter = $null
$line = $null
try {
    $suiteLogStream = [IO.File]::Open(
        $LogPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    $suiteLogWriter = New-Object IO.StreamWriter(
        $suiteLogStream,
        (New-Object Text.UTF8Encoding($false, $true)),
        4096,
        $true
    )
    $suiteLogWriter.AutoFlush = $true
    Write-SuiteLog 'VERDICT: culture probe' | Out-Null
    $line = (Get-Content -LiteralPath $LogPath -Raw).Trim()
}
finally {
    if ($suiteLogWriter) { $suiteLogWriter.Dispose() }
    if ($suiteLogStream) { $suiteLogStream.Dispose() }
}
[pscustomobject]@{
    errors = @($errors | ForEach-Object { $_.Message })
    line = $line
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


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize("rows", [[], ["one"], ["one", "two"]])
def test_git_query_call_sites_preserve_empty_and_nonempty_rows(rows):
    """Execute the actual runner assignments with PowerShell 5.1 strict mode."""
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    env["WEATHER_BOUNDED_SUITE_ROWS"] = json.dumps(rows)
    script = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT, [ref]$tokens, [ref]$errors
)
if ($errors.Count) { throw 'runner parse failure' }
$expectedRows = @(ConvertFrom-Json $env:WEATHER_BOUNDED_SUITE_ROWS | ForEach-Object { $_ })
$RepoRoot = $env:TEMP
$WorktreeRoot = $env:TEMP
$BranchRef = 'refs/heads/test'
function Invoke-SuiteCheckedLocalGit {
    param([string]$Root, [string[]]$Arguments, [string]$Label)
    return [pscustomobject]@{ ExitCode = 0; Rows = $expectedRows; Executable = 'git.exe' }
}
$assignments = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left -is [Management.Automation.Language.VariableExpressionAst]
}, $true))
$checked = @()
foreach ($name in @('dirty', 'trackedTestFiles', 'finalWorktreeTipRows',
                    'finalBranchTipRows', 'finalDirty', 'finalTrackedRows')) {
    $statement = @($assignments | Where-Object { $_.Left.VariablePath.UserPath -ceq $name })
    if ($statement.Count -ne 1) { throw "missing unique query assignment: $name" }
    Invoke-Expression $statement[0].Extent.Text
    $observed = (Get-Variable -Name $name).Value
    if ($observed -isnot [array] -or $observed.Count -ne $expectedRows.Count) {
        throw "query result lost its array shape: $name"
    }
    if (($observed -join '|') -cne ($expectedRows -join '|')) {
        throw "query result changed rows: $name"
    }
    $checked += $name
}
[pscustomobject]@{ checked = $checked; row_count = $expectedRows.Count } | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["row_count"] == len(rows)
    assert len(payload["checked"]) == 6


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize("breach", ["disk", "commit", "capture"])
def test_running_chunk_rechecks_admission_and_disposes_child_tree(breach, tmp_path):
    """Exercise the real running-child try/finally before the child can finish."""
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    env["WEATHER_BOUNDED_SUITE_BREACH"] = breach
    env["WEATHER_BOUNDED_SUITE_TMP"] = str(tmp_path)
    script = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT, [ref]$tokens, [ref]$errors
)
if ($errors.Count) { throw 'runner parse failure' }
$chunk = @($ast.FindAll({
    param($node)
    if ($node -isnot [Management.Automation.Language.TryStatementAst]) { return $false }
    return @($node.Body.Statements | Where-Object {
        $_ -is [Management.Automation.Language.AssignmentStatementAst] -and
        $_.Left -is [Management.Automation.Language.VariableExpressionAst] -and
        $_.Left.VariablePath.UserPath -ceq 'child'
    }).Count -eq 1
}, $true))
if ($chunk.Count -ne 1) { throw 'missing unique running-child try/finally' }
$admission = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq 'Assert-HostAdmission'
}, $true))
if ($admission.Count -ne 1) { throw 'missing host admission function' }
Invoke-Expression $admission[0].Extent.Text
$script:diskChecks = 0
$script:jobDisposals = 0
$script:childDisposals = 0
$script:lastLog = ''
$suiteRuntimeStopwatch = [pscustomobject]@{ Elapsed = [timespan]::Zero }
$suiteDeadline = (Get-Date).AddMinutes(1)
$MaxRuntimeSeconds = 60
$AbortCommitPercent = 66
$ordinal = 1
$python = 'fake-python.exe'
$argumentString = ''
$WorktreeRoot = $env:WEATHER_BOUNDED_SUITE_TMP
$junitTempPath = Join-Path $WorktreeRoot 'absent.xml'
function New-WeatherKillOnCloseJob {
    $job = [pscustomobject]@{ Kind = 'fake-job' }
    $job | Add-Member ScriptMethod Dispose { $script:jobDisposals++ }
    return $job
}
function Start-WeatherProcessInJob {
    param($Job, $FilePath, $ArgumentString, $WorkingDirectory)
    $process = [pscustomobject]@{ HasExited = $false }
    $process | Add-Member ScriptMethod Refresh { }
    $process | Add-Member ScriptMethod Dispose { $script:childDisposals++ }
    return $process
}
function Start-Sleep {
    param([int]$Seconds)
    $suiteRuntimeStopwatch.Elapsed += [timespan]::FromSeconds($Seconds)
    if ($suiteRuntimeStopwatch.Elapsed.TotalSeconds -gt 10) {
        throw 'running child was not checked promptly'
    }
}
function Assert-SuiteDiskHeadroom {
    $script:diskChecks++
    if ($env:WEATHER_BOUNDED_SUITE_BREACH -ceq 'disk') { throw 'disk reserve breached' }
}
function Get-CommitPercent {
    if ($env:WEATHER_BOUNDED_SUITE_BREACH -ceq 'commit') { return 67 }
    return 60
}
function Get-HealthyCaptureWorkerCount {
    if ($env:WEATHER_BOUNDED_SUITE_BREACH -ceq 'capture') { return 2 }
    return 3
}
function Write-SuiteLog { param([string]$Message) $script:lastLog = $Message }
$failure = $null
try { Invoke-Expression $chunk[0].Extent.Text }
catch { $failure = $_.Exception.Message }
[pscustomobject]@{
    failure = $failure
    disk_checks = $script:diskChecks
    job_disposals = $script:jobDisposals
    child_disposals = $script:childDisposals
    elapsed = $suiteRuntimeStopwatch.Elapsed.TotalSeconds
    log = $script:lastLog
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=REPO_ROOT, env=env, check=False, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    expected = {
        "disk": "disk reserve breached",
        "commit": "chunk-1-running refused: commit 67% exceeds 66%",
        "capture": "chunk-1-running refused: expected three healthy capture workers, found 2",
    }
    assert payload["failure"] == expected[breach]
    assert payload["disk_checks"] == 1
    assert payload["job_disposals"] == payload["child_disposals"] == 1
    assert payload["elapsed"] == 6
    if breach != "disk":
        assert "chunk-1-running admission:" in payload["log"]
        assert "ceiling=66%" in payload["log"]
