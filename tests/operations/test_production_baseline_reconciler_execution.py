from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "quiet_window_merge.ps1"
LOCAL_BASELINE = "3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac"
PUBLISHED_TARGET = "c932b54f8747df5cdefc4cc42f8454b6797f09ae"
REVIEWED_PARENT = "d2ab532a5bebd0868754322c5b34f72ebff8293b"
SOURCE_BRANCH = (
    "codex/workstation-production-baseline-synthetic-reconcile-2026-09-84a"
)
CONFIG_PATHS = (
    "config/location_market_events.json",
    "config/locations.json",
)
RAW_CONFIG_BYTES = {
    "config/location_market_events.json": (
        b'{\n  "execution_harness": "location_market_events"\n}\n'
    ),
    "config/locations.json": b'{\n  "execution_harness": "locations"\n}\n',
}
MOCK_TASK_XML = "<Task>production-baseline-reconciliation-test</Task>"
REVIEWED_TASK_XML_SHA256 = (
    "8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05"
)
EXPECTED_PUBLISHED_TREE = "6df5bac16d8c780c35b4601941eaca1137ea7070"

REAL_GIT = shutil.which("git.exe") or shutil.which("git")
WINDOWS_POWERSHELL = shutil.which("powershell.exe")
WINDOWS_EXECUTION = pytest.mark.skipif(
    os.name != "nt" or WINDOWS_POWERSHELL is None or REAL_GIT is None,
    reason="the reconciler execution harness requires Windows PowerShell and Git",
)


@dataclass(frozen=True)
class Harness:
    root: Path
    origin: Path
    production: Path
    source: Path
    script: Path
    fake_python: Path
    fake_roll_verdict: Path
    wrapper: Path
    published_target: str
    conflict_target: str
    source_tip: str
    source_tree: str
    source_sha256: str
    start_log: Path
    stop_log: Path
    task_read_count: Path
    capture_count: Path
    git_log: Path
    observed_marker: Path
    marker_write_count: Path
    post_replace_count: Path
    lease_log: Path
    roll_invocation_log: Path
    roll_classification_log: Path
    sleep_log: Path
    stop_exhausted_event: Path


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _git(
    repo: Path,
    *arguments: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    assert REAL_GIT is not None
    git_env = os.environ.copy()
    git_env["GIT_LFS_SKIP_SMUDGE"] = "1"
    if env:
        git_env.update(env)
    return _run(
        [REAL_GIT, *arguments],
        cwd=repo,
        check=check,
        env=git_env,
    )


def _rev(repo: Path, revision: str) -> str:
    return _git(repo, "rev-parse", revision).stdout.strip().lower()


def _git_bytes(repo: Path, *arguments: str) -> bytes:
    assert REAL_GIT is not None
    result = subprocess.run(
        [REAL_GIT, *arguments],
        cwd=repo,
        env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed ({result.returncode})\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    return result.stdout


def _configure_repo(repo: Path) -> None:
    for key, value in (
        ("user.name", "Reconciliation Execution Harness"),
        ("user.email", "reconciliation-execution@example.invalid"),
        ("commit.gpgSign", "false"),
        ("core.autocrlf", "false"),
        ("gc.auto", "0"),
    ):
        _git(repo, "config", key, value)


def _make_unrelated_target(origin: Path) -> str:
    assert REAL_GIT is not None
    tree = _rev(REPO_ROOT, f"{PUBLISHED_TARGET}^{{tree}}")
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_NAME": "Reconciliation Execution Harness",
            "GIT_AUTHOR_EMAIL": "reconciliation-execution@example.invalid",
            "GIT_COMMITTER_NAME": "Reconciliation Execution Harness",
            "GIT_COMMITTER_EMAIL": "reconciliation-execution@example.invalid",
            "GIT_AUTHOR_DATE": "2026-09-01T05:00:00Z",
            "GIT_COMMITTER_DATE": "2026-09-01T05:00:00Z",
        }
    )
    result = _run(
        [REAL_GIT, f"--git-dir={origin}", "commit-tree", tree],
        cwd=origin.parent,
        env=commit_env,
        input_text="test: unrelated published target\n",
    )
    return result.stdout.strip().lower()


def _make_config_changed_target(root: Path, origin: Path) -> str:
    worktree = root / "config-changed-target"
    _git(root, "clone", "--shared", str(origin), str(worktree))
    _configure_repo(worktree)
    _git(worktree, "checkout", "--force", PUBLISHED_TARGET)
    config = worktree / "config" / "locations.json"
    config.write_bytes(config.read_bytes() + b"\n")
    _git(worktree, "add", "--", "config/locations.json")
    commit_env = {
        "GIT_AUTHOR_DATE": "2026-09-01T05:05:00Z",
        "GIT_COMMITTER_DATE": "2026-09-01T05:05:00Z",
    }
    _git(
        worktree,
        "commit",
        "--no-gpg-sign",
        "-m",
        "test: change published generated config",
        env=commit_env,
    )
    target = _rev(worktree, "HEAD")
    _git(
        worktree,
        "push",
        "origin",
        f"{target}:refs/heads/config-changed-target",
    )
    return target


def _make_conflict_target(root: Path, origin: Path) -> str:
    worktree = root / "merge-conflict-target"
    _git(root, "clone", "--shared", str(origin), str(worktree))
    _configure_repo(worktree)
    _git(worktree, "checkout", "--force", LOCAL_BASELINE)
    config = worktree / "config" / "locations.json"
    config.write_bytes(b'{\n  "conflicting_target": true\n}\n')
    _git(worktree, "add", "--", "config/locations.json")
    commit_env = {
        "GIT_AUTHOR_DATE": "2026-09-01T05:06:00Z",
        "GIT_COMMITTER_DATE": "2026-09-01T05:06:00Z",
    }
    _git(
        worktree,
        "commit",
        "--no-gpg-sign",
        "-m",
        "test: create genuine merge conflict",
        env=commit_env,
    )
    target = _rev(worktree, "HEAD")
    _git(
        worktree,
        "push",
        "origin",
        f"{target}:refs/heads/merge-conflict-target",
    )
    return target


def _write_fake_python(root: Path) -> Path:
    mock = root / "fake_weather_python.py"
    mock.write_text(
        r'''from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


def bump(path: Path) -> int:
    value = int(path.read_text(encoding="ascii")) if path.exists() else 0
    value += 1
    path.write_text(str(value), encoding="ascii")
    return value


args = sys.argv[1:]
if Path.cwd().resolve() != Path(os.environ["RECON_TEST_REPO"]).resolve():
    print("special-mode Python child ran outside the production root", file=sys.stderr)
    raise SystemExit(96)
module = args[args.index("-m") + 1] if "-m" in args else ""
if module == "weather.operations.capture_recovery_check":
    call = bump(Path(os.environ["RECON_TEST_CAPTURE_COUNT"]))
    fail_at = int(os.environ.get("RECON_TEST_CAPTURE_FAIL_AT", "0"))
    ok = not fail_at or call != fail_at
    workers = [
        {"name": name, "ok": ok, "reasons": [] if ok else ["injected"]}
        for name in ("snapshot", "clob", "observation")
    ]
    print(json.dumps({"ok": ok, "workers": workers}))
    raise SystemExit(0 if ok else 3)

if module == "weather.operations.execution_tape_supervisor":
    print(json.dumps({"health": {"state": "STOPPED"}, "status": {"state": "STOPPED"}}))
    raise SystemExit(0)

if module == "weather.operations.documentation_transaction":
    if os.environ.get("RECON_TEST_DOCS_FAIL") == "1":
        print("injected documentation failure")
        raise SystemExit(9)
    repo = Path(args[args.index("--repo-root") + 1])
    tip = args[args.index("--integration-tip") + 1]
    branch = args[args.index("--branch") + 1]
    expected_tip = args[args.index("--expected-tip") + 1]
    payload = {
        "schema_version": "documentation_transaction_pending_v0.1",
        "status": "PENDING",
        "latest_integration_tip": tip,
        "integrations": [
            {
                "integration_tip": tip,
                "branch": branch,
                "expected_tip": expected_tip,
            }
        ],
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = hashlib.sha256(encoded).hexdigest()
    pending = repo / "data" / "alerts" / "documentation_transaction_pending.json"
    snapshot = repo / "data" / "alerts" / "documentation_transactions" / f"pending-{digest}.json"
    pending.parent.mkdir(parents=True, exist_ok=True)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    pending.write_bytes(encoded)
    snapshot.write_bytes(encoded)
    output = dict(payload)
    output["pending_sha256"] = digest
    print(json.dumps(output))
    raise SystemExit(0)

print(f"unexpected fake Python invocation: {args!r}", file=sys.stderr)
raise SystemExit(97)
''',
        encoding="utf-8",
    )
    launcher = root / "fake_python.cmd"
    launcher.write_text(
        f'@echo off\n"{sys.executable}" "{mock}" %*\nexit /b %ERRORLEVEL%\n',
        encoding="ascii",
    )
    return launcher


