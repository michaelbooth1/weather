"""Native regressions for failures that previously left no phase log."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell contract")


def _powershell(source: str, tmp_path: Path, **values: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"R1_OPS": str(OPS), "R1_TEMP": str(tmp_path), **values})
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", "$ErrorActionPreference = 'Stop'\n" + source],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


def _invoke_script(name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(OPS / name), *arguments],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )


def _journal(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@WINDOWS
def test_reviewed_git_does_not_reselect_from_duplicate_path(tmp_path: Path) -> None:
    result = _powershell(r"""
. (Join-Path $env:R1_OPS 'git_executable_identity.ps1')
$installed = @(Get-Command git.exe -CommandType Application -All)[0].Source
$firstRoot = New-Item -ItemType Directory -Path (Join-Path $env:R1_TEMP 'first Git')
$secondRoot = New-Item -ItemType Directory -Path (Join-Path $env:R1_TEMP 'second Git')
$first = Join-Path $firstRoot.FullName 'git.exe'
$second = Join-Path $secondRoot.FullName 'git.exe'
Copy-Item -LiteralPath $installed -Destination $first
Copy-Item -LiteralPath $installed -Destination $second
function Get-Command {
    param($Name, $CommandType, [switch]$All, $ErrorAction)
    [pscustomobject]@{ CommandType = 'Application'; Source = $first }
    [pscustomobject]@{ CommandType = 'Application'; Source = $second }
}
$identity = Get-WeatherGitExecutableIdentity
function Get-Command { throw 'Runtime unexpectedly reselected Git from PATH.' }
$selected = Assert-WeatherGitExecutableIdentity -Identity $identity
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $env:R1_OPS 'bounded_worktree_test_suite.ps1'), [ref]$tokens, [ref]$errors
)
if ($errors.Count) { throw 'Bounded suite did not parse.' }
$resolver = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-SuiteGitExecutable'
}, $false))[0]
Invoke-Expression $resolver.Extent.Text
$childSelected = Get-SuiteGitExecutable -Path $identity.path -ExpectedSha256 $identity.sha256 -ExpectedFileVersion $identity.file_version
[pscustomobject]@{ selected = $selected; child_selected = $childSelected; expected = $first } | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["selected"] == payload["expected"]
    assert payload["child_selected"] == payload["expected"]


@WINDOWS
@pytest.mark.parametrize("mutation", ["hash", "version", "relative", "missing", "changed_bytes", "directory"])
def test_git_identity_change_is_rejected(tmp_path: Path, mutation: str) -> None:
    result = _powershell(r"""
. (Join-Path $env:R1_OPS 'git_executable_identity.ps1')
$installed = @(Get-Command git.exe -CommandType Application -All)[0].Source
$selected = Join-Path $env:R1_TEMP 'git.exe'
Copy-Item -LiteralPath $installed -Destination $selected
$identity = Get-WeatherGitExecutableIdentity -Path $selected
switch ($env:R1_MUTATION) {
    'hash' { $identity.sha256 = '0' * 64 }
    'version' { $identity.file_version = 'unreviewed-version' }
    'relative' { $identity.path = 'git.exe' }
    'missing' { $identity.path = Join-Path $env:R1_TEMP 'absent/git.exe' }
    'changed_bytes' { [IO.File]::AppendAllText($selected, 'changed-after-freeze') }
    'directory' {
        $directory = Join-Path $env:R1_TEMP 'directory/git.exe'
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
        $identity.path = $directory
    }
}
try {
    Assert-WeatherGitExecutableIdentity -Identity $identity | Out-Null
} catch {
    [pscustomobject]@{ rejected = $true; reason = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 0
}
throw 'Changed Git identity was accepted.'
""", tmp_path, R1_MUTATION=mutation)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["rejected"] is True


