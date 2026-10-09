import hashlib
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


# -InterpreterPath (host Python upgrade prep, HOST-PY plan P7): the suite runs a
# staged venv's python.exe while RepoRoot keeps the shared production lease. The
# harness executes the script's own statements (the probe-sidecar refusal, the
# interpreter selection, the lease acquisition and the receipt log line) against
# real staging venvs.
INTERPRETER_FUNCTIONS = (
    "Get-SuiteDosDeviceTarget",
    "Assert-SuiteInterpreterLocalDrive",
    "Assert-SuiteInterpreterLocalRegularFile",
    "Get-SuiteInterpreterOverrideHashes",
    "Assert-SuiteInterpreterOverrideUnchanged",
    "Resolve-SuiteInterpreterOverride",
)
INTERPRETER_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT, [ref]$tokens, [ref]$errors
)
if ($errors.Count) { throw 'runner parse failure' }
$ops = Split-Path -Parent $env:WEATHER_BOUNDED_SUITE_SCRIPT
. (Join-Path $ops 'training_window_contract.ps1')
. (Join-Path $ops 'windows_kill_on_close_job.ps1')
foreach ($functionName in @(%FUNCTIONS%)) {
    $definition = @($ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq $functionName
    }, $true))
    if ($definition.Count -ne 1) { throw "missing unique $functionName" }
    Invoke-Expression $definition[0].Extent.Text
}
$top = @($ast.EndBlock.Statements)
$receipt = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text -ceq '$null -ne $interpreterOverride' -and
        $node.Extent.Text.Contains('"interpreter_override "')
}, $true))
if ($receipt.Count -ne 1) { throw 'receipt statement is not unique' }
""".replace(
    "%FUNCTIONS%", ", ".join(f"'{name}'" for name in INTERPRETER_FUNCTIONS)
)
INTERPRETER_HARNESS = INTERPRETER_PRELUDE + r"""
$sidecar = @($top | Where-Object {
    $_ -is [Management.Automation.Language.IfStatementAst] -and
        $_.Extent.Text.Contains('$interpreterProbeSidecar')
})
$select = @($top | Where-Object {
    $_ -is [Management.Automation.Language.IfStatementAst] -and
        $_.Extent.Text.Contains('[string]::IsNullOrEmpty($InterpreterPath)') -and
        -not $_.Extent.Text.Contains('$interpreterProbeSidecar')
})
$lease = @($top | Where-Object {
    $_ -is [Management.Automation.Language.AssignmentStatementAst] -and
        $_.Left.VariablePath.UserPath -ceq 'workloadLease'
})
if ($sidecar.Count -ne 1 -or $select.Count -ne 1 -or $lease.Count -ne 1) {
    throw 'sidecar, interpreter or lease statement is not unique'
}
$repoRootAssignments = @($top | Where-Object {
    $_ -is [Management.Automation.Language.AssignmentStatementAst] -and
        $_.Left.VariablePath.UserPath -ceq 'RepoRoot'
}).Count
$selectIndex = [array]::IndexOf($top, $select[0])
$sidecarIndex = [array]::IndexOf($top, $sidecar[0])
$leaseIndex = [array]::IndexOf($top, $lease[0])
function Write-WeatherLaunchDiagnostic {
    param($Journal, $Event, $Detail)
    $script:events += ,[string]$Event
}
function Enter-WeatherHeavyWorkloadLease {
    param($RepoRoot, $Workload)
    $script:leases += ,[pscustomobject]@{ repo_root = $RepoRoot; workload = $Workload }
    return 'lease'
}
function Write-SuiteLog { param([string]$Message) $script:logLines += ,$Message }
$results = @()
foreach ($case in (Get-Content -LiteralPath $env:WEATHER_INTERPRETER_CASES -Raw | ConvertFrom-Json)) {
    $script:events = @()
    $script:leases = @()
    $script:logLines = @()
    $RepoRoot = [string]$case.repo_root
    $InterpreterPath = [string]$case.interpreter_path
    $ExpectedInterpreterVersion = [string]$case.expected_version
    $LogPath = [string]$case.log_path
    $launchJournal = $null
    $python = $null
    $interpreterOverride = 'unset'
    $failure = $null
    $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
        Invoke-Expression $sidecar[0].Extent.Text
        if ($null -ne $case.probe_timeout) {
            $interpreterOverride = Resolve-SuiteInterpreterOverride `
                -Path $InterpreterPath -ProbeOutputPrefix ($LogPath + '.interpreter') `
                -LeaseRepoRoot $RepoRoot -ExpectedVersion $ExpectedInterpreterVersion `
                -ProbeTimeoutSeconds ([int]$case.probe_timeout)
            $python = $interpreterOverride.interpreter_path
        }
        else {
            Invoke-Expression $select[0].Extent.Text
            Invoke-Expression $lease[0].Extent.Text
            Invoke-Expression $receipt[0].Extent.Text
        }
    }
    catch { $failure = $_.Exception.Message }
    $results += ,[pscustomobject]@{
        name = [string]$case.name
        failure = $failure
        python = $python
        elapsed_seconds = $watch.Elapsed.TotalSeconds
        events = @($script:events)
        leases = @($script:leases)
        log = @($script:logLines)
        repo_root_assignments = $repoRootAssignments
        select_before_lease = ($selectIndex -ge 0 -and $selectIndex -lt $leaseIndex)
        sidecar_before_select = ($sidecarIndex -ge 0 -and $sidecarIndex -lt $selectIndex)
    }
}
ConvertTo-Json -InputObject @($results) -Depth 6 -Compress
"""
# Writes a suite log by executing the main body's own receipt line and every
# statement from the pre-verdict interpreter re-hash to the terminal `exit`.
VERDICT_HARNESS = INTERPRETER_PRELUDE + r"""
$writeLog = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq 'Write-SuiteLog'
}, $true))
Invoke-Expression $writeLog[0].Extent.Text
$main = @($top | Where-Object {
    $_ -is [Management.Automation.Language.TryStatementAst] -and
        $_.Extent.Text.Contains('=== bounded worktree suite starting ===')
})
if ($main.Count -ne 1) { throw 'main statement is not unique' }
$body = @($main[0].Body.Statements)
$tail = -1
for ($index = 0; $index -lt $body.Count; $index++) {
    if ($body[$index].Extent.Text.Contains('Assert-SuiteInterpreterOverrideUnchanged')) { $tail = $index; break }
}
if ($tail -lt 0) { throw 'pre-verdict interpreter re-hash is missing from the main body' }
$suiteLogWriter = [IO.StreamWriter]::new($env:WEATHER_VERDICT_LOG, $false, [Text.UTF8Encoding]::new($false))
$interpreterOverride = $null
if ($env:WEATHER_VERDICT_INTERPRETER) {
    $interpreterOverride = Resolve-SuiteInterpreterOverride `
        -Path $env:WEATHER_VERDICT_INTERPRETER -ProbeOutputPrefix ($env:WEATHER_VERDICT_LOG + '.interpreter') `
        -LeaseRepoRoot $env:WEATHER_VERDICT_REPO
}
Write-SuiteLog '=== bounded worktree suite starting ==='
Write-SuiteLog "worktree=$env:WEATHER_VERDICT_REPO branch=$env:WEATHER_VERDICT_BRANCH expected_tip=$env:WEATHER_VERDICT_TIP"
Invoke-Expression $receipt[0].Extent.Text
Write-SuiteLog 'planned chunks=2 files=40 max_files=20'
if ($env:WEATHER_VERDICT_MUTATE) {
    Add-Content -LiteralPath $env:WEATHER_VERDICT_MUTATE -Value '# swapped after the probe'
}
$SmokeTest = $false
$IntegrationPreflight = $false
$chunks = @(@('tests/a.py'), @('tests/b.py'))
$launchStatus = 'FAIL'
foreach ($statement in $body[$tail..($body.Count - 1)]) { Invoke-Expression $statement.Extent.Text }
throw 'verdict tail returned without exit'
"""
# The three merge-evidence readers, run for real against the logs written above
# with Scheduler, git and clock stubs (functions shadow cmdlets and git.exe).
READERS_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$cases = Get-Content -LiteralPath $env:WEATHER_READER_CASES -Raw | ConvertFrom-Json
$ops = $env:WEATHER_OPS
$global:StubTip = $env:WEATHER_READER_TIP
$global:StubRepo = $env:WEATHER_READER_REPO
function global:git {
    $global:LASTEXITCODE = 0
    if ($args -contains 'rev-parse') { return $global:StubTip }
    if ($args -contains 'bundle' -and $args -contains 'create') {
        Set-Content -LiteralPath ([string]$args[4]) -Value 'stub bundle'
    }
}
function global:Get-ScheduledTask {
    return [pscustomobject]@{
        State = 'Ready'
        Actions = @([pscustomobject]@{
            Execute = (Join-Path $PSHOME 'powershell.exe')
            WorkingDirectory = $global:StubRepo
            Arguments = $global:StubArguments
        })
    }
}
function global:Get-ScheduledTaskInfo {
    return [pscustomobject]@{ LastRunTime = $global:StubLastRun; LastTaskResult = 0 }
}
$results = @()
foreach ($case in $cases) {
    $first = [string](@(Get-Content -LiteralPath $case.log)[0])
    $global:StubLastRun = [datetime]::ParseExact(
        $first.Substring(0, 19), 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture
    )
    $global:StubArguments = [string]$case.arguments
    $outcome = $null
    if ($case.reader -eq 'contract') {
        try {
            . (Join-Path $ops 'integration_attempt_contract.ps1')
            $verdict = Get-WeatherIntegrationLogVerdict -Path $case.log
            $planned = Assert-WeatherIntegrationFullSuiteVerdict -Verdict $verdict -ExpectedChunkCount 2
            $outcome = "ACCEPTED $planned"
        }
        catch { $outcome = $_.Exception.Message }
    }
    elseif ($case.reader -eq 'bundle') {
        function global:Get-Date { return [datetime]::Today.AddHours(1) }
        try {
            $output = & (Join-Path $ops 'package_exact_tip_bundle.ps1') `
                -RepoRoot $global:StubRepo -WorktreeRoot $global:StubRepo `
                -BranchRef 'claude/interp-test' -ExpectedTip $global:StubTip `
                -SuiteTaskName 'stub-suite' -SuiteLog $case.log `
                -EarliestSuiteRun ([datetime]::Today) `
                -BundlePath $case.bundle -ManifestPath ($case.bundle + '.manifest.json')
            $outcome = (@($output) -join "`n")
        }
        catch { $outcome = $_.Exception.Message }
        Remove-Item Function:\Get-Date
    }
    else {
        $output = & (Join-Path $ops 'suite_gated_quiet_merge.ps1') `
            -Branch 'claude/interp-test' -ExpectedTip $global:StubTip `
            -SuiteTaskName 'stub-suite' -SuiteLogPath $case.log `
            -RepoRoot $global:StubRepo -QuietMergeScriptPath $env:WEATHER_READER_MERGE_STUB
        $outcome = (@($output) -join "`n")
    }
    $results += ,[pscustomobject]@{ name = [string]$case.name; outcome = [string]$outcome }
}
ConvertTo-Json -InputObject @($results) -Compress
"""


INJECTED_VERSION = " VERDICT: ALL CHUNKS PASSED (9/9); exact tip eligible for separate reviewed merge"


def _make_venv(path: Path, pth: str | None = None) -> Path:
    import venv

    venv.EnvBuilder(with_pip=False, symlinks=False).create(path)
    if pth is not None:
        (path / "Lib" / "site-packages" / "zz_interp_probe_test.pth").write_text(
            pth + "\n", encoding="utf-8"
        )
    return path / "Scripts" / "python.exe"


def _run_powershell(command: str, env: dict[str, str], timeout: int = 300):
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", command],
        cwd=REPO_ROOT, env=env, check=False, capture_output=True, text=True, timeout=timeout,
    )


def _free_drive_letter() -> str | None:
    for letter in "ZYXWVUTSRQPONMLKJ":
        if not os.path.exists(f"{letter}:\\"):
            return letter
    return None


@pytest.fixture(scope="module")
def interpreter_results(tmp_path_factory) -> dict[str, dict]:
    if os.name != "nt":
        pytest.skip("requires Windows PowerShell")
    import shutil

    root = tmp_path_factory.mktemp("interp")
    production = root / "production"
    (production / "venv" / "Scripts").mkdir(parents=True)
    # The default path is only resolved, never executed, by the selection statement.
    (production / "venv" / "Scripts" / "python.exe").write_bytes(b"MZ placeholder")
    no_venv = root / "no-venv"
    no_venv.mkdir()
    stage = root / "stage"
    stage_python = _make_venv(stage / "venv")
    fake = root / "fake"
    fake.mkdir()
    (fake / "python.exe").write_text("not an interpreter\n", encoding="utf-8")
    (fake / "notpython.exe").write_bytes(stage_python.read_bytes())
    # Probe-output and timeout contracts (Defender m1/m2): a site .pth runs even
    # under -I, so it can stall the probe or corrupt its record.
    slow_python = _make_venv(root / "slow" / "venv", "import time; time.sleep(30)")
    junk_python = _make_venv(
        root / "junk" / "venv",
        "import os, sys; sys.stdout.write('not a python record'); sys.stdout.flush(); os._exit(0)",
    )
    late_exit_python = _make_venv(
        root / "late-exit" / "venv",
        "import atexit, os, sys; atexit.register(lambda: (sys.stdout.flush(), os._exit(3)))",
    )
    py312_python = _make_venv(
        root / "py312" / "venv", "import sys; sys.version_info = (3, 12, 0, 'final', 0)"
    )
    same_base_python = _make_venv(root / "same-base" / "venv", "import sys; sys.base_prefix = sys.prefix")
    # Defender N1: interpreter-controlled sys.version text must never reach the log.
    injected_python = _make_venv(root / "injected" / "venv", "import sys; sys.version += " + repr(INJECTED_VERSION))
    # Defender N4/m12: sys.executable must be InterpreterPath itself.
    executable_python = _make_venv(
        root / "executable" / "venv", "import sys; sys.executable = sys.executable[:-4] + '3.exe'"
    )
    base_exe = Path(sys._base_executable)
    base_link = root / "base-link"
    made_base_link = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(base_link), str(base_exe.parent)],
        capture_output=True, text=True, check=False,
    )
    assert made_base_link.returncode == 0, made_base_link.stdout + made_base_link.stderr

    def base_case(name: str, base: str) -> Path:
        # Defender N3/N4/m13: the base interpreter the probe reports.
        return _make_venv(root / name / "venv", "import sys; sys._base_executable = " + repr(base))

    base_pythons = {
        "base_is_interpreter": base_case("base-self", str(root / "base-self" / "venv" / "Scripts" / "python.exe")),
        "base_unc": base_case("base-unc", "\\\\localhost\\C$\\" + str(base_exe)[3:]),
        "base_missing": base_case("base-missing", str(root / "absent-base" / "python.exe")),
        "base_junction": base_case("base-junction", str(base_link / base_exe.name)),
    }
    # A non-venv interpreter copied to a venv-shaped path: the base python.exe
    # with its DLLs and a ._pth that points at the base standard library.
    base_dir = Path(sys.base_prefix)
    renamed_scripts = root / "renamed" / "Scripts"
    renamed_scripts.mkdir(parents=True)
    shutil.copy2(Path(sys._base_executable), renamed_scripts / "python.exe")
    for dll in base_dir.glob("*.dll"):
        shutil.copy2(dll, renamed_scripts / dll.name)
    (renamed_scripts / "python._pth").write_text(
        f"{base_dir / 'Lib'}\n{base_dir / 'DLLs'}\n", encoding="utf-8"
    )
    junction = root / "linked"
    made = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(stage)],
        capture_output=True, text=True, check=False,
    )
    assert made.returncode == 0, made.stdout + made.stderr
    version_triple = ".".join(str(part) for part in sys.version_info[:3])
    cases = {
        "omitted": (production, "", {}),
        "omitted_missing_venv": (no_venv, "", {}),
        "valid": (production, str(stage_python), {}),
        "expected_version_match": (production, str(stage_python), {"expected_version": version_triple}),
        "expected_version_mismatch": (production, str(stage_python), {"expected_version": "3.11.999"}),
        "expected_without_path": (production, "", {"expected_version": version_triple}),
        "relative": (production, r"venv\Scripts\python.exe", {}),
        "missing": (production, str(root / "absent" / "python.exe"), {}),
        "not_normalized": (production, str(stage / "venv" / "Scripts") + r"\..\Scripts\python.exe", {}),
        "non_python_name": (production, str(fake / "notpython.exe"), {}),
        "non_python_file": (production, str(fake / "python.exe"), {}),
        "reparse_point": (production, str(junction / "venv" / "Scripts" / "python.exe"), {}),
        "slow_probe": (production, str(slow_python), {"probe_timeout": 3}),
        "junk_output": (production, str(junk_python), {}),
        "late_nonzero_exit": (production, str(late_exit_python), {}),
        "not_python_311": (production, str(py312_python), {}),
        "prefix_equals_base": (production, str(same_base_python), {}),
        "copied_base_interpreter": (production, str(renamed_scripts / "python.exe"), {}),
        "base_interpreter": (production, str(Path(sys._base_executable)), {}),
        "version_injection": (production, str(injected_python), {}),
        "executable_mismatch": (production, str(executable_python), {}),
        **{name: (production, str(python), {}) for name, python in base_pythons.items()},
    }
    launcher = shutil.which("py")
    if launcher:
        # The Defender's bypass: the py.exe launcher renamed to python.exe.
        renamed_launcher = root / "renamed-py" / "venv" / "Scripts"
        renamed_launcher.mkdir(parents=True)
        shutil.copy2(launcher, renamed_launcher / "python.exe")
        cases["renamed_py_launcher"] = (production, str(renamed_launcher / "python.exe"), {})
    letter = _free_drive_letter()
    subst_made = False
    if letter:
        subst_made = subprocess.run(
            ["subst", f"{letter}:", str(stage)], capture_output=True, text=True, check=False
        ).returncode == 0
    if subst_made:
        cases["subst_drive"] = (production, f"{letter}:\\venv\\Scripts\\python.exe", {})
    base_letter = _free_drive_letter()
    base_subst_made = False
    if base_letter:
        base_subst_made = subprocess.run(
            ["subst", f"{base_letter}:", str(base_exe.parent)], capture_output=True, text=True, check=False
        ).returncode == 0
    if base_subst_made:
        cases["base_subst"] = (
            production, str(base_case("base-subst", f"{base_letter}:\\{base_exe.name}")), {}
        )
    payload = []
    for name, (repo_root, interpreter, extra) in cases.items():
        logs = root / "logs" / name
        logs.mkdir(parents=True)
        payload.append({"name": name, "repo_root": str(repo_root), "interpreter_path": interpreter,
                        "log_path": str(logs / "suite.log"), "expected_version": "",
                        "probe_timeout": None, **extra})
    # A retry with the LogPath of a refused probe meets a clean refusal.
    junk_log = next(row["log_path"] for row in payload if row["name"] == "junk_output")
    payload.append({"name": "retry_same_log", "repo_root": str(production),
                    "interpreter_path": str(stage_python), "log_path": junk_log,
                    "expected_version": "", "probe_timeout": None})
    cases_path = root / "cases.json"
    cases_path.write_text(json.dumps(payload), encoding="utf-8")
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    env["WEATHER_INTERPRETER_CASES"] = str(cases_path)
    try:
        result = _run_powershell(INTERPRETER_HARNESS, env)
    finally:
        os.rmdir(junction)
        os.rmdir(base_link)
        if subst_made:
            subprocess.run(["subst", f"{letter}:", "/d"], capture_output=True, check=False)
        if base_subst_made:
            subprocess.run(["subst", f"{base_letter}:", "/d"], capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    results = {row["name"]: row for row in json.loads(result.stdout)}
    results["_paths"] = {
        "production": str(production),
        "stage_python": str(stage_python),
        "stage_root": str(stage / "venv"),
        "stage_sha256": hashlib.sha256(stage_python.read_bytes()).hexdigest(),
        "pyvenv_sha256": hashlib.sha256((stage / "venv" / "pyvenv.cfg").read_bytes()).hexdigest(),
        "base_executable": str(Path(sys._base_executable)),
        "base_sha256": hashlib.sha256(Path(sys._base_executable).read_bytes()).hexdigest(),
        "omitted_log": payload[0]["log_path"],
        "valid_log": payload[2]["log_path"],
        "junk_log": junk_log,
        "launcher": bool(launcher),
        "subst": subst_made,
        "base_subst": base_subst_made,
        "injected_log": next(row["log_path"] for row in payload if row["name"] == "version_injection"),
    }
    return results


@pytest.mark.spawns
def test_omitted_interpreter_path_keeps_the_production_venv_unchanged(interpreter_results):
    row = interpreter_results["omitted"]
    paths = interpreter_results["_paths"]
    assert row["failure"] is None
    assert row["python"] == str(Path(paths["production"]) / "venv" / "Scripts" / "python.exe")
    # No probe, no journal event, no receipt line: the default run is unchanged.
    assert row["events"] == [] and row["log"] == []
    assert list(Path(paths["omitted_log"]).parent.iterdir()) == []
    missing = interpreter_results["omitted_missing_venv"]
    assert missing["failure"].startswith("production venv interpreter is missing:")
    assert missing["leases"] == []


@pytest.mark.spawns
def test_valid_interpreter_path_runs_the_stage_python_and_is_recorded(interpreter_results):
    row = interpreter_results["valid"]
    paths = interpreter_results["_paths"]
    assert row["failure"] is None
    assert row["python"] == paths["stage_python"]
    assert row["events"] == ["INTERPRETER_OVERRIDE"]
    assert len(row["log"]) == 1 and row["log"][0].startswith("interpreter_override {")
    record = json.loads(row["log"][0][len("interpreter_override "):])
    assert record == {
        "interpreter_path": paths["stage_python"],
        "interpreter_sha256": paths["stage_sha256"],
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "python_version_sha256": hashlib.sha256(sys.version.encode("utf-8")).hexdigest(),
        "python_version_triple": ".".join(str(part) for part in sys.version_info[:3]),
        "expected_version": "",
        "sys_executable": paths["stage_python"],
        "sys_prefix": paths["stage_root"],
        "sys_base_prefix": sys.base_prefix,
        "pyvenv_cfg_path": str(Path(paths["stage_root"]) / "pyvenv.cfg"),
        "pyvenv_cfg_sha256": paths["pyvenv_sha256"],
        "base_executable": paths["base_executable"],
        "base_executable_sha256": paths["base_sha256"],
        "lease_repo_root": paths["production"],
    }
    probe = json.loads(Path(paths["valid_log"] + ".interpreter.stdout.log").read_text(encoding="utf-8"))
    assert probe["version"] == sys.version and probe["prefix"] == paths["stage_root"]
    matched = interpreter_results["expected_version_match"]
    assert matched["failure"] is None and matched["python"] == paths["stage_python"]
    assert json.loads(matched["log"][0][len("interpreter_override "):])["expected_version"] == ".".join(
        str(part) for part in sys.version_info[:3]
    )


@pytest.mark.spawns
@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("relative", "InterpreterPath must be an absolute, normalized local path"),
        ("not_normalized", "InterpreterPath must be an absolute, normalized local path"),
        ("missing", "InterpreterPath does not exist"),
        ("non_python_name", "InterpreterPath must name a python.exe"),
        ("non_python_file", "InterpreterPath version probe could not start"),
        ("reparse_point", "InterpreterPath traverses a reparse point"),
        ("slow_probe", "InterpreterPath version probe exceeded its bounded runtime"),
        ("junk_output", "InterpreterPath version probe did not identify a Python interpreter (exit=0)"),
        ("late_nonzero_exit", "InterpreterPath version probe did not identify a Python interpreter (exit=3)"),
        ("not_python_311", "InterpreterPath is not Python 3.11: 3.12.0"),
        ("expected_version_mismatch", "InterpreterPath is Python 3.11."),
        ("prefix_equals_base",
         "InterpreterPath is not a virtual environment interpreter: sys.prefix equals sys.base_prefix"),
        ("copied_base_interpreter", "InterpreterPath is not a virtual environment interpreter: sys.prefix"),
        ("base_interpreter", "InterpreterPath is not a virtual environment interpreter: sys.prefix"),
        ("executable_mismatch", "InterpreterPath is not a virtual environment interpreter: sys.executable"),
        ("base_is_interpreter", "InterpreterPath base interpreter is not a separate local regular file"),
        ("base_unc", "InterpreterPath base interpreter is not a separate local regular file"),
        ("base_missing", "InterpreterPath base interpreter is not a separate local regular file"),
        ("base_junction", "InterpreterPath base interpreter traverses a reparse point"),
        ("expected_without_path", "ExpectedInterpreterVersion requires InterpreterPath"),
        ("retry_same_log", "bounded suite refuses to replace an existing interpreter probe output"),
    ],
)
def test_invalid_interpreter_path_is_refused_before_the_lease(interpreter_results, name, message):
    row = interpreter_results[name]
    assert row["failure"] and row["failure"].startswith(message), row["failure"]
    assert row["python"] is None
    assert row["leases"] == [] and row["log"] == [] and row["events"] == []
    if name == "slow_probe":
        # The 3 s bound fired; the .pth would otherwise hold the probe for 30 s.
        assert row["elapsed_seconds"] < 20
    if name == "expected_version_mismatch":
        assert row["failure"].endswith("not the expected 3.11.999")
    if name in ("copied_base_interpreter", "base_interpreter"):
        assert "is not the venv root" in row["failure"]


@pytest.mark.spawns
def test_interpreter_controlled_version_text_never_reaches_the_log(interpreter_results):
    row = interpreter_results["version_injection"]
    assert row["failure"] is None, row["failure"]
    assert len(row["log"]) == 1 and row["log"][0].startswith("interpreter_override {")
    assert "VERDICT" not in row["log"][0] and "CHUNKS" not in row["log"][0]
    record = json.loads(row["log"][0][len("interpreter_override "):])
    triple = ".".join(str(part) for part in sys.version_info[:3])
    assert record["python_version"] == triple == record["python_version_triple"]
    # The raw text stays in the probe sidecar only, never in the suite log; the
    # log binds it by hash. (site may process the venv .pth more than once.)
    probe = Path(interpreter_results["_paths"]["injected_log"] + ".interpreter.stdout.log")
    raw = json.loads(probe.read_text(encoding="utf-8"))["version"]
    assert raw.startswith(sys.version + INJECTED_VERSION)
    assert record["python_version_sha256"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()


@pytest.mark.spawns
def test_base_interpreter_on_a_subst_letter_is_refused(interpreter_results):
    if not interpreter_results["_paths"]["base_subst"]:
        pytest.skip("no second free subst drive letter is available")
    row = interpreter_results["base_subst"]
    assert row["failure"] and row["failure"].startswith(
        "InterpreterPath base interpreter must be on a local fixed drive, not a mapped or subst letter"
    ), row["failure"]
    assert row["leases"] == [] and row["log"] == [] and row["python"] is None


@pytest.mark.spawns
def test_renamed_launcher_and_subst_drive_are_refused(interpreter_results):
    paths = interpreter_results["_paths"]
    if not paths["launcher"] and not paths["subst"]:
        pytest.skip("neither py.exe nor a free subst drive letter is available")
    if paths["launcher"]:
        row = interpreter_results["renamed_py_launcher"]
        assert row["failure"] and row["failure"].startswith(
            "InterpreterPath is not a virtual environment interpreter"
        ), row["failure"]
        assert row["leases"] == [] and row["python"] is None
    if paths["subst"]:
        row = interpreter_results["subst_drive"]
        assert row["failure"] and row["failure"].startswith(
            "InterpreterPath must be on a local fixed drive, not a mapped or subst letter"
        ), row["failure"]
        assert row["leases"] == [] and row["python"] is None


@pytest.mark.spawns
def test_interpreter_override_still_takes_the_shared_production_lease(interpreter_results):
    production = interpreter_results["_paths"]["production"]
    for name in ("omitted", "valid"):
        row = interpreter_results[name]
        assert row["leases"] == [{"repo_root": production, "workload": "bounded_worktree_test_suite"}]
    # RepoRoot is bound once, before the interpreter is chosen, and the
    # interpreter is chosen before the lease, so no stage root can take it.
    assert interpreter_results["valid"]["repo_root_assignments"] == 1
    assert interpreter_results["valid"]["select_before_lease"] is True
    assert interpreter_results["valid"]["sidecar_before_select"] is True


@pytest.fixture(scope="module")
def verdict_logs(tmp_path_factory) -> dict[str, dict]:
    if os.name != "nt":
        pytest.skip("requires Windows PowerShell")
    root = tmp_path_factory.mktemp("verdict")
    stage_python = _make_venv(root / "stage" / "venv")
    swap_python = _make_venv(root / "swap" / "venv")
    injected_python = _make_venv(
        root / "injected" / "venv", "import sys; sys.version += " + repr(INJECTED_VERSION)
    )
    repo = root / "repo"
    repo.mkdir()
    tip = "ab" * 20
    scenarios = {
        "default": ("", ""),
        "override": (str(stage_python), ""),
        "swapped": (str(swap_python), str(root / "swap" / "venv" / "pyvenv.cfg")),
        "injected": (str(injected_python), ""),
    }
    logs: dict[str, dict] = {}
    for name, (interpreter, mutate) in scenarios.items():
        log = root / f"{name}.log"
        env = os.environ.copy()
        env.update({
            "WEATHER_BOUNDED_SUITE_SCRIPT": str(SCRIPT),
            "WEATHER_VERDICT_LOG": str(log),
            "WEATHER_VERDICT_INTERPRETER": interpreter,
            "WEATHER_VERDICT_MUTATE": mutate,
            "WEATHER_VERDICT_REPO": str(repo),
            "WEATHER_VERDICT_BRANCH": "claude/interp-test",
            "WEATHER_VERDICT_TIP": tip,
        })
        result = _run_powershell(VERDICT_HARNESS, env, timeout=180)
        logs[name] = {
            "returncode": result.returncode,
            "output": result.stdout + result.stderr,
            "path": str(log),
            "lines": log.read_text(encoding="utf-8").splitlines(),
        }
    logs["_root"] = {"root": str(root), "repo": str(repo), "tip": tip}
    return logs


@pytest.mark.spawns
def test_override_run_never_writes_the_merge_eligible_verdict(verdict_logs):
    default = verdict_logs["default"]
    assert default["returncode"] == 0, default["output"]
    assert default["lines"][-1].endswith(
        "  VERDICT: ALL CHUNKS PASSED (2/2); exact tip eligible for separate reviewed merge"
    )
    assert not any("interpreter" in line for line in default["lines"])
    override = verdict_logs["override"]
    assert override["returncode"] == 0, override["output"]
    assert not any("ALL CHUNKS PASSED" in line for line in override["lines"])
    assert any("  interpreter_override {" in line for line in override["lines"])
    assert "interpreter override re-hash matched" in override["lines"][-2]
    assert re.search(
        r"  VERDICT: INTERPRETER QUALIFICATION PASSED \(2/2\); interpreter override "
        r"sha256=[0-9a-f]{64} python=3\.11\.[0-9]+; NOT merge evidence$",
        override["lines"][-1],
    ), override["lines"][-1]
    # An interpreter or pyvenv.cfg swapped after the probe gets no verdict at all.
    swapped = verdict_logs["swapped"]
    assert swapped["returncode"] != 0
    assert "interpreter override changed while the suite was running (pyvenv_cfg_sha256)" in swapped["output"]
    assert not any("VERDICT" in line for line in swapped["lines"])


# Defender N2: forms PowerShell 5.1 -File still binds to -InterpreterPath.
ARGUMENT_FORMS = (
    r' "-InterpreterPath" C:\stage\venv\Scripts\python.exe',
    r" '-InterpreterPath' C:\stage\venv\Scripts\python.exe",
    r' "-InterpreterPath:C:\stage\venv\Scripts\python.exe"',
    r' -WorktreeRoot "C:\wt\x"-InterpreterPath C:\stage\venv\Scripts\python.exe',
    " \u2013InterpreterPath C:\\stage\\venv\\Scripts\\python.exe",
    " \u2014InterpreterPath C:\\stage\\venv\\Scripts\\python.exe",
    " \u2015InterpreterPath C:\\stage\\venv\\Scripts\\python.exe",
    " \u2013Interp:C:\\stage\\venv\\Scripts\\python.exe",
)


@pytest.mark.spawns
def test_every_merge_evidence_reader_refuses_an_override_log(verdict_logs):
    meta = verdict_logs["_root"]
    root = Path(meta["root"])
    default_log = verdict_logs["default"]["path"]
    override_log = verdict_logs["override"]["path"]
    # Forgeries isolate each suite-gate layer: the verdict alone (receipt line
    # removed), and a merge-eligible log carrying an interpreter_override line.
    verdict_only = root / "override-verdict-only.log"
    verdict_only.write_text("\n".join(
        line for line in verdict_logs["override"]["lines"] if "interpreter_override {" not in line
    ) + "\n", encoding="utf-8")
    forged = root / "forged-receipt.log"
    default_lines = verdict_logs["default"]["lines"]
    forged.write_text("\n".join(
        default_lines[:2] + [default_lines[1][:21] + 'interpreter_override {"interpreter_path":"x"}']
        + default_lines[2:]
    ) + "\n", encoding="utf-8")
    # The pre-fix receipt (raw sys.version) carrying the merge phrase, and a
    # default log whose verdict is no longer the final line.
    receipt_injected = root / "override-receipt-injected.log"
    receipt_injected.write_text("\n".join(
        re.sub(r'"python_version":"[^"]*"', '"python_version":"3.11.9' + INJECTED_VERSION + '"', line)
        for line in verdict_logs["override"]["lines"]
    ) + "\n", encoding="utf-8")
    assert INJECTED_VERSION in receipt_injected.read_text(encoding="utf-8")
    trailing = root / "default-trailing.log"
    trailing.write_text("\n".join(default_lines + [default_lines[-1][:21] + "trailing line"]) + "\n",
                        encoding="utf-8")
    # A path that merely contains "interpreter" (like this branch's worktree) is not a parameter name.
    named_dir = root / "bounded-suite-interpreter-20261009"
    named_dir.mkdir()
    named_log = named_dir / "suite.log"
    named_log.write_bytes(Path(default_log).read_bytes())
    injected_log = verdict_logs["injected"]["path"]
    merge_stub = root / "quiet_merge_stub.ps1"
    merge_stub.write_text("Write-Output 'QUIET MERGE STUB INVOKED'\nexit 0\n", encoding="utf-8")
    suite_args = (
        r"-NoProfile -File C:\stub\scripts\ops\bounded_worktree_test_suite.ps1 "
        f"-ExpectedTip {meta['tip']} -BranchRef claude/interp-test -LogPath \"{{log}}\""
    )
    cases = [
        ("contract_default", "contract", default_log, ""),
        ("contract_override", "contract", override_log, ""),
        ("bundle_default", "bundle", default_log, ""),
        ("bundle_override", "bundle", override_log, ""),
        ("gate_default", "gate", default_log, ""),
        ("gate_override", "gate", override_log, ""),
        ("gate_verdict_only", "gate", str(verdict_only), ""),
        ("gate_forged_receipt", "gate", str(forged), ""),
        ("gate_interpreter_argument", "gate", default_log,
         r" -InterpreterPath C:\stage\venv\Scripts\python.exe"),
        ("gate_interpreter_prefix", "gate", default_log, r" -Interp:C:\stage\venv\Scripts\python.exe"),
        ("contract_injected", "contract", injected_log, ""),
        ("bundle_injected", "bundle", injected_log, ""),
        ("bundle_receipt_injected", "bundle", str(receipt_injected), ""),
        ("bundle_forged_receipt", "bundle", str(forged), ""),
        ("bundle_trailing_line", "bundle", str(trailing), ""),
        ("gate_injected", "gate", injected_log, ""),
        ("gate_named_path", "gate", str(named_log),
         r" -WorktreeRoot C:\wt\bounded-suite-interpreter-20261009"),
        *[(f"gate_argument_{index}", "gate", default_log, form) for index, form in enumerate(ARGUMENT_FORMS)],
    ]
    payload = [
        {"name": name, "reader": reader, "log": log,
         "arguments": suite_args.replace("{log}", log) + extra,
         "bundle": str(root / f"{name}.bundle")}
        for name, reader, log, extra in cases
    ]
    cases_path = root / "reader-cases.json"
    cases_path.write_text(json.dumps(payload), encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "WEATHER_READER_CASES": str(cases_path),
        "WEATHER_OPS": str(SCRIPT.parent),
        "WEATHER_READER_TIP": meta["tip"],
        "WEATHER_READER_REPO": meta["repo"],
        "WEATHER_READER_MERGE_STUB": str(merge_stub),
    })
    result = _run_powershell(READERS_HARNESS, env, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = {row["name"]: row["outcome"] for row in json.loads(result.stdout)}
    # Controls: the same harness accepts the default (production venv) log.
    assert outcome["contract_default"] == "ACCEPTED 2", outcome["contract_default"]
    assert outcome["bundle_default"].endswith(
        "PASS: exact-tip source bundle and manifest created"
    ), outcome["bundle_default"]
    assert outcome["gate_default"].endswith("QUIET MERGE STUB INVOKED"), outcome["gate_default"]
    # integration_attempt_contract.ps1 Assert-WeatherIntegrationFullSuiteVerdict.
    assert outcome["contract_override"] == "Full suite log is missing its exact PASS verdict."
    # package_exact_tip_bundle.ps1: receipt-line refusal, then the anchored last-line verdict.
    assert outcome["bundle_override"] == "latest suite log is an interpreter-override run, not merge evidence"
    assert not (root / "bundle_override.bundle").exists()
    # suite_gated_quiet_merge.ps1: receipt-line refusal, anchored verdict regex,
    # and the -InterpreterPath action-argument refusal.
    for name in ("gate_override", "gate_forged_receipt"):
        assert outcome[name] == (
            "SUITE GATE REFUSED: suite log is an interpreter-override run, not merge evidence"
        ), outcome[name]
    assert outcome["gate_verdict_only"] == (
        "SUITE GATE REFUSED: suite log does not end in the exact full-suite pass verdict"
    ), outcome["gate_verdict_only"]
    # Defender N1: the stage interpreter cannot talk its way into merge evidence.
    assert outcome["contract_injected"] == "Full suite log is missing its exact PASS verdict."
    for name in ("bundle_injected", "bundle_receipt_injected", "bundle_forged_receipt"):
        assert outcome[name] == "latest suite log is an interpreter-override run, not merge evidence", (
            name, outcome[name]
        )
    assert outcome["bundle_trailing_line"] == "latest suite log has no full-suite PASS verdict"
    for name in ("bundle_injected", "bundle_receipt_injected", "bundle_forged_receipt", "bundle_trailing_line"):
        assert not (root / f"{name}.bundle").exists()
    assert outcome["gate_injected"] == (
        "SUITE GATE REFUSED: suite log is an interpreter-override run, not merge evidence"
    ), outcome["gate_injected"]
    assert outcome["gate_named_path"].endswith("QUIET MERGE STUB INVOKED"), outcome["gate_named_path"]
    argument_names = [f"gate_argument_{index}" for index in range(len(ARGUMENT_FORMS))]
    for name in ("gate_interpreter_argument", "gate_interpreter_prefix", *argument_names):
        assert outcome[name] == (
            "SUITE GATE REFUSED: suite task action passes -InterpreterPath; "
            "an interpreter qualification run is not merge evidence"
        ), outcome[name]