def _write_fake_roll_verdict(root: Path) -> Path:
    script = root / "fake_roll_verdict.ps1"
    script.write_text(
        r'''[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Base,
    [Parameter(Mandatory = $true)][string]$Branch,
    [Parameter(Mandatory = $true)][string]$JsonOut
)

$ErrorActionPreference = "Stop"
$mode = [string]$env:RECON_TEST_ROLL_MODE
[IO.File]::AppendAllText(
    $env:RECON_TEST_ROLL_INVOCATION_LOG,
    ($mode + "`t" + $Base + "`t" + $Branch + "`t" + $JsonOut + [Environment]::NewLine)
)
if ($Base -cne $env:RECON_TEST_EXPECTED_ROLL_BASE) {
    throw "roll_verdict received unexpected -Base: $Base"
}
if ($Branch -cne $env:RECON_TEST_EXPECTED_ROLL_BRANCH) {
    throw "roll_verdict received unexpected -Branch: $Branch"
}

$exitCode = switch ($mode) {
    "exit_1" { 1 }
    "exit_2" { 2 }
    "exit_3" { 3 }
    "missing_json" { 3 }
    "stale_closure" { 3 }
    "missing_closure" { 3 }
    "dormant_closure" { 2 }
    default { 0 }
}
$verdict = switch ($exitCode) {
    0 { "ROLL-FREE" }
    2 { "ROLL-FREE-IF-DORMANT" }
    3 { "ROLL-SENSITIVE" }
    default { "UNDECIDABLE" }
}

if ($mode -cne "missing_json") {
    $baseSha = @(& $env:RECON_TEST_REAL_GIT -C $env:RECON_TEST_REPO rev-parse --short $Base)
    if ($LASTEXITCODE -ne 0 -or $baseSha.Count -ne 1) {
        throw "fake roll_verdict could not resolve the exact base"
    }
    $generatedAt = (Get-Date).ToUniversalTime()
    if ($mode -ceq "stale_closure") {
        $generatedAt = $generatedAt.AddMinutes(-10)
    }
    $closuresUsed = if ($mode -ceq "missing_closure") { @() } else { @("capture") }
    $problems = if ($mode -ceq "missing_closure") {
        @("missing closure evidence: execution harness")
    }
    elseif ($mode -ceq "dormant_closure") {
        @("DORMANT closure evidence: capture is old and uniquely load-bearing")
    }
    else { @() }
    $payload = [ordered]@{
        generated_at = $generatedAt.ToString("o")
        verdict = $verdict
        branch = $Branch
        base_ref = $Base
        base_sha = ([string]$baseSha[0]).Trim()
        closures_used = $closuresUsed
        problems = $problems
        files = @()
    }
    [IO.File]::WriteAllText(
        $JsonOut,
        (($payload | ConvertTo-Json -Depth 10) + "`n"),
        [Text.UTF8Encoding]::new($false)
    )
}

Write-Output "fake roll_verdict mode=$mode exit=$exitCode"
exit $exitCode
''',
        encoding="utf-8",
    )
    return script


def _adapt_script(
    source: str,
    *,
    origin: Path,
    fake_python: Path,
    fake_roll_verdict: Path,
    published_target: str,
    published_tree: str,
) -> str:
    canonical_origin = str(origin.resolve()).replace("'", "''")
    mock_task_sha = hashlib.sha256(MOCK_TASK_XML.encode()).hexdigest()
    replacements = {
        '$py = Join-Path $repo "venv\\Scripts\\python.exe"': (
            f"$py = '{str(fake_python.resolve()).replace(chr(39), chr(39) * 2)}'"
        ),
        '$reconciliationCanonicalOrigin = "https://github.com/michaelbooth1/weather.git"': (
            f"$reconciliationCanonicalOrigin = '{canonical_origin}'"
        ),
        REVIEWED_TASK_XML_SHA256: mock_task_sha,
        "$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value": (
            "$currentSid = $expectedPushSid"
        ),
    }
    if published_target != PUBLISHED_TARGET:
        replacements[PUBLISHED_TARGET] = published_target
    if published_tree != EXPECTED_PUBLISHED_TREE:
        replacements[EXPECTED_PUBLISHED_TREE] = published_tree
    adapted = source
    for needle, replacement in replacements.items():
        assert adapted.count(needle) >= 1, needle
        adapted = adapted.replace(needle, replacement)

    verdict_needle = (
        r'$verdictScript = Join-Path $repo "scripts\ops\roll_verdict.ps1"'
    )
    assert adapted.count(verdict_needle) == 2
    fake_verdict_path = str(fake_roll_verdict.resolve()).replace("'", "''")
    adapted = adapted.replace(
        verdict_needle,
        f"$verdictScript = '{fake_verdict_path}'",
        1,
    )

    classification_needle = (
        "$rollFree = ($rollVerdictExitCode -eq 0 -and "
        "$rollVerdictReadable)"
    )
    assert adapted.count(classification_needle) == 1
    classification_injection = r'''$rollFree = ($rollVerdictExitCode -eq 0 -and $rollVerdictReadable)
    if ($env:RECON_TEST_ROLL_CLASSIFICATION_LOG) {
        $classification = [ordered]@{
            exit_code = [int]$rollVerdictExitCode
            readable = [bool]$rollVerdictReadable
            roll_free = [bool]$rollFree
        } | ConvertTo-Json -Compress
        [IO.File]::AppendAllText(
            $env:RECON_TEST_ROLL_CLASSIFICATION_LOG,
            ($classification + [Environment]::NewLine)
        )
    }'''
    adapted = adapted.replace(
        classification_needle,
        classification_injection,
        1,
    )

    exhaustion_needle = (
        '            Note "WeatherOneShotPush containment stop attempt limit '
        'exhausted; no further Scheduler mutation, retaining lease for '
        'terminal/manual intervention"'
    )
    assert adapted.count(exhaustion_needle) == 1
    exhaustion_injection = exhaustion_needle + r'''
            if ($env:RECON_TEST_TASK_MODE -in @("stop_noop", "readback_failure")) {
                [IO.File]::WriteAllText(
                    $env:RECON_TEST_STOP_EXHAUSTED_EVENT,
                    "exhausted"
                )
            }'''
    adapted = adapted.replace(exhaustion_needle, exhaustion_injection, 1)

    lease_needle = ". $workloadLeaseScript"
    assert adapted.count(lease_needle) == 1
    lease_mock = r'''
. $workloadLeaseScript
function Enter-WeatherHeavyWorkloadLease {
    [IO.File]::AppendAllText($env:RECON_TEST_LEASE_LOG, "enter`r`n")
    return [PSCustomObject]@{ test_lease = $true }
}
function Exit-WeatherHeavyWorkloadLease {
    param($Lease)
    [IO.File]::AppendAllText($env:RECON_TEST_LEASE_LOG, "exit`r`n")
}
'''.strip()
    adapted = adapted.replace(lease_needle, lease_mock, 1)

    marker_needle = "    $parent = Split-Path -Parent $activeMarkerPath"
    assert adapted.count(marker_needle) == 1
    marker_injection = r'''    if ($env:RECON_TEST_FAIL_MARKER_PHASE -ceq $Phase) {
        $markerFailureCount = if (Test-Path -LiteralPath $env:RECON_TEST_MARKER_WRITE_COUNT) {
            [int][IO.File]::ReadAllText($env:RECON_TEST_MARKER_WRITE_COUNT)
        }
        else { 0 }
        $markerFailureCount++
        [IO.File]::WriteAllText(
            $env:RECON_TEST_MARKER_WRITE_COUNT,
            [string]$markerFailureCount
        )
        if ($markerFailureCount -eq [int]$env:RECON_TEST_FAIL_MARKER_OCCURRENCE) {
            if (Test-Path -LiteralPath $activeMarkerPath -PathType Leaf) {
                Copy-Item -LiteralPath $activeMarkerPath -Destination $env:RECON_TEST_OBSERVED_MARKER -Force
            }
            throw "injected marker replacement failure for $Phase occurrence $markerFailureCount"
        }
    }
    $parent = Split-Path -Parent $activeMarkerPath'''
    adapted = adapted.replace(marker_needle, marker_injection, 1)

    replace_needle = "            [IO.File]::Replace($temp, $activeMarkerPath, $backup, $true)"
    assert adapted.count(replace_needle) == 1
    post_replace_injection = r'''            [IO.File]::Replace($temp, $activeMarkerPath, $backup, $true)
            if ($env:RECON_TEST_FAIL_AFTER_REPLACE_PHASE -ceq $Phase) {
                $postReplaceCount = if (Test-Path -LiteralPath $env:RECON_TEST_POST_REPLACE_COUNT) {
                    [int][IO.File]::ReadAllText($env:RECON_TEST_POST_REPLACE_COUNT)
                }
                else { 0 }
                $postReplaceCount++
                [IO.File]::WriteAllText(
                    $env:RECON_TEST_POST_REPLACE_COUNT,
                    [string]$postReplaceCount
                )
                if ($postReplaceCount -eq [int]$env:RECON_TEST_FAIL_AFTER_REPLACE_OCCURRENCE) {
                    throw "injected fault after File.Replace for $Phase occurrence $postReplaceCount"
                }
            }'''
    return adapted.replace(replace_needle, post_replace_injection, 1)


