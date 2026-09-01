from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Any
from uuid import uuid4

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_SCRIPT = REPO_ROOT / "scripts" / "ops" / "boot_recovery.ps1"
ADOPTED_PRODUCTION_COMMIT = "3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac"
PUBLISHED_TARGET = "c932b54f8747df5cdefc4cc42f8454b6797f09ae"
EXPECTED_BOOT_SHA256 = "253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a"
EXPECTED_BOOT_BLOB = "8465de619d7c88fded5144d8903595fb4f8cc93a"
RECONCILIATION_BRANCH = "origin/master"
CONFIG_PATHS = (
    "config/locations.json",
    "config/location_market_events.json",
)
RAW_CONFIG_BYTES = {
    "config/locations.json": (
        b'{\n  "production_baseline_reconciliation_fixture": "locations"\n}\n'
    ),
    "config/location_market_events.json": (
        b'{\n  "production_baseline_reconciliation_fixture": "events"\n}\n'
    ),
}

REAL_GIT = shutil.which("git.exe") or shutil.which("git")
WINDOWS_POWERSHELL = shutil.which("powershell.exe")
WINDOWS_REPLAY = pytest.mark.skipif(
    os.name != "nt" or WINDOWS_POWERSHELL is None or REAL_GIT is None,
    reason="the adopted production boot script requires Windows PowerShell and Git",
)


@dataclass(frozen=True)
class SyntheticState:
    repo: Path
    config_commit: str | None
    merge_commit: str | None
    marker_path: Path
    marker_bytes: bytes | None
    evidence_bytes: dict[Path, bytes]


