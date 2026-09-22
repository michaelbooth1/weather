"""Executes reconcile_ordinary_quiet_merge.ps1 against a fake production repo."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "reconcile_ordinary_quiet_merge.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None or shutil.which("git") is None,
    reason="Windows PowerShell 5.1 and git are required",
)

CONFIG_PATHS = ("config/locations.json", "config/location_market_events.json")


def _git(repo: Path, *args: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@x", GIT_CONFIG_NOSYSTEM="1")
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True)
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / "config").mkdir()
    (repo / "src").mkdir()
    for rel in CONFIG_PATHS:
        (repo / rel).write_text("{}\n", encoding="utf-8")
    (repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    baseline = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "feature")
    source_tip = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-q", "master")
    (repo / CONFIG_PATHS[0]).write_text('{"refreshed": true}\n', encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "ops: preserve fleet-generated drift")
    pre_merge = _git(repo, "rev-parse", "HEAD")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge feature", source_tip)
    merge_commit = _git(repo, "rev-parse", "HEAD")

    origin = tmp_path / "origin.git"
    _git(repo, "init", "-q", "--bare", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "master")
    assert _git(repo, "rev-parse", "origin/master") == merge_commit

    alerts = repo / "data" / "alerts"
    (alerts / "documentation_transactions").mkdir(parents=True)
    snapshot = {
        "schema_version": "documentation_transaction_pending_v0.1",
        "status": "PENDING",
        "latest_integration_tip": merge_commit,
        "integrations": [{"branch": "origin/feature", "integration_tip": merge_commit, "expected_tip": source_tip}],
    }
    snapshot_bytes = json.dumps(snapshot, indent=2).encode("utf-8")
    pending_sha = hashlib.sha256(snapshot_bytes).hexdigest()
    (alerts / "documentation_transactions" / f"pending-{pending_sha}.json").write_bytes(snapshot_bytes)

    marker = {
        "schema": "quiet_window_merge_in_progress_v0.1",
        "repo_root": str(repo),
        "phase": "documented_unpublished",
        "operation_mode": "ordinary_synchronized_merge_v0.1",
        "branch": "origin/feature",
        "expected_tip": source_tip,
        "expected_baseline": baseline,
        "resolved_branch_tip": source_tip,
        "baseline_commit": baseline,
        "pre_merge_commit": pre_merge,
        "merge_commit": merge_commit,
        "capture_recovery_proved": True,
        "execution_tape_recovery_required": True,
        "execution_tape_recovery_proved": True,
        "documentation_transaction_recorded": True,
        "documentation_transaction_pending_sha256": pending_sha,
        "documentation_transaction_snapshot_path": f"data/alerts/documentation_transactions/pending-{pending_sha}.json",
        "publication_acknowledged": False,
    }
    marker_path = alerts / "quiet_window_merge_in_progress.json"
    marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")

    snapshots = repo / "data" / "snapshots"
    snapshots.mkdir(parents=True)
    (snapshots / ".execution_tape_status.json.writer.lock").write_text(
        json.dumps({"pid": 4242, "managed_process": {"pid": 4242}}), encoding="utf-8")

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    (stub_dir / "capture.json").write_text(json.dumps({
        "ok": True,
        "workers": [{"name": n, "ok": True} for n in ("snapshot_tracker", "market_microstructure", "observation_trigger")],
    }), encoding="utf-8")
    (stub_dir / "tape.json").write_text(json.dumps({
        "health": {"state": "RUNNING", "pid_alive": True, "runtime_identity_matches_current": True, "evidence_integrity": "PASS"},
        "status": {"state": "CONNECTED", "pid": 4242, "managed_process": {"pid": 4242}},
    }), encoding="utf-8")
    (stub_dir / "python.cmd").write_text(
        "@echo off\r\n"
        'if "%~2"=="weather.operations.capture_recovery_check" (type "%~dp0capture.json" & exit /b 0)\r\n'
        'if "%~2"=="weather.operations.execution_tape_supervisor" (type "%~dp0tape.json" & exit /b 0)\r\n'
        "exit /b 9\r\n",
        encoding="ascii",
    )
    return {"repo": repo, "marker": marker_path, "python": stub_dir / "python.cmd", "merge": merge_commit,
            "pre_merge": pre_merge, "alerts": alerts}


def _run(fx: dict[str, object], *extra: str, sha: str | None = None) -> subprocess.CompletedProcess[str]:
    marker = fx["marker"]
    assert isinstance(marker, Path)
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-RepoRoot", str(fx["repo"]), "-ExpectedActiveMarkerSha256", sha or _sha256(marker),
         "-ReviewReference", "test-review", "-Python", str(fx["python"]), "-ExecutionTapeRetrySeconds", "0", *extra],
        capture_output=True, text=True, check=False)


def test_dry_run_proves_everything_and_retains_marker(tmp_path: Path) -> None:
    fx = _build(tmp_path)
    result = _run(fx, "-DryRun")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DRY RUN" in result.stdout
    assert fx["marker"].exists()
    assert not (fx["alerts"] / "quiet_window_merge_reconciliations").exists()


def test_real_run_retires_marker_with_receipt_and_history(tmp_path: Path) -> None:
    fx = _build(tmp_path)
    marker_sha = _sha256(fx["marker"])
    marker_raw = fx["marker"].read_text(encoding="utf-8")
    result = _run(fx)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not fx["marker"].exists()
    receipt_path = fx["alerts"] / "quiet_window_merge_reconciliations" / f"ordinary-{marker_sha}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["stage"] == "reconciled_published"
    assert receipt["merge_commit"] == fx["merge"]
    assert receipt["marker_sha256"] == marker_sha
    assert receipt["marker_raw"] == marker_raw
    assert receipt["execution_tape"]["pid"] == 4242
    assert receipt["downstream_authority"] == "none"
    history = (fx["alerts"] / "quiet_window_merge_history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    row = json.loads(history[-1])
    assert row["stage"] == "reconciled_published" and row["marker_sha256"] == marker_sha
    assert row["receipt_sha256"] == _sha256(receipt_path)
    # A second run has nothing to retire.
    again = _run(fx, sha=marker_sha)
    assert again.returncode != 0 and "No active quiet-merge marker" in (again.stdout + again.stderr)


def test_refuses_when_remote_did_not_publish_the_merge(tmp_path: Path) -> None:
    fx = _build(tmp_path)
    repo = fx["repo"]
    assert isinstance(repo, Path)
    _git(repo, "update-ref", "refs/remotes/origin/master", str(fx["pre_merge"]))
    result = _run(fx)
    assert result.returncode != 0
    assert "does not prove publication" in (result.stdout + result.stderr)
    assert fx["marker"].exists()


def test_refuses_hash_mismatch_and_unhealthy_capture(tmp_path: Path) -> None:
    fx = _build(tmp_path)
    result = _run(fx, sha="0" * 64)
    assert result.returncode != 0 and "hash mismatch" in (result.stdout + result.stderr)
    stub = fx["python"]
    assert isinstance(stub, Path)
    (stub.parent / "capture.json").write_text(json.dumps({"ok": False, "workers": []}), encoding="utf-8")
    result = _run(fx)
    assert result.returncode != 0 and "not healthy" in (result.stdout + result.stderr)
    assert fx["marker"].exists()


def test_refuses_non_ordinary_operation_mode(tmp_path: Path) -> None:
    fx = _build(tmp_path)
    marker = fx["marker"]
    assert isinstance(marker, Path)
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["operation_mode"] = "production_baseline_reconciliation_v0.1"
    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    result = _run(fx)
    assert result.returncode != 0 and "not an ordinary synchronized merge" in (result.stdout + result.stderr)
    assert marker.exists()
