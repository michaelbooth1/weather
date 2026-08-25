import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "bounded_worktree_test_suite.ps1"
JOB_HELPER = REPO_ROOT / "scripts" / "ops" / "windows_kill_on_close_job.ps1"
REMOTE_GIT = REPO_ROOT / "scripts" / "ops" / "integration_attempt_remote_git.ps1"
QUIET_MERGE = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"
ATTEMPT_CREATOR = REPO_ROOT / "scripts" / "ops" / "new_integration_attempt.ps1"
ATTEMPT_CONTRACT = (
    REPO_ROOT / "scripts" / "ops" / "integration_attempt_contract.ps1"
)


def test_bounded_suite_is_fail_closed_and_non_mutating():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "00:30-09:00 heavy-work window" in text
    assert "$localMinute -lt 30" in text
    assert "$localMinute -ge (9 * 60)" in text
    assert "$hardStop = $localNow.Date.AddHours(9)" in text
    assert "[int]$MaxRuntimeSeconds = 5400" in text
    assert "$runtimeDeadline = $localNow.AddSeconds($MaxRuntimeSeconds)" in text
    assert "$runtimeStopwatch = [Diagnostics.Stopwatch]::StartNew()" in text
    assert "runtime_clock=monotonic_stopwatch" in text
    assert "function Test-SuiteRuntimeCeilingReached" in text
    assert "killing its complete child tree" in text
    assert "ExpectedTip" in text
    assert 'Arguments @("worktree", "list", "--porcelain")' in text
    assert '@("status", "--porcelain=v1", "--untracked-files=all")' in text
    assert "suite worktree is dirty" in text
    assert '@("ls-files", "--", "tests")' in text
    assert "Get-ChildItem -LiteralPath $testRoot" not in text
    assert "$env:PYTHONPATH = @(" in text
    assert "$WorktreeRoot," in text
    assert '(Join-Path $WorktreeRoot "src")' in text
    assert "pythonpath_worktree_root=true" in text
    assert '"PYTHONPYCACHEPREFIX"' in text
    assert '"PYTHONDONTWRITEBYTECODE"' in text
    assert '$env:PYTHONPYCACHEPREFIX = $pythonCacheRoot' in text
    assert '$env:PYTHONDONTWRITEBYTECODE = "1"' in text
    assert "function Get-SuiteCanonicalSystemTempRoot" in text
    assert "function Assert-SuiteFrozenSystemTempRoot" in text
    assert '$env:TMPDIR = $suiteSystemTempRoot' in text
    assert 'Name = "TMPDIR"' in text
    assert "Value = $previousTmpDir" in text
    assert '"WEATHER_INTEGRATION_TEST_OFFLINE"' in text
    assert '$env:WEATHER_INTEGRATION_TEST_OFFLINE = "1"' in text
    assert '"GIT_ALLOW_PROTOCOL"' in text
    assert 'GIT_ALLOW_PROTOCOL = "file"' in text
    assert "Enter-SuiteQualifiedPythonGitEnvironment" in text
    assert '"GIT_TERMINAL_PROMPT"' in text
    assert 'GIT_TERMINAL_PROMPT = "0"' in text
    assert "Exit-SuiteQualifiedPythonGitEnvironment" in text
    assert '"WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"' in text
    assert "$env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT = $RepoRoot" in text
    assert 'Name = "PYTHONPYCACHEPREFIX"' in text
    assert "Value = $previousPycachePrefix" in text
    assert 'Name = "PYTHONDONTWRITEBYTECODE"' in text
    assert "Value = $previousDontWriteBytecode" in text
    for name, value, previous in (
        ("PYTHONHASHSEED", "0", "$previousPythonHashSeed"),
        ("PYTHONUTF8", "1", "$previousPythonUtf8"),
        ("PYTHONIOENCODING", "utf-8", "$previousPythonIoEncoding"),
    ):
        assert f'"{name}"' in text
        assert f'$env:{name} = "{value}"' in text
        assert previous in text
    assert 'Name = "WEATHER_INTEGRATION_TEST_OFFLINE"' in text
    assert "Value = $previousIntegrationTestOffline" in text
    assert "Value = $previousGitAllowProtocol" in text
    assert "Value = $previousGitTerminalPrompt" in text
    assert 'Name = "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"' in text
    assert "Value = $previousIntegrationTestProductionRoot" in text
    for control, value, previous in (
        (
            "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT",
            "$WorktreeRoot",
            "$previousIntegrationTestCandidateRoot",
        ),
        (
            "WEATHER_INTEGRATION_TEST_SECRET_POLICY",
            '"conservative_v1"',
            "$previousIntegrationTestSecretPolicy",
        ),
        (
            "WEATHER_INTEGRATION_TEST_TEMP_POLICY",
            '"system_temp_unique_v1"',
            "$previousIntegrationTestTempPolicy",
        ),
    ):
        assert f'"{control}"' in text
        assert value in text
        assert previous in text
    assert '"WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT"' in text
    assert 'integration_test_allowed_write_root=none' in text
    assert "$previousIntegrationTestAllowedWriteRoot" in text
    assert "Get-SuiteSecretBearingEnvironmentNames" in text
    assert "secret_environment_scrubbed=true" in text
    assert "secret_environment_count=0" in text
    assert '"secret_environment_count": len(remaining_secret_names)' in text
    for field in ('"temp"', '"tmp"', '"tmpdir"'):
        assert field in text
    assert "Assert-SuitePythonCacheRoot" in text
    assert "Remove-SuiteOwnedPythonCacheRoot" in text
    assert "refusing to clean nonempty or reparse-point Python cache root" in text
    assert "$pendingDirectories = [Collections.Generic.Stack[string]]::new()" in text
    cleanup_start = text.index("function Remove-SuiteOwnedPytestTempPath")
    cleanup_end = text.index("function Remove-SuitePytestTempRoot", cleanup_start)
    cleanup = text[cleanup_start:cleanup_end]
    assert "[IO.SearchOption]::AllDirectories" not in cleanup
    assert cleanup.index("[IO.FileAttributes]::ReparsePoint") < cleanup.index(
        "$pendingDirectories.Push([string]$item.FullName)"
    )
    assert "Assert-NoIgnoredPythonImportArtifacts" in text
    assert "Assert-WeatherIntegrationRegularPathAncestry" in text
    assert "python_executable_sha256=" in text
    assert "handles_retained=true" in text
    assert text.count("[IO.Path]::GetTempPath()") == 1
    assert 'foreach ($name in @("TEMP", "TMP"))' in text
    assert '"$Phase requires ambient TMPDIR to equal the frozen system temp"' in text
    for protected_root in ("$RepoRoot", "$WorktreeRoot", "$evidenceRoot"):
        assert protected_root in text[
            text.index("function Assert-SuiteFrozenSystemTempRoot") :
            text.index("function Open-SuiteRetainedLog")
        ]
    frozen_entry = text.index("$suiteSystemTempRoot = Get-SuiteCanonicalSystemTempRoot")
    first_temp_create = min(
        text.index("$suiteChildOutputRoot = New-SuiteChildOutputRoot"),
        text.index("$suitePytestTempRoot = New-SuitePytestTempRoot"),
        text.index("[void][IO.Directory]::CreateDirectory($pythonCacheRoot)"),
    )
    assert frozen_entry < first_temp_create
    entry_admission = text.index(
        'Assert-HostAdmission -CommitCeiling $StartCommitPercent -Phase "entry"'
    )
    tracked_pre = text.index(
        "$trackedWorktreePre = Get-SuiteTrackedWorktreeFingerprint"
    )
    python_environment_pre = text.index(
        "$pythonEnvironmentPre = Get-SuitePythonEnvironmentFingerprint"
    )
    assert entry_admission < tracked_pre < python_environment_pre
    for native_shadow in (
        '".py"',
        '".pyi"',
        '".pyc"',
        '".pyo"',
        '".pyd"',
        '".so"',
        '".dll"',
        '".dylib"',
        "conftest.py",
        "pytest.ini",
        "pyproject.toml",
        "tox.ini",
        "setup.cfg",
        "sitecustomize.py",
    ):
        assert native_shadow in text
    assert "AdditionalPythonPath" in text
    assert "$additionalPythonRoots" in text
    assert "[IO.Path]::PathSeparator" in text
    assert "RequireLiveSdkContract" in text
    assert '$env:WEATHER_REQUIRE_LIVE_SDK_CONTRACT = "1"' in text
    assert "$previousLiveSdkRequirement" in text
    assert "Set-Location -LiteralPath $WorktreeRoot" in text
    assert "Set-Location -LiteralPath $previousLocation" in text
    assert "Get-CaptureRecoveryState" in text
    assert "integration_attempt_quiet_merge_preflight.ps1" in text
    assert "Assert-WeatherIntegrationQuietMergePreconditions" in text
    assert "weather.operations.capture_recovery_check" in text
    assert '$env:PYTHONPATH = Join-Path $RepoRoot "src"' in text
    assert "$captureRecovery.Payload.ok -ne $true" in text
    assert "$captureRows.Count -ne 3" in text
    assert "Get-HealthyCaptureWorkerCount" not in text
    assert "Get-Process -Id $pidValue" not in text
    assert 'Status = "loop_status.json"' not in text
    assert "Get-CommitPercent" in text
    assert "Start-WeatherProcessInJob" in text
    assert "New-WeatherKillOnCloseJob" in text
    assert "--junitxml" in text
    assert '"--basetemp", $pytestTempPath' in text
    assert "New-SuitePytestTempRoot" in text
    assert "canonical 50-GiB free-space floor" in text
    assert "53687091200" in text
    for volume_role in (
        "worktree",
        "production_data",
        "evidence_log",
        "pytest_temp",
        "system_temp",
    ):
        assert f"{volume_role} =" in text
    assert "$volumeRoot = [IO.Path]::GetPathRoot($path)" in text
    assert "VERDICT: ALL CHUNKS PASSED" in text
    assert "IntegrationPreflight" in text
    assert "test_schema_registry.py" in text
    assert "test_ci_workflow_contract.py" in text
    assert "test_offline_test_boundary.py" in text
    for hardening_ratchet in (
        "test_integration_attempt_preparation_scripts.py",
        "test_one_shot_readiness_script.py",
        "test_one_shot_registry_scripts.py",
        "test_status_script.py",
    ):
        assert hardening_ratchet in text
    assert "VERDICT: INTEGRATION PREFLIGHT PASSED" in text
    assert "[Globalization.CultureInfo]::InvariantCulture" in text
    assert "function Open-SuiteRetainedLog" in text
    assert "[IO.FileMode]::CreateNew" in text
    assert "[IO.FileShare]::Read" in text
    assert "function Write-SuiteRetainedSidecar" in text
    assert "function Write-SuiteRetainedByteSidecar" in text
    assert "Add-Content" not in text
    assert "[IO.File]::WriteAllText" not in text
    assert "git merge" not in text
    assert "git push" not in text
    assert "git checkout" not in text
    assert "Start-ScheduledTask" not in text
    assert "Register-ScheduledTask" not in text


