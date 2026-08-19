import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from weather.operations import (
    daily_refresh_locks,
    long_job_guard,
    process_lock_identity,
)


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


@pytest.mark.parametrize("pid", [0, -1, -999])
def test_nonpositive_owner_pid_is_verified_stale_without_process_observation(
    pid, monkeypatch
):
    def unexpected_observation(_pid):
        raise AssertionError("nonpositive PIDs must not be inspected")

    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        unexpected_observation,
    )

    diagnostic = long_job_guard.lock_owner_status({"pid": pid})

    assert diagnostic["active"] is False
    assert diagnostic["running"] is False
    assert diagnostic["stale"] is True
    assert diagnostic["stale_reason"] == "invalid_pid"


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


def test_stale_daily_lock_repair_refuses_path_replacement(tmp_path, monkeypatch):
    lock_path = tmp_path / "daily_refresh.lock"
    lock_path.write_text(json.dumps({"pid": -999}), encoding="utf-8")
    replacement = {
        "pid": 8080,
        "created_at_utc": "2026-08-19T09:00:00+00:00",
        long_job_guard.LOCK_OWNER_IDENTITY_FIELD: {
            "pid": 8080,
            "creation_time_token": "win32-filetime:replacement",
            "image_path": r"C:\Python311\python.exe",
        },
    }
    real_remove = process_lock_identity.remove_lock_payload_if_current

    def replace_before_remove(path, expected):
        path.write_text(json.dumps(replacement), encoding="utf-8")
        return real_remove(path, expected)

    monkeypatch.setattr(
        daily_refresh_locks,
        "remove_lock_payload_if_current",
        replace_before_remove,
    )

    diagnostic = daily_refresh_locks._remove_lock_if_verified_stale(
        lock_path,
        kind="daily_refresh_lock",
    )

    assert diagnostic["stale"] is True
    assert diagnostic["removed"] is False
    assert diagnostic["remove_refusal_reason"] == "lock_instance_replaced"
    assert json.loads(lock_path.read_text(encoding="utf-8")) == replacement


def test_stale_long_job_lock_repair_refuses_path_replacement(tmp_path, monkeypatch):
    lock_path = tmp_path / "long_job_guard.lock"
    lock_path.write_text(json.dumps({"pid": -999}), encoding="utf-8")
    replacement = {"pid": 9090, "job_name": "replacement"}
    real_remove = process_lock_identity.remove_lock_payload_if_current

    def replace_before_remove(path, expected):
        path.write_text(json.dumps(replacement), encoding="utf-8")
        return real_remove(path, expected)

    monkeypatch.setattr(
        long_job_guard,
        "remove_lock_payload_if_current",
        replace_before_remove,
    )

    with pytest.raises(long_job_guard.LongJobBusy, match="instance changed"):
        long_job_guard.acquire_long_job_lock(lock_path, "contender")

    assert json.loads(lock_path.read_text(encoding="utf-8")) == replacement


@pytest.mark.parametrize("owner", ["daily", "long_job"])
def test_release_revalidates_payload_inside_path_transaction(
    tmp_path,
    monkeypatch,
    owner,
):
    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        lambda pid: _running(
            pid,
            token="win32-filetime:ours",
            image=sys.executable,
            created_at="2026-08-19T09:00:00+00:00",
        ),
    )
    lock_path = tmp_path / f"{owner}.lock"
    if owner == "daily":
        acquired = daily_refresh_locks.acquire_lock(lock_path)
        release = daily_refresh_locks.release_lock
        module = daily_refresh_locks
    else:
        acquired = long_job_guard.acquire_long_job_lock(lock_path, "ours")
        release = long_job_guard.release_long_job_lock
        module = long_job_guard
    replacement = json.loads(lock_path.read_text(encoding="utf-8"))
    replacement[long_job_guard.LOCK_OWNER_IDENTITY_FIELD][
        "creation_time_token"
    ] = "win32-filetime:replacement"
    real_remove = process_lock_identity.remove_lock_payload_if_current

    def replace_before_remove(path, expected):
        path.write_text(json.dumps(replacement), encoding="utf-8")
        return real_remove(path, expected)

    monkeypatch.setattr(module, "remove_lock_payload_if_current", replace_before_remove)

    release(acquired)

    assert json.loads(lock_path.read_text(encoding="utf-8")) == replacement


def test_process_observation_is_redacted_before_diagnostics(monkeypatch):
    pid = 10010
    monkeypatch.setattr(
        long_job_guard,
        "observe_process_identity",
        lambda _pid: {
            "state": "running",
            "pid": pid,
            "image_path": r"C:\Python311\python.exe",
            "creation_time_token": "win32-filetime:current",
            "creation_time_utc": "2026-08-19T09:00:00+00:00",
            "inspectable": True,
            "command_line": "python.exe --wallet-secret do-not-persist",
            "argv": ["python.exe", "--wallet-secret", "do-not-persist"],
        },
    )
    detail = {
        "pid": pid,
        long_job_guard.LOCK_OWNER_IDENTITY_FIELD: {
            "pid": pid,
            "image_path": r"C:\Python311\python.exe",
            "creation_time_token": "win32-filetime:current",
        },
    }

    diagnostic = long_job_guard.lock_owner_status(detail)

    assert diagnostic["active"] is True
    assert diagnostic["identity_match"] is True
    assert diagnostic["observation"] == {
        "state": "running",
        "pid": pid,
        "image_path": r"C:\Python311\python.exe",
        "creation_time_token": "win32-filetime:current",
        "creation_time_utc": "2026-08-19T09:00:00+00:00",
        "inspectable": True,
    }
    assert "do-not-persist" not in json.dumps(diagnostic)


def test_lock_path_transaction_serializes_mutators(tmp_path):
    lock_path = tmp_path / "daily_refresh.lock"

    with process_lock_identity.lock_path_transaction(lock_path):
        with pytest.raises(process_lock_identity.LockPathTransactionBusy):
            with process_lock_identity.lock_path_transaction(
                lock_path,
                timeout_seconds=0.02,
            ):
                raise AssertionError("a second mutator entered the lock transaction")


def test_lock_path_transaction_serializes_separate_processes(tmp_path):
    lock_path = tmp_path / "daily_refresh.lock"
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(repo_root), str(repo_root / "src"), env.get("PYTHONPATH", "")]
    )
    child_code = (
        "import sys;"
        "from pathlib import Path;"
        "from weather.operations.process_lock_identity import "
        "LockPathTransactionBusy,lock_path_transaction;"
        "result='entered';"
        "\ntry:\n"
        "  with lock_path_transaction(Path(sys.argv[1]),"
        "timeout_seconds=float(sys.argv[2])): pass\n"
        "except LockPathTransactionBusy:\n"
        "  result='busy'\n"
        "print(result)"
    )

    def run_child(timeout_seconds):
        return subprocess.run(
            [
                sys.executable,
                "-c",
                child_code,
                str(lock_path),
                str(timeout_seconds),
            ],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()

    with process_lock_identity.lock_path_transaction(lock_path):
        assert run_child(0.05) == "busy"

    assert run_child(1.0) == "entered"
