from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from weather.operations import replay_cache_compression as compression
from weather.operations import replay_cache_compression_admission as admission
from weather.operations.ntfs_file_compression import LockedNtfsFile, MAX_FILE_BYTES, MIB
from weather.schema_registry import schema_version


NOW = datetime(2026, 9, 8, 5, tzinfo=timezone.utc)
RELATIVE = "backtest/replay_cache/atlanta-july-1/pooled_candidate_replay__" + "a" * 12 + "__" + "b" * 12 + "__" + "c" * 12 + ".json"


def request(root):
    return {"schema_version": schema_version("replay_cache_compression_request"),
            "production_repo_root": str(root), "approved_by": "fixture owner",
            "operation": "compress_and_retain", "execution_host_id": "a" * 64,
            "approved_at_utc": (NOW - timedelta(hours=12)).isoformat(),
            "expires_at_utc": (NOW + timedelta(hours=8)).isoformat(),
            "files": [{"path": RELATIVE, "size_bytes": 100,
                       "mtime_ns": str(int((NOW - timedelta(days=40)).timestamp()) * 10**9)}]}


def healthy_loops():
    return [{"name": name, "active": True, "degraded": False,
             "heartbeat_fresh": True, "pid_agreement": True,
             "process_diagnostics": {"status_pid_alive": True, "lock_pid_alive": True}}
            for name in ("snapshot", "clob", "observation_trigger")]


def test_bounded_request_validates(tmp_path):
    value = request(tmp_path)
    assert compression.validate_request(value, production_root=tmp_path, now=NOW) == value["files"]


@pytest.mark.parametrize("relative", ["../outside.json", "/absolute.json", "backtest/replay_cache/a/other.json",
                                      RELATIVE + ":stream", RELATIVE.replace("/", "\\"),
                                      "snapshots/" + RELATIVE, RELATIVE.replace("atlanta-july-1", "../a")])
def test_rejects_paths_outside_exact_cache_shape(tmp_path, relative):
    value = request(tmp_path)
    value["files"][0]["path"] = relative
    with pytest.raises(ValueError):
        compression.validate_request(value, production_root=tmp_path, now=NOW)


@pytest.mark.parametrize("change", ["duplicate", "eleven", "large", "zero", "bool_size", "recent",
                                    "future_approval", "expired", "overlong", "no_approval", "wrong_host"])