def _write_wrapper(root: Path) -> Path:
    wrapper = root / "invoke_reconciler.ps1"
    wrapper.write_text(
        r'''$ErrorActionPreference = "Stop"
$global:reconciliationTaskStarted = $false
$global:reconciliationTaskDispatchAt = $null
$global:reconciliationTaskPushed = $false
$global:reconciliationTaskStopped = $false
$global:reconciliationNow = [datetime]$env:RECON_TEST_NOW

function global:Get-Date {
    param([string]$Format)
    $value = $global:reconciliationNow
    if ($PSBoundParameters.ContainsKey("Format")) { return $value.ToString($Format) }
    return $value
}

function global:Start-Sleep {
    param([int]$Seconds, [int]$Milliseconds)
    $before = $global:reconciliationNow
    if ($PSBoundParameters.ContainsKey("Milliseconds")) {
        $global:reconciliationNow = $global:reconciliationNow.AddMilliseconds($Milliseconds)
    }
    else {
        $global:reconciliationNow = $global:reconciliationNow.AddSeconds($Seconds)
    }
    [IO.File]::AppendAllText(
        $env:RECON_TEST_SLEEP_LOG,
        ("{0:o}`t{1:o}`t{2}" -f $before, $global:reconciliationNow,
            $(if ($PSBoundParameters.ContainsKey("Milliseconds")) { $Milliseconds } else { $Seconds * 1000 })) +
            [Environment]::NewLine
    )
    if ($env:RECON_TEST_TASK_MODE -in @("stop_noop", "readback_failure") -and
        $before -ge $before.Date.AddHours(4) -and
        (Test-Path -LiteralPath $env:RECON_TEST_STOP_EXHAUSTED_EVENT)) {
        [Threading.Thread]::Sleep(60000)
    }
    if ($env:RECON_TEST_TASK_MODE -ceq "delayed_start" -and
        $global:reconciliationTaskStarted -and
        -not $global:reconciliationTaskPushed -and
        ($global:reconciliationNow - $global:reconciliationTaskDispatchAt).TotalSeconds -ge 50) {
        & $env:RECON_TEST_REAL_GIT -C $env:RECON_TEST_REPO push origin master
        if ($LASTEXITCODE -ne 0) { throw "delayed fake one-shot push failed" }
        $global:reconciliationTaskPushed = $true
    }
}

function global:git {
    param([Parameter(ValueFromRemainingArguments = $true)][object[]]$GitArguments)
    $tokens = @($GitArguments | ForEach-Object { [string]$_ })
    [IO.File]::AppendAllText(
        $env:RECON_TEST_GIT_LOG,
        (($tokens -join "`t") + [Environment]::NewLine)
    )
    $specialMerge = $env:RECON_TEST_GIT_MODE -ceq "merge_conflict" -and
        $tokens -contains "--no-commit" -and $tokens -contains "--no-ff" -and
        $tokens -contains $env:RECON_TEST_PUBLISHED_TARGET
    if ($specialMerge) {
        $conflictTokens = @($tokens | ForEach-Object {
            if ($_ -ceq $env:RECON_TEST_PUBLISHED_TARGET) {
                $env:RECON_TEST_CONFLICT_TARGET
            }
            else { $_ }
        })
        & $env:RECON_TEST_REAL_GIT @conflictTokens
        if ($LASTEXITCODE -eq 0) {
            & $env:RECON_TEST_REAL_GIT -C $env:RECON_TEST_REPO __injected_merge_failure__ 2>$null
        }
        return
    }
    & $env:RECON_TEST_REAL_GIT @tokens
}

function global:Get-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    if ($TaskName -ceq "WeatherExecutionTapeSupervisor") { return $null }
    if ($TaskName -cne "WeatherOneShotPush") { return $null }
    if ($env:RECON_TEST_TASK_MODE -ceq "absent") { return @() }
    if ($env:RECON_TEST_TASK_MODE -ceq "readback_failure" -and
        $global:reconciliationTaskStarted) {
        throw "injected post-start task readback failure"
    }
    $countPath = $env:RECON_TEST_TASK_READ_COUNT
    $count = if (Test-Path -LiteralPath $countPath) {
        [int][IO.File]::ReadAllText($countPath)
    }
    else { 0 }
    $count++
    [IO.File]::WriteAllText($countPath, [string]$count)
    if ($env:RECON_TEST_PREPUSH_DRIFT -eq "1" -and $count -ge 3) {
        $driftPath = Join-Path $env:RECON_TEST_REPO "config\locations.json"
        [IO.File]::AppendAllText($driftPath, " `r`n")
    }
    $mismatch = $env:RECON_TEST_TASK_MODE -ceq "mismatch_after_two" -and $count -ge 3
    $action = [PSCustomObject]@{
        Execute = "cmd.exe"
        Arguments = "/c git -C c:\Users\micha\Desktop\github\weather push origin master > C:\Users\micha\ops\logs\push-oneshot.log 2>&1"
        WorkingDirectory = $env:RECON_TEST_REPO
    }
    $settings = [PSCustomObject]@{
        Enabled = $env:RECON_TEST_TASK_MODE -cne "disabled"
        MultipleInstances = "IgnoreNew"
        ExecutionTimeLimit = "PT15M"
        StartWhenAvailable = $mismatch
    }
    $principal = [PSCustomObject]@{
        UserId = "micha"
        LogonType = "Interactive"
        RunLevel = "Limited"
    }
    $taskState = if ($global:reconciliationTaskStopped) {
        "Ready"
    }
    elseif ($env:RECON_TEST_TASK_MODE -ceq "queued_after_start" -and
        $global:reconciliationTaskStarted) {
        "Queued"
    }
    elseif ($env:RECON_TEST_TASK_MODE -ceq "running" -or
        ($env:RECON_TEST_TASK_MODE -in @("hang_after_start", "hang_coarse", "stop_noop") -and
            $global:reconciliationTaskStarted)) {
        "Running"
    }
    elseif ($env:RECON_TEST_TASK_MODE -ceq "delayed_start" -and
        $global:reconciliationTaskStarted) {
        $elapsed = (
            $global:reconciliationNow - $global:reconciliationTaskDispatchAt
        ).TotalSeconds
        if ($elapsed -lt 30) { "Ready" }
        elseif ($elapsed -lt 50) { "Running" }
        else { "Ready" }
    }
    else { "Ready" }
    $taskObject = [PSCustomObject]@{
        TaskPath = "\"
        State = $taskState
        Settings = $settings
        Principal = $principal
        Actions = @($action)
        Triggers = @()
    }
    if ($env:RECON_TEST_TASK_MODE -ceq "ambiguous") {
        return @($taskObject, $taskObject)
    }
    return $taskObject
}

function global:Get-ScheduledTaskInfo {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    if ($TaskName -cne "WeatherOneShotPush") { return $null }
    $delayedRunStarted = $env:RECON_TEST_TASK_MODE -ceq "delayed_start" -and
        $global:reconciliationTaskStarted -and
        ($global:reconciliationNow - $global:reconciliationTaskDispatchAt).TotalSeconds -ge 30
    $lastRun = if ($env:RECON_TEST_TASK_MODE -in @(
        "hang_coarse", "queued_after_start"
    )) {
        [datetime]"2026-08-31T01:30:00"
    }
    elseif ($global:reconciliationTaskStarted -and
        ($env:RECON_TEST_TASK_MODE -cne "delayed_start" -or $delayedRunStarted)) {
        if ($env:RECON_TEST_TASK_MODE -ceq "delayed_start") {
            $global:reconciliationTaskDispatchAt.AddSeconds(30)
        }
        else { $global:reconciliationTaskDispatchAt.AddSeconds(1) }
    }
    else { [datetime]"2026-08-31T01:30:00" }
    $lastResult = if ($global:reconciliationTaskStopped) {
        [long]3221225786
    }
    elseif ($global:reconciliationTaskStarted -and
        $env:RECON_TEST_TASK_MODE -in @("start_fail", "push_failure")) {
        1
    }
    else { 0 }
    return [PSCustomObject]@{
        LastRunTime = $lastRun
        LastTaskResult = $lastResult
    }
}

function global:Export-ScheduledTask {
    param([string]$TaskName, [string]$TaskPath, $ErrorAction)
    return $env:RECON_TEST_TASK_XML
}

function global:Start-ScheduledTask {
    param([string]$TaskName, $ErrorAction)
    [IO.File]::AppendAllText(
        $env:RECON_TEST_START_LOG,
        ($TaskName + [Environment]::NewLine)
    )
    if ($env:RECON_TEST_TASK_MODE -ceq "start_fail_before_dispatch") {
        $global:reconciliationNow = $global:reconciliationNow.AddMinutes(15)
        throw "injected task-start failure before dispatch"
    }
    $global:reconciliationTaskStarted = $true
    $global:reconciliationTaskDispatchAt = $global:reconciliationNow
    if ($env:RECON_TEST_TASK_MODE -ceq "queued_after_start") {
        $global:reconciliationNow = $global:reconciliationTaskDispatchAt.AddMinutes(15)
    }
    if ($env:RECON_TEST_TASK_MODE -in @("stop_noop", "readback_failure")) {
        # Put the first drain poll just before quiet-window closure. This makes
        # both bounded stop attempts and the post-04:00 read-only state
        # deterministic instead of dependent on Windows/Git host speed.
        $global:reconciliationNow = $global:reconciliationNow.Date.AddHours(3).AddMinutes(59).AddSeconds(55)
    }
    if ($env:RECON_TEST_TASK_MODE -ceq "start_fail") {
        throw "injected task-start failure after dispatch"
    }
    if ($env:RECON_TEST_TASK_MODE -in @(
        "no_ack", "push_failure", "hang_after_start", "hang_coarse", "stop_noop",
        "readback_failure", "queued_after_start"
    )) { return }
    if ($env:RECON_TEST_TASK_MODE -ceq "delayed_start") { return }
    & $env:RECON_TEST_REAL_GIT -C $env:RECON_TEST_REPO push origin master
    if ($LASTEXITCODE -ne 0) { throw "fake one-shot push failed" }
    $global:reconciliationTaskPushed = $true
}

function global:Stop-ScheduledTask {
    param($InputObject, $ErrorAction)
    [IO.File]::AppendAllText(
        $env:RECON_TEST_STOP_LOG,
        ("WeatherOneShotPush" + [Environment]::NewLine)
    )
    if ($env:RECON_TEST_TASK_MODE -notin @("stop_noop", "readback_failure")) {
        $global:reconciliationTaskStopped = $true
    }
}

$params = @{
    Branch = "origin/master"
    ExpectedTip = $env:RECON_TEST_EXPECTED_TIP
    ExpectedBaseline = $env:RECON_TEST_EXPECTED_BASELINE
    ExpectedLocalBaseline = $env:RECON_TEST_EXPECTED_LOCAL
    ExpectedPublishedTarget = $env:RECON_TEST_EXPECTED_PUBLISHED
    ExpectedSourceTip = $env:RECON_TEST_EXPECTED_SOURCE_TIP
    ExpectedSourceTree = $env:RECON_TEST_EXPECTED_SOURCE_TREE
    ExpectedSelfSha256 = $env:RECON_TEST_EXPECTED_SELF_SHA256
    RepoRoot = $env:RECON_TEST_REPO
    SettleSeconds = 0
    RollbackRecoverySeconds = 60
}
if ($env:RECON_TEST_SPECIAL_MODE -ne "0") {
    $params["ProductionBaselineReconciliation"] = $true
}
if ($env:RECON_TEST_DRY_RUN -eq "1") { $params["DryRun"] = $true }
& $env:RECON_TEST_SCRIPT @params
exit $LASTEXITCODE
''',
        encoding="utf-8",
    )
    return wrapper