def _git(
    repo: Path,
    *arguments: str,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    assert REAL_GIT is not None
    git_env = os.environ.copy()
    git_env["GIT_LFS_SKIP_SMUDGE"] = "1"
    if env is not None:
        git_env.update(env)
    result = subprocess.run(
        [REAL_GIT, *arguments],
        cwd=repo,
        env=git_env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed with {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _rev_parse(repo: Path, revision: str) -> str:
    return _git(repo, "rev-parse", revision).stdout.strip().lower()


def _git_bytes(repo: Path, *arguments: str) -> bytes:
    assert REAL_GIT is not None
    git_env = os.environ.copy()
    git_env["GIT_LFS_SKIP_SMUDGE"] = "1"
    result = subprocess.run(
        [REAL_GIT, *arguments],
        cwd=repo,
        env=git_env,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed with {result.returncode}\n"
            f"stdout:\n{result.stdout!r}\nstderr:\n{result.stderr!r}"
        )
    return result.stdout


def _marker_hashes(repo: Path) -> dict[str, str]:
    return {
        relative: hashlib.sha256((repo / relative).read_bytes()).hexdigest()
        for relative in CONFIG_PATHS
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _json_bytes(payload)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)
    return encoded


def _marker(
    repo: Path,
    *,
    phase: str,
    pre_merge_commit: str,
    actual_pre_merge_commit: str,
    updated_at: str = "2026-09-01T05:20:00Z",
    merge_commit: str | None = None,
    capture_recovery_proved: bool = False,
    documentation_transaction_recorded: bool = False,
    documentation_transaction_pending_sha256: str | None = None,
    documentation_transaction_snapshot_path: str | None = None,
    push_invocation_attempted: bool = False,
    push_pre_last_run_time: str | None = None,
    push_observed_last_run_time: str | None = None,
    push_last_task_result: int | None = None,
    push_runtime_state: str | None = None,
    push_terminal_proved: bool = False,
    push_run_observed: bool = False,
    push_stop_attempted: bool = False,
    push_stop_count: int = 0,
    push_stop_exhausted: bool = False,
    push_start_issued_at: str | None = None,
    push_containment_deadline: str | None = None,
    push_terminal_proved_at: str | None = None,
    push_containment_breached: bool = False,
    publication_acknowledged: bool = False,
) -> dict[str, Any]:
    return {
        "schema": "quiet_window_merge_in_progress_v0.1",
        "updated_at": updated_at,
        "repo_root": str(repo.resolve()),
        "phase": phase,
        "branch": RECONCILIATION_BRANCH,
        "expected_tip": PUBLISHED_TARGET,
        "expected_baseline": ADOPTED_PRODUCTION_COMMIT,
        "resolved_branch_tip": PUBLISHED_TARGET,
        "baseline_commit": ADOPTED_PRODUCTION_COMMIT,
        "pre_merge_commit": pre_merge_commit,
        "merge_commit": merge_commit,
        "capture_recovery_proved": capture_recovery_proved,
        "execution_tape_recovery_required": False,
        "execution_tape_readoption_expected": False,
        "execution_tape_rolled_but_inactive_skipped": False,
        "execution_tape_recovery_proved": False,
        "execution_tape_source_before": None,
        "documentation_transaction_recorded": documentation_transaction_recorded,
        "documentation_transaction_pending_sha256": (
            documentation_transaction_pending_sha256
        ),
        "documentation_transaction_snapshot_path": (
            documentation_transaction_snapshot_path
        ),
        "push_invocation_attempted": push_invocation_attempted,
        "push_pre_last_run_time": push_pre_last_run_time,
        "push_observed_last_run_time": push_observed_last_run_time,
        "push_last_task_result": push_last_task_result,
        "push_runtime_state": push_runtime_state,
        "push_terminal_proved": push_terminal_proved,
        "push_run_observed": push_run_observed,
        "push_stop_attempted": push_stop_attempted,
        "push_stop_count": push_stop_count,
        "push_stop_exhausted": push_stop_exhausted,
        "push_start_issued_at": push_start_issued_at,
        "push_containment_deadline": push_containment_deadline,
        "push_terminal_proved_at": push_terminal_proved_at,
        "push_containment_breached": push_containment_breached,
        "publication_acknowledged": publication_acknowledged,
        "auto_refreshed_paths": list(CONFIG_PATHS),
        "auto_refreshed_sha256": _marker_hashes(repo),
        # Additive reconciliation evidence. The existing v0.1 identity fields stay
        # schema-compatible with the adopted boot consumer. Until M is proved,
        # pre_merge_commit deliberately remains the rejected target sentinel.
        "operation_mode": "production_baseline_reconciliation_v0.1",
        "reconciliation_local_baseline": ADOPTED_PRODUCTION_COMMIT,
        "reconciliation_published_target": PUBLISHED_TARGET,
        "reconciliation_actual_pre_merge_commit": actual_pre_merge_commit,
        "reconciliation_boot_guard_commit": PUBLISHED_TARGET,
    }


def _write_precommit_marker(
    repo: Path,
    *,
    phase: str,
    actual_pre_merge_commit: str,
    capture_recovery_proved: bool = False,
) -> bytes:
    assert phase.startswith("reconciliation_")
    assert phase != "preparing"
    payload = _marker(
        repo,
        phase=phase,
        pre_merge_commit=PUBLISHED_TARGET,
        actual_pre_merge_commit=actual_pre_merge_commit,
        capture_recovery_proved=capture_recovery_proved,
    )
    assert payload["baseline_commit"] == ADOPTED_PRODUCTION_COMMIT
    assert payload["expected_baseline"] == ADOPTED_PRODUCTION_COMMIT
    assert payload["pre_merge_commit"] == PUBLISHED_TARGET
    assert len(payload["reconciliation_actual_pre_merge_commit"]) == 40
    return _atomic_write_json(
        repo / "data" / "alerts" / "quiet_window_merge_in_progress.json",
        payload,
    )


def _clone_at_local_baseline(tmp_path: Path) -> Path:
    repo = tmp_path / "synthetic-production"
    _git(
        REPO_ROOT,
        "clone",
        "--shared",
        "--no-checkout",
        str(REPO_ROOT),
        str(repo),
    )
    for key, value in (
        ("user.name", "Production Reconciliation Replay"),
        ("user.email", "reconciliation-replay@example.invalid"),
        ("commit.gpgSign", "false"),
        ("core.autocrlf", "false"),
        ("gc.auto", "0"),
    ):
        _git(repo, "config", key, value)
    _git(repo, "checkout", "--force", "-B", "master", ADOPTED_PRODUCTION_COMMIT)
    _git(repo, "update-ref", "refs/remotes/origin/master", PUBLISHED_TARGET)
    assert _rev_parse(repo, "HEAD") == ADOPTED_PRODUCTION_COMMIT
    assert _rev_parse(repo, "origin/master") == PUBLISHED_TARGET
    return repo


def _write_raw_config(repo: Path) -> None:
    for relative, raw_bytes in RAW_CONFIG_BYTES.items():
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw_bytes)


def _write_pre_marker_snapshot(repo: Path) -> dict[Path, bytes]:
    """Model the durable raw snapshot that exists before the first marker."""
    snapshot_root = (
        repo
        / "data"
        / "alerts"
        / "production_baseline_reconciliation"
        / "synthetic-replay-snapshot"
    )
    evidence: dict[Path, bytes] = {}
    config_entries: dict[str, dict[str, Any]] = {}
    for relative, raw_bytes in RAW_CONFIG_BYTES.items():
        destination = snapshot_root / "raw" / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw_bytes)
        evidence[destination] = raw_bytes
        config_entries[relative] = {
            "snapshot_path": destination.relative_to(repo).as_posix(),
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "length": len(raw_bytes),
        }

    transcript_path = snapshot_root / "roll-verdict-output.txt"
    transcript_bytes = (
        b"synthetic fake-only roll-verdict transcript; no production command ran\n"
    )
    transcript_path.write_bytes(transcript_bytes)
    evidence[transcript_path] = transcript_bytes
    manifest_path = snapshot_root / "manifest.json"
    manifest_bytes = _atomic_write_json(
        manifest_path,
        {
            "schema": "production_baseline_reconciliation_snapshot_v0.1",
            "created_at": "2026-09-01T05:19:00Z",
            "local_baseline": ADOPTED_PRODUCTION_COMMIT,
            "published_target": PUBLISHED_TARGET,
            "config": config_entries,
            "roll_verdict": {
                "explicit_base": ADOPTED_PRODUCTION_COMMIT,
                "explicit_branch": PUBLISHED_TARGET,
                "exit_code": 0,
                "readable": True,
                "transcript_path": transcript_path.relative_to(repo).as_posix(),
                "transcript_sha256": hashlib.sha256(transcript_bytes).hexdigest(),
            },
            "dependency_sha256": {},
        },
    )
    evidence[manifest_path] = manifest_bytes
    return evidence


def _write_documentation_snapshot(
    repo: Path,
    merge_commit: str,
) -> tuple[str, str, dict[Path, bytes]]:
    payload = {
        "schema_version": "documentation_transaction_pending_v0.1",
        "status": "PENDING",
        "latest_integration_tip": merge_commit,
        "integrations": [
            {
                "integration_tip": merge_commit,
                "branch": RECONCILIATION_BRANCH,
                "expected_tip": PUBLISHED_TARGET,
            }
        ],
    }
    snapshot_bytes = _json_bytes(payload)
    pending_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()
    snapshot_relative = (
        "data/alerts/documentation_transactions/"
        f"pending-{pending_sha256}.json"
    )
    snapshot_path = repo / Path(snapshot_relative)
    pending_path = repo / "data" / "alerts" / "documentation_transaction_pending.json"
    assert _atomic_write_json(snapshot_path, payload) == snapshot_bytes
    assert _atomic_write_json(pending_path, payload) == snapshot_bytes
    return (
        pending_sha256,
        snapshot_relative,
        {snapshot_path: snapshot_bytes, pending_path: snapshot_bytes},
    )


def _commit_raw_config(repo: Path) -> str:
    _git(repo, "add", "--", *CONFIG_PATHS)
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": "2026-09-01T05:21:00Z",
            "GIT_COMMITTER_DATE": "2026-09-01T05:21:00Z",
        }
    )
    _git(
        repo,
        "commit",
        "--no-gpg-sign",
        "-m",
        "test: capture production raw config",
        env=commit_env,
    )
    config_commit = _rev_parse(repo, "HEAD")
    parents = _git(repo, "rev-list", "--parents", "-n", "1", config_commit).stdout.split()
    changed = set(
        filter(
            None,
            _git(
                repo,
                "diff",
                "--name-only",
                ADOPTED_PRODUCTION_COMMIT,
                config_commit,
            ).stdout.splitlines(),
        )
    )
    assert parents == [config_commit, ADOPTED_PRODUCTION_COMMIT]
    assert changed == set(CONFIG_PATHS)
    return config_commit