def test_bounded_suite_capture_admission_is_pid_reuse_resistant():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    start = text.index("function Get-CaptureRecoveryState")
    end = text.index('Write-SuiteLog "=== bounded worktree suite starting ==="')
    admission = text[start:end]

    assert "weather.operations.capture_recovery_check" in admission
    assert '"--repo-root", $RepoRoot, "--json"' in admission
    assert "$captureProcess.Stdout" in admission
    assert "$captureProcess.StdoutSha256" in admission
    assert "write_json_atomic" not in admission
    assert "$captureJsonPath" not in admission
    assert "Invoke-SuitePythonChild" in admission
    assert '$env:PYTHONPATH = Join-Path $RepoRoot "src"' in admission
    assert "$capturePreviousPythonPath" in admission
    assert "canonical capture recovery returned no JSON object" in admission
    assert "$null -eq $capturePayload" in admission
    assert '"capture_recovery_check_v1"' in admission
    assert "canonical capture recovery JSON has the wrong object shape" in admission
    assert "canonical capture recovery JSON has the wrong schema" in admission
    assert "canonical capture recovery JSON is bound to a different repo_root" in admission
    assert '"-m", "weather.operations.capture_recovery_check"' in admission
    assert "canonical capture recovery pre-child production tip" in admission
    assert "canonical capture recovery post-child production tip" in admission
    assert "canonical capture recovery execution identity is not production-bound" in admission
    assert "src/weather/operations/capture_recovery_check.py" in admission
    assert "'^[0-9a-f]{16}$'" in admission
    assert "canonical capture recovery JSON has the wrong worker shape" in admission
    assert 'PSObject.Properties["recorded_source_fingerprint"]' in admission
    assert 'PSObject.Properties["current_source_fingerprint"]' in admission
    assert 'PSObject.Properties["runtime_identity_matches_current"]' in admission
    assert "recorded_source_fingerprint -cne" in admission
    assert '"snapshot_tracker", "market_microstructure", "observation_trigger"' in admission
    assert "$captureRecovery.ExitCode -ne 0" in admission
    assert "$captureRecovery.Payload.ok -ne $true" in admission
    assert "$captureRows.Count -ne 3" in admission
    assert "Get-Process" not in admission
    assert "last_heartbeat" not in admission


def test_bounded_suite_refuses_ambient_offline_and_production_root_controls():
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'bounded suite did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Assert-SuiteNoAmbientControls'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing ambient-control guard' }
Invoke-Expression $functionAst.Extent.Text
$controls = @{
    WEATHER_INTEGRATION_TEST_OFFLINE = '1'
    WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT = 'C:\forged-production-root'
    WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT = 'C:\forged-evidence-root'
    WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT = 'C:\forged-write-root'
    WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT = 'C:\forged-candidate-root'
    WEATHER_INTEGRATION_TEST_SECRET_POLICY = 'forged'
    WEATHER_INTEGRATION_TEST_TEMP_POLICY = 'forged'
    PYTHONHASHSEED = 'forged'
    PYTHONUTF8 = '0'
    PYTHONIOENCODING = 'utf-16'
    GIT_ALLOW_PROTOCOL = 'https:file'
    GIT_TERMINAL_PROMPT = '1'
    GIT_CONFIG_NOSYSTEM = '0'
    GIT_CONFIG_SYSTEM = 'C:\forged-system.gitconfig'
    GIT_CONFIG_GLOBAL = 'C:\forged-global.gitconfig'
    GIT_CONFIG_COUNT = '1'
    GIT_ATTR_NOSYSTEM = '0'
    GIT_PROTOCOL_FROM_USER = '1'
    GIT_OPTIONAL_LOCKS = '1'
    GIT_CONFIG_PARAMETERS = "'protocol.allow=always'"
    GIT_DIR = 'C:\forged-git-dir'
    GIT_WORK_TREE = 'C:\forged-worktree'
    GIT_INDEX_FILE = 'C:\forged-index'
    GIT_OBJECT_DIRECTORY = 'C:\forged-objects'
    GIT_ALTERNATE_OBJECT_DIRECTORIES = 'C:\forged-alternates'
    GIT_COMMON_DIR = 'C:\forged-common'
    GIT_NAMESPACE = 'forged'
    GIT_CEILING_DIRECTORIES = 'C:\'
    GIT_DISCOVERY_ACROSS_FILESYSTEM = '1'
    GIT_EXEC_PATH = 'C:\forged-exec'
    GIT_TEMPLATE_DIR = 'C:\forged-template'
    WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE = '1'
}
foreach ($name in $controls.Keys) {
    $previous = [Environment]::GetEnvironmentVariable($name, 'Process')
    try {
        [Environment]::SetEnvironmentVariable($name, $controls[$name], 'Process')
        $blocked = $false
        try { Assert-SuiteNoAmbientControls -Names @($name) }
        catch { $blocked = $_.Exception.Message -like '*Ambient Python/test controls*' }
        if (-not $blocked) { throw "ambient control was accepted: $name" }
    }
    finally { [Environment]::SetEnvironmentVariable($name, $previous, 'Process') }
}
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_every_python_child_is_job_contained_file_backed_and_output_bounded():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    helper_start = text.index("function Invoke-SuitePythonChild")
    helper_end = text.index("function Assert-NoIgnoredPythonImportArtifacts")
    helper = text[helper_start:helper_end]

    assert "Start-WeatherProcessInJobWithRedirectedOutput" in helper
    assert "New-WeatherKillOnCloseJob" in helper
    assert helper.index("New-WeatherKillOnCloseJob") < helper.index(
        "Start-WeatherProcessInJobWithRedirectedOutput"
    )
    assert "WaitForExit(200)" in helper
    assert "1048576" in helper
    assert "$hardStop" in helper
    assert "Test-SuiteRuntimeCeilingReached" in helper
    assert "$MaxOutputBytes" in helper
    assert "ReadStandardOutputBytes" in helper
    assert "ReadStandardErrorBytes" in helper
    assert "TerminateAndWaitForEmpty(5000)" in helper
    assert helper.index("TerminateAndWaitForEmpty(5000)") < helper.index(
        "ReadStandardOutputBytes"
    )
    assert "New-SuiteUtf8Snapshot" in helper
    assert "Write-SuiteRetainedByteSidecar" in helper
    assert "python-diagnostic" in helper
    assert "StdoutPath" in helper
    assert "StderrPath" in helper
    assert "Remove-SuiteOwnedPythonChildOutput" in helper
    assert "& $python" not in text
    assert text.count("Invoke-SuitePythonChild `") == 5
    assert "Start-WeatherProcessInJob `" not in text


def test_python_child_bootstrap_retains_reviewed_pth_and_frozen_tools():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    contract = ATTEMPT_CONTRACT.read_text(
        encoding="utf-8-sig"
    )
    pth_start = text.index("function Open-SuiteQualifiedPthBootstrap")
    pth_end = text.index("function Assert-SuiteQualifiedPthBootstrapUnchanged")
    pth = text[pth_start:pth_end]
    child_start = text.index("function Invoke-SuitePythonChild")
    child_end = text.index("function Assert-NoIgnoredPythonImportArtifacts")
    child = text[child_start:child_end]

    assert "exactly two reviewed .pth files" in pth
    assert "distutils-precedence.pth" in pth
    assert "__editable__\\.weather_market-" in pth
    assert "editable_exact_production_src" in pth
    assert "distutils_precedence_guarded" in pth
    assert "$suiteEvidenceReadStreams.Add($snapshot.Stream)" in pth
    assert "Open-SuiteBoundedFileSnapshot" in pth
    assert "[IO.FileShare]::Read" in text
    assert "Assert-SuiteQualifiedPthBootstrapUnchanged -Phase $Phase" in child
    assert child.index("Assert-SuiteQualifiedPthBootstrapUnchanged") < child.index(
        "Start-WeatherProcessInJobWithRedirectedOutput"
    )
    assert '$env:SETUPTOOLS_USE_DISTUTILS = "stdlib"' in text
    assert 'Name = "SETUPTOOLS_USE_DISTUTILS"' in text
    assert "setuptools_use_distutils" in contract
    assert 'add_runtime(executable.with_name("pythonw.exe"), "launcher")' in text
    assert 'kind -ceq "launcher"' in contract
    for control in (
        "WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE",
        "WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE",
        "WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE",
    ):
        assert control in text
        assert control in contract
    assert text.index("$suitePthBootstrap = Open-SuiteQualifiedPthBootstrap") < (
        text.index("$importProbeProcess = Invoke-SuitePythonChild")
    )
    assert 'Join-Path $WorktreeRoot "src\\weather\\__init__.py"' in text
    assert "suite imports do not resolve from the exact worktree" in text
    assert text.rindex("Assert-SuiteQualifiedPthBootstrapUnchanged") < text.index(
        "VERDICT: ALL CHUNKS PASSED"
    )


def test_python_child_git_environment_is_scoped_isolated_and_fingerprinted():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    contract = ATTEMPT_CONTRACT.read_text(
        encoding="utf-8-sig"
    )
    child = text[
        text.index("function Invoke-SuitePythonChild") :
        text.index("function Assert-NoIgnoredPythonImportArtifacts")
    ]
    for name in (
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_COUNT",
        "GIT_ATTR_NOSYSTEM",
        "GIT_PROTOCOL_FROM_USER",
        "GIT_OPTIONAL_LOCKS",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
        "GIT_CEILING_DIRECTORIES",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM",
        "GIT_EXEC_PATH",
        "GIT_TEMPLATE_DIR",
    ):
        assert name in text
    for field in (
        "git_config_nosystem",
        "git_config_system",
        "git_config_global",
        "git_config_count",
        "git_attr_nosystem",
        "git_protocol_from_user",
        "git_optional_locks",
        "git_topology_environment_clear",
        "git_topology_environment_count",
    ):
        assert field in text
        assert field in contract
    enter = child.index("Enter-SuiteQualifiedPythonGitEnvironment")
    launch = child.index("Start-WeatherProcessInJobWithRedirectedOutput")
    restore = child.index("Exit-SuiteQualifiedPythonGitEnvironment")
    assert enter < launch < restore
    assert "-PrimaryError $launchFailure" in child
    assert "Assert-SuitePythonGitTopologyClear -Phase $Phase" in child
    assert "git_child_environment_isolated=true" in text
    assert "weather_git_environment_cleanup_failure" in text


def test_evidence_root_and_capture_probe_modes_are_frozen_and_restored():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    contract = ATTEMPT_CONTRACT.read_text(
        encoding="utf-8-sig"
    )
    for name in (
        "WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT",
        "WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE",
    ):
        assert name in text
    assert "bounded suite evidence root" in text
    assert "separate from unique system-temp writes" in text
    assert "integration_test_evidence_root_protected=true" in text
    assert "evidence_root" in contract
    assert "read_only_production_probe" in contract
    capture = text[
        text.index("function Get-CaptureRecoveryState") :
        text.index("function Assert-HostAdmission")
    ]
    assert '$env:WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE = "1"' in capture
    assert "$capturePreviousReadOnlyProductionProbe" in capture
    assert "weather_capture_environment_cleanup_failure" in capture
    assert capture.index(
        '$env:WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE = "1"'
    ) < capture.index("Invoke-SuitePythonChild")


