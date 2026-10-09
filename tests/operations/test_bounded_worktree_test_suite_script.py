import json
import re
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "bounded_worktree_test_suite.ps1"
WINDOWS_POWERSHELL_REQUIRED = pytest.mark.skipif(
    os.name != "nt",
    reason="requires Windows PowerShell",
)


@WINDOWS_POWERSHELL_REQUIRED
def test_chunk_temp_survives_pytest_initialization_and_restores_after_failure(tmp_path):
    child_test = tmp_path / "test_child_temp.py"
    child_test.write_text(
        "import os, tempfile\nfrom pathlib import Path\n"
        "def test_temp(tmp_path):\n"
        "    root = Path(os.environ['TEMP'])\n"
        "    assert root.is_dir() and root.name == 'temp'\n"
        "    assert tmp_path.parent.parent == root.parent\n"
        "    with tempfile.TemporaryDirectory() as folder:\n"
        "        assert Path(folder).parent == root\n",
        encoding="utf-8",
    )
    native = tmp_path / "probe.ps1"
    native.write_text(r'''
param($Source, $Root, $Python, $ChildTest)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'script parse failed' }
foreach ($name in @('Enter-SuiteChunkTemp','Exit-SuiteChunkTemp')) {
    $node = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name}, $true)
    . ([scriptblock]::Create($node.Extent.Text))
}
$oldTemp = $env:TEMP; $oldTmp = $env:TMP
$saved = $null
try {
    $saved = Enter-SuiteChunkTemp -Root $Root
    & $Python -m pytest -q -p no:cacheprovider --basetemp (Join-Path $Root 'pytest') $ChildTest
    if ($LASTEXITCODE -ne 0) { throw 'child-temp-contract-failed' }
    throw 'controlled-failure'
}
catch {
    if ($_.Exception.Message -ne 'controlled-failure') { throw }
}
finally { if ($null -ne $saved) { Exit-SuiteChunkTemp -Saved $saved } }
if ($env:TEMP -ne $oldTemp -or $env:TMP -ne $oldTmp) { throw 'parent temp environment changed' }
Write-Output 'TEMP_CONTRACT_PASS'
''', encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(native),
         str(SCRIPT), str(tmp_path / "chunk"), sys.executable, str(child_test)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TEMP_CONTRACT_PASS" in result.stdout


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
    assert '@("--basetemp", $chunkPytestBaseTemp)' in text
    assert '$chunkPytestBaseTemp = Join-Path $chunkBaseTemp "pytest"' in text
    assert 'Enter-SuiteChunkTemp -Root $chunkBaseTemp' in text
    assert 'Exit-SuiteChunkTemp -Saved $chunkTempEnvironment' in text
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
@pytest.mark.spawns
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
@pytest.mark.spawns
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


# Get-HealthyCaptureWorkerCount run end to end against a temporary data\snapshots
# tree whose loop_status.json and writer lock name this PowerShell process, so
# only the heartbeat age decides. Timestamps are written as JSON strings and read
# back through ConvertFrom-Json exactly as on the host (Windows PowerShell 5.1
# leaves them as strings). Get-Date is pinned to the injected moment's local
# clock face so a restored wall-clock line is judged at the same instant.
WORKER_AGE_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'bounded suite does not parse' }
foreach ($name in @('ConvertTo-StatusInstant', 'ConvertTo-StatusUtcInstant', 'Get-HealthyCaptureWorkerCount')) {
    $functionAst = @($ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)) | Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing $name" }
    Invoke-Expression $functionAst.Extent.Text
}
$global:suiteTestNow = $null
function Get-Date { $global:suiteTestNow.DateTime }
$RepoRoot = $env:WEATHER_BOUNDED_SUITE_ROOT
$snapshotRoot = Join-Path $RepoRoot 'data\snapshots'
New-Item -ItemType Directory -Force -Path $snapshotRoot | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $snapshotRoot '.loop_status.json.writer.lock'),
    (@{ pid = $PID } | ConvertTo-Json -Compress), $utf8)
