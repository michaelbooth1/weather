from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from weather.backtesting.settlement_ledger import fetch_gamma_event
from weather.market import mm_credentials
from weather import integration_test_safety
from weather.market import (
    exchange_economics,
    execution_tape_capture,
    mm_geographic_eligibility,
    mm_user_stream,
)
from weather.market.mm_exchange import RequestsTransport
from weather.market.market_microstructure_capture import ClobClient
from weather.market.mm_official_adapter import fetch_current_positions
from weather.market.mm_official_transport import fetch_wallet_deployed
from weather.operations.location_config_refresh import fetch_gamma_events
from weather.operations import daily_refresh, supervisor, taker_bot_daily_roll
from weather.operations import windows_processes
from weather.operations import market_making_preflight_recovery


ROOT = Path(__file__).resolve().parents[2]
OFFLINE_ENV = "WEATHER_INTEGRATION_TEST_OFFLINE"
OPS_ROOT = ROOT / "scripts" / "ops"
REMOTE_GIT = OPS_ROOT / "integration_attempt_remote_git.ps1"


def _powershell_executable() -> str:
    bound = os.environ.get("WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE")
    if bound and Path(bound).is_file():
        return bound
    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    pytest.skip("PowerShell is unavailable on this test host")


def _powershell(command: str, *, env: dict[str, str] | None = None):
    return subprocess.run(
        [
            _powershell_executable(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_every_operations_scheduler_mutation_has_an_immediately_dominating_guard():
    helper_definition = "function Assert-WeatherIntegrationSchedulerMutationAllowed"
    definitions = [
        path
        for path in OPS_ROOT.glob("*.ps1")
        if helper_definition in path.read_text(encoding="utf-8-sig")
    ]
    assert definitions == [REMOTE_GIT]

    direct_loaders = []
    for path in OPS_ROOT.glob("*.ps1"):
        text = path.read_text(encoding="utf-8-sig")
        if "$schedulerBoundaryScript = Join-Path $PSScriptRoot" not in text:
            continue
        direct_loaders.append(path)
        for required in (
            "Test-Path -LiteralPath $schedulerBoundaryScript -PathType Leaf",
            "Function:\\Assert-WeatherIntegrationSchedulerMutationAllowed",
            "$schedulerBoundaryCommand.ScriptBlock.File",
            "Scheduler mutation boundary helper did not load from its canonical file.",
        ):
            assert required in text, f"{path.name}: missing fail-closed loader proof"
    assert direct_loaders

    command = r"""
$ErrorActionPreference = 'Stop'
$verbs = @(
    'Register-ScheduledTask', 'Enable-ScheduledTask',
    'Disable-ScheduledTask', 'Start-ScheduledTask', 'Stop-ScheduledTask',
    'Unregister-ScheduledTask', 'Set-ScheduledTask'
)
function Test-GuardedSchedulerMutation {
    param(
        [Management.Automation.Language.CommandAst]$Mutation,
        [string]$Verb
    )
    $current = [Management.Automation.Language.Ast]$Mutation
    while ($null -ne $current.Parent) {
        $parent = $current.Parent
        $statementProperty = $parent.PSObject.Properties['Statements']
        if ($null -ne $statementProperty) {
            $statements = @($parent.Statements)
            $index = -1
            for ($position = 0; $position -lt $statements.Count; $position++) {
                if ([object]::ReferenceEquals($statements[$position], $current)) {
                    $index = $position
                    break
                }
            }
            if ($index -gt 0) {
                $previous = $statements[$index - 1]
                $guards = @($previous.FindAll({
                    param($node)
                    $node -is [Management.Automation.Language.CommandAst] -and
                        $node.GetCommandName() -ceq
                            'Assert-WeatherIntegrationSchedulerMutationAllowed'
                }, $true))
                foreach ($guard in $guards) {
                    $pattern = '(?s)-CommandName\s+["'']' +
                        [regex]::Escape($Verb) + '["''](?:\s|`|$)'
                    if ($guard.Extent.Text -match $pattern) { return $true }
                }
                return $false
            }
        }
        $current = $parent
    }
    return $false
}
$violations = New-Object System.Collections.Generic.List[string]
$mutationCount = 0
foreach ($path in @(Get-ChildItem -LiteralPath $env:WEATHER_OPS_ROOT -Filter *.ps1 -File)) {
    $tokens = $null
    $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile(
        $path.FullName,
        [ref]$tokens,
        [ref]$errors
    )
    if (@($errors).Count -ne 0) {
        throw "PowerShell parser errors in $($path.Name)"
    }
    $text = [IO.File]::ReadAllText($path.FullName)
    $mutations = @($ast.FindAll({
        param($node)
        $node -is [Management.Automation.Language.CommandAst] -and
            $verbs -contains $node.GetCommandName()
    }, $true))
    if ($mutations.Count -ne 0 -and
        $text -notmatch 'integration_attempt_(?:remote_git|contract)\.ps1') {
        $violations.Add("$($path.Name): canonical guard source is not loaded")
    }
    foreach ($mutation in $mutations) {
        $mutationCount++
        $verb = [string]$mutation.GetCommandName()
        if (-not (Test-GuardedSchedulerMutation -Mutation $mutation -Verb $verb)) {
            $violations.Add(
                "$($path.Name):$($mutation.Extent.StartLineNumber):$verb"
            )
        }
    }
}
if ($mutationCount -lt 1) { throw 'Scheduler mutation inventory was empty' }
if ($violations.Count -ne 0) {
    throw "unguarded Scheduler mutation(s): $($violations -join ', ')"
}
"PASS:$mutationCount"
"""
    env = os.environ.copy()
    env["WEATHER_OPS_ROOT"] = str(OPS_ROOT)
    result = _powershell(command, env=env)

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().startswith("PASS:")


def test_offline_scheduler_guard_allows_only_moduleless_function_mocks(tmp_path):
    script_mock = tmp_path / "script_backed_scheduler_mock.ps1"
    script_mock.write_text(
        "function Start-ScheduledTask { 'script-mock-only' }\n",
        encoding="utf-8",
    )
    command = r"""
$ErrorActionPreference = 'Stop'
. $env:WEATHER_REMOTE_GIT
$previousOffline = [Environment]::GetEnvironmentVariable(
    'WEATHER_INTEGRATION_TEST_OFFLINE',
    'Process'
)
try {
    [Environment]::SetEnvironmentVariable(
        'WEATHER_INTEGRATION_TEST_OFFLINE',
        '1',
        'Process'
    )
    $verbs = @(
        'Register-ScheduledTask', 'Enable-ScheduledTask',
        'Disable-ScheduledTask', 'Start-ScheduledTask', 'Stop-ScheduledTask',
        'Unregister-ScheduledTask', 'Set-ScheduledTask'
    )
    foreach ($verb in $verbs) {
        Set-Item -LiteralPath "Function:\$verb" -Value { 'mock-only' }
        Assert-WeatherIntegrationSchedulerMutationAllowed `
            -CommandName $verb -Phase 'moduleless function behavior probe'
        Remove-Item -LiteralPath "Function:\$verb" -Force
    }

    Set-Alias -Name Register-ScheduledTask -Value Write-Output -Scope Script
    $aliasBlocked = $false
    try {
        Assert-WeatherIntegrationSchedulerMutationAllowed `
            -CommandName 'Register-ScheduledTask' -Phase 'alias behavior probe'
    }
    catch { $aliasBlocked = $_.Exception.Message -like '*in-process Function mock*' }
    Remove-Item -LiteralPath Alias:\Register-ScheduledTask -Force
    if (-not $aliasBlocked) { throw 'Scheduler alias was accepted offline' }

    $fakeModule = New-Module -Name WeatherOfflineSchedulerProbe -ScriptBlock {
        function Enable-ScheduledTask { 'module-mock-only' }
        Export-ModuleMember -Function Enable-ScheduledTask
    }
    Import-Module $fakeModule -Force
    $moduleBlocked = $false
    try {
        Assert-WeatherIntegrationSchedulerMutationAllowed `
            -CommandName 'Enable-ScheduledTask' -Phase 'module behavior probe'
    }
    catch { $moduleBlocked = $_.Exception.Message -like '*in-process Function mock*' }
    Remove-Module WeatherOfflineSchedulerProbe -Force
    if (-not $moduleBlocked) { throw 'module-backed Scheduler function was accepted offline' }

    . $env:WEATHER_SCRIPT_SCHEDULER_MOCK
    $scriptBackedBlocked = $false
    try {
        Assert-WeatherIntegrationSchedulerMutationAllowed `
            -CommandName 'Start-ScheduledTask' -Phase 'script-backed behavior probe'
    }
    catch { $scriptBackedBlocked = $_.Exception.Message -like '*in-process Function mock*' }
    Remove-Item -LiteralPath Function:\Start-ScheduledTask -Force
    if (-not $scriptBackedBlocked) {
        throw 'script-backed Scheduler function was accepted offline'
    }

    $cmdletBlocked = $false
    try {
        Assert-WeatherIntegrationSchedulerMutationAllowed `
            -CommandName 'Disable-ScheduledTask' -Phase 'cmdlet behavior probe'
    }
    catch { $cmdletBlocked = $_.Exception.Message -like '*in-process Function mock*' }
    if (-not $cmdletBlocked) { throw 'real Scheduler cmdlet was accepted offline' }
    'PASS'
}
finally {
    foreach ($verb in @(
        'Register-ScheduledTask', 'Enable-ScheduledTask',
        'Disable-ScheduledTask', 'Start-ScheduledTask', 'Stop-ScheduledTask',
        'Unregister-ScheduledTask', 'Set-ScheduledTask'
    )) {
        Remove-Item -LiteralPath "Function:\$verb" -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath Alias:\Register-ScheduledTask `
        -Force -ErrorAction SilentlyContinue
    Remove-Module WeatherOfflineSchedulerProbe -Force -ErrorAction SilentlyContinue
    [Environment]::SetEnvironmentVariable(
        'WEATHER_INTEGRATION_TEST_OFFLINE',
        $previousOffline,
        'Process'
    )
}
"""
    env = os.environ.copy()
    env["WEATHER_REMOTE_GIT"] = str(REMOTE_GIT)
    env["WEATHER_SCRIPT_SCHEDULER_MOCK"] = str(script_mock)
    result = _powershell(command, env=env)

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "PASS"


def test_tracked_bootstrap_blocks_descendant_socket_before_network_io(tmp_path):
    env = os.environ.copy()
    env[OFFLINE_ENV] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "src")]
    )
    code = """
import socket
import os
assert os.environ["WEATHER_INTEGRATION_TEST_BOOTSTRAP_READY"] == "1"
try:
    socket.create_connection(("127.0.0.1", 9), timeout=0.01)
except RuntimeError as error:
    assert "offline boundary" in str(error)
else:
    raise SystemExit("guarded socket call unexpectedly reached the network")
import _socket
try:
    _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
except RuntimeError as error:
    assert "offline boundary" in str(error)
else:
    raise SystemExit("low-level socket construction escaped the offline boundary")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_tracked_bootstrap_keeps_child_offline_and_git_local_only(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")
    env = os.environ.copy()
    env[OFFLINE_ENV] = "0"
    env["GIT_ALLOW_PROTOCOL"] = "https"
    env["GIT_TERMINAL_PROMPT"] = "1"
    code = """