def test_runtime_ceiling_uses_monotonic_elapsed_time_not_wall_clock(tmp_path: Path):
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'bounded suite did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Test-SuiteRuntimeCeilingReached'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'monotonic ceiling helper missing' }
Invoke-Expression $functionAst.Extent.Text
$MaxRuntimeSeconds = 60
$runtimeDeadline = (Get-Date).AddYears(-1)
$runtimeStopwatch = [pscustomobject]@{ Elapsed = [TimeSpan]::FromSeconds(59.999) }
if (Test-SuiteRuntimeCeilingReached) { throw 'monotonic ceiling fired early' }
$runtimeDeadline = (Get-Date).AddYears(1)
$runtimeStopwatch = [pscustomobject]@{ Elapsed = [TimeSpan]::FromSeconds(60) }
if (-not (Test-SuiteRuntimeCeilingReached)) { throw 'monotonic ceiling did not fire' }
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_free_space_gate_uses_the_canonical_fifty_gib_floor_for_all_volumes():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Assert-SuiteRelevantVolumeFreeSpace" in text
    assert "53687091200" in text
    for role in (
        "worktree",
        "production_data",
        "evidence_log",
        "pytest_temp",
        "system_temp",
    ):
        assert f"{role} =" in text
    entry = text.index('Assert-SuiteRelevantVolumeFreeSpace -Phase "entry"')
    pre_fingerprint = text.index(
        "$trackedWorktreePre = Get-SuiteTrackedWorktreeFingerprint"
    )
    first_git = text.index("$worktreeQuery = Invoke-WeatherIntegrationCheckedLocalGit")
    chunk = text.index(
        'Assert-SuiteRelevantVolumeFreeSpace -Phase ("chunk-{0:D3}"'
    )
    child = text.index("$childResult = Invoke-SuitePythonChild", chunk)
    assert entry < first_git < pre_fingerprint
    assert 'Assert-SuiteRelevantVolumeFreeSpace -Phase "post-lease"' in text
    assert chunk < child

    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'bounded suite did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Assert-SuiteMinimumFreeBytes'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'free-space floor helper missing' }
Invoke-Expression $functionAst.Extent.Text
Assert-SuiteMinimumFreeBytes `
    -AvailableBytes 53687091200 -RequiredBytes 53687091200 -Label 'exact floor'
$blocked = $false
try {
    Assert-SuiteMinimumFreeBytes `
        -AvailableBytes 53687091199 -RequiredBytes 53687091200 -Label 'below floor'
}
catch { $blocked = $_.Exception.Message -like '*at least 50 GiB*' }
if (-not $blocked) { throw 'below-floor volume was accepted' }
$wrongFloorBlocked = $false
try {
    Assert-SuiteMinimumFreeBytes `
        -AvailableBytes 53687091200 -RequiredBytes 2147483648 -Label 'wrong floor'
}
catch { $wrongFloorBlocked = $_.Exception.Message -like '*canonical 50-GiB*' }
if (-not $wrongFloorBlocked) { throw 'noncanonical floor was accepted' }
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_exact_import_probe_rejects_ignored_native_shadows_and_uses_exact_init():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    shadow_start = text.index("function Assert-NoIgnoredPythonImportArtifacts")
    shadow_end = text.index("function Get-SuiteJUnitSummary")
    shadow = text[shadow_start:shadow_end]
    assert "ls-files" in shadow
    assert '"--others", "--ignored"' in shadow
    assert '"--exclude-standard"' in shadow
    for import_root in ("app", "src", "tests", "weather", "tools", "scripts"):
        assert f'"{import_root}"' in shadow
    assert '":(glob)$_/**"' in shadow
    assert '":(glob)data/**"' not in shadow
    assert '"data", "venv", ".venv", ".git"' in shadow
    assert '"--others", "--ignored", "--exclude-standard", "-z"' in shadow
    assert '"--others", "--exclude-standard", "-z"' in shadow
    for secret_surface in (".env", ".python-version", ".netrc", "pip.ini", ".pypirc"):
        assert secret_surface in shadow
    assert "ignored/untracked candidate autoload, import, or secret artifacts" in shadow
    assert 'Join-Path $WorktreeRoot "src\\weather\\__init__.py"' in text
    assert "$resolvedImport.Equals(" in text
    assert text.count("Assert-NoIgnoredPythonImportArtifacts") >= 4
    assert "Get-SuiteWorktreeAuthorityTuple" in text
    initial = text.index("Assert-NoIgnoredPythonImportArtifacts", shadow_end)
    final = text.rindex("Assert-NoIgnoredPythonImportArtifacts")
    assert initial < text.index("exact-worktree import probe")
    assert final > text.index("finalDirty")
    assert final < text.index("VERDICT: ALL CHUNKS PASSED")


def test_python_environment_fingerprint_is_contained_strict_and_pre_post_stable():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    start = text.index("function Get-SuitePythonEnvironmentFingerprint")
    end = text.index("function Get-SuiteJUnitSummary")
    fingerprint = text[start:end]

    assert "Invoke-SuitePythonChild" in fingerprint
    assert "python_environment_fingerprint_v2" in fingerprint
    assert "importlib.metadata" in fingerprint
    assert "executable_sha256" in fingerprint
    assert "distribution.files" in fingerprint
    assert 'record_hash.mode != "sha256"' in fingerprint
    assert "bytes do not match RECORD" in fingerprint
    assert "def assert_regular_directory" in fingerprint
    assert '"Python stdlib root"' in fingerprint
    assert 'root.glob("*.dll")' in fingerprint
    assert "crosses a reparse point" in fingerprint
    assert '"runtime_files"' in fingerprint
    assert '"file_count"' in fingerprint
    assert '"total_bytes"' in fingerprint
    assert '"controls":' in fingerprint
    assert "pythonhashseed" in fingerprint
    assert "pythonutf8" in fingerprint
    assert "pythonioencoding" in fingerprint
    assert "production_root" in fingerprint
    assert "git_allow_protocol" in fingerprint
    assert "git_terminal_prompt" in fingerprint
    assert "candidate_root" in fingerprint
    assert "allowed_write_root" in fingerprint
    assert "secret_environment_clear" in fingerprint
    assert "temp_policy" in fingerprint
    assert "ConvertFrom-Json -ErrorAction Stop" in fingerprint
    assert "Get-FileHash" not in fingerprint
    assert "pip install" not in fingerprint.lower()
    pre = text.index('$pythonEnvironmentPre = Get-SuitePythonEnvironmentFingerprint -Phase "pre"')
    import_probe = text.index("exact-worktree import probe")
    final_dirty = text.index("$finalDirtyQuery = Invoke-WeatherIntegrationCheckedLocalGit")
    post = text.index('$pythonEnvironmentPost = Get-SuitePythonEnvironmentFingerprint -Phase "post"')
    stable = text.index('"python_environment stable=true "')
    terminal = text.index("VERDICT: ALL CHUNKS PASSED")
    assert pre < import_probe
    assert final_dirty < post < stable < terminal
    assert "post-fingerprint clean-worktree query" in text[post:stable]
    assert "pre_sha256=$($pythonEnvironmentPre.Sha256)" in text
    assert "post_sha256=$($pythonEnvironmentPost.Sha256)" in text
    assert "$LogPath.python-environment.pre.json" in text
    assert "$LogPath.python-environment.post.json" in text
    assert "files=$($pythonEnvironmentPost.FileCount)" in text
    assert "bytes=$($pythonEnvironmentPost.TotalBytes)" in text


def test_tracked_worktree_content_is_retained_lfs_aware_and_chunk_sandwiched():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    start = text.index("function Get-SuiteTrackedWorktreeFingerprint")
    end = text.index("function Get-SuitePythonEnvironmentFingerprint")
    fingerprint = text[start:end]

    assert "tracked_worktree_content_fingerprint_v1" in fingerprint
    assert '@("ls-files", "--stage", "-z")' in fingerprint
    assert '@("ls-files", "-v", "-z")' in fingerprint
    assert '":(attr:filter=lfs)"' in fingerprint
    assert '@("cat-file", "blob", [string]$stageIdentity.BlobOid)' in fingerprint
    assert '[string]$Matches.flag -cne "H"' in fingerprint
    assert "assume-unchanged, skip-worktree" in fingerprint
    assert "[IO.FileShare]::Read" in fingerprint
    assert "Get-SuiteRetainedStreamSha256" in fingerprint
    assert "$suiteTrackedBaseline.Add" in fingerprint
    assert "LFS worktree bytes do not match the index pointer" in fingerprint
    assert "aggregate bytes exceed the 4-GiB bound" in fingerprint
    assert '"{0}`t{1}`t{2}`t{3}`t{4}`t{5}`t{6}`n"' in fingerprint

    assert "$LogPath.tracked-worktree.pre.json" in text
    assert "$LogPath.tracked-worktree.post.json" in text
    assert '"tracked_worktree phase=pre schema=tracked_worktree_content_fingerprint_v1 "' in text
    assert '"tracked_worktree phase=post schema=tracked_worktree_content_fingerprint_v1 "' in text
    assert '"tracked_worktree stable=true "' in text
    loop = text.index("for ($index = 0; $index -lt $chunks.Count; $index++)")
    pre = text.index('Assert-SuiteWorktreeCheckpoint -Phase ("chunk-{0:D3}-pre"', loop)
    child = text.index("$childResult = Invoke-SuitePythonChild", pre)
    post = text.index(
        'Assert-SuiteWorktreeCheckpoint `\n                -Phase ("chunk-{0:D3}-post"',
        child,
    )
    junit = text.index("$junitSummary = Get-SuiteJUnitSummary", post)
    assert pre < child < post < junit
    assert "$childInvocationFailure = $_" in text[child:post]
    assert "weather_post_child_checkpoint_failure" in text[post:junit]

    remote = REMOTE_GIT.read_text(encoding="utf-8-sig")
    assert '"for-each-ref", "cat-file"' in remote
    assert "git cat-file blob <oid>" in remote
    assert "[int]$MaxOutputBytes = 1048576" in remote


def test_bounded_suite_scrubs_secret_transport_environment_and_owns_temp_state():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    for marker in (
        "PIP_INDEX_URL",
        "POLYMARKET_",
        "POLYMM_",
        "GCM_",
        "HTTP_PROXY",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "GIT_ASKPASS",
        "SSH_AUTH_SOCK",
        "PRIVATE_KEY",
        "CONNECTION_STRING",
        "|URL|URI|DSN|AUTH|COOKIE|KEY|CERT)",
    ):
        assert marker in text
    assert "$secretEnvironmentRestorations.Add" in text
    assert "secret-bearing environment restoration failed" in text
    assert "secret_environment_scrubbed=true" in text
    assert "secret_environment_clear" in text
    assert "WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT" in text
    assert "integration_test_allowed_write_root=none" in text
    assert '"--basetemp", $pytestTempPath' in text
    assert "^chunk-[0-9]{3}-[0-9a-f]{32}$" in text
    assert "pytest temp exceeded its 100000-entry cleanup bound" in text
    assert "pytest temp exceeded its 1-GiB cleanup bound" in text
    assert "Remove-Item -LiteralPath $fullPath -Recurse" in text
    assert "Remove-SuitePytestTempRoot" in text
    scrub = text.index(
        "foreach ($secretName in @(Get-SuiteSecretBearingEnvironmentNames))"
    )
    safe_git = text.index(
        'Assert-WeatherIntegrationSafeGitEnvironment -Phase "bounded suite entry"'
    )
    first_git = text.index("$worktreeQuery = Invoke-WeatherIntegrationCheckedLocalGit")
    assert scrub < safe_git < first_git
    assert text.rindex("foreach ($secretRestoration") > text.index("finally {")


def test_secret_environment_policy_rejects_endpoint_session_and_signing_names():
    env = os.environ.copy()
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    script = r"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'bounded suite did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Test-SuiteSecretBearingEnvironmentName'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'secret policy helper missing' }
Invoke-Expression $functionAst.Extent.Text
foreach ($name in @(
    'SERVICE_URL','SERVICE_URI','DATABASE_DSN','SESSION_AUTH','BROWSER_COOKIE',
    'SIGNING_KEY','CLIENT_CERT','PIP_PROXY','PIP_TRUSTED_HOST',
    'GIT_SSH_VARIANT','git_ssl_custom_channel','GCM_CREDENTIAL_STORE'
)) {
    if (-not (Test-SuiteSecretBearingEnvironmentName -Name $name)) {
        throw "secret/endpoint name was accepted: $name"
    }
}
foreach ($name in @(
    'PATH','TEMP','PYTHONHASHSEED','WEATHER_INTEGRATION_TEST_SECRET_POLICY',
    'PUBLIC_STORAGE_REFERENCE','FUNDER_ADDRESS'
)) {
    if (Test-SuiteSecretBearingEnvironmentName -Name $name) {
        throw "public control was scrubbed: $name"
    }
}
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_git_lfs_configuration_is_exact_complete_and_execution_is_pinned(
    tmp_path: Path,
):
    repo = tmp_path / "lfs-config-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    canonical = {
        "filter.lfs.clean": "git-lfs clean -- %f",
        "filter.lfs.smudge": "git-lfs smudge -- %f",
        "filter.lfs.process": "git-lfs filter-process",
        "filter.lfs.required": "true",
    }
    for key, value in canonical.items():
        subprocess.run(
            ["git", "-C", str(repo), "config", "--local", key, value],
            check=True,
        )

    remote = REMOTE_GIT.read_text(encoding="utf-8-sig")
    for key, value in canonical.items():
        assert f"'{key}' = '{value}'" in remote
    assert "refuses a partial Git LFS filter definition" in remote
    assert "$gitLfsIdentityStream = [IO.File]::Open(" in remote
    assert '"filter.lfs.clean=$quotedGitLfs clean -- %f"' in remote
    assert '"filter.lfs.required=true"' in remote

    env = os.environ.copy()
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["WEATHER_LFS_REPO"] = str(repo)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
function Get-WeatherIntegrationGitLfsExecutablePath {
    param([string]$Phase,[string]$GitExecutable)
    return (Join-Path $PSHOME 'powershell.exe')
}
$result = Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
    -Root $env:WEATHER_LFS_REPO -Label 'LFS behavior probe'
