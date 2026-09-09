from argparse import Namespace
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

from weather.operations import cold_snapshot_compression as subject
from weather.operations import storage_recovery_inventory as metadata
from weather.operations.ntfs_file_compression import LockedNtfsFile, MIB
from weather.paths import repo_path
from weather.schema_registry import schema_version

NOW = datetime(2026, 9, 9, 5, tzinfo=timezone.utc)
FOLDER = "snapshots/highest-temperature-in-toronto-on-july-1-2026"
RELATIVE = FOLDER + "/replay_inputs.jsonl"
SHA = "a" * 40


def candidate():
    return {"path": RELATIVE, "size_bytes": 100, "allocated_bytes": 4096,
            "mtime_ns": str(int((NOW - timedelta(days=45)).timestamp()) * 10**9),
            "file_id": "4", "device": "3", "attributes": 32}


def request(root, rows=None):
    return {"schema_version": schema_version("cold_snapshot_compression_request"),
            "production_repo_root": str(root), "approved_by": "fixture owner",
            "execution_host_id": "a" * 64, "operation": "compress_and_retain",
            "approved_at_utc": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at_utc": (NOW + timedelta(hours=1)).isoformat(),
            "files": rows or [candidate()], "inventory_wrapper_sha256": "b" * 64,
            "inventory_wrapper_receipt": str(root / "scratch/storage_recovery_inventory/one/wrapper-result.json")}


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory_chain(root, payload, *, manifest_mutation=None, wrapper_mutation=None):
    row = payload["files"][0]
    bound = {"status": "PASS", "source_git_sha": SHA, "request_sha256": "c" * 64,
             "execution_host_id": "a" * 64, "cleanup_eligible": False}
    manifest = {**bound, "schema_version": schema_version("storage_recovery_inventory"),
                "data_root": str(root / "data"),
                "folders": [{"path": FOLDER, "status": "COMPLETE"}], "files": [row]}
    if manifest_mutation:
        manifest_mutation(manifest)
    path = Path(payload["inventory_wrapper_receipt"])
    manifest_hash = save(path.parent / "inventory.json", manifest)
    result_hash = save(path.parent / "result.json", {**bound, "inventory_sha256": manifest_hash})
    wrapper = {**bound, "hard_stop": False, "teardown_proved": True,
               "deleted_files": 0, "reclaimed_bytes": 0, "child_result_sha256": result_hash}
    if wrapper_mutation:
        wrapper_mutation(wrapper)
    payload["inventory_wrapper_sha256"] = save(path, wrapper)
    return manifest


def test_request_accepts_only_exact_cold_inventory_rows(tmp_path):
    assert subject.validate_request(request(tmp_path), production_root=tmp_path, now=NOW) == [candidate()]


@pytest.mark.parametrize("key,value", [
    ("path", "snapshots/../source.json"), ("path", "snapshots/" + "x" * 20 + "/source.json"),
    ("path", FOLDER + "/.writer.lock.json"), ("path", FOLDER + "/a/../source.json"),
    ("path", FOLDER + "/raw.gz"), ("path", "backtest/replay_cache/file.json"),
    ("path", "snapshots/highest-temperature-in-toronto-on-september-1-2026/file.json"),
    ("size_bytes", 0), ("size_bytes", 64 * MIB + 1), ("allocated_bytes", 0),
    ("attributes", 32 | 0x800), ("attributes", 32 | 0x200), ("attributes", True),
    ("mtime_ns", str(int(NOW.timestamp()) * 10**9)), ("file_id", "4.0"), ("device", "-1"),
])
def test_unsafe_candidate_is_rejected(tmp_path, key, value):
    payload = request(tmp_path)
    payload["files"][0][key] = value
    with pytest.raises(ValueError):
        subject.validate_request(payload, production_root=tmp_path, now=NOW)