def _begin_target_merge(repo: Path) -> None:
    _git(repo, "merge", "--no-commit", "--no-ff", PUBLISHED_TARGET)
    merge_head = Path(_git(repo, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip())
    if not merge_head.is_absolute():
        merge_head = repo / merge_head
    assert merge_head.read_text(encoding="ascii").strip().lower() == PUBLISHED_TARGET


def _commit_target_merge(repo: Path, config_commit: str) -> str:
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": "2026-09-01T05:22:00Z",
            "GIT_COMMITTER_DATE": "2026-09-01T05:22:00Z",
        }
    )
    _git(
        repo,
        "commit",
        "--no-gpg-sign",
        "-m",
        "test: synthesize production reconciliation merge",
        env=commit_env,
    )
    merge_commit = _rev_parse(repo, "HEAD")
    parents = _git(repo, "rev-list", "--parents", "-n", "1", merge_commit).stdout.split()
    assert parents == [merge_commit, config_commit, PUBLISHED_TARGET]
    return merge_commit


def _build_synthetic_state(tmp_path: Path, boundary: str) -> SyntheticState:
    repo = _clone_at_local_baseline(tmp_path)
    marker_path = repo / "data" / "alerts" / "quiet_window_merge_in_progress.json"
    _write_raw_config(repo)
    evidence_bytes = _write_pre_marker_snapshot(repo)
    if boundary == "snapshot_before_marker":
        assert not marker_path.exists()
        return SyntheticState(
            repo, None, None, marker_path, None, dict(evidence_bytes)
        )

    marker_bytes = _write_precommit_marker(
        repo,
        phase="reconciliation_preparing",
        actual_pre_merge_commit=ADOPTED_PRODUCTION_COMMIT,
    )
    if boundary == "marker_before_config_commit":
        return SyntheticState(
            repo, None, None, marker_path, marker_bytes, dict(evidence_bytes)
        )

    config_commit = _commit_raw_config(repo)
    marker_bytes = _write_precommit_marker(
        repo,
        phase="reconciliation_prepared",
        actual_pre_merge_commit=config_commit,
    )
    if boundary == "after_config_commit":
        return SyntheticState(
            repo,
            config_commit,
            None,
            marker_path,
            marker_bytes,
            dict(evidence_bytes),
        )

    _begin_target_merge(repo)
    marker_bytes = _write_precommit_marker(
        repo,
        phase="reconciliation_merge_uncommitted",
        actual_pre_merge_commit=config_commit,
    )
    if boundary in {"merge_head_abort_success", "merge_head_abort_failure"}:
        return SyntheticState(
            repo,
            config_commit,
            None,
            marker_path,
            marker_bytes,
            dict(evidence_bytes),
        )

    marker_bytes = _write_precommit_marker(
        repo,
        phase="reconciliation_capture_recovered_uncommitted",
        actual_pre_merge_commit=config_commit,
        capture_recovery_proved=True,
    )
    merge_commit = _commit_target_merge(repo, config_commit)
    if boundary == "merge_commit_before_postcommit_marker":
        return SyntheticState(
            repo,
            config_commit,
            merge_commit,
            marker_path,
            marker_bytes,
            dict(evidence_bytes),
        )

    # This is the one permitted semantic switch: only after exact [C, T] is
    # proved do the canonical boot-consumed fields atomically expose C and M.
    canonical = _marker(
        repo,
        phase="merge_committed_unpublished",
        pre_merge_commit=config_commit,
        actual_pre_merge_commit=config_commit,
        merge_commit=merge_commit,
        capture_recovery_proved=True,
    )
    assert _rev_parse(repo, "HEAD") == merge_commit
    assert _git(repo, "rev-list", "--parents", "-n", "1", merge_commit).stdout.split() == [
        merge_commit,
        config_commit,
        PUBLISHED_TARGET,
    ]
    marker_bytes = _atomic_write_json(marker_path, canonical)
    if boundary == "complete_postcommit_marker":
        return SyntheticState(
            repo,
            config_commit,
            merge_commit,
            marker_path,
            marker_bytes,
            dict(evidence_bytes),
        )

    pending_sha256, snapshot_relative, documentation_bytes = (
        _write_documentation_snapshot(repo, merge_commit)
    )
    evidence_bytes.update(documentation_bytes)
    push_attempted = boundary in {
        "push_attempted_unpublished",
        "containment_stop_attempted_unpublished",
        "containment_stop_exhausted_unpublished",
        "terminal_containment_breached_unpublished",
        "terminal_unpublished_marker",
        "origin_ack_before_published_marker",
        "complete_published_marker",
    }
    push_terminal_proved = boundary in {
        "terminal_containment_breached_unpublished",
        "terminal_unpublished_marker",
        "origin_ack_before_published_marker",
        "complete_published_marker",
    }
    push_stop_attempted = boundary in {
        "containment_stop_attempted_unpublished",
        "containment_stop_exhausted_unpublished",
        "terminal_containment_breached_unpublished",
    }
    push_stop_count = {
        "containment_stop_attempted_unpublished": 1,
        "containment_stop_exhausted_unpublished": 2,
        "terminal_containment_breached_unpublished": 2,
    }.get(boundary, 0)
    push_stop_exhausted = boundary in {
        "containment_stop_exhausted_unpublished",
        "terminal_containment_breached_unpublished",
    }
    push_containment_breached = (
        boundary == "terminal_containment_breached_unpublished"
    )
    publication_acknowledged = boundary == "complete_published_marker"
    if boundary in {
        "origin_ack_before_published_marker",
        "complete_published_marker",
    }:
        # Fake local remote-tracking acknowledgement only. No remote or network
        # is configured or contacted by this replay fixture.
        _git(repo, "update-ref", "refs/remotes/origin/master", merge_commit)

    if publication_acknowledged:
        phase = "published"
    else:
        assert boundary in {
            "documented_unpublished",
            "push_attempted_unpublished",
            "containment_stop_attempted_unpublished",
            "containment_stop_exhausted_unpublished",
            "terminal_containment_breached_unpublished",
            "terminal_unpublished_marker",
            "origin_ack_before_published_marker",
        }
        phase = "documented_unpublished"
    canonical = _marker(
        repo,
        phase=phase,
        pre_merge_commit=config_commit,
        actual_pre_merge_commit=config_commit,
        updated_at=(
            "2026-09-01T08:00:02.0000000Z"
            if push_containment_breached
            else "2026-09-01T05:20:00Z"
        ),
        merge_commit=merge_commit,
        capture_recovery_proved=True,
        documentation_transaction_recorded=True,
        documentation_transaction_pending_sha256=pending_sha256,
        documentation_transaction_snapshot_path=snapshot_relative,
        push_invocation_attempted=push_attempted,
        push_pre_last_run_time=(
            "2026-09-01T04:30:00.0000000Z" if push_attempted else None
        ),
        push_observed_last_run_time=(
            "2026-09-01T05:00:01.0000000Z"
            if push_terminal_proved or push_stop_attempted
            else None
        ),
        push_last_task_result=(
            0 if push_terminal_proved else 267009 if push_stop_attempted else None
        ),
        push_runtime_state=(
            "Ready"
            if push_terminal_proved
            else "Running"
            if push_stop_attempted
            else None
        ),
        push_terminal_proved=push_terminal_proved,
        push_run_observed=push_terminal_proved,
        push_stop_attempted=push_stop_attempted,
        push_stop_count=push_stop_count,
        push_stop_exhausted=push_stop_exhausted,
        push_start_issued_at=(
            "2026-09-01T05:00:00.0000000Z" if push_attempted else None
        ),
        push_containment_deadline=(
            "2026-09-01T05:15:00.0000000Z" if push_attempted else None
        ),
        push_terminal_proved_at=(
            "2026-09-01T08:00:01.0000000Z"
            if push_containment_breached
            else "2026-09-01T05:02:00.0000000Z"
            if push_terminal_proved
            else None
        ),
        push_containment_breached=push_containment_breached,
        publication_acknowledged=publication_acknowledged,
    )
    marker_bytes = _atomic_write_json(marker_path, canonical)
    return SyntheticState(
        repo,
        config_commit,
        merge_commit,
        marker_path,
        marker_bytes,
        dict(evidence_bytes),
    )


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _write_adapted_boot_script(tmp_path: Path, repo: Path) -> Path:
    source = BOOT_SCRIPT.read_bytes()
    assert hashlib.sha256(source).hexdigest() == EXPECTED_BOOT_SHA256
    assert _git(REPO_ROOT, "hash-object", str(BOOT_SCRIPT)).stdout.strip() == EXPECTED_BOOT_BLOB
    needle = b'$repo = "C:\\Users\\micha\\Desktop\\github\\weather"'
    replacement = f"$repo = {_powershell_quote(str(repo.resolve()))}".encode("utf-8")
    assert source.count(needle) == 1
    adapted = source.replace(needle, replacement)
    assert adapted.count(replacement) == 1
    assert adapted.replace(replacement, needle, 1) == source
    destination = tmp_path / "adopted_boot_recovery_replay.ps1"
    destination.write_bytes(adapted)
    return destination