import os
import sys
from pathlib import Path
from weather import integration_test_safety
assert os.environ["WEATHER_INTEGRATION_TEST_OFFLINE"] == "1"
assert os.environ["WEATHER_INTEGRATION_TEST_BOOTSTRAP_READY"] == "1"
assert os.environ["GIT_ALLOW_PROTOCOL"] == "file"
assert os.environ["GIT_TERMINAL_PROMPT"] == "0"
assert os.environ["GIT_PROTOCOL_FROM_USER"] == "0"
assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
assert os.environ["GIT_CONFIG_COUNT"] == "0"
assert os.environ["GIT_ATTR_NOSYSTEM"] == "1"
assert os.environ["GIT_OPTIONAL_LOCKS"] == "0"
assert Path(os.environ["GIT_CONFIG_SYSTEM"]) == Path(os.devnull)
assert Path(os.environ["GIT_CONFIG_GLOBAL"]) == Path(os.devnull)
assert os.environ["PYTHONNOUSERSITE"] == "1"
assert os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
if os.environ.get("WEATHER_INTEGRATION_TEST_TEMP_POLICY") == "system_temp_unique_v1":
    assert Path(os.environ["TEMP"]).resolve() == Path(os.environ["TMP"]).resolve()
    assert Path(os.environ["TEMP"]).resolve() == Path(os.environ["TMPDIR"]).resolve()