def test_batch_bounds_and_duplicate_files(tmp_path):
    payload = request(tmp_path)
    payload["files"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        subject.validate_request(payload, production_root=tmp_path, now=NOW)
    payload["files"] = [{**candidate(), "path": FOLDER + f"/{i}.json", "size_bytes": 64 * MIB}
                        for i in range(17)]
    with pytest.raises(ValueError, match="one GiB"):
        subject.validate_request(payload, production_root=tmp_path, now=NOW)
    payload["files"] = [candidate()] * 257
    with pytest.raises(ValueError, match="256"):
        subject.validate_request(payload, production_root=tmp_path, now=NOW)


@pytest.mark.parametrize("key,value", [
    ("operation", "delete"), ("approved_by", ""), ("execution_host_id", "invalid"),
    ("expires_at_utc", NOW.isoformat()),
    ("approved_at_utc", (NOW + timedelta(seconds=1)).isoformat()),
    ("expires_at_utc", (NOW + timedelta(hours=73)).isoformat()),
])
def test_approval_scope_is_enforced(tmp_path, key, value):
    payload = request(tmp_path)
    payload[key] = value
    with pytest.raises(ValueError):
        subject.validate_request(payload, production_root=tmp_path, now=NOW)


def test_inventory_chain_requires_matching_completed_source_and_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda path: nullcontext())
    payload = request(tmp_path)
    inventory_chain(tmp_path, payload)
    assert subject.read_inventory(payload, payload["files"], production_root=tmp_path,
                                  source_git_sha=SHA)["status"] == "PASS"
    payload["files"][0]["size_bytes"] += 1
    with pytest.raises(ValueError, match="candidate"):
        subject.read_inventory(payload, payload["files"], production_root=tmp_path, source_git_sha=SHA)


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(status="PARTIAL"), lambda m: m.update(source_git_sha="d" * 40),
    lambda m: m.update(execution_host_id="d" * 64), lambda m: m.update(cleanup_eligible=True),
    lambda m: m["folders"][0].update(status="PARTIAL"),
    lambda m: m["files"].append(dict(m["files"][0])),
])
def test_rehashed_unsafe_inventory_remains_rejected(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda path: nullcontext())
    payload = request(tmp_path)
    inventory_chain(tmp_path, payload, manifest_mutation=mutation)
    with pytest.raises(ValueError):
        subject.read_inventory(payload, payload["files"], production_root=tmp_path, source_git_sha=SHA)


@pytest.mark.parametrize("mutation", [
    lambda w: w.update(teardown_proved=False), lambda w: w.update(hard_stop=True),
    lambda w: w.update(status="FAILED"), lambda w: w.update(source_git_sha="d" * 40),
])
def test_unfinished_inventory_wrapper_never_admits_compression(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda path: nullcontext())
    payload = request(tmp_path)
    inventory_chain(tmp_path, payload, wrapper_mutation=mutation)
    with pytest.raises(ValueError):
        subject.read_inventory(payload, payload["files"], production_root=tmp_path, source_git_sha=SHA)


class FakeFile:
    def __init__(self, *, changed_hash=False, savings=3072):
        row = candidate()
        self.row = {"size_bytes": row["size_bytes"], "allocation_bytes": row["allocated_bytes"],
                    "mtime_ns": int(row["mtime_ns"]), "volume_serial": int(row["device"]),
                    "file_index": int(row["file_id"]), "attributes": row["attributes"],
                    "creation_filetime": 123, "compression_format": 0}
        self.compressed = False
        self.changed_hash = changed_hash
        self.savings = savings
        self.reads = 0

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def metadata(self): return dict(self.row)
    def digest(self, **kwargs):
        self.reads += 1
        return "changed" if self.compressed and self.changed_hash else "original"
    def compress(self):
        self.compressed = True
        self.row.update(compression_format=2, allocation_bytes=4096 - self.savings)


def exercise(fake, *, apply=True, journal=lambda *args: None, guard=lambda: None):
    return subject.compress_candidate(Path("unused"), candidate(), apply=apply,
                                      journal=journal, guard=guard, opener=lambda *a, **k: fake)


def test_dry_run_reads_no_payload_and_does_not_compress():
    fake = FakeFile()
    result = exercise(fake, apply=False)
    assert result["status"] == "PLANNED" and result["reclaimed_bytes"] == 0
    assert fake.reads == 0 and not fake.compressed