def _write_instrumentation_wrapper(tmp_path: Path) -> Path:
    wrapper = tmp_path / "invoke_adopted_boot_replay.ps1"
    wrapper.write_text(
        r'''$ErrorActionPreference = "Stop"

function global:Get-CimInstance {
    [CmdletBinding()]
    param([Parameter(Position = 0)][string]$ClassName)

    if ($ClassName -eq "Win32_OperatingSystem") {
        return [PSCustomObject]@{ LastBootUpTime = (Get-Date).AddMinutes(-10) }
    }
    return @()
}

function global:Get-WinEvent {
    [CmdletBinding()]
    param([hashtable]$FilterHashtable, [int]$MaxEvents)
    return $null
}

function global:git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArguments)

    [IO.File]::AppendAllText(
        $env:BOOT_REPLAY_GIT_LOG,
        (($GitArguments -join "`t") + [Environment]::NewLine)
    )
    $isHardReset = $GitArguments.Count -ge 2 -and
        $GitArguments[0] -ceq "reset" -and
        $GitArguments[1] -ceq "--hard"
    $isBlockedAbort = $env:BOOT_REPLAY_FAIL_ABORT -eq "1" -and
        $GitArguments.Count -ge 2 -and
        $GitArguments[0] -ceq "merge" -and
        $GitArguments[1] -ceq "--abort"
    if ($isHardReset -or $isBlockedAbort) {
        $label = if ($isHardReset) { "HARD_RESET_BLOCKED" } else { "ABORT_BLOCKED" }
        [IO.File]::AppendAllText(
            $env:BOOT_REPLAY_GIT_LOG,
            ($label + [Environment]::NewLine)
        )
        & $env:BOOT_REPLAY_REAL_GIT -C $env:BOOT_REPLAY_REPO `
            __boot_replay_forced_failure__ 2>$null
        $nativeExit = $LASTEXITCODE
        $global:LASTEXITCODE = $nativeExit
        return
    }

    & $env:BOOT_REPLAY_REAL_GIT -C $env:BOOT_REPLAY_REPO @GitArguments
    $nativeExit = $LASTEXITCODE
    $global:LASTEXITCODE = $nativeExit
}

& $env:BOOT_REPLAY_SCRIPT -NoWait
exit $LASTEXITCODE
''',
        encoding="utf-8",
    )
    return wrapper