def _build_harness(
    tmp_path: Path,
    *,
    unrelated_target: bool = False,
    changed_target_config: bool = False,
) -> Harness:
    assert REAL_GIT is not None
    root = tmp_path / "reconciler-execution"
    root.mkdir()
    origin = root / "origin.git"
    _git(REPO_ROOT, "clone", "--bare", "--shared", str(REPO_ROOT), str(origin))
    if unrelated_target:
        published_target = _make_unrelated_target(origin)
    elif changed_target_config:
        published_target = _make_config_changed_target(root, origin)
    else:
        published_target = PUBLISHED_TARGET
    published_tree = _rev(REPO_ROOT, f"{PUBLISHED_TARGET}^{{tree}}")
    if published_target != PUBLISHED_TARGET:
        published_tree = _rev(origin, f"{published_target}^{{tree}}")
    _git(
        root,
        f"--git-dir={origin}",
        "update-ref",
        "refs/heads/master",
        published_target,
    )
    conflict_target = _make_conflict_target(root, origin)

    production = root / "production"
    _git(root, "clone", "--no-checkout", str(origin), str(production))
    _configure_repo(production)
    _git(production, "checkout", "--force", "-B", "master", LOCAL_BASELINE)
    for relative, raw_bytes in RAW_CONFIG_BYTES.items():
        destination = production / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw_bytes)
    assert _rev(production, "HEAD") == LOCAL_BASELINE
    assert _rev(production, "origin/master") == published_target

    fake_python = _write_fake_python(root)
    fake_roll_verdict = _write_fake_roll_verdict(root)
    source = root / "source"
    _git(
        root,
        "clone",
        "--shared",
        "--no-checkout",
        str(REPO_ROOT),
        str(source),
    )
    _configure_repo(source)
    _git(source, "checkout", "--force", "-B", SOURCE_BRANCH, REVIEWED_PARENT)
    _git(source, "remote", "set-url", "origin", str(origin.resolve()))
    source_script = source / "scripts" / "ops" / "quiet_window_merge.ps1"
    adapted = _adapt_script(
        SCRIPT.read_text(encoding="utf-8"),
        origin=origin,
        fake_python=fake_python,
        fake_roll_verdict=fake_roll_verdict,
        published_target=published_target,
        published_tree=published_tree,
    )
    source_script.write_text(adapted, encoding="utf-8", newline="")
    _git(source, "add", "--", "scripts/ops/quiet_window_merge.ps1")
    commit_env = {
        "GIT_AUTHOR_DATE": "2026-09-01T05:10:00Z",
        "GIT_COMMITTER_DATE": "2026-09-01T05:10:00Z",
    }
    _git(
        source,
        "commit",
        "--no-gpg-sign",
        "-m",
        "test: adapted reconciliation entry",
        env=commit_env,
    )
    assert not _git(source, "status", "--porcelain=v1").stdout.strip()

    wrapper = _write_wrapper(root)
    return Harness(
        root=root,
        origin=origin,
        production=production,
        source=source,
        script=source_script,
        fake_python=fake_python,
        fake_roll_verdict=fake_roll_verdict,
        wrapper=wrapper,
        published_target=published_target,
        conflict_target=conflict_target,
        source_tip=_rev(source, "HEAD"),
        source_tree=_rev(source, "HEAD^{tree}"),
        source_sha256=hashlib.sha256(source_script.read_bytes()).hexdigest(),
        start_log=root / "task-start.log",
        stop_log=root / "task-stop.log",
        task_read_count=root / "task-read-count.txt",
        capture_count=root / "capture-count.txt",
        git_log=root / "git.log",
        observed_marker=root / "observed-marker.json",
        marker_write_count=root / "marker-write-count.txt",
        post_replace_count=root / "post-replace-count.txt",
        lease_log=root / "lease.log",
        roll_invocation_log=root / "roll-invocation.log",
        roll_classification_log=root / "roll-classification.jsonl",
        sleep_log=root / "sleep.log",
        stop_exhausted_event=root / "stop-exhausted.txt",
    )