@WINDOWS
def test_historical_git_record_does_not_require_installed_binary(tmp_path: Path) -> None:
    result = _powershell(r"""
. (Join-Path $env:R1_OPS 'git_executable_identity.ps1')
$identity = [pscustomobject]@{
    path = Join-Path $env:R1_TEMP 'retired/git.exe'
    sha256 = 'a' * 64
    file_version = 'historical-version'
}
Assert-WeatherGitExecutableIdentityRecord -Identity $identity
try { Assert-WeatherGitExecutableIdentity -Identity $identity | Out-Null }
catch { Write-Output 'record-readable-execution-rejected'; exit 0 }
throw 'Missing runtime executable was accepted.'
""", tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "record-readable-execution-rejected"


@WINDOWS
def test_bounded_suite_early_failure_is_durable_and_cannot_replace_evidence(tmp_path: Path) -> None:
    log = tmp_path / "preflight.log"
    args = (
        "-RepoRoot", str(tmp_path / "missing-repository"),
        "-WorktreeRoot", str(tmp_path / "missing-worktree"),
        "-ExpectedTip", "a" * 40, "-BranchRef", "codex/r1-test", "-LogPath", str(log),
    )
    first = _invoke_script("bounded_worktree_test_suite.ps1", *args)
    assert first.returncode != 0
    assert not log.exists(), "Failure should precede the ordinary phase logger."
    bootstrap = Path(str(log) + ".bootstrap.jsonl")
    records = _journal(bootstrap)
    assert [record["event"] for record in records] == ["WRAPPER_ENTERED", "WRAPPER_EXIT"]
    assert records[-1]["detail"]["status"] == "FAIL"
    assert "missing-repository" in records[-1]["detail"]["failure"]
    assert records[-1]["detail"]["failure_type"]
    before = bootstrap.read_bytes()
    second = _invoke_script("bounded_worktree_test_suite.ps1", *args)
    assert second.returncode != 0
    assert bootstrap.read_bytes() == before


@WINDOWS
def test_candidate_bootstrap_does_not_require_git_helper_in_production(tmp_path: Path) -> None:
    production = tmp_path / "production"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    helpers = production / "scripts" / "ops"
    helpers.mkdir(parents=True)
    # Stop at the existing production-owned boundary, before any admission or
    # native process work. The new helper exists only beside the candidate runner.
    (helpers / "training_window_contract.ps1").write_text(
        "throw 'reached-existing-production-boundary'\n", encoding="utf-8"
    )
    for name in ("windows_kill_on_close_job.ps1", "workload_admission.ps1"):
        (helpers / name).write_text("# isolated fixture\n", encoding="utf-8")
    log = tmp_path / "bootstrap.log"
    result = _invoke_script(
        "bounded_worktree_test_suite.ps1", "-RepoRoot", str(production),
        "-WorktreeRoot", str(candidate), "-ExpectedTip", "a" * 40,
        "-BranchRef", "codex/bootstrap-test", "-LogPath", str(log),
    )
    assert result.returncode != 0
    assert not (helpers / "git_executable_identity.ps1").exists()
    records = _journal(Path(str(log) + ".bootstrap.jsonl"))
    assert records[-1]["detail"]["status"] == "FAIL"
    assert "reached-existing-production-boundary" in records[-1]["detail"]["failure"]
    assert not log.exists()


@WINDOWS
def test_outer_suite_records_bad_manifest_before_scheduler_or_child(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    result = _invoke_script(
        "integration_attempt_suite.ps1", "-ManifestPath", str(manifest),
        "-ExpectedManifestSha256", "0" * 64,
    )
    assert result.returncode != 0
    records = _journal(Path(str(manifest) + ".suite-bootstrap.jsonl"))
    assert [record["event"] for record in records] == ["WRAPPER_ENTERED", "WRAPPER_EXIT"]
    assert records[0]["detail"]["binding"]["expected_manifest_sha256"] == "0" * 64
    assert records[-1]["detail"]["status"] == "FAIL"
    assert "manifest hash mismatch" in records[-1]["detail"]["failure"]
    assert not (tmp_path / "suite-receipt.json").exists()


@WINDOWS
def test_bootstrap_journal_is_bounded_and_never_authorizes_work(tmp_path: Path) -> None:
    result = _powershell(r"""
. (Join-Path $env:R1_OPS 'integration_launch_diagnostics.ps1')
$path = Join-Path $env:R1_TEMP 'bootstrap.jsonl'
$journal = New-WeatherLaunchDiagnostics -Path $path -Operation test -ScriptPath (Join-Path $env:R1_OPS 'integration_launch_diagnostics.ps1') -Binding ([ordered]@{ attempt = 'test' })
$rejected = $false
try {
    Write-WeatherLaunchDiagnostic -Journal $journal -Event 'oversize' -Detail ('x' * 65536)
} catch { $rejected = $true }
Close-WeatherLaunchDiagnostics -Journal $journal -Status FAIL
[pscustomobject]@{ rejected = $rejected; length = (Get-Item -LiteralPath $path).Length } | ConvertTo-Json -Compress
""", tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["rejected"] is True
    assert payload["length"] < 65536
    records = _journal(tmp_path / "bootstrap.jsonl")
    assert records[-1]["detail"]["status"] == "FAIL"
    assert all("authority" not in record for record in records)


@WINDOWS
def test_new_attempt_freezes_selected_git_and_helper_hashes(tmp_path: Path) -> None:
    git = shutil.which("git.exe")
    assert git
    repository = tmp_path / "repository"
    repository.mkdir()

    def git_run(*arguments: str) -> str:
        result = subprocess.run(
            [git, "-C", str(repository), *arguments], capture_output=True, text=True,
            check=False, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    git_run("init", "--initial-branch=master")
    git_run("config", "user.name", "Reliability Test")
    git_run("config", "user.email", "reliability@example.invalid")
    (repository / "tests").mkdir()
    (repository / "tests" / "test_example.py").write_text("def test_example():\n    assert True\n", encoding="utf-8")
    git_run("add", "tests/test_example.py")
    git_run("commit", "-m", "fixture")
    tip = git_run("rev-parse", "HEAD")
    git_run("update-ref", "refs/remotes/origin/master", tip)
    worktree = tmp_path / "candidate"
    git_run("worktree", "add", "-b", "codex/r1-test", str(worktree), tip)
    # Only source needed by the manifest's hash inventory; no runtime data.
    scripts = repository / "scripts" / "ops"
    scripts.mkdir(parents=True)
    for name in (
        "integration_attempt_contract.ps1", "new_integration_attempt.ps1",
        "register_integration_attempt.ps1", "close_integration_attempt.ps1",
        "bounded_worktree_test_suite.ps1", "integration_attempt_suite.ps1",
        "integration_attempt_merge.ps1", "assert_integration_attempt_success.ps1",
        "dispatch_integration_attempt_recovery.ps1", "boot_recovery.ps1",
        "register_boot_recovery.ps1", "quiet_window_merge.ps1",
        "training_window_contract.ps1", "windows_kill_on_close_job.ps1",
        "workload_admission.ps1", "roll_verdict.ps1",
        "git_executable_identity.ps1", "integration_launch_diagnostics.ps1",
    ):
        shutil.copyfile(OPS / name, scripts / name)
    attempt = tmp_path / "attempt"
    result = _invoke_script(
        "new_integration_attempt.ps1", "-RepoRoot", str(repository),
        "-WorktreeRoot", str(worktree), "-ExpectedTip", tip,
        "-BranchRef", "codex/r1-test", "-AttemptRoot", str(attempt), "-AttemptId", "r1-test",
        "-SuiteAtLocal", "2026-09-13T00:30:00", "-MergeAtLocal", "2026-09-13T01:00:00",
        "-ReviewReference", "isolated regression fixture", "-GitExecutablePath", git,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads((attempt / "manifest.json").read_text(encoding="utf-8-sig"))
    identity = payload["suite"]["git_executable"]
    assert Path(identity["path"]).resolve() == Path(git).resolve()
    assert len(identity["sha256"]) == 64
    assert identity["file_version"]
    assert payload["orchestration"]["git_identity"]["sha256"]
    assert payload["orchestration"]["launch_diagnostics"]["sha256"]