assert Path(os.environ["WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE"]).is_file()
assert Path(os.environ["WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE"]).is_file()
powershell_executable = os.environ.get(
    "WEATHER_INTEGRATION_TEST_POWERSHELL_EXECUTABLE"
)
if powershell_executable is not None:
    assert Path(powershell_executable).is_file()
python_roots = [Path(value) for value in os.environ["PYTHONPATH"].split(os.pathsep)]
assert len(python_roots) == 2
assert (python_roots[0] / "sitecustomize.py").is_file()
assert python_roots[1] == python_roots[0] / "src"
production_root_text = os.environ.get("WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT")
if production_root_text:
    production_root = Path(production_root_text)
    forbidden_import_roots = {
        production_root.resolve(),
        (production_root / "src").resolve(),
    }
    assert all(
        Path(value or os.getcwd()).resolve() not in forbidden_import_roots
        for value in sys.path
    )
candidate_root = python_roots[0].resolve()
assert Path(integration_test_safety.__file__).resolve().is_relative_to(
    candidate_root / "src"
)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_pytest_collection_requires_the_completed_tracked_bootstrap():
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert (
        'OFFLINE_BOOTSTRAP_READY_ENV = "WEATHER_INTEGRATION_TEST_BOOTSTRAP_READY"'
        in conftest
    )
    assert "os.environ.get(OFFLINE_BOOTSTRAP_READY_ENV) != \"1\"" in conftest
    assert "offline bootstrap did not complete" in conftest


def test_tracked_bootstrap_scrubs_parent_and_replacement_child_secrets(tmp_path):
    env = os.environ.copy()
    env[OFFLINE_ENV] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "src")])
    secret_names = (
        "ACTIONS_RUNTIME_TOKEN",
        "PIP_INDEX_URL",
        "WEATHER_FAKE_CONNECTION_STRING",
        "GIT_SSH_COMMAND",
    )
    for name in secret_names:
        env[name] = "fixture-secret-never-log"
    code = """
import os
import subprocess
import sys
secret_names = (
    "ACTIONS_RUNTIME_TOKEN",
    "PIP_INDEX_URL",
    "WEATHER_FAKE_CONNECTION_STRING",
    "GIT_SSH_COMMAND",
)
assert all(name not in os.environ for name in secret_names)
replacement = os.environ.copy()
for name in secret_names:
    replacement[name] = "fixture-secret-never-log"
result = subprocess.run(
    [sys.executable, "-c", "import os; assert not any(name in os.environ for name in " + repr(secret_names) + ")"],
    env=replacement,
    check=False,
)
assert result.returncode == 0
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_tracked_bootstrap_scrubs_git_redirects_from_replacement_child(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    replacement = os.environ.copy()
    replacement.update(
        {
            "GIT_DIR": str(tmp_path / "forged-git-dir"),
            "GIT_WORK_TREE": str(tmp_path / "forged-worktree"),
            "GIT_CONFIG_PARAMETERS": "'protocol.allow=always'",
            "GIT_CONFIG_KEY_0": "protocol.allow",
            "GIT_CONFIG_VALUE_0": "always",
            "GIT_CONFIG_COUNT": "1",
            "GIT_EXTERNAL_DIFF": "weather-unapproved-native-probe",
        }
    )
    code = """