def _invoke(
    harness: Harness,
    *,
    dry_run: bool = False,
    special_mode: bool = True,
    expected_baseline: str = LOCAL_BASELINE,
    expected_local: str = LOCAL_BASELINE,
    expected_tip: str | None = None,
    expected_published: str | None = None,
    expected_source_tip: str | None = None,
    expected_source_tree: str | None = None,
    expected_self_sha256: str | None = None,
    task_mode: str = "good",
    git_mode: str = "good",
    capture_fail_at: int = 0,
    docs_fail: bool = False,
    roll_mode: str = "good",
    prepush_drift: bool = False,
    fail_marker_phase: str = "",
    fail_marker_occurrence: int = 1,
    fail_after_replace_phase: str = "",
    fail_after_replace_occurrence: int = 1,
    now: str = "2026-09-01T01:30:00",
    timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    assert WINDOWS_POWERSHELL is not None
    assert REAL_GIT is not None
    environment = os.environ.copy()
    environment.update(
        {
            "RECON_TEST_SCRIPT": str(harness.script.resolve()),
            "RECON_TEST_REPO": str(harness.production.resolve()),
            "RECON_TEST_REAL_GIT": REAL_GIT,
            "RECON_TEST_GIT_LOG": str(harness.git_log),
            "RECON_TEST_GIT_MODE": git_mode,
            "RECON_TEST_PUBLISHED_TARGET": harness.published_target,
            "RECON_TEST_CONFLICT_TARGET": harness.conflict_target,
            "RECON_TEST_EXPECTED_TIP": expected_tip or harness.published_target,
            "RECON_TEST_EXPECTED_BASELINE": expected_baseline,
            "RECON_TEST_EXPECTED_LOCAL": expected_local,
            "RECON_TEST_EXPECTED_PUBLISHED": (
                expected_published or harness.published_target
            ),
            "RECON_TEST_EXPECTED_SOURCE_TIP": (
                expected_source_tip or harness.source_tip
            ),
            "RECON_TEST_EXPECTED_SOURCE_TREE": (
                expected_source_tree or harness.source_tree
            ),
            "RECON_TEST_EXPECTED_SELF_SHA256": (
                expected_self_sha256 or harness.source_sha256
            ),
            "RECON_TEST_SPECIAL_MODE": "1" if special_mode else "0",
            "RECON_TEST_DRY_RUN": "1" if dry_run else "0",
            "RECON_TEST_TASK_MODE": task_mode,
            "RECON_TEST_TASK_XML": MOCK_TASK_XML,
            "RECON_TEST_START_LOG": str(harness.start_log),
            "RECON_TEST_STOP_LOG": str(harness.stop_log),
            "RECON_TEST_TASK_READ_COUNT": str(harness.task_read_count),
            "RECON_TEST_CAPTURE_COUNT": str(harness.capture_count),
            "RECON_TEST_CAPTURE_FAIL_AT": str(capture_fail_at),
            "RECON_TEST_DOCS_FAIL": "1" if docs_fail else "0",
            "RECON_TEST_ROLL_MODE": roll_mode,
            "RECON_TEST_EXPECTED_ROLL_BASE": LOCAL_BASELINE,
            "RECON_TEST_EXPECTED_ROLL_BRANCH": harness.published_target,
            "RECON_TEST_ROLL_INVOCATION_LOG": str(harness.roll_invocation_log),
            "RECON_TEST_ROLL_CLASSIFICATION_LOG": str(
                harness.roll_classification_log
            ),
            "RECON_TEST_PREPUSH_DRIFT": "1" if prepush_drift else "0",
            "RECON_TEST_FAIL_MARKER_PHASE": fail_marker_phase,
            "RECON_TEST_FAIL_MARKER_OCCURRENCE": str(fail_marker_occurrence),
            "RECON_TEST_OBSERVED_MARKER": str(harness.observed_marker),
            "RECON_TEST_MARKER_WRITE_COUNT": str(harness.marker_write_count),
            "RECON_TEST_FAIL_AFTER_REPLACE_PHASE": fail_after_replace_phase,
            "RECON_TEST_FAIL_AFTER_REPLACE_OCCURRENCE": str(
                fail_after_replace_occurrence
            ),
            "RECON_TEST_POST_REPLACE_COUNT": str(harness.post_replace_count),
            "RECON_TEST_LEASE_LOG": str(harness.lease_log),
            "RECON_TEST_SLEEP_LOG": str(harness.sleep_log),
            "RECON_TEST_STOP_EXHAUSTED_EVENT": str(
                harness.stop_exhausted_event
            ),
            "RECON_TEST_NOW": now,
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "commit.gpgSign",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_KEY_1": "core.autocrlf",
            "GIT_CONFIG_VALUE_1": "false",
        }
    )
    return _run(
        [
            WINDOWS_POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness.wrapper),
        ],
        cwd=harness.production,
        env=environment,
        check=False,
        timeout=timeout,
    )