def test_verified_compression_records_preimage_before_mutation():
    fake, journal = FakeFile(), []
    def record(phase, row):
        assert fake.compressed is (phase == "after")
        journal.append((phase, row))
    result = exercise(fake, journal=record)
    assert result["reclaimed_bytes"] == 3072 and result["status"] == "VERIFIED"
    assert [r[0] for r in journal] == ["before", "after"]
    assert journal[0][1]["sha256"] == journal[1][1]["sha256"] == "original"


@pytest.mark.parametrize("options", [{"changed_hash": True}, {"savings": 0}, {"savings": -4096}])
def test_corruption_or_unproductive_result_stops_expansion(options):
    fake = FakeFile(**options)
    with pytest.raises(ValueError):
        exercise(fake)
    assert fake.compressed


def test_flush_failure_or_expired_admission_prevents_mutation():
    fake = FakeFile()
    def failed_flush(*args): raise OSError("flush")
    with pytest.raises(OSError):
        exercise(fake, journal=failed_flush)
    assert not fake.compressed
    flushed = False
    def journal(*args):
        nonlocal flushed
        flushed = True
    def guard():
        if flushed: raise ValueError("deadline")
    with pytest.raises(ValueError, match="deadline"):
        exercise(fake, journal=journal, guard=guard)
    assert not fake.compressed


@pytest.mark.parametrize("key", ["file_index", "volume_serial", "mtime_ns", "allocation_bytes", "attributes"])
def test_native_identity_change_blocks_before_read_or_mutation(key):
    fake = FakeFile()
    fake.row[key] += 1
    with pytest.raises(ValueError, match="identity"):
        exercise(fake)
    assert fake.reads == 0 and not fake.compressed


@pytest.mark.skipif(os.name != "nt", reason="native end-to-end compression fixture")
def test_native_run_retains_exact_bytes_and_receipts(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    source = tmp_path / "data" / RELATIVE
    source.parent.mkdir(parents=True)
    original = b'{"synthetic":"' + b"a" * (2 * MIB) + b'"}\n'
    source.write_bytes(original)
    stamp = int((now - timedelta(days=45)).timestamp()) * 10**9
    os.utime(source, ns=(stamp, stamp))
    observed = metadata.inventory(tmp_path / "data", [FOLDER], as_of=now.date(), guard=lambda: None)
    assert observed["status"] == "PASS"
    payload = request(tmp_path, observed["files"])
    payload.update(approved_at_utc=(now - timedelta(minutes=1)).isoformat(),
                   expires_at_utc=(now + timedelta(hours=1)).isoformat())
    inventory_chain(tmp_path, payload)
    request_path = tmp_path / "approved.json"
    digest = save(request_path, payload)
    save(tmp_path / "data/logs/heavy_workload.lock", {"execution_host_id": "a" * 64})
    output = tmp_path / "scratch/cold_snapshot_compression/attempt"
    output.mkdir(parents=True)
    monkeypatch.setenv(subject.ENV_PREFIX + "SOURCE_ROOT", str(repo_path()))
    monkeypatch.setenv(subject.ENV_PREFIX + "OWNER_PID", "1")
    monkeypatch.setenv(subject.ENV_PREFIX + "DEADLINE_UTC", (now + timedelta(seconds=60)).isoformat())
    monkeypatch.setattr(subject, "verify_current_lease", lambda *a, **k: None)
    monkeypatch.setattr(subject, "observe_capture_admission", lambda *a: {"status": "PASS"})
    monkeypatch.setattr(subject, "set_current_process_below_normal", lambda: None)
    args = Namespace(production_repo_root=str(tmp_path), output_root=str(output),
                     request=str(request_path), request_sha256=digest, source_git_sha=SHA, apply=True)
    assert subject.run(args) == 0
    assert (output / "request.json").read_bytes() == request_path.read_bytes()
    assert hashlib.sha256((output / "request.json").read_bytes()).hexdigest() == digest
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "PASS" and result["deleted_files"] == 0
    assert result["cleanup_eligible"] is False and result["reclaimed_bytes"] > 0
    assert source.read_bytes() == original
    after = json.loads((output / "000-after.json").read_text())
    assert after["sha256"] == hashlib.sha256(original).hexdigest()
    assert after["after"]["allocation_bytes"] == metadata.native_allocation(source, source.stat())
    with pytest.raises(ValueError):
        subject.run(args)
    assert json.loads((output / "result.json").read_text()) == result