def _run_adopted_boot(
    tmp_path: Path,
    state: SyntheticState,
    *,
    fail_abort: bool,
) -> tuple[subprocess.CompletedProcess[str], list[tuple[str, ...]], dict[str, Any]]:
    assert WINDOWS_POWERSHELL is not None
    assert REAL_GIT is not None
    adapted = _write_adapted_boot_script(tmp_path, state.repo)
    wrapper = _write_instrumentation_wrapper(tmp_path)
    git_log = tmp_path / "boot-git.log"
    environment = os.environ.copy()
    environment.update(
        {
            "BOOT_REPLAY_SCRIPT": str(adapted),
            "BOOT_REPLAY_REAL_GIT": REAL_GIT,
            "BOOT_REPLAY_REPO": str(state.repo.resolve()),
            "BOOT_REPLAY_GIT_LOG": str(git_log),
            "BOOT_REPLAY_FAIL_ABORT": "1" if fail_abort else "0",
        }
    )
    result = subprocess.run(
        [
            WINDOWS_POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(wrapper),
        ],
        cwd=state.repo,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        check=False,
    )
    calls = [
        tuple(line.split("\t"))
        for line in git_log.read_text(encoding="utf-8-sig").splitlines()
        if line and not line.endswith("_BLOCKED")
    ]
    event_path = state.repo / "data" / "alerts" / "boot_events.jsonl"
    assert event_path.is_file(), f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    event_lines = event_path.read_text(encoding="utf-8-sig").splitlines()
    event = json.loads(event_lines[-1])
    return result, calls, event