def _production_state(harness: Harness) -> dict[str, Any]:
    data_root = harness.production / "data"
    return {
        "head": _rev(harness.production, "HEAD"),
        "master": _rev(harness.production, "master"),
        "origin_master": _rev(harness.production, "origin/master"),
        "canonical_remote_master": _rev(harness.origin, "refs/heads/master"),
        "status": _git(
            harness.production, "status", "--porcelain=v1", "--untracked-files=all"
        ).stdout,
        "refs": _git(harness.production, "show-ref").stdout,
        "production_index": (harness.production / ".git" / "index").read_bytes(),
        "source_index": (harness.source / ".git" / "index").read_bytes(),
        "config": {
            relative: (harness.production / relative).read_bytes()
            for relative in CONFIG_PATHS
        },
        "data_files": {
            str(path.relative_to(harness.production)).replace(
                "\\", "/"
            ): path.read_bytes()
            for path in data_root.rglob("*")
            if path.is_file()
        }
        if data_root.is_dir()
        else {},
        "marker": (
            harness.production
            / "data"
            / "alerts"
            / "quiet_window_merge_in_progress.json"
        ).read_bytes()
        if (
            harness.production
            / "data"
            / "alerts"
            / "quiet_window_merge_in_progress.json"
        ).is_file()
        else None,
        "start_count": len(_start_lines(harness)),
        "stop_count": len(_stop_lines(harness)),
    }


def _start_lines(harness: Harness) -> list[str]:
    if not harness.start_log.is_file():
        return []
    return harness.start_log.read_text(encoding="utf-8-sig").splitlines()


def _stop_lines(harness: Harness) -> list[str]:
    if not harness.stop_log.is_file():
        return []
    return harness.stop_log.read_text(encoding="utf-8-sig").splitlines()


def _sleep_records(harness: Harness) -> list[tuple[str, str, int]]:
    if not harness.sleep_log.is_file():
        return []
    return [
        (parts[0], parts[1], int(parts[2]))
        for line in harness.sleep_log.read_text(
            encoding="utf-8-sig"
        ).splitlines()
        if line and len(parts := line.split("\t")) == 3
    ]


def _roll_invocations(harness: Harness) -> list[tuple[str, ...]]:
    if not harness.roll_invocation_log.is_file():
        return []
    return [
        tuple(line.split("\t"))
        for line in harness.roll_invocation_log.read_text(
            encoding="utf-8-sig"
        ).splitlines()
        if line
    ]


def _roll_classifications(harness: Harness) -> list[dict[str, Any]]:
    if not harness.roll_classification_log.is_file():
        return []
    return [
        json.loads(line)
        for line in harness.roll_classification_log.read_text(
            encoding="utf-8-sig"
        ).splitlines()
        if line
    ]


