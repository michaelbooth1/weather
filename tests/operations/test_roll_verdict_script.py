import re
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "roll_verdict.ps1"


def test_execution_tape_closure_is_required_only_while_armed_or_active() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor"' in text
    assert '[string]$executionTask.State -ne "Disabled"' in text
    assert '"data\\snapshots\\.execution_tape_status.json.writer.lock"' in text
    assert 'Get-OptionalPropertyValue -InputObject $executionWorker -Name "state"' in text
    assert '$statusFiles += "data\\snapshots\\execution_tape_supervisor_status.json"' in text


def test_sparse_retained_closure_status_is_safe_under_inherited_strict_mode() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Get-OptionalPropertyValue" in text
    for name in ("state", "ensure_status", "reason"):
        assert f'Get-OptionalPropertyValue -InputObject $doc -Name "{name}"' in text
    assert 'Get-OptionalPropertyValue -InputObject $identity -Name "source_scope_files"' in text
    assert "$doc.state" not in text
    assert "$doc.ensure_status" not in text
    assert "$doc.reason" not in text


def test_roll_verdict_uses_only_pinned_sanitized_bounded_git() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '[string]$GitExecutable = ""' in text
    assert '[string]$ExpectedGitExecutableSha256 = ""' in text
    assert '[string]$ExpectedRemoteGitSha256 = ""' in text
    assert '[string]$ExpectedJobContainmentSha256 = ""' in text
    assert "function Open-WeatherRollVerdictPinnedDependency" in text
    assert '"integration_attempt_remote_git.ps1"' in text
    assert '"windows_kill_on_close_job.ps1"' in text
    assert ". $remoteGitPin.Path" in text
    assert "Assert-WeatherIntegrationSafeGitEnvironment" in text
    assert "Get-WeatherIntegrationGitExecutablePath" in text
    assert "$resolvedGitExecutable" in text
    assert "$resolvedGitExecutableSha256" in text
    assert "[IO.FileShare]::Read" in text
    assert text.count("Invoke-WeatherIntegrationCheckedLocalGit `") == 5
    assert text.count("-ExpectedGitExecutableSha256 $resolvedGitExecutableSha256") == 5
    assert 'GIT_NO_REPLACE_OBJECTS = "1"' not in text
    assert "$LASTEXITCODE" not in text
    assert re.search(r"(?i)&\s*(?:git(?:\.exe)?|\$resolvedGitExecutable)\b", text) is None


def test_roll_verdict_preserves_git_query_and_verdict_exit_semantics() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    origin = text.index('$originQuery = Invoke-WeatherIntegrationCheckedLocalGit `')
    counts = text.index('$countQuery = Invoke-WeatherIntegrationCheckedLocalGit `')
    base = text.index('$baseQuery = Invoke-WeatherIntegrationCheckedLocalGit `')
    changed = text.index('$changedQuery = Invoke-WeatherIntegrationCheckedLocalGit `')
    verdict = text.index("switch ($verdict)")
    assert origin < counts < base < changed < verdict
    assert text.count("-AllowedExitCodes @(0..255)") == 3
    assert '$haveOrigin = ([int]$originQuery.ExitCode -eq 0)' in text
    assert '$counts = if ([int]$countQuery.ExitCode -eq 0)' in text
    assert '$changed = if ([int]$changedQuery.ExitCode -eq 0)' in text
    assert '"ROLL-FREE" { exit 0 }' in text
    assert '"ROLL-FREE-IF-DORMANT" { exit 2 }' in text
    assert '"ROLL-SENSITIVE" { exit 3 }' in text
    assert "default { exit 1 }" in text
    assert '$rollVerdictPrimaryFailure.Exception.Data[' in text
    assert '"weather_cleanup_failure"' in text
