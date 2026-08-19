import json
import os
import sys
from datetime import datetime

import pytest

from weather.operations import daily_refresh_locks, long_job_guard


def _filetime_token(created_at):
    unix_seconds = datetime.fromisoformat(created_at).timestamp()
    return f"win32-filetime:{int(unix_seconds * 10_000_000) + 116444736000000000}"


def _running(pid, *, token, image, created_at):
    return {
        "state": "running",
        "pid": int(pid),
        "creation_time_token": token,
        "creation_time_utc": created_at,
        "image_path": image,
    }


def _self_or(pid, other_pid, other):
    if int(pid) == int(other_pid):
        return other
    return _running(
        pid,
        token="win32-filetime:self",
        image=sys.executable,
        created_at="2026-08-19T09:00:00+00:00",
    )


def test_legacy_lock_with_reused_unrelated_pid_is_verified_stale(
    tmp_path, monkeypatch
):
    reused_pid = 3212
    observation = _running(
        reused_pid,
        token=_filetime_token("2026-08-19T08:00:00+00:00"),
        image=r"C:\Program Files\Codex\codex.exe",
        created_at="2026-08-19T08:00:00+00:00",
    )
    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        lambda pid: _self_or(pid, reused_pid, observation),
    )
    lock_path = tmp_path / "daily_refresh.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": reused_pid,
                "created_at_utc": "2026-08-19T05:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    diagnostic = daily_refresh_locks.lock_diagnostic(
        lock_path, kind="daily_refresh_lock"
    )
    acquired = daily_refresh_locks.acquire_lock(lock_path)
    replacement = json.loads(lock_path.read_text(encoding="utf-8"))
    daily_refresh_locks.release_lock(acquired)

    assert diagnostic["owner_running"] is True
    assert diagnostic["legacy_lock"] is True
    assert diagnostic["stale"] is True
    assert diagnostic["stale_reason"] == "legacy_pid_reused_after_lock"
    assert acquired == lock_path
    assert replacement["pid"] == os.getpid()
    assert replacement[long_job_guard.LOCK_OWNER_IDENTITY_FIELD][
        "creation_time_token"
    ] == "win32-filetime:self"
    assert not lock_path.exists()


def test_genuine_active_legacy_python_owner_remains_active(tmp_path, monkeypatch):
    owner_pid = 4242
    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        lambda pid: _running(
            pid,
            token=_filetime_token("2026-08-19T04:59:58+00:00"),
            image=r"C:\Python311\python.exe",
            created_at="2026-08-19T04:59:58+00:00",
        ),
    )
    lock_path = tmp_path / "daily_refresh.lock"
    original = {
        "pid": owner_pid,
        "created_at_utc": "2026-08-19T05:00:00+00:00",
    }
    lock_path.write_text(json.dumps(original), encoding="utf-8")

    diagnostic = daily_refresh_locks.lock_diagnostic(
        lock_path, kind="daily_refresh_lock"
    )
    acquired = daily_refresh_locks.acquire_lock(lock_path)

    assert diagnostic["owner_running"] is True
    assert diagnostic["legacy_lock"] is True
    assert diagnostic["stale"] is False
    assert diagnostic["stale_reason"] == ""
    assert acquired is None
    assert json.loads(lock_path.read_text(encoding="utf-8")) == original


def test_new_lock_creation_token_mismatch_is_stale_even_when_pid_is_alive(
    tmp_path, monkeypatch
):
    owner_pid = 5151
    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        lambda pid: _running(
            pid,
            token="win32-filetime:new-instance",
            image=r"C:\Python311\python.exe",
            created_at="2026-08-19T08:00:00+00:00",
        ),
    )
    lock_path = tmp_path / "daily_refresh.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": owner_pid,
                "created_at_utc": "2026-08-19T05:00:00+00:00",
                long_job_guard.LOCK_OWNER_IDENTITY_FIELD: {
                    "pid": owner_pid,
                    "creation_time_token": "win32-filetime:old-instance",
                    "image_path": r"C:\Python311\python.exe",
                },
            }
        ),
        encoding="utf-8",
    )

    diagnostic = daily_refresh_locks.lock_diagnostic(
        lock_path, kind="daily_refresh_lock"
    )

    assert diagnostic["owner_running"] is True
    assert diagnostic["legacy_lock"] is False
    assert diagnostic["owner_identity_match"] is False
    assert diagnostic["stale"] is True
    assert diagnostic["stale_reason"] == "process_identity_mismatch"