def _assert_no_git_config_or_scheduler_mutation(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    for key in (
        "head",
        "master",
        "origin_master",
        "canonical_remote_master",
        "status",
        "refs",
        "production_index",
        "source_index",
        "config",
        "marker",
        "start_count",
        "stop_count",
    ):
        assert after[key] == before[key], key


def _git_calls(harness: Harness) -> list[tuple[str, ...]]:
    if not harness.git_log.is_file():
        return []
    return [
        tuple(line.split("\t"))
        for line in harness.git_log.read_text(encoding="utf-8-sig").splitlines()
        if line
    ]


def _marker(harness: Harness) -> dict[str, Any]:
    path = (
        harness.production
        / "data"
        / "alerts"
        / "quiet_window_merge_in_progress.json"
    )
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _assert_no_hard_reset(harness: Harness) -> None:
    assert not any(
        "reset" in call and "--hard" in call for call in _git_calls(harness)
    )


@WINDOWS_EXECUTION
def test_reconciliation_dry_run_does_not_mutate_production_or_scheduler(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    before = _production_state(harness)

    result = _invoke(harness, dry_run=True)

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode == 0, diagnostic
    assert "DRY RUN PASS" in result.stdout
    assert _production_state(harness) == before
    assert _start_lines(harness) == []
    invocation = _roll_invocations(harness)
    assert len(invocation) == 1
    assert invocation[0][:3] == ("good", LOCAL_BASELINE, PUBLISHED_TARGET)
    assert _roll_classifications(harness) == [
        {"exit_code": 0, "readable": True, "roll_free": True}
    ]
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize(
    ("roll_mode", "expected_exit", "expected_readable"),
    (
        ("exit_1", 1, False),
        ("exit_2", 2, True),
        ("exit_3", 3, True),
        ("missing_json", 3, False),
        ("stale_closure", 3, False),
        ("missing_closure", 3, False),
        ("dormant_closure", 2, False),
    ),
    ids=(
        "undecidable-exit-1",
        "roll-free-if-dormant-exit-2",
        "roll-sensitive-exit-3",
        "missing-json",
        "stale-closure-evidence",
        "missing-closure-evidence",
        "fresh-verdict-with-dormant-closure-evidence",
    ),
)
def test_roll_verdict_faults_remain_sensitive_and_dry_run_is_read_only(
    tmp_path: Path,
    roll_mode: str,
    expected_exit: int,
    expected_readable: bool,
) -> None:
    harness = _build_harness(tmp_path)
    before = _production_state(harness)

    result = _invoke(harness, dry_run=True, roll_mode=roll_mode)

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode == 0, diagnostic
    assert "DRY RUN PASS" in result.stdout
    assert _production_state(harness) == before
    assert _start_lines(harness) == []
    assert _stop_lines(harness) == []
    assert not harness.lease_log.exists()
    invocation = _roll_invocations(harness)
    assert len(invocation) == 1
    assert invocation[0][:3] == (roll_mode, LOCAL_BASELINE, PUBLISHED_TARGET)
    assert _roll_classifications(harness) == [
        {
            "exit_code": expected_exit,
            "readable": expected_readable,
            "roll_free": False,
        }
    ]
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize("task_mode", ("good", "delayed_start"))
def test_reconciliation_success_builds_exact_c_m_and_publishes_once(
    tmp_path: Path,
    task_mode: str,
) -> None:
    harness = _build_harness(tmp_path)

    result = _invoke(harness, task_mode=task_mode)

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode == 0, diagnostic
    merge_commit = _rev(harness.production, "HEAD")
    assert _rev(harness.production, "master") == merge_commit
    assert _rev(harness.production, "origin/master") == merge_commit
    assert _rev(harness.origin, "refs/heads/master") == merge_commit
    parents = _git(
        harness.production, "rev-list", "--parents", "-n", "1", merge_commit
    ).stdout.split()
    assert len(parents) == 3
    assert parents[0] == merge_commit
    config_commit = parents[1]
    assert parents[2] == harness.published_target
    assert _git(
        harness.production, "rev-list", "--parents", "-n", "1", config_commit
    ).stdout.split() == [config_commit, LOCAL_BASELINE]
    assert set(
        _git(
            harness.production,
            "diff",
            "--name-only",
            harness.published_target,
            merge_commit,
        ).stdout.splitlines()
    ) == set(CONFIG_PATHS)
    for relative, expected in RAW_CONFIG_BYTES.items():
        assert (harness.production / relative).read_bytes() == expected
        assert _git_bytes(
            harness.production, "show", f"{merge_commit}:{relative}"
        ) == expected
        assert _git_bytes(
            harness.production, "show", f"{config_commit}:{relative}"
        ) == expected
    assert _start_lines(harness) == ["WeatherOneShotPush"]
    assert _stop_lines(harness) == []
    assert not (
        harness.production
        / "data"
        / "alerts"
        / "quiet_window_merge_in_progress.json"
    ).exists()
    report = json.loads(
        (
            harness.production / "data" / "alerts" / "quiet_window_merge_last.json"
        ).read_text(encoding="utf-8-sig")
    )
    assert report["stage"] == "pushed"
    assert report["merge_commit"] == merge_commit
    assert report["push_invocation_attempted"] is True
    assert report["push_run_observed"] is True
    assert report["push_terminal_proved"] is True
    assert report["push_runtime_state"] == "Ready"
    assert report["push_last_task_result"] == 0
    assert report["push_containment_breached"] is False
    assert report["publication_acknowledged"] is True
    for relative, expected in RAW_CONFIG_BYTES.items():
        snapshot_relative = report["reconciliation_snapshot_paths"][relative][
            "snapshot_path"
        ]
        assert (harness.production / snapshot_relative).read_bytes() == expected
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
def test_late_start_budget_refuses_before_any_production_mutation(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    before = _production_state(harness)

    result = _invoke(harness, now="2026-09-01T03:44:00")

    assert result.returncode != 0
    assert "publication time budget is already impossible before mutation" in result.stdout
    _assert_no_git_config_or_scheduler_mutation(before, _production_state(harness))
    assert not harness.lease_log.exists()
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize("task_mode", ("hang_after_start", "hang_coarse"))
def test_on_demand_task_is_stopped_and_terminally_proved_at_its_deadline(
    tmp_path: Path,
    task_mode: str,
) -> None:
    harness = _build_harness(tmp_path)

    result = _invoke(harness, task_mode=task_mode)

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, diagnostic
    assert _start_lines(harness) == ["WeatherOneShotPush"]
    assert _stop_lines(harness) == ["WeatherOneShotPush"]
    assert _rev(harness.origin, "refs/heads/master") == harness.published_target
    marker = _marker(harness)
    assert marker["push_invocation_attempted"] is True
    assert marker["push_stop_attempted"] is True
    assert marker["push_stop_count"] == 1
    assert marker["push_terminal_proved"] is True
    assert marker["push_runtime_state"] == "Ready"
    assert marker["push_containment_breached"] is False
    assert harness.lease_log.read_text(encoding="utf-8-sig").splitlines() == [
        "enter",
        "exit",
    ]
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize(
    ("task_mode", "run_observed"),
    (
        ("queued_after_start", True),
        ("start_fail_before_dispatch", False),
    ),
)
def test_ambiguous_dispatch_states_are_stopped_then_terminally_proved(
    tmp_path: Path,
    task_mode: str,
    run_observed: bool,
) -> None:
    harness = _build_harness(tmp_path)

    result = _invoke(harness, task_mode=task_mode)

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, diagnostic
    assert _start_lines(harness) == ["WeatherOneShotPush"]
    assert _stop_lines(harness) == ["WeatherOneShotPush"]
    assert _rev(harness.origin, "refs/heads/master") == harness.published_target
    marker = _marker(harness)
    assert marker["push_invocation_attempted"] is True
    assert marker["push_run_observed"] is run_observed
    assert marker["push_stop_count"] == 1
    assert marker["push_terminal_proved"] is True
    assert marker["push_runtime_state"] == "Ready"
    assert harness.lease_log.read_text(encoding="utf-8-sig").splitlines() == [
        "enter",
        "exit",
    ]
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
def test_persistent_stop_failure_keeps_lease_and_never_reports_terminal(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)

    with pytest.raises(subprocess.TimeoutExpired):
        _invoke(harness, task_mode="stop_noop", timeout=10)

    assert _start_lines(harness) == ["WeatherOneShotPush"]
    assert _stop_lines(harness) == ["WeatherOneShotPush"] * 2
    assert _rev(harness.origin, "refs/heads/master") == harness.published_target
    assert harness.lease_log.read_text(encoding="utf-8-sig").splitlines() == [
        "enter"
    ]
    marker = _marker(harness)
    assert marker["push_invocation_attempted"] is True
    assert marker["push_stop_attempted"] is True
    assert marker["push_stop_count"] == 2
    assert marker["push_stop_exhausted"] is True
    assert marker["push_terminal_proved"] is False
    assert any(record[0].startswith("2026-09-01T04:00:00") for record in _sleep_records(harness))
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
def test_post_start_readback_failure_uses_bounded_post_window_polling(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)

    with pytest.raises(subprocess.TimeoutExpired):
        _invoke(harness, task_mode="readback_failure", timeout=10)

    assert _start_lines(harness) == ["WeatherOneShotPush"]
    assert _stop_lines(harness) == ["WeatherOneShotPush"] * 2
    assert _rev(harness.origin, "refs/heads/master") == harness.published_target
    assert harness.lease_log.read_text(encoding="utf-8-sig").splitlines() == [
        "enter"
    ]
    marker = _marker(harness)
    assert marker["push_invocation_attempted"] is True
    assert marker["push_stop_count"] == 2
    assert marker["push_stop_exhausted"] is True
    assert marker["push_terminal_proved"] is False
    post_window_sleeps = [
        record
        for record in _sleep_records(harness)
        if record[0].startswith("2026-09-01T04:00:00")
    ]
    assert post_window_sleeps
    assert all(record[2] == 2000 for record in post_window_sleeps)
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize(
    "variation",
    (
        "wrong_local",
        "wrong_head",
        "wrong_branch",
        "wrong_published",
        "moved_cached_target",
        "wrong_source_tip",
        "wrong_source_tree",
        "wrong_source_sha",
        "wrong_origin",
        "moved_remote",
        "nonancestor",
        "config_blob",
        "unexpected_dirty",
    ),
)
def test_reconciliation_adversarial_preflight_refuses_before_git_mutation(
    tmp_path: Path,
    variation: str,
) -> None:
    harness = _build_harness(
        tmp_path,
        unrelated_target=variation == "nonancestor",
        changed_target_config=variation == "config_blob",
    )
    invoke: dict[str, Any] = {}
    if variation == "wrong_local":
        invoke["expected_local"] = "0" * 40
    elif variation == "wrong_head":
        _git(
            harness.production,
            "checkout",
            "--force",
            "-B",
            "master",
            f"{LOCAL_BASELINE}^",
        )
        for relative, raw_bytes in RAW_CONFIG_BYTES.items():
            (harness.production / relative).write_bytes(raw_bytes)
    elif variation == "wrong_branch":
        _git(harness.production, "checkout", "-b", "not-master")
    elif variation == "wrong_published":
        invoke["expected_published"] = "1" * 40
    elif variation == "moved_cached_target":
        _git(
            harness.production,
            "update-ref",
            "refs/remotes/origin/master",
            LOCAL_BASELINE,
        )
    elif variation == "wrong_source_tip":
        invoke["expected_source_tip"] = "2" * 40
    elif variation == "wrong_source_tree":
        invoke["expected_source_tree"] = "3" * 40
    elif variation == "wrong_source_sha":
        invoke["expected_self_sha256"] = "4" * 64
    elif variation == "wrong_origin":
        _git(
            harness.production,
            "remote",
            "set-url",
            "origin",
            str((harness.root / "wrong-origin.git").resolve()),
        )
    elif variation == "moved_remote":
        moved = _make_unrelated_target(harness.origin)
        _git(
            harness.root,
            f"--git-dir={harness.origin}",
            "update-ref",
            "refs/heads/master",
            moved,
        )
        # Keep the production remote-tracking ref stale at T. The reconciler
        # must consult the canonical remote read-only, not trust this cache.
        assert _rev(harness.production, "origin/master") == harness.published_target
    elif variation == "unexpected_dirty":
        readme = harness.production / "README.md"
        readme.write_bytes(readme.read_bytes() + b"\nunexpected dirty path\n")
    before = _production_state(harness)

    result = _invoke(harness, **invoke)

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, diagnostic
    after = _production_state(harness)
    assert after["head"] == before["head"]
    assert after["master"] == before["master"]
    assert after["origin_master"] == before["origin_master"]
    assert after["status"] == before["status"]
    assert after["config"] == before["config"] == RAW_CONFIG_BYTES
    assert after["marker"] is None
    assert after["start_count"] == 0
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
def test_special_inputs_without_switch_refuse_without_entering_mutation(
    tmp_path: Path,
) -> None:
    harness = _build_harness(tmp_path)
    before = _production_state(harness)

    result = _invoke(harness, special_mode=False)

    assert result.returncode != 0
    assert "inputs require -ProductionBaselineReconciliation" in result.stdout
    _assert_no_git_config_or_scheduler_mutation(before, _production_state(harness))
    assert _start_lines(harness) == []
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize("task_mode", ("absent", "running", "disabled", "ambiguous"))
def test_reconciliation_refuses_unsafe_one_shot_task_states_before_mutation(
    tmp_path: Path,
    task_mode: str,
) -> None:
    harness = _build_harness(tmp_path)
    before = _production_state(harness)

    result = _invoke(harness, task_mode=task_mode)

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, diagnostic
    _assert_no_git_config_or_scheduler_mutation(before, _production_state(harness))
    assert _start_lines(harness) == []
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize(
    ("failure", "rolled_back", "phase", "push_attempted"),
    (
        ("merge_conflict", True, None, None),
        ("capture", True, None, None),
        ("documentation", False, "merge_committed_unpublished", False),
        ("task_mismatch", False, "documented_unpublished", False),
        ("start_failure", False, "documented_unpublished", True),
        ("push_failure", False, "documented_unpublished", True),
        ("no_ack", False, "documented_unpublished", True),
        ("prepush_drift", False, "documented_unpublished", False),
    ),
)
def test_reconciliation_failure_injections_preserve_safe_state(
    tmp_path: Path,
    failure: str,
    rolled_back: bool,
    phase: str | None,
    push_attempted: bool | None,
) -> None:
    harness = _build_harness(tmp_path)
    invoke: dict[str, Any] = {}
    if failure == "merge_conflict":
        invoke["git_mode"] = "merge_conflict"
    elif failure == "capture":
        invoke["capture_fail_at"] = 2
    elif failure == "documentation":
        invoke["docs_fail"] = True
    elif failure == "task_mismatch":
        invoke["task_mode"] = "mismatch_after_two"
    elif failure == "start_failure":
        invoke["task_mode"] = "start_fail"
    elif failure == "push_failure":
        invoke["task_mode"] = "push_failure"
    elif failure == "no_ack":
        invoke["task_mode"] = "no_ack"
    elif failure == "prepush_drift":
        invoke["prepush_drift"] = True

    result = _invoke(harness, **invoke)

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, diagnostic
    assert _rev(harness.origin, "refs/heads/master") == harness.published_target
    if rolled_back:
        assert _rev(harness.production, "HEAD") == LOCAL_BASELINE
        assert not (
            harness.production
            / "data"
            / "alerts"
            / "quiet_window_merge_in_progress.json"
        ).exists()
        for relative, expected in RAW_CONFIG_BYTES.items():
            assert (harness.production / relative).read_bytes() == expected
        assert _start_lines(harness) == []
    else:
        merge_commit = _rev(harness.production, "HEAD")
        parents = _git(
            harness.production, "rev-list", "--parents", "-n", "1", merge_commit
        ).stdout.split()
        assert len(parents) == 3
        assert parents[2] == harness.published_target
        marker = _marker(harness)
        assert marker["phase"] == phase
        assert marker["pre_merge_commit"] == parents[1]
        assert marker["merge_commit"] == merge_commit
        assert marker["push_invocation_attempted"] is push_attempted
        expected_starts = (
            1
            if failure in {"start_failure", "push_failure", "no_ack"}
            else 0
        )
        assert len(_start_lines(harness)) == expected_starts
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize(
    (
        "phase",
        "occurrence",
        "retained_phase",
        "sentinel",
        "push_attempted",
        "terminal_proved",
        "start_count",
        "remote_published",
    ),
    (
        ("reconciliation_preparing", 1, None, False, False, False, 0, False),
        (
            "reconciliation_prepared",
            1,
            "reconciliation_preparing",
            True,
            False,
            False,
            0,
            False,
        ),
        (
            "reconciliation_merge_uncommitted",
            1,
            "reconciliation_prepared",
            True,
            False,
            False,
            0,
            False,
        ),
        (
            "reconciliation_capture_recovered_uncommitted",
            1,
            "reconciliation_merge_uncommitted",
            True,
            False,
            False,
            0,
            False,
        ),
        (
            "merge_committed_unpublished",
            1,
            "reconciliation_capture_recovered_uncommitted",
            True,
            False,
            False,
            0,
            False,
        ),
        (
            "documented_unpublished",
            1,
            "merge_committed_unpublished",
            False,
            False,
            False,
            0,
            False,
        ),
        (
            "documented_unpublished",
            2,
            "documented_unpublished",
            False,
            False,
            False,
            0,
            False,
        ),
        (
            "documented_unpublished",
            3,
            "documented_unpublished",
            False,
            True,
            False,
            0,
            False,
        ),
        (
            "documented_unpublished",
            4,
            "documented_unpublished",
            False,
            True,
            False,
            1,
            True,
        ),
        (
            "published",
            1,
            "documented_unpublished",
            False,
            True,
            True,
            1,
            True,
        ),
    ),
)
def test_marker_replacement_failure_preserves_the_prior_safe_marker(
    tmp_path: Path,
    phase: str,
    occurrence: int,
    retained_phase: str | None,
    sentinel: bool,
    push_attempted: bool,
    terminal_proved: bool,
    start_count: int,
    remote_published: bool,
) -> None:
    harness = _build_harness(tmp_path)

    result = _invoke(
        harness,
        fail_marker_phase=phase,
        fail_marker_occurrence=occurrence,
    )

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, diagnostic
    if retained_phase is None:
        assert not harness.observed_marker.exists()
        assert _rev(harness.production, "HEAD") == LOCAL_BASELINE
        assert _start_lines(harness) == []
        assert _rev(harness.origin, "refs/heads/master") == harness.published_target
        _assert_no_hard_reset(harness)
        return

    assert harness.observed_marker.is_file(), diagnostic
    observed = json.loads(harness.observed_marker.read_text(encoding="utf-8-sig"))
    assert observed["phase"] == retained_phase
    assert observed["push_invocation_attempted"] is push_attempted
    assert observed.get("push_terminal_proved", False) is terminal_proved
    if sentinel:
        assert observed["pre_merge_commit"] == harness.published_target
        assert observed["pre_merge_commit"] != observed.get(
            "reconciliation_actual_pre_merge_commit"
        )
        assert observed.get("merge_commit") in (None, "")
    else:
        assert observed["pre_merge_commit"] == observed.get(
            "reconciliation_actual_pre_merge_commit"
        )
        assert observed.get("merge_commit")
    assert len(_start_lines(harness)) == start_count
    expected_remote = (
        _rev(harness.production, "HEAD")
        if remote_published
        else harness.published_target
    )
    assert _rev(harness.origin, "refs/heads/master") == expected_remote
    _assert_no_hard_reset(harness)


@WINDOWS_EXECUTION
@pytest.mark.parametrize(
    ("phase", "occurrence", "active_phase", "backup_phase", "attempted"),
    (
        (
            "merge_committed_unpublished",
            1,
            "merge_committed_unpublished",
            "reconciliation_capture_recovered_uncommitted",
            False,
        ),
        (
            "documented_unpublished",
            2,
            "documented_unpublished",
            "documented_unpublished",
            True,
        ),
    ),
)
def test_post_replace_fault_retains_complete_active_and_prior_marker_bytes(
    tmp_path: Path,
    phase: str,
    occurrence: int,
    active_phase: str,
    backup_phase: str,
    attempted: bool,
) -> None:
    harness = _build_harness(tmp_path)

    result = _invoke(
        harness,
        fail_after_replace_phase=phase,
        fail_after_replace_occurrence=occurrence,
    )

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, diagnostic
    active = _marker(harness)
    assert active["phase"] == active_phase
    assert active["push_invocation_attempted"] is attempted
    backups = list(
        (harness.production / "data" / "alerts").glob(
            ".quiet_window_merge_in_progress.json.*.bak"
        )
    )
    assert len(backups) == 1
    prior = json.loads(backups[0].read_text(encoding="utf-8-sig"))
    assert prior["phase"] == backup_phase
    assert prior["push_invocation_attempted"] is False
    assert _start_lines(harness) == []
    assert _rev(harness.origin, "refs/heads/master") == harness.published_target
    _assert_no_hard_reset(harness)