import os
for name in (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_EXTERNAL_DIFF",
):
    assert name not in os.environ
assert os.environ["GIT_CONFIG_COUNT"] == "0"
assert os.environ["GIT_ALLOW_PROTOCOL"] == "file"
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=replacement,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("flag", ["-E", "-I", "-S", "-Es"])
def test_tracked_bootstrap_rejects_python_flags_that_disable_it(flag, tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    with pytest.raises(RuntimeError, match="disable the tracked"):
        subprocess.run(
            [sys.executable, flag, "-c", "raise SystemExit('not reached')"],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )


def test_tracked_bootstrap_rejects_python_alias_flags_and_shell(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    with pytest.raises(
        RuntimeError,
        match="disable the tracked|exact offline test allowlist",
    ):
        subprocess.run(
            ["python", "-I", "-c", "raise SystemExit('not reached')"],
            cwd=tmp_path,
            check=False,
        )
    with pytest.raises(RuntimeError, match="opaque shell subprocesses"):
        subprocess.run("exit 0", cwd=tmp_path, shell=True, check=False)


def test_tracked_bootstrap_rejects_opaque_and_overridden_process_forms(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    with pytest.raises(RuntimeError, match="opaque subprocess argument forms"):
        subprocess.run(
            f'"{sys.executable}" -c "raise SystemExit(0)"',
            cwd=tmp_path,
            shell=False,
            check=False,
        )
    with pytest.raises(RuntimeError, match="executable overrides"):
        subprocess.run(
            [sys.executable, "-c", "raise SystemExit('not reached')"],
            executable=sys.executable,
            cwd=tmp_path,
            check=False,
        )
    with pytest.raises(RuntimeError, match="Job-breakaway flags"):
        subprocess.run(
            [sys.executable, "-c", "raise SystemExit('not reached')"],
            creationflags=getattr(
                subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000
            ),
            cwd=tmp_path,
            check=False,
        )


def test_tracked_bootstrap_rejects_unapproved_native_executables(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    with pytest.raises(RuntimeError, match="exact offline test allowlist"):
        subprocess.run(
            ["weather-unapproved-native-probe", "--version"],
            cwd=tmp_path,
            check=False,
        )

    base_python = getattr(sys, "_base_executable", "")
    bound_python = os.environ["WEATHER_INTEGRATION_TEST_PYTHON_EXECUTABLE"]
    if base_python and Path(base_python).resolve() != Path(bound_python).resolve():
        with pytest.raises(RuntimeError, match="exact offline test allowlist"):
            subprocess.run(
                [base_python, "-c", "raise SystemExit('not reached')"],
                cwd=tmp_path,
                check=False,
            )


def test_tracked_bootstrap_rejects_git_network_and_credential_commands(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    git = os.environ["WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE"]
    for arguments in (
        ["credential", "fill"],
        ["ls-remote", "https://example.invalid/weather.git"],
        ["-c", "protocol.allow=always", "status"],
        ["--git-dir", str(tmp_path / "redirected.git"), "status"],
        ["weather-unreviewed-alias"],
    ):
        with pytest.raises(RuntimeError, match="Git .*forbidden|Git -c override"):
            subprocess.run([git, *arguments], cwd=tmp_path, check=False)


def test_tracked_bootstrap_rejects_git_child_execution_configuration(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    git = os.environ["WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE"]
    repo = tmp_path / "configured-repo"
    subprocess.run([git, "init", "-q", str(repo)], check=True)
    subprocess.run(
        [git, "-C", str(repo), "config", "user.name", "Offline Fixture"],
        check=True,
    )
    subprocess.run(
        [git, "-C", str(repo), "config", "user.email", "offline@example.invalid"],
        check=True,
    )

    for key, value in (
        ("filter.escape.clean", "weather-unapproved-native-probe"),
        ("diff.escape.command", "weather-unapproved-native-probe"),
        ("core.editor", "weather-unapproved-native-probe"),
        ("core.pager", "weather-unapproved-native-probe"),
        ("alias.escape", "!weather-unapproved-native-probe"),
        ("credential.helper", "!weather-unapproved-native-probe"),
        ("core.sshCommand", "weather-unapproved-native-probe"),
        ("protocol.allow", "always"),
    ):
        with pytest.raises(RuntimeError, match="reviewed inert fixture grammar"):
            subprocess.run(
                [git, "-C", str(repo), "config", "--local", key, value],
                check=False,
            )

    for key, value in (
        ("filter.lfs.clean", "git-lfs clean -- %f"),
        ("filter.lfs.smudge", "git-lfs smudge -- %f"),
        ("filter.lfs.process", "git-lfs filter-process"),
        ("filter.lfs.required", "true"),
    ):
        subprocess.run(
            [git, "-C", str(repo), "config", "--local", key, value],
            check=True,
        )
    (repo / "payload.txt").write_text("fixture\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="external-execution Git configuration"):
        subprocess.run(
            [git, "-C", str(repo), "add", "payload.txt"], check=False
        )
    with pytest.raises(RuntimeError, match="external-execution Git configuration"):
        subprocess.run([git, "-C", str(repo), "status"], check=False)

    clean_repo = tmp_path / "clean-repo"
    subprocess.run([git, "init", "-q", str(clean_repo)], check=True)
    with pytest.raises(RuntimeError, match="inline message"):
        subprocess.run(
            [git, "-C", str(clean_repo), "commit", "--allow-empty"],
            check=False,
        )
    with pytest.raises(RuntimeError, match="executable, filter, textconv"):
        subprocess.run(
            [git, "-C", str(clean_repo), "diff", "--ext-diff"],
            check=False,
        )

    config_path = clean_repo / ".git" / "config"
    config_path.write_text(
        config_path.read_text(encoding="utf-8-sig")
        + "\n[diff \"escape\"]\n\ttextconv = weather-unapproved-native-probe\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="external-execution Git configuration"):
        subprocess.run([git, "-C", str(clean_repo), "diff"], check=False)


@pytest.mark.skipif(not hasattr(os, "startfile"), reason="Windows-only process API")
def test_tracked_bootstrap_rejects_os_startfile(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    with pytest.raises(RuntimeError, match="direct process APIs"):
        os.startfile(tmp_path)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("command", "message"),
    [
        (
            "Invoke-WebRequest -Uri https://example.invalid/",
            "external-I/O or credential tooling",
        ),
        ("cmdkey.exe /list", "external-I/O or credential tooling"),
        (
            "Get-Content -LiteralPath 'C:\\weather\\.env'",
            "secret file or credential-store",
        ),
        ("schtasks.exe /Query", "Scheduler mutation"),
        (
            "[System.Net.WebRequest]::Create('https://example.invalid/')",
            "external-I/O or credential tooling",
        ),
        (
            "[System.Net.Dns]::GetHostAddresses('example.invalid')",
            "external-I/O or credential tooling",
        ),
        (
            "$root = $env:WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT; "
            "Set-Content -LiteralPath (Join-Path $root 'escape.txt') -Value unsafe",
            "direct protected-root mutation",
        ),
        ("Invoke-Expression '$value = 1'", "dynamic PowerShell evaluation"),
        ("Add-Type -TypeDefinition 'public class Escape {}'", "Add-Type execution"),
        (
            "[Management.Automation.ScriptBlock]::Create('Get-Date')",
            "encoded or dynamic PowerShell creation",
        ),
    ],
)
def test_tracked_bootstrap_rejects_powershell_external_io(command, message, tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    with pytest.raises(RuntimeError, match=message):
        subprocess.run(
            [
                _powershell_executable(),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ],
            cwd=tmp_path,
            check=False,
        )


def test_tracked_bootstrap_denies_python_writes_to_production_root(tmp_path):
    if os.environ.get("WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"):
        pytest.skip("production-root authority is already latched by the host runner")
    production = tmp_path / "production"
    evidence = production / "immutable-evidence"
    outside = tmp_path / "outside"
    production.mkdir()
    evidence.mkdir()
    outside.mkdir()
    (production / ".env").write_text("SECRET=fixture-only\n", encoding="utf-8")
    (production / "retained-directory").mkdir()
    env = os.environ.copy()
    env[OFFLINE_ENV] = "1"
    env["WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"] = str(production)
    env["WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"] = str(ROOT)
    env["WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT"] = str(evidence)
    env["WEATHER_INTEGRATION_TEST_SECRET_POLICY"] = "conservative_v1"
    candidate_probe = ROOT / f".offline-boundary-write-probe-{tmp_path.name}"
    assert not candidate_probe.exists()
    env["WEATHER_TEST_CANDIDATE_PROBE"] = str(candidate_probe)
    env.pop("WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT", None)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "src")])
    code = """
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
production = Path(os.environ["WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"])
candidate = Path(os.environ["WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"])
evidence = Path(os.environ["WEATHER_INTEGRATION_TEST_EVIDENCE_ROOT"])
outside = production.parent / "outside"
try:
    (production / "data" / "snapshots" / "forbidden.txt").parent.mkdir(parents=True)
except RuntimeError as error:
    assert "repository filesystem mutation" in str(error)
else:
    raise SystemExit("production directory creation unexpectedly succeeded")
try:
    (production / "forbidden.txt").write_text("unsafe", encoding="utf-8")
except RuntimeError as error:
    assert "repository filesystem mutation" in str(error)
else:
    raise SystemExit("production file write unexpectedly succeeded")
try:
    shutil.rmtree(production / "retained-directory")
except RuntimeError as error:
    assert "repository filesystem mutation" in str(error)
else:
    raise SystemExit("production recursive deletion unexpectedly succeeded")
try:
    (production / ".env").read_text(encoding="utf-8")
except RuntimeError as error:
    assert "secret-file reads" in str(error)
else:
    raise SystemExit("production secret file read unexpectedly succeeded")
if os.name == "nt":
    try:
        (production / ".env::$DATA").read_text(encoding="utf-8")
    except RuntimeError as error:
        assert "secret-file reads" in str(error)
    else:
        raise SystemExit("production secret alternate stream unexpectedly succeeded")
    device_production = Path("//?/" + str(production))
    try:
        (device_production / "device-write.txt").write_text("unsafe", encoding="utf-8")
    except RuntimeError as error:
        assert "device-prefixed paths" in str(error)
    else:
        raise SystemExit("production device-path write unexpectedly succeeded")
    try:
        (device_production / ".env").read_text(encoding="utf-8")
    except RuntimeError as error:
        assert "device-prefixed paths" in str(error)
    else:
        raise SystemExit("production device-path secret read unexpectedly succeeded")
try:
    sqlite3.connect((production / "guard.db").as_uri() + "?mode=rwc", uri=True)
except RuntimeError as error:
    assert "SQLite file URIs" in str(error)
else:
    raise SystemExit("SQLite URI write into production unexpectedly succeeded")
git = os.environ["WEATHER_INTEGRATION_TEST_GIT_EXECUTABLE"]
subprocess.run(
    [git, "-C", str(production), "status", "--short"],
    text=True,
    capture_output=True,
    check=False,
)
try:
    subprocess.run(
        [git, "-C", str(production), "config", "user.name", "unsafe"],
        check=False,
    )
except RuntimeError as error:
    assert "Git mutation of a protected repository" in str(error)
else:
    raise SystemExit("Git config mutation of production unexpectedly launched")
try:
    Path(os.environ["WEATHER_TEST_CANDIDATE_PROBE"]).write_text(
        "unsafe", encoding="utf-8"
    )
except RuntimeError as error:
    assert "repository filesystem mutation" in str(error)
else:
    raise SystemExit("candidate repository write unexpectedly succeeded")
try:
    (evidence / "qualification.json").write_text("unsafe", encoding="utf-8")
except RuntimeError as error:
    assert "repository filesystem mutation" in str(error)
else:
    raise SystemExit("immutable evidence write unexpectedly succeeded")
(outside / "outside.txt").write_text("allowed", encoding="utf-8")
try:
    os.replace(outside / "outside.txt", production / "replacement.txt")
except RuntimeError as error:
    assert "repository filesystem mutation" in str(error)
else:
    raise SystemExit("production replacement unexpectedly succeeded")
assert not (production / "forbidden.txt").exists()
assert (production / "retained-directory").is_dir()
assert (outside / "outside.txt").read_text(encoding="utf-8") == "allowed"
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert not candidate_probe.exists()
    assert not (evidence / "qualification.json").exists()


def test_tracked_bootstrap_rejects_production_write_exceptions(tmp_path):
    if os.environ.get("WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"):
        pytest.skip("production-root authority is already latched by the host runner")
    production = tmp_path / "production"
    exception = production / "exception"
    exception.mkdir(parents=True)
    env = os.environ.copy()
    env[OFFLINE_ENV] = "1"
    env["WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"] = str(production)
    env["WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"] = str(ROOT)
    env["WEATHER_INTEGRATION_TEST_SECRET_POLICY"] = "conservative_v1"
    env["WEATHER_INTEGRATION_TEST_ALLOWED_WRITE_ROOT"] = str(exception)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "src")])

    result = subprocess.run(
        [sys.executable, "-c", "print('REACHED_UNGUARDED_PAYLOAD')"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "protected-tree write exceptions are forbidden" in result.stderr
    assert "REACHED_UNGUARDED_PAYLOAD" not in result.stdout
    assert "REACHED_UNGUARDED_PAYLOAD" not in result.stderr


def test_tracked_bootstrap_rejects_mismatched_tmpdir_before_payload(tmp_path):
    if os.environ.get("WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"):
        pytest.skip("production-root authority is already latched by the host runner")

    production = tmp_path / "production"
    suite_temp = tmp_path / "suite-temp"
    mismatched_temp = tmp_path / "mismatched-temp"
    production.mkdir()
    suite_temp.mkdir()
    mismatched_temp.mkdir()
    env = os.environ.copy()
    env[OFFLINE_ENV] = "1"
    env["WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"] = str(production)
    env["WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"] = str(ROOT)
    env["WEATHER_INTEGRATION_TEST_SECRET_POLICY"] = "conservative_v1"
    env["WEATHER_INTEGRATION_TEST_TEMP_POLICY"] = "system_temp_unique_v1"
    env["TEMP"] = str(suite_temp)
    env["TMP"] = str(suite_temp)
    env["TMPDIR"] = str(mismatched_temp)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "src")])

    result = subprocess.run(
        [sys.executable, "-c", "print('REACHED_UNGUARDED_PAYLOAD')"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode != 0
    assert "repository write boundary is malformed" in result.stderr
    assert "REACHED_UNGUARDED_PAYLOAD" not in result.stdout
    assert "REACHED_UNGUARDED_PAYLOAD" not in result.stderr


def test_tracked_bootstrap_allows_only_explicit_read_only_production_probe(tmp_path):
    if os.environ.get("WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"):
        pytest.skip("production-root authority is already latched by the host runner")

    probe = ROOT / f".offline-production-read-only-probe-{tmp_path.name}"
    assert not probe.exists()
    env = os.environ.copy()
    env[OFFLINE_ENV] = "1"
    env["WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"] = str(ROOT)
    env["WEATHER_INTEGRATION_TEST_CANDIDATE_ROOT"] = str(ROOT)
    env["WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE"] = "1"
    env["WEATHER_INTEGRATION_TEST_SECRET_POLICY"] = "conservative_v1"
    env["WEATHER_TEST_PRODUCTION_PROBE_PATH"] = str(probe)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "src")])
    unarmed_env = env.copy()
    unarmed_env.pop("WEATHER_INTEGRATION_TEST_READ_ONLY_PRODUCTION_PROBE")
    unarmed = subprocess.run(
        [sys.executable, "-c", "print('REACHED_UNGUARDED_PAYLOAD')"],
        cwd=tmp_path,
        env=unarmed_env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert unarmed.returncode != 0
    assert "repository write boundary is malformed" in unarmed.stderr
    assert "REACHED_UNGUARDED_PAYLOAD" not in unarmed.stdout
    assert "REACHED_UNGUARDED_PAYLOAD" not in unarmed.stderr
    code = """
from pathlib import Path
import os
from weather import integration_test_safety
root = Path(os.environ["WEATHER_INTEGRATION_TEST_PRODUCTION_ROOT"]).resolve()
assert Path(integration_test_safety.__file__).resolve().is_relative_to(root / "src")
try:
    Path(os.environ["WEATHER_TEST_PRODUCTION_PROBE_PATH"]).write_text(
        "unsafe", encoding="utf-8"
    )
except RuntimeError as error:
    assert "repository filesystem mutation" in str(error)
else:
    raise SystemExit("read-only production probe wrote to production")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert not probe.exists()


@pytest.mark.parametrize(
    "operation",
    [
        lambda: mm_credentials._read_windows_generic_credential("Weather/Test"),
        lambda: mm_credentials.windows_generic_credential_exists("Weather/Test"),
        lambda: mm_credentials.write_windows_generic_credential(
            "Weather/Test", "fixture-only"
        ),
        lambda: mm_credentials.delete_windows_generic_credential("Weather/Test"),
    ],
)
def test_real_windows_credential_io_is_blocked(monkeypatch, operation):
    monkeypatch.setenv(OFFLINE_ENV, "1")
    with pytest.raises(RuntimeError, match="offline boundary"):
        operation()


def test_injected_credential_reader_remains_available(monkeypatch):
    monkeypatch.setenv(OFFLINE_ENV, "1")
    assert (
        mm_credentials.resolve_credential_reference(
            "wincred://Weather/Test", wincred_reader=lambda target: f"fake:{target}"
        )
        == "fake:Weather/Test"
    )


def test_real_process_mutation_boundaries_refuse_offline(monkeypatch):
    monkeypatch.setenv(OFFLINE_ENV, "1")

    with pytest.raises(RuntimeError, match="offline boundary"):
        supervisor.terminate_python_pid(123, pid_check=lambda _pid: True)
    monkeypatch.setattr(
        taker_bot_daily_roll,
        "pid_matches_taker_bot",
        lambda _pid, _date: True,
    )
    with pytest.raises(RuntimeError, match="offline boundary"):
        taker_bot_daily_roll.retire_taker_bot_process_tree(
            123, "2026-08-25"
        )
    with pytest.raises(RuntimeError, match="offline boundary"):
        market_making_preflight_recovery._command_result(
            {
                "suggested_command":
                    "python -m weather.collection.snapshot_tracker --help",
                "incident_keys": [],
                "market_ids": [],
                "gates": [],
                "root_causes": [],
            },
            cwd=None,
            execute=True,
            timeout_seconds=1,
        )
    monkeypatch.setattr(daily_refresh.os, "name", "nt")
    with pytest.raises(RuntimeError, match="offline boundary"):
        daily_refresh._trigger_evidence_stage(
            type("Args", (), {"disable_stage_trigger": False})(),
            {"target_date": "2026-08-25"},
        )


@pytest.mark.skipif(os.name != "nt", reason="native Windows process boundary")
def test_native_windows_process_termination_refuses_offline(monkeypatch):
    monkeypatch.setenv(OFFLINE_ENV, "1")
    monkeypatch.setattr(windows_processes, "_open_process", lambda *_args: object())
    monkeypatch.setattr(
        windows_processes,
        "_creation_time_token",
        lambda _handle: "win32-filetime:100",
    )
    monkeypatch.setattr(
        windows_processes,
        "_remote_command_line",
        lambda _handle: "fixture managed command",
    )
    monkeypatch.setattr(windows_processes, "CloseHandle", lambda _handle: None)

    with pytest.raises(RuntimeError, match="offline boundary"):
        windows_processes.terminate_verified_process(
            123,
            expected_creation_time_token="win32-filetime:100",
            command_line_check=lambda command: command == "fixture managed command",
        )


def test_offline_credential_boundary_is_sticky_after_environment_tamper(monkeypatch):
    original = os.environ.get(OFFLINE_ENV)
    monkeypatch.setenv(OFFLINE_ENV, "1")
    importlib.reload(integration_test_safety)
    if original == "1":
        with pytest.raises(RuntimeError, match="environment removal"):
            monkeypatch.delenv(OFFLINE_ENV)
    else:
        monkeypatch.delenv(OFFLINE_ENV)
    try:
        with pytest.raises(RuntimeError, match="offline boundary"):
            mm_credentials._read_windows_generic_credential("Weather/Test")
    finally:
        # Restore the module to the surrounding process's real environment so
        # this behavioral probe cannot change later tests' safety semantics.
        if original is None:
            monkeypatch.delenv(OFFLINE_ENV, raising=False)
        else:
            monkeypatch.setenv(OFFLINE_ENV, original)
        importlib.reload(integration_test_safety)


def test_bootstrap_rejects_direct_process_api_and_protected_env_tamper(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    with pytest.raises(RuntimeError, match="direct process APIs"):
        os.system("exit 0")
    with pytest.raises(RuntimeError, match="environment mutation"):
        os.environ[OFFLINE_ENV] = "0"


def test_subprocess_audit_rejects_cached_popen_environment_escape(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    original_popen = next(
        cls for cls in subprocess.Popen.__mro__[1:] if cls.__module__ == "subprocess"
    )
    with pytest.raises(RuntimeError, match="subprocess environment escaped"):
        original_popen(
            [sys.executable, "-c", "raise SystemExit('not reached')"],
            cwd=tmp_path,
            env={"WEATHER_INTEGRATION_TEST_OFFLINE": "0"},
        )


def test_subprocess_audit_rejects_cached_popen_executable_escape(tmp_path):
    if os.environ.get(OFFLINE_ENV) != "1":
        pytest.skip("process-level bootstrap is exercised by the bounded offline suite")

    original_popen = next(
        cls for cls in subprocess.Popen.__mro__[1:] if cls.__module__ == "subprocess"
    )
    with pytest.raises(
        RuntimeError,
        match="exact offline test allowlist|opaque subprocess argument forms",
    ):
        original_popen(
            ["weather-unapproved-native-probe", "--version"],
            cwd=tmp_path,
            env=os.environ.copy(),
        )


def test_default_market_transports_refuse_before_external_io(monkeypatch):
    monkeypatch.setenv(OFFLINE_ENV, "1")

    with pytest.raises(RuntimeError, match="offline boundary"):
        fetch_gamma_event("highest-temperature-in-example-on-august-25-2026")
    with pytest.raises(RuntimeError, match="offline boundary"):
        fetch_gamma_events(max_pages=1)
    with pytest.raises(RuntimeError, match="offline boundary"):
        exchange_economics._default_fetch_json("https://example.invalid/economics")
    with pytest.raises(RuntimeError, match="offline boundary"):
        exchange_economics._default_fetch_text("https://example.invalid/rules")
    with pytest.raises(RuntimeError, match="offline boundary"):
        RequestsTransport().request("GET", "https://clob.polymarket.com/")
    with pytest.raises(RuntimeError, match="offline boundary"):
        ClobClient().get_order_book("fixture-token")
    with pytest.raises(RuntimeError, match="offline boundary"):
        fetch_wallet_deployed("0x" + "1" * 40, 3)
    with pytest.raises(RuntimeError, match="offline boundary"):
        fetch_current_positions("0x" + "1" * 40, "0x" + "2" * 64)
    with pytest.raises(RuntimeError, match="offline boundary"):
        mm_geographic_eligibility._fetch_official(opener=None, timeout_seconds=1)
    with pytest.raises(RuntimeError, match="offline boundary"):
        mm_user_stream._default_websocket_factory(
            "wss://ws-subscriptions-clob.polymarket.com/ws/user", timeout=1
        )
    with pytest.raises(RuntimeError, match="offline boundary"):
        execution_tape_capture._default_websocket_factory(
            "wss://ws-subscriptions-clob.polymarket.com/ws/market", timeout=1
        )


def test_injected_http_transport_remains_available(monkeypatch):
    monkeypatch.setenv(OFFLINE_ENV, "1")

    class Response:
        status = 200

        def read(self, _maximum=None):
            return b'{"deployed":true}'

        def close(self):
            return None

    assert fetch_wallet_deployed(
        "0x" + "1" * 40,
        3,
        opener=lambda *_args, **_kwargs: Response(),
    ) is True
