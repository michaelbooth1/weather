from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.operations.capture_recovery_check import WORKERS, check_capture_recovery


NOW = datetime(2026, 8, 14, 2, 20, tzinfo=timezone.utc)


def _write_worker(root: Path, spec, *, pid: int = 42, age_seconds: int = 10) -> None:
    snapshots = root / "data" / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    status = {
        "pid": pid,
        "last_heartbeat": (NOW - timedelta(seconds=age_seconds)).isoformat(),
        "runtime_identity": {"source_fingerprint": f"source-{spec.name}"},
    }
    (snapshots / spec.status_file).write_text(json.dumps(status), encoding="utf-8")
    (snapshots / spec.lock_file).write_text(json.dumps({"pid": pid}), encoding="utf-8")


def _matching_identity(recorded, *, repo_root):
    del repo_root
    return dict(recorded)


def test_requires_all_three_fresh_live_locked_identity_current_workers(tmp_path: Path) -> None:
    for spec in WORKERS:
        _write_worker(tmp_path, spec)

    result = check_capture_recovery(
        tmp_path,
        now=NOW,
        process_alive=lambda pid: pid == 42,
        current_identity=_matching_identity,
    )

    assert result["ok"] is True
    assert [row["name"] for row in result["workers"]] == [spec.name for spec in WORKERS]
    assert all(row["runtime_identity_matches_current"] for row in result["workers"])


def test_snapshot_sleep_window_is_valid_but_stays_below_capture_gap_limit(tmp_path: Path) -> None:
    for spec in WORKERS:
        age_seconds = 660 if spec.name == "snapshot_tracker" else 10
        _write_worker(tmp_path, spec, age_seconds=age_seconds)

    healthy = check_capture_recovery(
        tmp_path,
        now=NOW,
        process_alive=lambda pid: pid == 42,
        current_identity=_matching_identity,
    )
    assert healthy["ok"] is True

    snapshot = WORKERS[0]
    assert snapshot.name == "snapshot_tracker"
    assert snapshot.max_age_seconds == 720.0
    _write_worker(tmp_path, snapshot, age_seconds=721)
    stale = check_capture_recovery(
        tmp_path,
        now=NOW,
        process_alive=lambda pid: pid == 42,
        current_identity=_matching_identity,
    )
    snapshot_row = next(row for row in stale["workers"] if row["name"] == snapshot.name)
    assert stale["ok"] is False
    assert "heartbeat_stale" in snapshot_row["reasons"]


def test_fails_closed_on_stale_heartbeat_dead_pid_lock_mismatch_and_identity(tmp_path: Path) -> None:
    for spec in WORKERS:
        _write_worker(tmp_path, spec)
    snapshots = tmp_path / "data" / "snapshots"

    snapshot_status = json.loads((snapshots / WORKERS[0].status_file).read_text())
    snapshot_status["last_heartbeat"] = (NOW - timedelta(hours=1)).isoformat()
    (snapshots / WORKERS[0].status_file).write_text(json.dumps(snapshot_status))
    (snapshots / WORKERS[1].lock_file).write_text(json.dumps({"pid": 99}))

    def stale_identity(recorded, *, repo_root):
        del recorded, repo_root
        return {"source_fingerprint": "different"}

    result = check_capture_recovery(
        tmp_path,
        now=NOW,
        process_alive=lambda pid: False,
        current_identity=stale_identity,
    )

    assert result["ok"] is False
    reasons = {row["name"]: set(row["reasons"]) for row in result["workers"]}
    assert "heartbeat_stale" in reasons["snapshot_tracker"]
    assert "writer_lock_pid_mismatch" in reasons["market_microstructure"]
    assert all("pid_not_alive" in row_reasons for row_reasons in reasons.values())
    assert all("runtime_identity_stale" in row_reasons for row_reasons in reasons.values())


def test_missing_status_and_lock_are_explicit_failures(tmp_path: Path) -> None:
    result = check_capture_recovery(
        tmp_path,
        now=NOW,
        process_alive=lambda pid: False,
        current_identity=_matching_identity,
    )

    assert result["ok"] is False
    assert all("status_unreadable:FileNotFoundError" in row["reasons"] for row in result["workers"])
    assert all("lock_unreadable:FileNotFoundError" in row["reasons"] for row in result["workers"])