@pytest.mark.parametrize("state", ["unknown", "running"])
def test_unverifiable_identity_fails_closed_as_active(tmp_path, monkeypatch, state):
    owner_pid = 6161
    observation = {
        "state": state,
        "pid": owner_pid,
        "image_path": None,
        "creation_time_token": None,
        "creation_time_utc": None,
    }
    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        lambda _pid: observation,
    )
    lock_path = tmp_path / "daily_refresh.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": owner_pid,
                "created_at_utc": "2026-08-19T05:00:00+00:00",
                long_job_guard.LOCK_OWNER_IDENTITY_FIELD: {
                    "pid": owner_pid,
                    "creation_time_token": "win32-filetime:expected",
                    "image_path": r"C:\Python311\python.exe",
                },
            }
        ),
        encoding="utf-8",
    )

    diagnostic = daily_refresh_locks.lock_diagnostic(
        lock_path, kind="daily_refresh_lock"
    )

    assert diagnostic["stale"] is False
    assert daily_refresh_locks.acquire_lock(lock_path) is None
    assert lock_path.exists()


def test_long_job_lock_replaces_reused_legacy_pid_and_records_identity(
    tmp_path, monkeypatch
):
    reused_pid = 7171
    reused = _running(
        reused_pid,
        token=_filetime_token("2026-08-19T08:00:00+00:00"),
        image=r"C:\Program Files\Codex\codex.exe",
        created_at="2026-08-19T08:00:00+00:00",
    )
    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        lambda pid: _self_or(pid, reused_pid, reused),
    )
    lock_path = tmp_path / "long_job_guard.lock"
    lock_path.write_text(
        json.dumps(
            {
                "pid": reused_pid,
                "job_name": "stale_backfill",
                "started_at_utc": "2026-08-19T05:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    audit = {}

    acquired = long_job_guard.acquire_long_job_lock(
        lock_path, "replacement", audit=audit
    )
    replacement = json.loads(lock_path.read_text(encoding="utf-8"))
    long_job_guard.release_long_job_lock(acquired)

    assert audit["stale_lock_detected_count"] == 1
    assert audit["stale_lock_repair_count"] == 1
    assert audit["stale_lock_reason"] == "legacy_pid_reused_after_lock"
    assert replacement["job_name"] == "replacement"
    assert replacement[long_job_guard.LOCK_OWNER_IDENTITY_FIELD][
        "creation_time_token"
    ] == "win32-filetime:self"
    assert not lock_path.exists()


def test_release_does_not_remove_replacement_process_instance(tmp_path, monkeypatch):
    current_token = {"value": "win32-filetime:ours"}
    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        lambda pid: _running(
            pid,
            token=current_token["value"],
            image=sys.executable,
            created_at="2026-08-19T09:00:00+00:00",
        ),
    )
    lock_path = tmp_path / "daily_refresh.lock"
    acquired = daily_refresh_locks.acquire_lock(lock_path)
    replacement = json.loads(lock_path.read_text(encoding="utf-8"))
    replacement[long_job_guard.LOCK_OWNER_IDENTITY_FIELD][
        "creation_time_token"
    ] = "win32-filetime:replacement"
    lock_path.write_text(json.dumps(replacement), encoding="utf-8")

    daily_refresh_locks.release_lock(acquired)

    assert lock_path.exists()