$cases = Get-Content -LiteralPath $env:WEATHER_BOUNDED_SUITE_CASES -Raw | ConvertFrom-Json
$results = [ordered]@{}
foreach ($case in @($cases)) {
    $global:suiteTestNow = [datetimeoffset]::Parse(
        [string]$case.now, [Globalization.CultureInfo]::InvariantCulture)
    $status = '{"pid": ' + $PID + ', "last_heartbeat": "' + [string]$case.heartbeat + '"}'
    [IO.File]::WriteAllText((Join-Path $snapshotRoot 'loop_status.json'), $status, $utf8)
    $results[[string]$case.name] = Get-HealthyCaptureWorkerCount -Now $global:suiteTestNow
}
$results | ConvertTo-Json -Compress
"""

# Toronto falls back at 2026-11-01 06:00Z: 01:59:59 EDT (-04:00) is followed by
# 01:00:00 EST (-05:00), so 01:00-02:00 local repeats inside the 00:30-09:00
# suite window. "now" is given in the host's local offset, as Get-Date shows it.
WORKER_AGE_CASES = [
    # 150 s real age; a wall-clock difference reads -57.5 min (spurious refusal).
    {"name": "fresh_across_fall_back", "heartbeat": "2026-11-01T01:58:00-04:00",
     "now": "2026-11-01T01:00:30-05:00"},
    # 62 min real age; a wall-clock difference reads 120 s (falsely admitted).
    {"name": "stale_hour_hidden_by_fall_back", "heartbeat": "2026-11-01T01:10:00-04:00",
     "now": "2026-11-01T01:12:00-05:00"},
    {"name": "exactly_720_across_fall_back", "heartbeat": "2026-11-01T01:50:00-04:00",
     "now": "2026-11-01T01:02:00-05:00"},
    {"name": "just_over_720_across_fall_back", "heartbeat": "2026-11-01T01:49:59-04:00",
     "now": "2026-11-01T01:02:00-05:00"},
    # Written after fall-back, read "before" it on the clock face: 6 min in the future.
    {"name": "future_heartbeat", "heartbeat": "2026-11-01T01:05:00-05:00",
     "now": "2026-11-01T01:59:00-04:00"},
    {"name": "utc_heartbeat", "heartbeat": "2026-11-01T05:59:00+00:00",
     "now": "2026-11-01T01:01:00-05:00"},
    {"name": "unparseable_heartbeat", "heartbeat": "not-a-time",
     "now": "2026-11-01T01:01:00-05:00"},
]


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_admission_ages_snapshot_heartbeat_on_utc_instants_across_fall_back(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps(WORKER_AGE_CASES), encoding="utf-8")
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    env["WEATHER_BOUNDED_SUITE_ROOT"] = str(tmp_path / "repo")
    env["WEATHER_BOUNDED_SUITE_CASES"] = str(cases_path)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WORKER_AGE_HARNESS],
        cwd=REPO_ROOT, env=env, check=False, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    counts = json.loads(result.stdout.strip().splitlines()[-1])
    # Only the snapshot worker's files exist, so a healthy snapshot worker counts 1.
    assert counts == {
        "fresh_across_fall_back": 1,
        "stale_hour_hidden_by_fall_back": 0,
        "exactly_720_across_fall_back": 1,
        "just_over_720_across_fall_back": 0,
        "future_heartbeat": 0,
        "utc_heartbeat": 1,
        "unparseable_heartbeat": 0,
    }


def _function_text(path: Path, name: str) -> str | None:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    match = re.search(r"(?ms)^function " + re.escape(name) + r" \{\n.*?^\}\n", text)
    return None if match is None else match.group(0)


def test_status_instant_parser_copies_stay_byte_identical():
    # status.ps1 runs as one hash-pinned file and cannot dot-source a helper, so
    # each script carries its own copy. They must not drift apart.
    ops = REPO_ROOT / "scripts" / "ops"
    suite = _function_text(SCRIPT, "ConvertTo-StatusInstant")
    assert suite is not None
    assert "AssumeUniversal" in suite and "[datetimeoffset]::Parse(" in suite
    assert _function_text(ops / "status.ps1", "ConvertTo-StatusInstant") == suite
    probe = _function_text(ops / "bounded_execution_tape_probe.ps1", "ConvertTo-StatusInstant")
    assert probe in (None, suite)
    # The DateTime-by-Kind front end (status.ps1 and this suite only) is pinned
    # the same way; the parser above stays unchanged so the probe copy matches.
    front = _function_text(SCRIPT, "ConvertTo-StatusUtcInstant")
    assert front is not None and "[DateTimeKind]::Local" in front
    assert _function_text(ops / "status.ps1", "ConvertTo-StatusUtcInstant") == front
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "$heartbeat = ConvertTo-StatusUtcInstant $status.last_heartbeat" in text
    assert "$ageSeconds = ($Now - $heartbeat).TotalSeconds" in text
    assert "[datetime]$status.last_heartbeat" not in text


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.parametrize("breach", ["disk", "commit", "capture"])
@pytest.mark.spawns
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
# This fixture isolates admission/Job disposal. The real temp helpers have
# their own native pytest-initialization and failure-restoration test above.
$chunkBaseTemp = $null
$chunkTempEnvironment = $null
function Enter-SuiteChunkTemp { param($Root) return @{} }
function Exit-SuiteChunkTemp { param($Saved) }
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


TIMING_TABLE = REPO_ROOT / "tests" / "bounded_suite_file_timings.json"
NEW_FILE = "tests/operations/test_zz_file_absent_from_the_timing_table.py"
PACKER_HARNESS = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT, [ref]$tokens, [ref]$errors
)
if ($errors.Count) { throw 'runner parse failure' }
foreach ($name in @('Read-SuiteFileTimingTable', 'Get-SuiteTimePackedChunks')) {
    $definition = @($ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $name
    }, $true))
    if ($definition.Count -ne 1) { throw "missing unique function: $name" }
    Invoke-Expression $definition[0].Extent.Text
}
# Windows PowerShell 5.1 emits a parsed JSON array as one pipeline object.
$cases = Get-Content -LiteralPath $env:WEATHER_BOUNDED_SUITE_CASES -Raw | ConvertFrom-Json
$results = @()
foreach ($case in $cases) {
    try {
        $table = Read-SuiteFileTimingTable -Path ([string]$case.table)
        $chunks = Get-SuiteTimePackedChunks -TestFiles @($case.files | ForEach-Object { [string]$_ }) `
            -MaxFilesPerChunk ([int]$case.cap) -TimingTable $table
        $results += ,[pscustomobject]@{
            present = $table.Present
            chunks = @($chunks | ForEach-Object { ,@($_) })
            error = $null
        }
    }
    catch {
        $results += ,[pscustomobject]@{ present = $null; chunks = @(); error = $_.Exception.Message }
    }
}
ConvertTo-Json -InputObject @($results) -Depth 6 -Compress
"""