if ([int]$result.LfsFilterEntryCount -ne 4 -or
    [string]::IsNullOrWhiteSpace([string]$result.GitLfsExecutable)) {
    throw 'canonical complete LFS configuration was not accepted'
}
'OK'
"""
    accepted = subprocess.run(
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
        timeout=30,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout.strip() == "OK"

    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "config",
            "--local",
            "filter.lfs.required",
            "false",
        ],
        check=True,
    )
    refused = subprocess.run(
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
        timeout=30,
    )
    assert refused.returncode != 0
    assert "refuses effective Git execution redirect filter.lfs.required" in refused.stderr


def test_toolchain_fingerprint_is_contained_retained_and_pre_post_stable():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    start = text.index("function Get-SuiteIntegrationToolchainFingerprint")
    end = text.index("function Get-SuiteJUnitSummary")
    fingerprint = text[start:end]

    assert "integration_toolchain_fingerprint_v1" in fingerprint
    assert "Get-WeatherIntegrationGitExecutablePath" in fingerprint
    assert "Invoke-WeatherIntegrationBoundedProcess" in fingerprint
    assert '-Arguments @("-c", "core.fsmonitor=false", "--version")' in fingerprint
    assert "Open-SuiteBoundedFileSnapshot" in fingerprint
    assert "gitSha256" in fingerprint
    assert "gitLfsSha256" in fingerprint
    assert "git_lfs" in fingerprint
    assert "Git LFS toolchain version" in fingerprint
    assert "powerShellSha256" in fingerprint
    assert "$PSVersionTable.PSVersion" in fingerprint
    assert "$PSVersionTable.CLRVersion" in fingerprint
    assert "[IntPtr]::Size" in fingerprint
    assert "Get-FileHash" not in fingerprint
    assert "$suiteEvidenceReadStreams.Add($gitSnapshot.Stream)" in fingerprint
    assert "$suiteEvidenceReadStreams.Add($gitLfsSnapshot.Stream)" in fingerprint
    assert "$suiteEvidenceReadStreams.Add($powerShellSnapshot.Stream)" in fingerprint
    assert "-ExpectedExecutableSha256 $gitSha256" in fingerprint
    assert fingerprint.index("$suiteEvidenceReadStreams.Add($gitSnapshot.Stream)") < (
        fingerprint.index("Invoke-WeatherIntegrationBoundedProcess")
    )
    assert "$LogPath.integration-toolchain.pre.json" in text
    assert "$LogPath.integration-toolchain.post.json" in text
    pre = text.index(
        '$toolchainPre = Get-SuiteIntegrationToolchainFingerprint -Phase "pre"'
    )
    python_pre = text.index(
        '$pythonEnvironmentPre = Get-SuitePythonEnvironmentFingerprint -Phase "pre"'
    )
    post = text.index(
        '$toolchainPost = Get-SuiteIntegrationToolchainFingerprint -Phase "post"'
    )
    python_post = text.index(
        '$pythonEnvironmentPost = Get-SuitePythonEnvironmentFingerprint -Phase "post"'
    )
    stable = text.index('"integration_toolchain stable=true "')
    assert pre < python_pre < post < python_post < stable
    assert "pre_sha256=$($toolchainPre.Sha256)" in text
    assert "post_sha256=$($toolchainPost.Sha256)" in text


def test_redirected_job_api_assigns_before_resume_and_bounds_remote_git_output():
    job = JOB_HELPER.read_text(encoding="utf-8-sig")
    remote = REMOTE_GIT.read_text(encoding="utf-8-sig")

    assert "StartAssignedRedirected" in job
    assert "PROC_THREAD_ATTRIBUTE_HANDLE_LIST" in job
    assert "STARTF_USESTDHANDLES" in job
    assert "CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT" in job
    assert '"Weather.Operations.KillOnCloseJobV3" -as [type]' in job
    redirected = job[
        job.index("public RedirectedAssignedProcessV3 StartAssignedRedirected") :
    ]
    assert redirected.index("AssignProcessToJobObject") < redirected.index("ResumeThread")
    assert "GENERIC_READ | GENERIC_WRITE" in redirected
    assert "FILE_SHARE_READ" in redirected
    assert "CREATE_NEW" in redirected
    assert "ReadStandardOutputBytes" in job
    assert "GetStandardOutputLength" in job
    assert "TerminateJobObject" in job
    assert "QueryInformationJobObject" in job
    assert "accounting.ActiveProcesses" in job
    assert "TerminateAndWaitForEmpty" in job
    assert "CloseHandle(drained kill-on-close Job) failed" in job
    assert "CloseHandle(kill-on-close Job) failed" in job
    assert "CloseHandle(retained output) failed" in job
    assert "Start-WeatherProcessInJobWithRedirectedOutput" in job
    assert ". $weatherIntegrationJobHelper" in remote
    assert "Start-WeatherProcessInJobWithRedirectedOutput" in remote
    assert "MaxOutputBytes = 1048576" in remote
    assert "ExpectedExecutableSha256" in remote
    assert "ExecutableSha256 = $executableSha256" in remote
    assert "Assert-WeatherIntegrationRegularPathAncestry" in remote
    assert "retained executable identity" in remote
    assert "GetStandardOutputLength" in remote
    assert "ReadStandardOutputBytes" in remote
    assert "Get-WeatherIntegrationByteSha256 -Bytes $stdoutBytes" in remote
    assert "Get-WeatherIntegrationByteSha256 -Bytes $stderrBytes" in remote
    assert "StdoutSha256 = $stdoutSha256" in remote
    assert "StderrSha256 = $stderrSha256" in remote
    assert "WaitForExit(200)" in remote
    assert "TerminateAndWaitForEmpty(5000)" in remote
    assert remote.index("TerminateAndWaitForEmpty(5000)") < remote.index(
        "ReadStandardOutputBytes"
    )
    assert "Job active-process" in remote
    assert "weather_tree_drain_failure" in remote
    assert "child exited with code $observedChildExitCode" in remote
    assert "post-exit containment or evidence processing failed" in remote
    assert "weather_post_exit_failure" in remote
    assert "weather_tree_drain_failure" in SCRIPT.read_text(encoding="utf-8-sig")
    assert "child exited with code $observedChildExitCode" in SCRIPT.read_text(
        encoding="utf-8-sig"
    )
    assert "Remove-WeatherIntegrationOwnedBoundedOutputRoot" in remote
    assert "ReadToEndAsync" not in remote
    assert "taskkill" not in remote.lower()


def test_job_helper_upgrade_is_not_skipped_when_v2_type_is_preloaded():
    env = os.environ.copy()
    env["WEATHER_JOB_HELPER"] = str(JOB_HELPER)
    script = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
namespace Weather.Operations {
    public sealed class KillOnCloseJobV2 { }
}
'@
. $env:WEATHER_JOB_HELPER
$v3 = 'Weather.Operations.KillOnCloseJobV3' -as [type]
if ($null -eq $v3 -or
    $null -eq $v3.GetMethod('StartAssignedRedirected') -or
    $null -eq $v3.GetMethod('TerminateAndWaitForEmpty')) {
    throw 'V3 Job API was skipped behind a preloaded V2 type'
}
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_remote_git_refuses_ambient_identity_transport_helper_and_trace_controls():
    remote = REMOTE_GIT.read_text(encoding="utf-8-sig")
    quiet = QUIET_MERGE.read_text(encoding="utf-8-sig")

    for control in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_REPLACE_REF_BASE",
        "GIT_SHALLOW_FILE",
        "GIT_CONFIG_PARAMETERS",
        "GIT_EXEC_PATH",
        "GIT_SSL_NO_VERIFY",
        "GIT_SSL_CAINFO",
        "GIT_SSL_CAPATH",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "SSH_ASKPASS_REQUIRE",
        "GIT_PROXY_COMMAND",
        "GIT_SSH_COMMAND",
        "GIT_TRACE",
        "GIT_EXTERNAL_DIFF",
        "GIT_DIFF_OPTS",
        "GIT_PAGER",
        "PAGER",
        "GIT_NO_REPLACE_OBJECTS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "GIT_AUTHOR_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_EDITOR",
        "GIT_SEQUENCE_EDITOR",
        "EDITOR",
        "VISUAL",
    ):
        assert control in remote
    assert "$_ -match '^GCM_'" in remote
    assert "Assert-WeatherIntegrationSafeGitEnvironment" in remote
    assert remote.count("Assert-WeatherIntegrationSafeGitEnvironment -Phase") >= 3
    assert "Get-WeatherIntegrationBlockedGitEnvironmentNames" in remote
    assert "integration_attempt_remote_git.ps1" in quiet
    assert "Assert-WeatherIntegrationSafeGitEnvironment" in quiet
    assert "Invoke-WeatherIntegrationBoundedRemoteGit" in quiet
    assert '"WEATHER_INTEGRATION_TEST_OFFLINE"' in quiet
    assert '"WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"' in quiet
    assert "$DryRun.IsPresent" in quiet
    assert "offline integration qualification refuses every non-DryRun quiet merge" in quiet


def test_checked_local_git_is_absolute_sanitized_and_fail_closed(tmp_path: Path):
    remote = REMOTE_GIT.read_text(encoding="utf-8-sig")
    suite = SCRIPT.read_text(encoding="utf-8-sig")

    local_start = remote.index("function Assert-WeatherIntegrationLocalGitQueryArguments")
    local_end = remote.index("function Invoke-WeatherIntegrationBoundedRemoteGit")
    local = remote[local_start:local_end]
    assert "Assert-WeatherIntegrationSafeGitEnvironment" in local
    assert "Get-WeatherIntegrationGitExecutablePath" in local
    assert "function Get-WeatherIntegrationGitExecutablePath" in remote
    assert "$gitPath = [IO.Path]::GetFullPath" in remote
    assert "Invoke-WeatherIntegrationBoundedProcess" in local
    assert 'GIT_CONFIG_NOSYSTEM = "1"' in local
    assert 'GIT_OPTIONAL_LOCKS = "0"' in local
    assert 'GIT_NO_REPLACE_OBJECTS = "1"' in local
    assert '"core.fsmonitor=false"' in local
    assert '"--no-ext-diff", "--no-textconv"' in local
    assert "$commandName -cnotin $queryCommands" in local
    assert "^--output(?:=|$)" in local
    assert "refuses Git diff output-file redirection" in local
    assert "UseEffectiveConfig" in local
    assert "Assert-WeatherIntegrationSafeRemoteGitConfiguration" in remote
    assert 'GIT_DIR = "NUL"' in remote
    assert "disables repository" in remote
    for protected_config in (
        "http.proxy",
        "http.sslverify",
        "http.sslcainfo",
        "http.sslcert",
        "http.extraheader",
        "core.gitproxy",
        "credential.helper",
        "manager-core",
        "core.hookspath",
        "core.attributesfile",
        r"merge\..*\.driver",
        r"filter\..*\.(clean|smudge|process)",
        r"diff\..*\.(command|textconv)",
        r"submodule\..*\.(url|update|branch|fetchrecursesubmodules)",
        "core.hookspath=nul",
    ):
        assert protected_config in remote.lower()
    assert "Assert-WeatherIntegrationSafeRepositoryGitConfiguration" in quiet
    for query_command in (
        "symbolic-ref",
        "branch",
        "merge-base",
        "diff",
        "ls-tree",
        "check-ref-format",
        "rev-list",
        "for-each-ref",
    ):
        assert f'"{query_command}"' in local
    assert "Invoke-WeatherIntegrationCheckedLocalGit" in suite
    assert "Assert-WeatherIntegrationSafeGitEnvironment -Phase \"bounded suite entry\"" in suite
    assert "& git" not in suite
    assert "$LASTEXITCODE" not in suite

    env = os.environ.copy()
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["WEATHER_LOCAL_GIT_FAILURE_ROOT"] = str(tmp_path)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$unsafeArgumentsBlocked = 0
foreach ($unsafeArguments in @(
    ,@('Config', 'user.name', 'unsafe'),
    ,@('diff', '--output', 'unsafe.txt'),
    ,@('diff', '--OuTpUt=unsafe.txt')
)) {
    try {
        Assert-WeatherIntegrationLocalGitQueryArguments `
            -Arguments $unsafeArguments `
            -Label 'synthetic local Git mutation probe'
    }
    catch { $unsafeArgumentsBlocked++ }
}
if ($unsafeArgumentsBlocked -ne 3) {
    throw 'checked local Git accepted a command-casing or output-file mutation bypass'
}
$statusBlocked = $false
try {
    Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $env:WEATHER_LOCAL_GIT_FAILURE_ROOT `
        -Arguments @('status', '--porcelain=v1') `
        -Label 'synthetic status failure' | Out-Null
}
catch { $statusBlocked = $_.Exception.Message -like '*failed with exit code*' }
$lsFilesBlocked = $false
try {
    Invoke-WeatherIntegrationCheckedLocalGit `
        -Root $env:WEATHER_LOCAL_GIT_FAILURE_ROOT `
        -Arguments @('ls-files', '--', 'tests') `
        -Label 'synthetic ls-files failure' | Out-Null
}
catch { $lsFilesBlocked = $_.Exception.Message -like '*failed with exit code*' }
if (-not $statusBlocked -or -not $lsFilesBlocked) {
    throw 'checked local Git accepted a failed authority query'
}
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_git_executable_resolver_rejects_a_second_distinct_application(
    tmp_path: Path,
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    # Get-Command resolves executable extensions by namespace; the resolver
    # must reject ambiguity before attempting to execute either candidate.
    (first / "git.exe").write_bytes(b"MZ-first")
    (second / "git.exe").write_bytes(b"MZ-second")
    env = os.environ.copy()
    for name in ("GIT_PAGER", "PAGER"):
        env.pop(name, None)
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["PATH"] = os.pathsep.join((str(first), str(second), env.get("PATH", "")))
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$blocked = $false
try { Get-WeatherIntegrationGitExecutablePath -Phase 'ambiguous Git probe' | Out-Null }
catch {
    $blocked = $_.Exception.Message -like '*exactly one distinct regular git.exe*'
}
if (-not $blocked) { throw 'a second git.exe Application path was accepted' }
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_scheduler_mutation_helper_allows_only_in_process_function_mocks():
    remote = REMOTE_GIT.read_text(encoding="utf-8-sig")
    assert "function Assert-WeatherIntegrationSchedulerMutationAllowed" in remote
    for command in (
        "Register-ScheduledTask",
        "Enable-ScheduledTask",
        "Disable-ScheduledTask",
        "Stop-ScheduledTask",
        "Start-ScheduledTask",
        "Unregister-ScheduledTask",
        "Set-ScheduledTask",
    ):
        assert command in remote
    assert "CommandType -cne \"Function\"" in remote
    assert "resolved.ModuleName" in remote
    assert "resolved.Source" in remote

    env = os.environ.copy()
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$previous = $env:WEATHER_INTEGRATION_TEST_OFFLINE
try {
    $env:WEATHER_INTEGRATION_TEST_OFFLINE = '1'
    function Register-ScheduledTask { }
    Assert-WeatherIntegrationSchedulerMutationAllowed `
        -CommandName 'Register-ScheduledTask' -Phase 'synthetic mock'
    Remove-Item Function:\Register-ScheduledTask
    $blocked = $false
    try {
        Assert-WeatherIntegrationSchedulerMutationAllowed `
            -CommandName 'Register-ScheduledTask' -Phase 'synthetic real command'
    }
    catch { $blocked = $_.Exception.Message -like '*refuses actual Scheduler mutation*' }
    if (-not $blocked) { throw 'actual Scheduler mutation command was accepted offline' }
}
finally {
    Remove-Item Function:\Register-ScheduledTask -ErrorAction SilentlyContinue
    $env:WEATHER_INTEGRATION_TEST_OFFLINE = $previous
}
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_remote_git_rejects_effective_proxy_tls_and_credential_redirects(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = os.environ.copy()
    for name in ("GIT_PAGER", "PAGER"):
        env.pop(name, None)
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["WEATHER_REMOTE_CONFIG_ROOT"] = str(repo)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$root = $env:WEATHER_REMOTE_CONFIG_ROOT
$url = 'https://github.com/example/weather.git'
git -C $root config core.hooksPath 'C:\forged-hooks'
if ($LASTEXITCODE -ne 0) { throw 'could not install synthetic hooks redirect' }
$hooksBlocked = $false
try {
    Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
        -Root $root -Label 'synthetic hooks redirect' | Out-Null
}
catch { $hooksBlocked = $_.Exception.Message -like '*core.hookspath*' }
git -C $root config --unset-all core.hooksPath
if ($LASTEXITCODE -ne 0) { throw 'could not remove synthetic hooks redirect' }
git -C $root config filter.forged.process 'forged-filter-process'
if ($LASTEXITCODE -ne 0) { throw 'could not install synthetic process filter' }
$filterBlocked = $false
try {
    Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
        -Root $root -Label 'synthetic process filter' | Out-Null
}
catch { $filterBlocked = $_.Exception.Message -like '*filter.forged.process*' }
git -C $root config --unset-all filter.forged.process
if ($LASTEXITCODE -ne 0) { throw 'could not remove synthetic process filter' }
git -C $root config submodule.forged.url 'https://example.invalid/forged.git'
if ($LASTEXITCODE -ne 0) { throw 'could not install synthetic submodule redirect' }
$submoduleBlocked = $false
try {
    Assert-WeatherIntegrationSafeRepositoryGitConfiguration `
        -Root $root -Label 'synthetic submodule redirect' | Out-Null
}
catch { $submoduleBlocked = $_.Exception.Message -like '*submodule.forged.url*' }
git -C $root config --unset-all submodule.forged.url
if ($LASTEXITCODE -ne 0) { throw 'could not remove synthetic submodule redirect' }
git -C $root config http.proxy 'http://127.0.0.1:9'
if ($LASTEXITCODE -ne 0) { throw 'could not install synthetic proxy' }
$proxyBlocked = $false
try {
    Assert-WeatherIntegrationSafeRemoteGitConfiguration `
        -Root $root -RemoteUrl $url -Label 'synthetic proxy' | Out-Null
}
catch { $proxyBlocked = $_.Exception.Message -like '*http.proxy*' }
git -C $root config --unset-all http.proxy
if ($LASTEXITCODE -ne 0) { throw 'could not remove synthetic proxy' }
git -C $root config http.sslVerify false
if ($LASTEXITCODE -ne 0) { throw 'could not install synthetic TLS override' }
$tlsBlocked = $false
try {
    Assert-WeatherIntegrationSafeRemoteGitConfiguration `
        -Root $root -RemoteUrl $url -Label 'synthetic TLS override' | Out-Null
}
catch { $tlsBlocked = $_.Exception.Message -like '*sslVerify*' }
git -C $root config --unset-all http.sslVerify
if ($LASTEXITCODE -ne 0) { throw 'could not remove synthetic TLS override' }
git -C $root config credential.helper '!forged-helper'
if ($LASTEXITCODE -ne 0) { throw 'could not install synthetic credential helper' }
$credentialBlocked = $false
try {
    Assert-WeatherIntegrationSafeRemoteGitConfiguration `
        -Root $root -RemoteUrl $url -Label 'synthetic credential redirect' | Out-Null
}
catch { $credentialBlocked = $_.Exception.Message -like '*Credential Manager helper*' }
if (-not $hooksBlocked -or -not $filterBlocked -or -not $submoduleBlocked -or
    -not $proxyBlocked -or -not $tlsBlocked -or -not $credentialBlocked) {
    throw 'effective remote transport controls did not fail closed'
}
'OK'
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
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_offline_remote_git_refuses_network_and_allows_explicit_local_remote(
    tmp_path: Path,
):
    remote_text = REMOTE_GIT.read_text(encoding="utf-8-sig")
    bounded_start = remote_text.index("function Invoke-WeatherIntegrationBoundedRemoteGit")
    bounded_end = remote_text.index("function Invoke-WeatherIntegrationCanonicalLsRemote")
    bounded = remote_text[bounded_start:bounded_end]
    assert bounded.index("Assert-WeatherIntegrationOfflineRemoteGitAllowed") < (
        bounded.index("Get-WeatherIntegrationGitExecutablePath")
    )
    assert "Get-WeatherIntegrationOfflineFixtureBoundary" in remote_text
    assert '"WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"' in remote_text
    assert '"WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"' in remote_text
    assert '"WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT"' in remote_text
    assert '"system_temp_unique_v1"' in remote_text
    assert "local fixture repository contains a reparse point" in remote_text
    assert "local fixture repository must be a direct bare repository" in remote_text
    assert "local fixture repository contains an active or ambiguous hook" in remote_text
    assert "immediate pre-launch revalidation" in bounded
    assert bounded.rindex("Assert-WeatherIntegrationOfflineRemoteGitAllowed") < (
        bounded.index("return Invoke-WeatherIntegrationBoundedProcess")
    )

    repo = tmp_path / "repo"
    local_remote = tmp_path / "local.git"
    local_reparse = tmp_path / "local-reparse.git"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "init", "-q", "--bare", str(local_remote)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "remote",
            "add",
            "origin",
            "https://example.invalid/network.git",
        ],
        check=True,
    )
    env = os.environ.copy()
    blocked_ambient = {
        "PAGER",
        "EDITOR",
        "VISUAL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    for name in tuple(env):
        if name.upper().startswith(("GIT_", "GCM_")) or name.upper() in blocked_ambient:
            env.pop(name, None)
    env.update(
        {
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": "NUL",
            "GIT_CONFIG_GLOBAL": "NUL",
            "GIT_CONFIG_COUNT": "0",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["WEATHER_OFFLINE_GIT_ROOT"] = str(repo)
    env["WEATHER_LOCAL_GIT_REMOTE"] = str(local_remote)
    env["WEATHER_LOCAL_GIT_REMOTE_URI"] = local_remote.as_uri()
    env["WEATHER_LOCAL_GIT_REPARSE"] = str(local_reparse)
    env["WEATHER_PROTECTED_GIT_REMOTE"] = str(REPO_ROOT / ".git")
    env["WEATHER_INTEGRATION_TEST_OFFLINE"] = "1"
    env["WEATHER_INTEGRATION_TEST_TEMP_POLICY"] = "system_temp_unique_v1"
    system_temp = str(Path(tempfile.gettempdir()).resolve())
    for name in ("TEMP", "TMP", "TMPDIR"):
        env[name] = system_temp
    for name in (
        "WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT",
        "WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT",
        "WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT",
    ):
        env[name] = str(REPO_ROOT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$directBlocked = $false
try {
    Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $env:WEATHER_OFFLINE_GIT_ROOT `
        -Arguments @('ls-remote', 'https://example.invalid/network.git') `
        -Label 'offline direct network refusal' | Out-Null
}
catch { $directBlocked = $_.Exception.Message -like '*refuses network or ambiguous*' }
$nameBlocked = $false
try {
    Invoke-WeatherIntegrationBoundedRemoteGit `
        -Root $env:WEATHER_OFFLINE_GIT_ROOT `
        -Arguments @('ls-remote', 'origin') `
        -Label 'offline configured network refusal' | Out-Null
}
catch { $nameBlocked = $_.Exception.Message -like '*refuses configured remote*' }
$relativeBlocked = $false
try {
    Assert-WeatherIntegrationOfflineRemoteGitAllowed `
        -Root $env:WEATHER_OFFLINE_GIT_ROOT `
        -Arguments @('ls-remote', '..\local.git') `
        -Label 'offline relative local refusal'
}
catch { $relativeBlocked = $_.Exception.Message -like '*relative local-remote escape*' }
$protectedBlocked = $false
try {
    Assert-WeatherIntegrationOfflineRemoteGitAllowed `
        -Root $env:WEATHER_OFFLINE_GIT_ROOT `
        -Arguments @(
            'push', '--force', $env:WEATHER_PROTECTED_GIT_REMOTE,
            'HEAD:refs/heads/offline-probe'
        ) `
        -Label 'offline protected Git directory refusal'
}
catch { $protectedBlocked = $_.Exception.Message -like '*overlaps a protected*' }
$reparseBlocked = $false
try {
    New-Item -ItemType Junction `
        -Path $env:WEATHER_LOCAL_GIT_REPARSE `
        -Target $env:WEATHER_LOCAL_GIT_REMOTE | Out-Null
    try {
        Assert-WeatherIntegrationOfflineRemoteGitAllowed `
            -Root $env:WEATHER_OFFLINE_GIT_ROOT `
            -Arguments @('ls-remote', $env:WEATHER_LOCAL_GIT_REPARSE) `
            -Label 'offline reparse local refusal'
    }
    catch { $reparseBlocked = $_.Exception.Message -like '*reparse*' }
}
finally {
    if (Test-Path -LiteralPath $env:WEATHER_LOCAL_GIT_REPARSE) {
        Remove-Item -LiteralPath $env:WEATHER_LOCAL_GIT_REPARSE -Force
    }
}
$forceFixtureAccepted = $true
try {
    Assert-WeatherIntegrationOfflineRemoteGitAllowed `
        -Root $env:WEATHER_OFFLINE_GIT_ROOT `
        -Arguments @(
            'push', '--force', $env:WEATHER_LOCAL_GIT_REMOTE,
            'HEAD:refs/heads/offline-probe'
        ) `
        -Label 'offline force-push fixture validation'
}
catch { $forceFixtureAccepted = $false }
$hookBlocked = $false
$activeHook = Join-Path $env:WEATHER_LOCAL_GIT_REMOTE 'hooks\pre-receive'
try {
    [IO.File]::WriteAllText($activeHook, "forbidden`n")
    try {
        Assert-WeatherIntegrationOfflineRemoteGitAllowed `
            -Root $env:WEATHER_OFFLINE_GIT_ROOT `
            -Arguments @(
                'push', '--force', $env:WEATHER_LOCAL_GIT_REMOTE,
                'HEAD:refs/heads/offline-probe'
            ) `
            -Label 'offline active receive-hook refusal'
    }
    catch { $hookBlocked = $_.Exception.Message -like '*active or ambiguous hook*' }
}
finally {
    if (Test-Path -LiteralPath $activeHook -PathType Leaf) {
        Remove-Item -LiteralPath $activeHook -Force
    }
}
$configPath = Join-Path $env:WEATHER_LOCAL_GIT_REMOTE 'config'
$configBytes = [IO.File]::ReadAllBytes($configPath)
$hookPathConfigBlocked = $false
try {
    [IO.File]::AppendAllText(
        $configPath, "`n[core]`n`thooksPath = C:\forged-hooks`n"
    )
    try {
        Assert-WeatherIntegrationOfflineRemoteGitAllowed `
            -Root $env:WEATHER_OFFLINE_GIT_ROOT `
            -Arguments @(
                'push', '--force', $env:WEATHER_LOCAL_GIT_REMOTE,
                'HEAD:refs/heads/offline-probe'
            ) `
            -Label 'offline remote hooksPath refusal'
    }
    catch { $hookPathConfigBlocked = $_.Exception.Message -like '*unsupported core key*' }
}
finally { [IO.File]::WriteAllBytes($configPath, $configBytes) }
$receiveConfigBlocked = $false
try {
    [IO.File]::AppendAllText(
        $configPath, "`n[receive]`n`tprocReceiveRefs = refs/heads`n"
    )
    try {
        Assert-WeatherIntegrationOfflineRemoteGitAllowed `
            -Root $env:WEATHER_OFFLINE_GIT_ROOT `
            -Arguments @(
                'push', '--force', $env:WEATHER_LOCAL_GIT_REMOTE,
                'HEAD:refs/heads/offline-probe'
            ) `
            -Label 'offline remote receive config refusal'
    }
    catch { $receiveConfigBlocked = $_.Exception.Message -like '*non-core section*' }
}
finally { [IO.File]::WriteAllBytes($configPath, $configBytes) }
$local = Invoke-WeatherIntegrationBoundedRemoteGit `
    -Root $env:WEATHER_OFFLINE_GIT_ROOT `
    -Arguments @('ls-remote', $env:WEATHER_LOCAL_GIT_REMOTE) `
    -Label 'offline explicit local allowance'
$fileUri = Invoke-WeatherIntegrationBoundedRemoteGit `
    -Root $env:WEATHER_OFFLINE_GIT_ROOT `
    -Arguments @('ls-remote', $env:WEATHER_LOCAL_GIT_REMOTE_URI) `
    -Label 'offline canonical file URI allowance'
if (-not $directBlocked -or -not $nameBlocked -or -not $relativeBlocked -or
    -not $protectedBlocked -or -not $reparseBlocked -or
    -not $forceFixtureAccepted -or -not $hookBlocked -or
    -not $hookPathConfigBlocked -or -not $receiveConfigBlocked -or
    $local.ExitCode -ne 0 -or
    $fileUri.ExitCode -ne 0) {
    throw 'offline remote-Git boundary failed'
}
'OK'
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
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_remote_git_accepts_only_the_exact_offline_git_control_tuple():
    remote_text = REMOTE_GIT.read_text(encoding="utf-8-sig")
    for name, value in (
        ("GIT_ALLOW_PROTOCOL", "file"),
        ("GIT_TERMINAL_PROMPT", "0"),
        ("GIT_PROTOCOL_FROM_USER", "0"),
        ("GIT_CONFIG_NOSYSTEM", "1"),
        ("GIT_CONFIG_SYSTEM", "NUL"),
        ("GIT_CONFIG_GLOBAL", "NUL"),
        ("GIT_CONFIG_COUNT", "0"),
        ("GIT_ATTR_NOSYSTEM", "1"),
        ("GIT_OPTIONAL_LOCKS", "0"),
    ):
        assert f'{name} = "{value}"' in remote_text

    env = os.environ.copy()
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
foreach ($name in @(Get-WeatherIntegrationBlockedGitEnvironmentNames)) {
    [Environment]::SetEnvironmentVariable($name, $null, 'Process')
}
$env:WEATHER_INTEGRATION_TEST_OFFLINE = '1'
$exact = [ordered]@{
    GIT_ALLOW_PROTOCOL = 'file'
    GIT_TERMINAL_PROMPT = '0'
    GIT_PROTOCOL_FROM_USER = '0'
    GIT_CONFIG_NOSYSTEM = '1'
    GIT_CONFIG_SYSTEM = 'NUL'
    GIT_CONFIG_GLOBAL = 'NUL'
    GIT_CONFIG_COUNT = '0'
    GIT_ATTR_NOSYSTEM = '1'
    GIT_OPTIONAL_LOCKS = '0'
}
foreach ($entry in $exact.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
}
Assert-WeatherIntegrationSafeGitEnvironment -Phase 'exact offline tuple'
$mutations = @(
    [pscustomobject]@{ Name = 'GIT_ALLOW_PROTOCOL'; Value = 'files' },
    [pscustomobject]@{ Name = 'GIT_OPTIONAL_LOCKS'; Value = '1' },
    [pscustomobject]@{ Name = 'GIT_CONFIG_SYSTEM'; Value = 'C:\forged' },
    [pscustomobject]@{ Name = 'GIT_DIR'; Value = 'C:\forged-topology' },
    [pscustomobject]@{ Name = 'GIT_AUTHOR_EMAIL'; Value = 'forged@example.invalid' },
    [pscustomobject]@{ Name = 'GIT_TRACE'; Value = '1' },
    [pscustomobject]@{ Name = 'GIT_ASKPASS'; Value = 'C:\forged-helper.exe' }
)
foreach ($mutation in $mutations) {
    $previous = [Environment]::GetEnvironmentVariable($mutation.Name, 'Process')
    try {
        [Environment]::SetEnvironmentVariable(
            $mutation.Name, $mutation.Value, 'Process'
        )
        $blocked = $false
        try {
            Assert-WeatherIntegrationSafeGitEnvironment `
                -Phase "mutated offline tuple $($mutation.Name)"
        }
        catch { $blocked = $_.Exception.Message -like "*$($mutation.Name)*" }
        if (-not $blocked) {
            throw "mutated offline Git control was accepted: $($mutation.Name)"
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            $mutation.Name, $previous, 'Process'
        )
    }
}
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_remote_git_ambient_exec_path_refusal_precedes_git_launch(tmp_path: Path):
    env = os.environ.copy()
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["WEATHER_REMOTE_TEST_ROOT"] = str(tmp_path)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$previous = $env:GIT_EXEC_PATH
try {
    $env:GIT_EXEC_PATH = 'C:\forged-git-exec-path'
    $originBlocked = $false
    try { Get-WeatherIntegrationCanonicalOriginUrl -Root $env:WEATHER_REMOTE_TEST_ROOT }
    catch { $originBlocked = $_.Exception.Message -like '*refuses ambient Git*GIT_EXEC_PATH*' }
    $remoteBlocked = $false
    try {
        Invoke-WeatherIntegrationBoundedRemoteGit `
            -Root $env:WEATHER_REMOTE_TEST_ROOT `
            -Arguments @('ls-remote', 'https://example.invalid/repo.git') | Out-Null
    }
    catch { $remoteBlocked = $_.Exception.Message -like '*refuses ambient Git*GIT_EXEC_PATH*' }
    if (-not $originBlocked -or -not $remoteBlocked) {
        throw 'ambient GIT_EXEC_PATH reached a Git launch boundary'
    }
    foreach ($control in @(
        'HTTPS_PROXY', 'http_proxy', 'CURL_CA_BUNDLE', 'SSL_CERT_FILE',
        'GCM_CREDENTIAL_STORE', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_DATE',
        'GIT_EDITOR', 'EDITOR'
    )) {
        $oldValue = [Environment]::GetEnvironmentVariable($control, 'Process')
        try {
            [Environment]::SetEnvironmentVariable($control, 'forged', 'Process')
            $controlBlocked = $false
            try { Assert-WeatherIntegrationSafeGitEnvironment -Phase 'ambient probe' }
            catch { $controlBlocked = $_.Exception.Message -like "*$control*" }
            if (-not $controlBlocked) { throw "ambient Git control was accepted: $control" }
        }
        finally {
            [Environment]::SetEnvironmentVariable($control, $oldValue, 'Process')
        }
    }
}
finally { $env:GIT_EXEC_PATH = $previous }
'OK'
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
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_probe_and_junit_hashes_come_from_the_same_retained_bytes_as_parsing():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$captureJsonSha256 = [string]$captureProcess.StdoutSha256" in text
    assert "$importProbeSha256 = [string]$importProbeProcess.StdoutSha256" in text
    junit_start = text.index("function Get-SuiteJUnitSummary")
    junit_end = text.index("function Get-CommitPercent")
    junit = text[junit_start:junit_end]
    assert "Open-SuiteBoundedFileSnapshot" not in junit
    assert "$memory.Write($snapshot.Bytes" in junit
    assert '$summary["sha256"] = $snapshot.Sha256' in junit
    assert "Write-SuiteRetainedByteSidecar" in junit
    assert "-Path $EvidencePath -Bytes $snapshot.Bytes" in junit
    assert "Get-FileHash" not in junit
    assert "Get-FileHash -LiteralPath $junitPath" not in text
    assert '([guid]::NewGuid().ToString("N"))' in text
    assert "unique test-child JUnit path already exists" in text
    junit_path = text.index('$junitEvidencePath = "{0}.{1}.chunk-{2:D3}.xml"')
    junit_start = text.index('"chunk $ordinal/$($chunks.Count) starting "', junit_path)
    assert text.index("Test-Path -LiteralPath $junitEvidencePath", junit_path) < junit_start
    child = text.index("$childResult = Invoke-SuitePythonChild", junit_start)
    held_open = text.index(
        "$junitReadHandle = Open-SuiteBoundedFileReadHandle", child
    )
    checkpoint = text.index(
        'Assert-SuiteWorktreeCheckpoint `\n                -Phase ("chunk-{0:D3}-post"',
        held_open,
    )
    held_read = text.index(
        "$junitSnapshot = Read-SuiteBoundedFileHandleSnapshot", checkpoint
    )
    summary = text.index("$junitSummary = Get-SuiteJUnitSummary", held_read)
    handle_dispose = text.index("$junitReadHandle.Stream.Dispose()", summary)
    assert child < held_open < checkpoint < held_read < summary < handle_dispose
    assert "-Snapshot $junitSnapshot" in text[summary:handle_dispose]
    assert "Remove-SuiteOwnedJUnitTemp -Path $junitTempPath" in text


def test_redirected_job_api_preserves_output_and_kills_on_output_overflow(
    tmp_path: Path,
):
    env = os.environ.copy()
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["WEATHER_REMOTE_TEST_ROOT"] = str(tmp_path)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$powershell = Join-Path $PSHOME 'powershell.exe'
$heldOut = Join-Path $env:WEATHER_REMOTE_TEST_ROOT 'held-stdout.txt'
$heldErr = Join-Path $env:WEATHER_REMOTE_TEST_ROOT 'held-stderr.txt'
$renamedOut = Join-Path $env:WEATHER_REMOTE_TEST_ROOT 'forged-stdout.txt'
$heldJob = New-WeatherKillOnCloseJob
$heldProcess = Start-WeatherProcessInJobWithRedirectedOutput `
    -Job $heldJob `
    -FilePath $powershell `
    -ArgumentString '-NoProfile -NonInteractive -Command "[Console]::Out.Write(''held-output'')"' `
    -WorkingDirectory $env:WEATHER_REMOTE_TEST_ROOT `
    -StandardOutputPath $heldOut `
    -StandardErrorPath $heldErr
if (-not $heldProcess.WaitForExit(5000)) { throw 'held process did not exit' }
$heldJob.TerminateAndWaitForEmpty(5000)
$heldJob = $null
$replacementRefused = $false
try { Move-Item -LiteralPath $heldOut -Destination $renamedOut -ErrorAction Stop }
catch { $replacementRefused = $true }
$heldBytes = $heldProcess.ReadStandardOutputBytes(1024)
if ([Text.Encoding]::UTF8.GetString($heldBytes) -cne 'held-output') {
    throw 'retained stdout bytes changed after child exit'
}
$heldProcess.Dispose()
if (-not $replacementRefused) { throw 'retained stdout path was replaceable' }
foreach ($path in @($heldOut, $heldErr, $renamedOut)) {
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}
$result = Invoke-WeatherIntegrationBoundedProcess `
    -Executable $powershell `
    -Arguments @(
        '-NoProfile', '-NonInteractive', '-Command',
        '[Console]::Out.Write(''bounded-ok''); [Console]::Error.Write(''bounded-warning'')'
    ) `
    -WorkingDirectory $env:WEATHER_REMOTE_TEST_ROOT `
    -TimeoutSeconds 5 `
    -Label 'redirected success'
if ($result.Stdout -notlike '*bounded-ok*' -or
    $result.Stderr -notlike '*bounded-warning*') {
    throw 'redirected output was not preserved'
}
$overflowClosed = $false
try {
    Invoke-WeatherIntegrationBoundedProcess `
        -Executable $powershell `
        -Arguments @(
            '-NoProfile', '-NonInteractive', '-Command',
            '[Console]::Out.Write((''x'' * 4096)); Start-Sleep -Seconds 5'
        ) `
        -WorkingDirectory $env:WEATHER_REMOTE_TEST_ROOT `
        -TimeoutSeconds 5 `
        -MaxOutputBytes 1024 `
        -Label 'redirected overflow' | Out-Null
}
catch {
    $overflowClosed = (
        $_.Exception.Message -like '*exceeded its redirected-output bound*' -and
        $_.Exception.Message -like '*proved its child process tree was terminated*'
    )
}
if (-not $overflowClosed) { throw 'redirected output overflow did not fail closed' }
$timeoutClosed = $false
try {
    Invoke-WeatherIntegrationBoundedProcess `
        -Executable $powershell `
        -Arguments @(
            '-NoProfile', '-NonInteractive', '-Command',
            'Start-Sleep -Seconds 5'
        ) `
        -WorkingDirectory $env:WEATHER_REMOTE_TEST_ROOT `
        -TimeoutSeconds 1 `
        -Label 'redirected timeout' | Out-Null
}
catch {
    $timeoutClosed = (
        $_.Exception.Message -like '*timed out after 1 seconds*' -and
        $_.Exception.Message -like '*active-process count proved*'
    )
}
if (-not $timeoutClosed) { throw 'redirected timeout did not prove Job tree drain' }
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_explicit_job_drain_kills_descendant_before_return(tmp_path: Path):
    ready = tmp_path / "drain-parent-ready.txt"
    delayed_marker = tmp_path / "drain-descendant-escaped.txt"
    descendant = tmp_path / "drain-descendant.ps1"
    descendant.write_text(
        "param([string]$Marker)\n"
        "Start-Sleep -Seconds 4\n"
        "[IO.File]::WriteAllText($Marker, 'escaped')\n",
        encoding="utf-8",
    )
    parent = tmp_path / "drain-parent.ps1"
    parent.write_text(
        "param([string]$Child,[string]$Ready,[string]$Marker)\n"
        "$powershell = Join-Path $PSHOME 'powershell.exe'\n"
        "$arguments = ('-NoProfile -NonInteractive -ExecutionPolicy Bypass "
        "-File \"{0}\" -Marker \"{1}\"' -f $Child,$Marker)\n"
        "Start-Process -FilePath $powershell -ArgumentList $arguments "
        "-WindowStyle Hidden | Out-Null\n"
        "[IO.File]::WriteAllText($Ready, 'ready')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["WEATHER_JOB_HELPER"] = str(JOB_HELPER)
    env["WEATHER_DRAIN_ROOT"] = str(tmp_path)
    env["WEATHER_DRAIN_PARENT"] = str(parent)
    env["WEATHER_DRAIN_DESCENDANT"] = str(descendant)
    env["WEATHER_DRAIN_READY"] = str(ready)
    env["WEATHER_DRAIN_MARKER"] = str(delayed_marker)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_JOB_HELPER
$powershell = Join-Path $PSHOME 'powershell.exe'
$arguments = ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" ' +
    '-Child "{1}" -Ready "{2}" -Marker "{3}"') -f `
    $env:WEATHER_DRAIN_PARENT,$env:WEATHER_DRAIN_DESCENDANT,`
    $env:WEATHER_DRAIN_READY,$env:WEATHER_DRAIN_MARKER
$job = $null
$process = $null
try {
    $job = New-WeatherKillOnCloseJob
    $process = Start-WeatherProcessInJob `
        -Job $job -FilePath $powershell -ArgumentString $arguments `
        -WorkingDirectory $env:WEATHER_DRAIN_ROOT
    if (-not $process.WaitForExit(5000)) { throw 'synthetic parent did not exit' }
    if (-not (Test-Path -LiteralPath $env:WEATHER_DRAIN_READY -PathType Leaf)) {
        throw 'synthetic parent did not launch its descendant'
    }
    $job.TerminateAndWaitForEmpty(5000)
    $job = $null
    Start-Sleep -Seconds 5
    if (Test-Path -LiteralPath $env:WEATHER_DRAIN_MARKER) {
        throw 'Job drain returned while a descendant survived'
    }
}
finally {
    if ($job) { $job.Dispose() }
    if ($process) { $process.Dispose() }
}
'OK'
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
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"


def test_kill_on_close_job_stops_descendant_when_owning_wrapper_is_killed(
    tmp_path: Path,
):
    ready = tmp_path / "descendant-ready.txt"
    delayed_marker = tmp_path / "descendant-escaped.txt"
    child = tmp_path / "delayed-marker-child.ps1"
    child.write_text(
        "param([string]$Ready,[string]$Marker)\n"
        "[IO.File]::WriteAllText($Ready, 'ready')\n"
        "Start-Sleep -Seconds 4\n"
        "[IO.File]::WriteAllText($Marker, 'escaped')\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "job-owning-wrapper.ps1"
    wrapper.write_text(
        "param([string]$Helper,[string]$Child,[string]$Ready,[string]$Marker)\n"
        ". $Helper\n"
        "$powershell = Join-Path $PSHOME 'powershell.exe'\n"
        "$arguments = ('-NoProfile -NonInteractive -File \"{0}\" "
        "-Ready \"{1}\" -Marker \"{2}\"' -f $Child,$Ready,$Marker)\n"
        "$job = New-WeatherKillOnCloseJob\n"
        "$process = Start-WeatherProcessInJob -Job $job -FilePath $powershell "
        "-ArgumentString $arguments -WorkingDirectory (Split-Path -Parent $Child)\n"
        "while (-not $process.HasExited) { Start-Sleep -Milliseconds 200; $process.Refresh() }\n",
        encoding="utf-8",
    )
    owner = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper),
            "-Helper",
            str(JOB_HELPER),
            "-Child",
            str(child),
            "-Ready",
            str(ready),
            "-Marker",
            str(delayed_marker),
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not ready.exists():
            if owner.poll() is not None:
                raise AssertionError("Job-owning wrapper exited before child readiness")
            time.sleep(0.1)
        assert ready.exists(), "Job child did not reach readiness"
        owner.kill()
        owner.wait(timeout=5)
        time.sleep(5)
        assert not delayed_marker.exists()
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)


def test_ignored_import_shadow_guard_rejects_bytecode_and_info_excluded_source(
    tmp_path: Path,
):
    repo = tmp_path / "shadow-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "data").mkdir()
    (repo / "src" / "weather").mkdir(parents=True)
    (repo / ".gitignore").write_text(
        "data/*.py\n*.pyc\n", encoding="utf-8"
    )
    (repo / ".git" / "info" / "exclude").write_text(
        "src/weather/shadow.py\nsitecustomize.py\n", encoding="utf-8"
    )
    env = os.environ.copy()
    for name in ("GIT_PAGER", "PAGER"):
        env.pop(name, None)
    env["WEATHER_BOUNDED_SUITE_SCRIPT"] = str(SCRIPT)
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["WEATHER_SHADOW_REPO"] = str(repo)
    script = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:WEATHER_BOUNDED_SUITE_SCRIPT,
    [ref]$tokens,
    [ref]$errors
)
if (@($errors).Count -ne 0) { throw 'bounded suite did not parse' }
$functionAst = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Assert-NoIgnoredPythonImportArtifacts'
}, $true)) | Select-Object -First 1
if ($null -eq $functionAst) { throw 'missing ignored-shadow guard' }
$splitAst = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Split-SuiteNulRecords'
}, $true)) | Select-Object -First 1
if ($null -eq $splitAst) { throw 'missing NUL-record parser' }
Invoke-Expression $splitAst.Extent.Text
Invoke-Expression $functionAst.Extent.Text
$WorktreeRoot = $env:WEATHER_SHADOW_REPO
Assert-NoIgnoredPythonImportArtifacts
[IO.File]::WriteAllText((Join-Path $WorktreeRoot 'data\evidence.py'), 'not executable')
Assert-NoIgnoredPythonImportArtifacts
[IO.File]::WriteAllBytes(
    (Join-Path $WorktreeRoot 'src\weather\shadow.pyc'),
    [byte[]](1,2,3)
)
$bytecodeBlocked = $false
try { Assert-NoIgnoredPythonImportArtifacts }
catch { $bytecodeBlocked = $_.Exception.Message -like '*autoload, import, or secret artifacts*' }
if (-not $bytecodeBlocked) { throw 'ignored sourceless bytecode was accepted' }
Remove-Item -LiteralPath (Join-Path $WorktreeRoot 'src\weather\shadow.pyc') -Force
[IO.File]::WriteAllText(
    (Join-Path $WorktreeRoot 'src\weather\shadow.py'),
    'shadowed = $true'
)
$sourceBlocked = $false
try { Assert-NoIgnoredPythonImportArtifacts }
catch { $sourceBlocked = $_.Exception.Message -like '*autoload, import, or secret artifacts*' }
if (-not $sourceBlocked) { throw 'info-excluded Python source was accepted' }
Remove-Item -LiteralPath (Join-Path $WorktreeRoot 'src\weather\shadow.py') -Force
[IO.File]::WriteAllText((Join-Path $WorktreeRoot 'sitecustomize.py'), 'shadowed = $true')
$controlBlocked = $false
try { Assert-NoIgnoredPythonImportArtifacts }
catch { $controlBlocked = $_.Exception.Message -like '*autoload, import, or secret artifacts*' }
if (-not $controlBlocked) { throw 'root singleton import control was accepted' }
'OK'
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
    assert result.stdout.strip() == "OK"


def test_bounded_suite_runs_production_preflight_before_capture_checker():
    text = SCRIPT.read_text(encoding="utf-8-sig")
    creator = ATTEMPT_CREATOR.read_text(encoding="utf-8-sig")
    contract = ATTEMPT_CONTRACT.read_text(encoding="utf-8-sig")
    helper = (
        REPO_ROOT
        / "scripts"
        / "ops"
        / "integration_attempt_quiet_merge_preflight.ps1"
    )
    start = text.index("function Assert-HostAdmission")
    end = text.index('Write-SuiteLog "=== bounded worktree suite starting ==="')
    admission = text[start:end]

    assert helper.read_text(encoding="utf-8-sig")
    assert "$quietMergePreflightScript" in text
    assert ". $quietMergePreflightScript" in text
    assert "quiet_merge_preflight = Join-Path $RepoRoot" in creator
    assert (
        "Attempt orchestration file changed after freeze: quiet_merge_preflight"
        in contract
    )
    assert "Assert-WeatherIntegrationQuietMergePreconditions" in admission
    assert admission.index("Assert-WeatherIntegrationQuietMergePreconditions") < (
        admission.index("Get-CaptureRecoveryState")
    )
    assert "quiet_merge_preflight=PASS" in admission


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
$functionAsts = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in @(
            'Open-SuiteRetainedLog',
            'Write-SuiteLog',
            'Write-SuiteRetainedByteSidecar',
            'Write-SuiteRetainedSidecar'
        )
}, $true))
foreach ($name in @(
    'Open-SuiteRetainedLog',
    'Write-SuiteLog',
    'Write-SuiteRetainedByteSidecar',
    'Write-SuiteRetainedSidecar'
)) {
    $functionAst = @($functionAsts | Where-Object Name -eq $name) |
        Select-Object -First 1
    if ($null -eq $functionAst) { throw "missing $name" }
    Invoke-Expression $functionAst.Extent.Text
}
$culture = [Globalization.CultureInfo](Get-Culture).Clone()
$culture.DateTimeFormat.TimeSeparator = '.'
[Threading.Thread]::CurrentThread.CurrentCulture = $culture
$LogPath = $env:WEATHER_BOUNDED_SUITE_LOG
$suiteLogHandle = Open-SuiteRetainedLog -Path $LogPath
$suiteLogWriter = $suiteLogHandle.Writer
$suiteSidecarStreams = [System.Collections.Generic.List[System.IO.FileStream]]::new()
$sidecarPath = "$LogPath.inventory.txt"
try {
    Write-SuiteLog 'VERDICT: culture probe' | Out-Null
    $lineWhileHeld = (Get-Content -LiteralPath $LogPath -Raw).Trim()
    $logReplacementRefused = $false
    try {
        Move-Item -LiteralPath $LogPath -Destination "$LogPath.forged" -ErrorAction Stop
    }
    catch { $logReplacementRefused = $true }
    $logWriteRefused = $false
    try {
        $forged = [IO.File]::Open(
            $LogPath, [IO.FileMode]::Open, [IO.FileAccess]::Write,
            [IO.FileShare]::ReadWrite
        )
        $forged.Dispose()
    }
    catch { $logWriteRefused = $true }
    Write-SuiteRetainedSidecar -Path $sidecarPath -Text "one`n" | Out-Null
    $sidecarReplacementRefused = $false
    try {
        Move-Item -LiteralPath $sidecarPath `
            -Destination "$sidecarPath.forged" -ErrorAction Stop
    }
    catch { $sidecarReplacementRefused = $true }
}
finally {
    foreach ($stream in @($suiteSidecarStreams)) { $stream.Dispose() }
    $suiteLogWriter.Dispose()
    $suiteLogHandle.Stream.Dispose()
}
$existingLogRefused = $false
try { Open-SuiteRetainedLog -Path $LogPath | Out-Null }
catch { $existingLogRefused = $_.Exception.Message -like '*existing log*' }
$existingSidecarRefused = $false
try { Write-SuiteRetainedSidecar -Path $sidecarPath -Text "two`n" | Out-Null }
catch { $existingSidecarRefused = $_.Exception.Message -like '*existing evidence sidecar*' }
[pscustomobject]@{
    errors = @($errors | ForEach-Object { $_.Message })
    line = $lineWhileHeld
    log_replacement_refused = $logReplacementRefused
    log_write_refused = $logWriteRefused
    existing_log_refused = $existingLogRefused
    sidecar_replacement_refused = $sidecarReplacementRefused
    existing_sidecar_refused = $existingSidecarRefused
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
    assert payload["log_replacement_refused"] is True
    assert payload["log_write_refused"] is True
    assert payload["existing_log_refused"] is True
    assert payload["sidecar_replacement_refused"] is True
    assert payload["existing_sidecar_refused"] is True