def _merge_head_exists(repo: Path) -> bool:
    merge_head = Path(_git(repo, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip())
    if not merge_head.is_absolute():
        merge_head = repo / merge_head
    return merge_head.is_file()


def test_replay_is_pinned_to_the_exact_adopted_production_boot_blob() -> None:
    if REAL_GIT is None:
        pytest.skip("Git is required to verify the adopted production blob")

    source = BOOT_SCRIPT.read_bytes()
    adopted_spec = f"{ADOPTED_PRODUCTION_COMMIT}:scripts/ops/boot_recovery.ps1"
    adopted_blob = _git(REPO_ROOT, "rev-parse", adopted_spec).stdout.strip().lower()
    adopted_source = subprocess.run(
        [REAL_GIT, "show", adopted_spec],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    ).stdout

    assert hashlib.sha256(source).hexdigest() == EXPECTED_BOOT_SHA256
    assert _git(REPO_ROOT, "hash-object", str(BOOT_SCRIPT)).stdout.strip() == EXPECTED_BOOT_BLOB
    assert adopted_blob == EXPECTED_BOOT_BLOB
    assert source == adopted_source


def test_target_sentinel_is_rejected_by_the_adopted_premerge_predicate() -> None:
    if REAL_GIT is None:
        pytest.skip("Git is required to verify the exact reconciliation topology")

    ancestry = _git(
        REPO_ROOT,
        "merge-base",
        "--is-ancestor",
        ADOPTED_PRODUCTION_COMMIT,
        PUBLISHED_TARGET,
        check=False,
    )
    target_parents = _git(
        REPO_ROOT, "rev-list", "--parents", "-n", "1", PUBLISHED_TARGET
    ).stdout.split()
    changed = set(
        _git(
            REPO_ROOT,
            "diff",
            "--name-only",
            ADOPTED_PRODUCTION_COMMIT,
            PUBLISHED_TARGET,
        ).stdout.splitlines()
    )

    assert ancestry.returncode == 0
    assert PUBLISHED_TARGET != ADOPTED_PRODUCTION_COMMIT
    assert target_parents[:2] == [PUBLISHED_TARGET, ADOPTED_PRODUCTION_COMMIT]
    assert len(target_parents) == 3  # T is a merge, not a one-parent config child.
    assert changed - set(CONFIG_PATHS)  # T also changes non-allowlisted paths.
    for relative in CONFIG_PATHS:
        assert _rev_parse(
            REPO_ROOT, f"{ADOPTED_PRODUCTION_COMMIT}:{relative}"
        ) == _rev_parse(REPO_ROOT, f"{PUBLISHED_TARGET}:{relative}")


@WINDOWS_REPLAY
@pytest.mark.parametrize(
    "boundary",
    [
        "snapshot_before_marker",
        "marker_before_config_commit",
        "after_config_commit",
        "merge_head_abort_success",
        "merge_head_abort_failure",
        "merge_commit_before_postcommit_marker",
        "complete_postcommit_marker",
        "documented_unpublished",
        "push_attempted_unpublished",
        "containment_stop_attempted_unpublished",
        "containment_stop_exhausted_unpublished",
        "terminal_containment_breached_unpublished",
        "terminal_unpublished_marker",
        "origin_ack_before_published_marker",
        "complete_published_marker",
    ],
)
def test_adopted_boot_replay_never_reaches_hard_reset(
    tmp_path: Path,
    boundary: str,
) -> None:
    state = _build_synthetic_state(tmp_path, boundary)
    if state.marker_bytes is not None:
        marker_payload = json.loads(state.marker_bytes)
        assert {
            "push_stop_attempted",
            "push_stop_count",
            "push_stop_exhausted",
            "push_start_issued_at",
            "push_containment_deadline",
            "push_terminal_proved_at",
            "push_containment_breached",
        } <= marker_payload.keys()
        if boundary == "terminal_containment_breached_unpublished":
            assert marker_payload["push_stop_attempted"] is True
            assert marker_payload["push_stop_count"] == 2
            assert marker_payload["push_stop_exhausted"] is True
            assert marker_payload["push_terminal_proved"] is True
            assert marker_payload["push_containment_breached"] is True
    fail_abort = boundary == "merge_head_abort_failure"
    pre_boot_head = _rev_parse(state.repo, "HEAD")
    pre_boot_merge_head = _merge_head_exists(state.repo)
    result, git_calls, event = _run_adopted_boot(
        tmp_path,
        state,
        fail_abort=fail_abort,
    )

    diagnostic = f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    expected_exit = 2 if boundary == "snapshot_before_marker" else 3
    assert result.returncode == expected_exit, diagnostic
    assert not any(call[:2] == ("reset", "--hard") for call in git_calls), diagnostic
    assert not any(
        call and call[0] in {"fetch", "push", "ls-remote"} for call in git_calls
    ), diagnostic
    if state.marker_bytes is None:
        assert not state.marker_path.exists()
    else:
        assert state.marker_path.read_bytes() == state.marker_bytes
    for evidence_path, expected_bytes in state.evidence_bytes.items():
        assert evidence_path.read_bytes() == expected_bytes
    for relative, raw_bytes in RAW_CONFIG_BYTES.items():
        assert (state.repo / relative).read_bytes() == raw_bytes

    if boundary == "snapshot_before_marker":
        assert pre_boot_head == ADOPTED_PRODUCTION_COMMIT
        assert _rev_parse(state.repo, "HEAD") == ADOPTED_PRODUCTION_COMMIT
        assert not _merge_head_exists(state.repo)
        assert set(_git(state.repo, "diff", "--name-only").stdout.splitlines()) == set(
            CONFIG_PATHS
        )
        assert event["merge_marker_phase"] is None
        assert event["interrupted_merge_recovery_failed"] is False
        assert event["merge_reconciliation_required"] is False
    elif boundary == "marker_before_config_commit":
        assert pre_boot_head == ADOPTED_PRODUCTION_COMMIT
        assert _rev_parse(state.repo, "HEAD") == ADOPTED_PRODUCTION_COMMIT
        assert not _merge_head_exists(state.repo)
        assert set(_git(state.repo, "diff", "--name-only").stdout.splitlines()) == set(
            CONFIG_PATHS
        )
        assert event["merge_marker_phase"] == "reconciliation_preparing"
        assert event["interrupted_merge_recovery_failed"] is True
        assert event["merge_reconciliation_required"] is False
    elif boundary == "after_config_commit":
        assert state.config_commit is not None
        assert pre_boot_head == state.config_commit
        assert _rev_parse(state.repo, "HEAD") == state.config_commit
        assert not _merge_head_exists(state.repo)
        assert event["merge_marker_phase"] == "reconciliation_prepared"
        assert event["interrupted_merge_recovery_failed"] is True
        assert event["merge_reconciliation_required"] is False
    elif boundary in {"merge_head_abort_success", "merge_head_abort_failure"}:
        assert state.config_commit is not None
        assert pre_boot_merge_head is True
        assert ("merge", "--abort") in git_calls
        assert _rev_parse(state.repo, "HEAD") == state.config_commit
        assert _merge_head_exists(state.repo) is fail_abort
        assert event["merge_marker_phase"] == "reconciliation_merge_uncommitted"
        assert event["interrupted_merge_recovery_failed"] is True
        assert event["merge_reconciliation_required"] is False
    elif boundary == "merge_commit_before_postcommit_marker":
        assert state.merge_commit is not None
        assert pre_boot_head == state.merge_commit
        assert _rev_parse(state.repo, "HEAD") == state.merge_commit
        assert not _merge_head_exists(state.repo)
        assert event["merge_marker_phase"] == (
            "reconciliation_capture_recovered_uncommitted"
        )
        assert event["interrupted_merge_recovery_failed"] is True
        assert event["merge_reconciliation_required"] is False
    else:
        assert boundary in {
            "complete_postcommit_marker",
            "documented_unpublished",
            "push_attempted_unpublished",
            "containment_stop_attempted_unpublished",
            "containment_stop_exhausted_unpublished",
            "terminal_containment_breached_unpublished",
            "terminal_unpublished_marker",
            "origin_ack_before_published_marker",
            "complete_published_marker",
        }
        assert state.config_commit is not None
        assert state.merge_commit is not None
        assert pre_boot_head == state.merge_commit
        assert _rev_parse(state.repo, "HEAD") == state.merge_commit
        assert not _merge_head_exists(state.repo)
        expected_phase = {
            "complete_postcommit_marker": "merge_committed_unpublished",
            "documented_unpublished": "documented_unpublished",
            "push_attempted_unpublished": "documented_unpublished",
            "containment_stop_attempted_unpublished": "documented_unpublished",
            "containment_stop_exhausted_unpublished": "documented_unpublished",
            "terminal_containment_breached_unpublished": "documented_unpublished",
            "terminal_unpublished_marker": "documented_unpublished",
            "origin_ack_before_published_marker": "documented_unpublished",
            "complete_published_marker": "published",
        }[boundary]
        assert event["merge_marker_phase"] == expected_phase
        assert event["interrupted_merge_recovery_failed"] is False
        assert event["merge_reconciliation_required"] is True
        expected_origin = (
            state.merge_commit
            if boundary
            in {"origin_ack_before_published_marker", "complete_published_marker"}
            else PUBLISHED_TARGET
        )
        assert _rev_parse(state.repo, "origin/master") == expected_origin
        assert event["origin_master"] == expected_origin
        assert _git(
            state.repo,
            "rev-list",
            "--parents",
            "-n",
            "1",
            state.merge_commit,
        ).stdout.split() == [state.merge_commit, state.config_commit, PUBLISHED_TARGET]

    if state.config_commit is not None:
        for relative, raw_bytes in RAW_CONFIG_BYTES.items():
            assert _git_bytes(
                state.repo,
                "show",
                f"{_rev_parse(state.repo, 'HEAD')}:{relative}",
            ) == raw_bytes
