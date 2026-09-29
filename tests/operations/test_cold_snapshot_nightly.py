from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path

import pytest

from weather.operations import cold_snapshot_nightly as night
from weather.operations import cold_snapshot_compression as cold
from weather.operations import storage_recovery_inventory as inventory
from weather.operations.ntfs_file_compression import MIB, LockedNtfsFile
from weather.schema_registry import schema_version

NOW = datetime(2026, 9, 24, 5, tzinfo=timezone.utc)
FOLDER = "snapshots/highest-temperature-in-nyc-on-september-1-2026"


def row(name="snapshots.jsonl", size=90 * MIB):
    return {"path": FOLDER + "/" + name, "size_bytes": size, "allocated_bytes": size,
            "attributes": 32, "mtime_ns": str(int((NOW - timedelta(days=20)).timestamp()) * 10**9),
            "file_id": "1", "device": "2"}


def test_large_files_fit_batches_and_nightly_budget():
    rows = [row(f"{index:02d}.jsonl", 256 * MIB) for index in range(12)]
    batches = list(night.plan_batches(rows, 1536 * MIB, now=NOW))
    assert [len(batch) for batch in batches] == [4, 2]
    assert sum(item["size_bytes"] for batch in batches for item in batch) == 1536 * MIB
    assert list(night.plan_batches(rows, 255 * MIB, now=NOW)) == []
    assert sum(map(len, night.plan_batches(rows, night.MAX_NIGHT_BYTES, now=NOW, remaining_files=3))) == 3


@pytest.mark.parametrize("change", [
    {"size_bytes": 257 * MIB}, {"attributes": 0x820}, {"path": FOLDER + "/nested/file.jsonl"},
    {"path": FOLDER + "/raw.gz"}, {"path": "mm_runs/a/ledger.jsonl"},
    {"mtime_ns": str(int(NOW.timestamp()) * 10**9)},
])
def test_excluded_files_are_retained(change):
    assert list(night.plan_batches([{**row(), **change}], night.MAX_NIGHT_BYTES, now=NOW)) == []


def test_fourteen_day_boundary_refuses_and_old_attended_contract_stays_thirty_days():
    hot = "snapshots/highest-temperature-in-nyc-on-september-10-2026"
    with pytest.raises(ValueError, match="fourteen"):
        list(night.plan_batches([{**row(), "path": hot + "/snapshots.jsonl"}], night.MAX_NIGHT_BYTES, now=NOW))
    with pytest.raises(ValueError, match="thirty"):
        inventory.validate_folders([FOLDER], as_of=NOW.date())
    assert inventory.validate_folders([FOLDER], as_of=NOW.date(), min_age_days=14)


def test_batch_stops_on_first_failure_and_never_mutates_later_file(tmp_path):
    touched = []
    def failure(path, expected, **kwargs):
        touched.append(expected["path"])
        raise ValueError("post-compression content or native identity mismatch")
    with pytest.raises(ValueError, match="mismatch"):
        night.execute_batch([row("a.jsonl"), row("b.jsonl")], tmp_path, tmp_path,
                            apply=True, guard=lambda: None, compress=failure)
    assert touched == [FOLDER + "/a.jsonl"]


def test_policy_is_expiring_host_bound_and_budget_limited(tmp_path):
    policy = {"schema_version": schema_version("cold_snapshot_nightly_policy"),
        "production_repo_root": str(tmp_path), "execution_host_id": "a" * 64,
        "operation": "compress_and_retain", "approved_by": "fixture owner",
        "approved_at_utc": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at_utc": (NOW + timedelta(days=30)).isoformat(), "nightly_budget_bytes": 32 * 1024 * MIB}
    assert night.validate_policy(policy, tmp_path, NOW) == night.MAX_NIGHT_BYTES
    for change in ({"nightly_budget_bytes": night.MAX_NIGHT_BYTES + 1}, {"operation": "delete"},
                   {"expires_at_utc": NOW.isoformat()}, {"execution_host_id": "unknown"}):
        with pytest.raises(ValueError):
            night.validate_policy({**policy, **change}, tmp_path, NOW)


@pytest.mark.skipif(os.name != "nt", reason="native NTFS fixture")
def test_native_large_file_streaming_integrity_and_writer_exclusion(tmp_path):
    path = tmp_path / "large.jsonl"
    block = b'{"synthetic":"' + b'a' * (MIB - 16) + b'"}\n'
    digest = hashlib.sha256()
    with path.open("wb") as stream:
        for _ in range(72):
            stream.write(block)
            digest.update(block)
    assert path.stat().st_size > 64 * MIB
    with pytest.raises(ValueError, match="size bound"):
        with LockedNtfsFile(path, writable=True):
            pass
    # A simultaneous writer causes native CreateFile sharing failure.
    with path.open("ab"):
        with pytest.raises(OSError):
            with night.LARGE_OPENER(path, writable=True):
                pass
    with night.LARGE_OPENER(path, writable=True) as opened:
        before = opened.metadata()
    expected = {"path": "large.jsonl", "size_bytes": before["size_bytes"],
        "allocated_bytes": before["allocation_bytes"], "mtime_ns": str(before["mtime_ns"]),
        "device": str(before["volume_serial"]), "file_id": str(before["file_index"]),
        "attributes": before["attributes"]}
    journals = []
    result = cold.compress_candidate(path, expected, apply=True, guard=lambda: None,
        journal=lambda phase, item: journals.append((phase, item)), opener=night.LARGE_OPENER)
    assert result["sha256"] == digest.hexdigest()
    assert result["status"] == "VERIFIED" and result["reclaimed_bytes"] > 0
    assert [phase for phase, _ in journals] == ["before", "after"]
    assert path.exists() and path.stat().st_size == before["size_bytes"]
