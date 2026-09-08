from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

from weather.operations import storage_recovery_inventory_cli as subject
from weather.operations import replay_cache_compression_admission as compression
from weather.operations import storage_recovery_inventory as metadata
from weather.paths import repo_path
from weather.schema_registry import schema_version

NOW = datetime(2026, 9, 9, 5, tzinfo=timezone.utc)
FOLDER = "snapshots/highest-temperature-in-toronto-on-july-1-2026"


def request(root):
    return {"schema_version": schema_version("storage_recovery_inventory_request"),
            "production_repo_root": str(root), "approved_by": "fixture owner",
            "operation": "metadata_only", "execution_host_id": "a" * 64,
            "approved_at_utc": (NOW - timedelta(hours=1)).isoformat(),
            "expires_at_utc": (NOW + timedelta(hours=1)).isoformat(),
            "folders": [FOLDER]}


def resources():
    return dict(now=NOW, available=8 * 1024**3, commit=50,
                free_disk=subject.MIN_FREE_DISK_BYTES,
                loops=[{"name": name, "active": True, "degraded": False,
                        "heartbeat_fresh": True, "pid_agreement": True,
                        "heartbeat_age_seconds": 1, "last_clean_iteration_age_seconds": 60,
                        "process_identity_matches_lock": True,
                        "process_diagnostics": {"status_pid_alive": True, "lock_pid_alive": True}}
                       for name in ("snapshot", "clob", "observation_trigger")])


def test_inventory_has_own_disk_reservation_without_changing_compression_gate():
    args = resources()
    assert subject.check_resources(**args)["status"] == "PASS"
    assert compression.check_resources(**args)["status"] == "BLOCK"
    args["free_disk"] -= 1
    assert subject.check_resources(**args)["status"] == "BLOCK"


@pytest.mark.parametrize("key,value", [
    ("commit", 70), ("commit", float("nan")), ("commit", None),
    ("available", 4 * 1024**3 - 1), ("available", None),
    ("free_disk", None), ("free_disk", True), ("loops", []),
    ("now", NOW.replace(hour=13)), ("now", NOW.replace(hour=9)),
])
def test_resource_failures_are_closed(key, value):
    args = resources()
    args[key] = value
    assert subject.check_resources(**args)["status"] == "BLOCK"


@pytest.mark.parametrize("key,value", [
    ("active", False), ("degraded", True), ("heartbeat_fresh", False),
    ("pid_agreement", False), ("process_identity_matches_lock", False),
    ("heartbeat_age_seconds", 181), ("last_clean_iteration_age_seconds", 901),
    ("process_diagnostics", {}),
])
def test_capture_failures_block_inventory(key, value):
    args = resources()
    args["loops"][0][key] = value
    assert subject.check_resources(**args)["status"] == "BLOCK"


def test_request_accepts_only_expiring_exact_cold_selection(tmp_path):
    assert subject.validate_request(request(tmp_path), production_root=tmp_path, now=NOW) == [FOLDER]


@pytest.mark.parametrize("key,value", [
    ("operation", "delete"), ("schema_version", "unknown"),
    ("approved_by", ""), ("execution_host_id", "wrong"),
    ("approved_at_utc", (NOW + timedelta(seconds=1)).isoformat()),
    ("expires_at_utc", NOW.isoformat()),
    ("expires_at_utc", (NOW + timedelta(hours=73)).isoformat()),
    ("folders", ["snapshots"]), ("folders", [FOLDER, FOLDER]),
    ("folders", ["snapshots/highest-temperature-in-toronto-on-september-1-2026"]),
])
def test_request_scope_and_time_fail_closed(tmp_path, key, value):
    payload = request(tmp_path)
    payload[key] = value
    with pytest.raises(ValueError):
        subject.validate_request(payload, production_root=tmp_path, now=NOW)


def test_request_rejects_unknown_fields_or_different_root(tmp_path):
    payload = request(tmp_path)
    payload["apply"] = True
    with pytest.raises(ValueError):
        subject.validate_request(payload, production_root=tmp_path, now=NOW)
    with pytest.raises(ValueError):
        subject.validate_request(request(tmp_path), production_root=tmp_path / "other", now=NOW)


def test_inventory_serialization_is_bounded_and_create_only(tmp_path, monkeypatch):
    destination = tmp_path / "inventory.json"
    payload = {"files": [{"path": FOLDER}], "cleanup_eligible": False}
    digest, size = subject.write_inventory(destination, payload)
    assert digest == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert size == destination.stat().st_size
    with pytest.raises(FileExistsError):
        subject.write_inventory(destination, payload)
    monkeypatch.setattr(metadata, "MAX_OUTPUT_BYTES", 10)
    with pytest.raises(ValueError, match="hard output bound"):
        subject.write_inventory(tmp_path / "too-large.json", payload)
    assert not (tmp_path / "too-large.json").exists()


def test_output_is_one_new_attempt_under_exact_production_parent(tmp_path):
    output = tmp_path / "scratch/storage_recovery_inventory/attempt"
    output.mkdir(parents=True)
    subject.validate_output(output, tmp_path)
    (output / "request.json").write_text("{}")
    with pytest.raises(FileExistsError):
        subject.validate_output(output, tmp_path)
    nested = output / "nested"
    nested.mkdir()
    with pytest.raises(ValueError):
        subject.validate_output(nested, tmp_path)


def test_imports_are_bound_to_current_worktree():
    for module in (subject, metadata):
        assert Path(module.__file__).resolve().is_relative_to(repo_path("src/weather"))


@pytest.mark.skipif(os.name != "nt", reason="native NTFS compressed allocation")
def test_inventory_counts_physical_compressed_allocation(tmp_path):
    from weather.operations.ntfs_file_compression import LockedNtfsFile
    path = tmp_path / "compressible.json"
    path.write_bytes(b"0" * (2 * 1024**2))
    before = metadata.native_allocation(path, path.stat())
    with LockedNtfsFile(path, writable=True) as opened:
        opened.compress()
    after = metadata.native_allocation(path, path.stat())
    assert 0 < after < before
    assert path.read_bytes() == b"0" * (2 * 1024**2)