def _tracked_test_files() -> list[str]:
    rows = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", "tests"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    return sorted(
        row for row in (r.replace("\\", "/") for r in rows)
        if re.match(r"^tests/(?:.*/)?test_[^/]*\.py$", row)
    )


def _run_packer(cases: list[dict], tmp_path: Path) -> list[dict]:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    env["WEATHER_BOUNDED_SUITE_CASES"] = str(cases_path)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PACKER_HARNESS],
        cwd=REPO_ROOT, env=env, check=False, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    return payload if isinstance(payload, list) else [payload]


def _chunk_lists(result: dict) -> list[list[str]]:
    return [[chunk] if isinstance(chunk, str) else list(chunk) for chunk in result["chunks"]]


def test_bounded_suite_plans_time_packed_chunks_without_raising_the_cap():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "[ValidateRange(1, 25)]\n    [int]$MaxFilesPerChunk = 25" in text
    assert r'Join-Path $WorktreeRoot "tests\bounded_suite_file_timings.json"' in text
    assert "-TestFiles $testFiles -MaxFilesPerChunk $MaxFilesPerChunk -TimingTable $timingTable" in text
    assert (
        'Write-SuiteLog "planned chunks=$($chunks.Count) files=$($testFiles.Count) '
        'max_files=$MaxFilesPerChunk"'
    ) in text
    assert "suite chunk packing did not place every test file exactly once" in text
    assert "[int64]$item.Length -gt 1048576" in text
    table = json.loads(TIMING_TABLE.read_text(encoding="utf-8"))
    assert table["format_version"] == 1
    assert 0 < table["default_seconds"] <= 3600
    assert all(re.match(r"^tests/(?:.*/)?test_[^/]*\.py$", name) for name in table["files"])
    assert all(0 <= seconds <= 86400 for seconds in table["files"].values())


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_time_packing_places_every_tracked_test_file_in_exactly_one_chunk(tmp_path):
    """Meta-test over the real inventory and the checked-in timing table."""
    files = _tracked_test_files()
    table = str(TIMING_TABLE)
    results = _run_packer(
        [
            {"files": files, "cap": 20, "table": table},
            {"files": list(reversed(files)), "cap": 20, "table": table},
            {"files": files, "cap": 25, "table": table},
            {"files": files, "cap": 20, "table": str(tmp_path / "absent.json")},
            {"files": files + [NEW_FILE], "cap": 20, "table": table},
            {"files": [NEW_FILE] + files, "cap": 20, "table": table},
        ],
        tmp_path,
    )
    for result, cap in zip(results[:4], (20, 20, 25, 20)):
        assert result["error"] is None, result["error"]
        chunks = _chunk_lists(result)
        placed = [file for chunk in chunks for file in chunk]
        assert sorted(placed) == files
        assert len(placed) == len(set(placed))
        assert len(chunks) == -(-len(files) // cap)
        assert all(1 <= len(chunk) <= cap for chunk in chunks)
        assert all(chunk == sorted(chunk) for chunk in chunks)
    assert results[0]["present"] is True and results[3]["present"] is False
    assert _chunk_lists(results[0]) == _chunk_lists(results[1])
    # A file the table has never seen is placed exactly once, deterministically.
    with_new = _chunk_lists(results[4])
    assert with_new == _chunk_lists(results[5])
    assert sorted(file for chunk in with_new for file in chunk) == sorted(files + [NEW_FILE])


@WINDOWS_POWERSHELL_REQUIRED
@pytest.mark.spawns
def test_time_packing_is_deterministic_lpt_and_fails_closed_on_bad_tables(tmp_path):
    def table(path: Path, body) -> str:
        path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
        return str(path)

    files = [f"tests/test_{name}.py" for name in "abcdef"]
    good = table(tmp_path / "good.json", {
        "format_version": 1, "default_seconds": 2.0,
        "files": {"tests/test_a.py": 9.0, "tests/test_b.py": 7.0, "tests/test_c.py": 5.0,
                  "tests/test_d.py": 1.0, "tests/test_stale.py": 50.0},
    })
    bad = {
        "malformed": "{",
        "version": {"format_version": 2, "default_seconds": 1, "files": {}},
        "default": {"format_version": 1, "default_seconds": 0, "files": {}},
        "name": {"format_version": 1, "default_seconds": 1, "files": {"tools/x.py": 1}},
        "negative": {"format_version": 1, "default_seconds": 1, "files": {"tests/test_a.py": -1}},
        "text": {"format_version": 1, "default_seconds": 1, "files": {"tests/test_a.py": "9"}},
    }
    cases = [{"files": files, "cap": 2, "table": good}]
    cases += [{"files": files, "cap": 2, "table": table(tmp_path / f"{key}.json", body)}
              for key, body in bad.items()]
    cases += [{"files": files + ["tests/test_a.py"], "cap": 4, "table": good}]
    results = _run_packer(cases, tmp_path)
    # Weights a=9, b=7, c=5, e=f=2 (default), d=1; three chunks of at most two.
    assert _chunk_lists(results[0]) == [
        ["tests/test_a.py", "tests/test_d.py"],
        ["tests/test_b.py", "tests/test_f.py"],
        ["tests/test_c.py", "tests/test_e.py"],
    ]
    for result in results[1:1 + len(bad)]:
        assert result["error"] and "suite file timing table" in result["error"]
    assert "repeats a file" in results[-1]["error"]