def test_request_bounds_fail_closed(tmp_path, change):
    value = request(tmp_path)
    candidate = value["files"][0]
    if change == "duplicate": value["files"] *= 2
    elif change == "eleven": value["files"] *= 11
    elif change == "large": candidate["size_bytes"] = MAX_FILE_BYTES + 1
    elif change == "zero": candidate["size_bytes"] = 0
    elif change == "bool_size": candidate["size_bytes"] = True
    elif change == "recent": candidate["mtime_ns"] = str(int(NOW.timestamp()) * 10**9)
    elif change == "future_approval": value["approved_at_utc"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "expired": value["expires_at_utc"] = NOW.isoformat()
    elif change == "overlong": value["expires_at_utc"] = (NOW + timedelta(days=4)).isoformat()
    elif change == "no_approval": value["approved_by"] = ""
    elif change == "wrong_host": value["execution_host_id"] = "portable"
    with pytest.raises(ValueError):
        compression.validate_request(value, production_root=tmp_path, now=NOW)


def test_batch_byte_cap(tmp_path):
    value = request(tmp_path)
    value["files"] = [{**value["files"][0], "size_bytes": MAX_FILE_BYTES,
                       "path": RELATIVE.replace("atlanta-july-1", f"atlanta-{index}")}
                      for index in range(9)]
    with pytest.raises(ValueError, match="512 MiB"):
        compression.validate_request(value, production_root=tmp_path, now=NOW)


@pytest.mark.parametrize("hour,minute,allowed", [(0, 29, False), (0, 30, True), (8, 59, True), (9, 0, False), (14, 0, False), (23, 0, False)])
def test_protected_capture_window(hour, minute, allowed):
    instant = NOW.replace(hour=hour, minute=minute).replace(tzinfo=admission.ZoneInfo("America/Toronto"))
    row = admission.check_resources(now=instant, available=8 * admission.GIB, commit=50,
                                    free_disk=30 * admission.GIB, loops=healthy_loops())
    assert (row["status"] == "PASS") is allowed


@pytest.mark.parametrize("field,value", [("available", None), ("available", 4 * admission.GIB - 1),
                                        ("commit", None), ("commit", 70), ("commit", float("nan")),
                                        ("free_disk", admission.MIN_FREE_DISK_BYTES - 1), ("loops", [])])
def test_resource_failure_blocks(field, value):
    arguments = dict(now=NOW, available=8 * admission.GIB, commit=50,
                     free_disk=30 * admission.GIB, loops=healthy_loops())
    arguments[field] = value
    assert admission.check_resources(**arguments)["status"] == "BLOCK"


def test_dead_capture_pid_blocks_even_fresh_status():
    loops = healthy_loops()
    loops[0]["process_diagnostics"]["status_pid_alive"] = False
    assert admission.check_resources(now=NOW, available=8 * admission.GIB, commit=50,
                                     free_disk=30 * admission.GIB, loops=loops)["status"] == "BLOCK"


class FakeFile:
    def __init__(self, *, drift=False, changed_hash=False, savings=80):
        self.row = {"size_bytes": 100, "allocation_bytes": 100, "volume_serial": 1,
                    "file_index": 2, "mtime_ns": 123, "creation_filetime": 456,
                    "compression_format": 0, "attributes": 32}
        self.compressed = False
        self.drift, self.changed_hash, self.savings = drift, changed_hash, savings

    def __enter__(self): return self
    def __exit__(self, *args): return None
    def metadata(self): return dict(self.row)
    def digest(self, **kwargs): return "changed" if self.compressed and self.changed_hash else "original"
    def compress(self):
        self.compressed = True
        self.row.update(compression_format=2, allocation_bytes=100 - self.savings)
        if self.drift: self.row["file_index"] = 99


def exercise(fake, *, apply=True, journal=None, guard=lambda: None):
    return compression.compress_candidate(Path("unused"), {"path": RELATIVE, "size_bytes": 100, "mtime_ns": "123"},
                                          apply=apply, guard=guard, journal=journal or (lambda *args: None),
                                          opener=lambda *args, **kwargs: fake)


def test_plan_never_compresses_and_preserves_preimage():
    fake, rows = FakeFile(), []
    result = exercise(fake, apply=False, journal=lambda *row: rows.append(row))
    assert not fake.compressed and result["status"] == "PLANNED"
    assert rows[0][0] == "before" and rows[0][1]["sha256"] == "original"


def test_flush_failure_prevents_compression():
    fake = FakeFile()
    def fail(*args): raise OSError("receipt flush failed")
    with pytest.raises(OSError): exercise(fake, journal=fail)
    assert not fake.compressed


def test_admission_rechecked_after_receipt_flush():
    fake, flushed = FakeFile(), False
    def journal(*args):
        nonlocal flushed
        flushed = True
    def guard():
        if flushed: raise ValueError("deadline")
    with pytest.raises(ValueError, match="deadline"): exercise(fake, journal=journal, guard=guard)
    assert not fake.compressed


@pytest.mark.parametrize("options", [{"drift": True}, {"changed_hash": True}, {"savings": 0}, {"savings": -4096}])
def test_changed_or_unproductive_file_stops_expansion(options):
    fake = FakeFile(**options)
    with pytest.raises(ValueError): exercise(fake)
    assert fake.compressed  # The operation never deletes or automatically rolls back.


def test_exact_drift_and_already_compressed_fail_before_mutation():
    fake = FakeFile()
    fake.row["mtime_ns"] = 124
    with pytest.raises(ValueError, match="changed"): exercise(fake)
    assert not fake.compressed
    fake.row.update(mtime_ns=123, compression_format=2)
    with pytest.raises(ValueError, match="already"): exercise(fake)
    assert not fake.compressed


def test_receipts_are_create_only_and_bounded(tmp_path):
    destination = tmp_path / "before.json"
    compression.write_receipt(destination, {"original": True})
    with pytest.raises(FileExistsError): compression.write_receipt(destination, {"replacement": True})
    assert json.loads(destination.read_text()) == {"original": True}
    with pytest.raises(ValueError): compression.write_receipt(tmp_path / "large.json", {"large": "x" * 65536})
    assert not (tmp_path / "large.json").exists()


def test_duplicate_keys_and_oversized_requests_fail(tmp_path):
    source = tmp_path / "request.json"
    source.write_text('{"files": [], "files": [1]}')
    with pytest.raises(ValueError, match="duplicate"):
        compression.read_bounded_json(source, 32768)
    source.write_bytes(b" " * 32769)
    with pytest.raises(ValueError, match="bound"):
        compression.read_bounded_json(source, 32768)


def test_lease_requires_live_owner_and_actual_wrapper_ancestry():
    owner = 4242
    record = {"workload": "replay_cache_compression", "execution_host_profile": "capture_colocated_v1",
              "pid": owner, "owner_process_creation_time_token": "win32-filetime:123"}
    table = {os.getpid(): {"parent_pid": 4241}, 4241: {"parent_pid": owner}}
    describe = lambda *args: {"creation_time_token": "win32-filetime:123"}
    admission.verify_lease_owner(record, owner_pid=owner, table=table, describe=describe)
    with pytest.raises(ValueError, match="process identity"):
        admission.verify_lease_owner(record, owner_pid=owner, table=table,
                                     describe=lambda *args: {"creation_time_token": "win32-filetime:999"})
    with pytest.raises(ValueError, match="ancestor"):
        admission.verify_lease_owner(record, owner_pid=owner,
                                     table={os.getpid(): {"parent_pid": 3333}}, describe=describe)
    with pytest.raises(ValueError, match="lease identity"):
        admission.verify_lease_owner({**record, "execution_host_profile": "workstation_offline_v1"},
                                     owner_pid=owner, table=table, describe=describe)


@pytest.mark.skipif(os.name != "nt", reason="native full workflow with fixture-only admission")
def test_native_run_journals_success_and_rejects_spent_attempt(tmp_path, monkeypatch):
    from argparse import Namespace
    from weather.paths import repo_path
    source = tmp_path / "data" / RELATIVE
    source.parent.mkdir(parents=True)
    source.write_bytes(b'{"synthetic":"' + b"a" * (2 * MIB) + b'"}')
    old = int((datetime.now(timezone.utc) - timedelta(days=45)).timestamp()) * 10**9
    os.utime(source, ns=(old, old))
    payload = request(tmp_path)
    payload.update(approved_at_utc=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                   expires_at_utc=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    payload["files"][0].update(size_bytes=source.stat().st_size, mtime_ns=str(source.stat().st_mtime_ns))
    request_path = tmp_path / "approved.json"
    request_path.write_text(json.dumps(payload))
    lease = tmp_path / "data/logs/heavy_workload.lock"
    lease.parent.mkdir(parents=True)
    lease.write_text(json.dumps({"execution_host_id": "a" * 64}))
    output = tmp_path / "scratch/storage_reclaim/fixture-attempt"
    output.mkdir(parents=True)
    monkeypatch.setenv("WEATHER_CACHE_COMPRESSION_SOURCE_ROOT", str(repo_path()))
    monkeypatch.setenv("WEATHER_CACHE_COMPRESSION_OWNER_PID", "1")
    monkeypatch.setenv("WEATHER_CACHE_COMPRESSION_DEADLINE_UTC",
                       (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat())
    # Only fixture admission is replaced; native locking/hash/compression/journal
    # code runs unchanged against this test's new synthetic temporary file.
    monkeypatch.setattr(compression, "verify_current_lease", lambda *args: None)
    monkeypatch.setattr(compression, "capture_admission", lambda *args: {"status": "PASS"})
    args = Namespace(production_repo_root=str(tmp_path), output_root=str(output), request=str(request_path),
                     request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),
                     source_git_sha="a" * 40, apply=True)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    assert compression.run(args) == 0
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "PASS" and result["deleted_files"] == 0 and result["reclaimed_bytes"] > 0
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    before = json.loads((output / "00-before.json").read_text())
    after = json.loads((output / "00-after.json").read_text())
    assert before["sha256"] == after["sha256"] == original
    with pytest.raises(FileExistsError): compression.run(args)
    assert json.loads((output / "result.json").read_text()) == result


@pytest.mark.skipif(os.name != "nt", reason="native NTFS locking and compression")
def test_native_cache_compression_reader_parity_and_writer_exclusion(tmp_path):
    from weather.backtesting.replay_cache import ReplayCacheKey, read_entry, write_entry
    key = ReplayCacheKey("fixture", "probe", "a" * 64, "b" * 64, "c" * 64)
    path = write_entry(tmp_path, key, rows=[{"id": i, "p": [0.1, 0.2, 0.7]} for i in range(10000)],
                       replay_results={}, coverage={}, diagnostics={})
    original = read_entry(tmp_path, key)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with LockedNtfsFile(path, writable=True) as opened:
        before = opened.metadata()
        with pytest.raises(OSError):
            with path.open("r+b"): pass
        with pytest.raises(OSError): path.rename(path.with_suffix(".moved"))
        with pytest.raises(OSError): path.parent.rename(path.parent.with_name("moved-parent"))
        opened.compress()
        after = opened.metadata()
        assert opened.digest(guard=lambda: None, bytes_per_second=0) == digest
        assert all(before[field] == after[field] for field in compression.IDENTITY_FIELDS)
        assert after["compression_format"] == 2
        assert after["allocation_bytes"] < before["allocation_bytes"]
        assert read_entry(tmp_path, key) == original
    assert path.exists()


@pytest.mark.skipif(os.name != "nt", reason="native NTFS and incompressible capacity measurement")
def test_native_maximum_incompressible_file_preserves_bytes(tmp_path):
    path = tmp_path / "incompressible.json"
    expected = hashlib.sha256()
    with path.open("wb") as stream:
        for _ in range(64):
            block = os.urandom(MIB)
            stream.write(block)
            expected.update(block)
    started = time.monotonic()
    with LockedNtfsFile(path, writable=True) as opened:
        before = opened.metadata()
        opened.compress()
        after = opened.metadata()
        assert opened.digest(guard=lambda: None, bytes_per_second=0) == expected.hexdigest()
        assert all(before[field] == after[field] for field in compression.IDENTITY_FIELDS)
        assert after["allocation_bytes"] <= before["allocation_bytes"] + MAX_FILE_BYTES
    print(json.dumps({"native_incompressible_bytes": MAX_FILE_BYTES, "before": before["allocation_bytes"],
                      "after": after["allocation_bytes"], "elapsed_seconds": time.monotonic() - started,
                      "test_process_memory": admission.process_memory_bytes()}, sort_keys=True))


@pytest.mark.skipif(os.name != "nt", reason="native hardlink protection")
def test_native_rejects_hardlinked_cache_and_existing_writer(tmp_path):
    path, link = tmp_path / "entry.json", tmp_path / "link.json"
    path.write_bytes(b"content")
    os.link(path, link)
    with pytest.raises(ValueError, match="ordinary"):
        with LockedNtfsFile(path, writable=True): pass
    link.unlink()
    with path.open("r+b"):
        with pytest.raises(OSError):
            with LockedNtfsFile(path, writable=True): pass


@pytest.mark.skipif(os.name != "nt", reason="native PowerShell parsing")
def test_wrapper_powershell_syntax():
    from weather.paths import repo_path
    script = repo_path("scripts", "ops", "replay_cache_compression_run.ps1")
    command = "$errors=$null;$tokens=$null;[System.Management.Automation.Language.Parser]::ParseFile('" + str(script) + "',[ref]$tokens,[ref]$errors)|Out-Null;if($errors.Count){throw ($errors|Out-String)}"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
