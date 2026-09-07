from copy import deepcopy
from contextlib import nullcontext
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
from weather.operations.ntfs_file_compression import LockedNtfsFile, MAX_FILE_BYTES, MIB, PinnedNtfsDirectory
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
             "heartbeat_age_seconds": 1, "last_clean_iteration_age_seconds": 60,
             "process_identity_matches_lock": True,
             "process_diagnostics": {"status_pid_alive": True, "lock_pid_alive": True}}
            for name in ("snapshot", "clob", "observation_trigger")]


def finish_fixture_plan(args, payload):
    output = Path(args.output_root)
    wrapper = output / "wrapper-result.json"
    compression.write_receipt(wrapper, {
        "status": "PASS", "apply": False, "hard_stop": False, "teardown_proved": True,
        "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
        "execution_host_id": payload["execution_host_id"],
        "child_result_sha256": hashlib.sha256((output / "result.json").read_bytes()).hexdigest(),
    })
    return wrapper


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
                                          opener=lambda *args, **kwargs: fake,
                                          baseline={"sha256": "original", "before": FakeFile().row} if apply else None)


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
    monkeypatch.setattr(compression, "set_current_process_below_normal", lambda: None)
    args = Namespace(production_repo_root=str(tmp_path), output_root=str(output), request=str(request_path),
                     request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),
                     source_git_sha="a" * 40, apply=False, plan_receipt=None, plan_receipt_sha256=None)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    assert compression.run(args) == 0
    wrapper = finish_fixture_plan(args, payload)
    apply_output = output.with_name("fixture-apply")
    apply_output.mkdir()
    args.output_root = str(apply_output)
    args.apply = True
    args.plan_receipt = str(wrapper)
    args.plan_receipt_sha256 = hashlib.sha256(wrapper.read_bytes()).hexdigest()
    output = apply_output
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


@pytest.mark.parametrize("field,value", [
    ("heartbeat_age_seconds", -1), ("heartbeat_age_seconds", 181),
    ("heartbeat_age_seconds", float("inf")), ("heartbeat_age_seconds", None),
    ("last_clean_iteration_age_seconds", 901), ("last_clean_iteration_age_seconds", None),
    ("process_identity_matches_lock", False),
])
def test_fresh_heartbeat_cannot_hide_stalled_or_replaced_snapshot(field, value):
    loops = healthy_loops()
    loops[0][field] = value
    assert admission.check_resources(now=NOW, available=8 * admission.GIB, commit=50,
                                     free_disk=30 * admission.GIB, loops=loops)["status"] == "BLOCK"


@pytest.mark.parametrize("change", ["identity", "bytes"])
def test_apply_rejects_replacement_with_same_size_and_timestamp(change):
    fake = FakeFile()
    if change == "identity": fake.row["file_index"] = 999
    else: fake.digest = lambda **kwargs: "same-length-replacement"
    with pytest.raises(ValueError, match="reviewed plan"):
        exercise(fake)
    assert not fake.compressed


def test_apply_cannot_skip_reviewed_plan():
    fake = FakeFile()
    with pytest.raises(ValueError, match="requires the reviewed plan"):
        compression.compress_candidate(Path("unused"), {}, apply=True, guard=lambda: None,
                                       journal=lambda *args: None, opener=lambda *args, **kwargs: fake)
    assert not fake.compressed


@pytest.fixture
def reviewed_plan(tmp_path, monkeypatch):
    from argparse import Namespace
    monkeypatch.setattr(compression, "PinnedNtfsDirectory", lambda path: nullcontext())
    payload = request(tmp_path)
    output = tmp_path / "scratch/storage_reclaim/plan"
    output.mkdir(parents=True)
    args = Namespace(output_root=str(output), request_sha256="b" * 64, source_git_sha="a" * 40,
                     apply=True, plan_receipt=None, plan_receipt_sha256=None)
    before = {**FakeFile().row, "mtime_ns": int(payload["files"][0]["mtime_ns"])}
    plan = {"schema_version": schema_version("replay_cache_compression_receipt"),
            "status": "PASS", "apply": False, "request_sha256": args.request_sha256,
            "source_git_sha": args.source_git_sha, "deleted_files": 0, "reclaimed_bytes": 0,
            "results": [{"path": RELATIVE, "before": before, "sha256": "c" * 64,
                         "status": "PLANNED", "action": "PLAN_ONLY", "reclaimed_bytes": 0}]}
    compression.write_receipt(output / "result.json", plan)
    wrapper = finish_fixture_plan(args, payload)
    args.plan_receipt, args.plan_receipt_sha256 = str(wrapper), hashlib.sha256(wrapper.read_bytes()).hexdigest()
    return args, payload, tmp_path, tmp_path / "scratch/storage_reclaim/apply"


def test_reviewed_plan_binds_complete_teardown_and_native_preimage(reviewed_plan):
    args, payload, root, output = reviewed_plan
    rows = compression.read_reviewed_plan(args, payload, payload["files"], root, output)
    assert rows[0]["sha256"] == "c" * 64 and rows[0]["before"]["file_index"] == 2


@pytest.mark.parametrize("change", ["wrapper_hash", "child_hash", "failed", "no_teardown",
                                    "wrong_source", "wrong_request", "wrong_host", "was_apply"])
def test_apply_rejects_unreviewed_or_unfinished_plan(reviewed_plan, change):
    args, payload, root, output = reviewed_plan
    path = Path(args.plan_receipt)
    wrapper = json.loads(path.read_text())
    if change == "wrapper_hash": args.plan_receipt_sha256 = "0" * 64
    elif change == "child_hash": (path.parent / "result.json").write_text("{}")
    else:
        field, value = {"failed": ("status", "FAILED"), "no_teardown": ("teardown_proved", False),
                        "wrong_source": ("source_git_sha", "d" * 40),
                        "wrong_request": ("request_sha256", "d" * 64),
                        "wrong_host": ("execution_host_id", "d" * 64), "was_apply": ("apply", True)}[change]
        wrapper[field] = value
        path.write_text(json.dumps(wrapper))
        args.plan_receipt_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        compression.read_reviewed_plan(args, payload, payload["files"], root, output)


def test_output_traversal_cannot_escape_evidence_root(tmp_path):
    with pytest.raises(ValueError, match="evidence"):
        compression._validate_output(tmp_path / "scratch/storage_reclaim/../../data", tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="native evidence namespace pinning")
def test_native_evidence_directory_cannot_move_during_compression(tmp_path):
    output = tmp_path / "evidence/attempt"
    output.mkdir(parents=True)
    with PinnedNtfsDirectory(output):
        with pytest.raises(OSError): output.rename(output.with_name("replaced"))
        with pytest.raises(OSError): output.parent.rename(tmp_path / "other")
        compression.write_receipt(output / "before.json", {"bound": True})
    assert json.loads((output / "before.json").read_text()) == {"bound": True}


@pytest.mark.skipif(os.name != "nt", reason="native OS-held lease verification")
def test_native_stale_lease_record_is_not_ownership(tmp_path):
    path = tmp_path / "lease.json"
    path.write_text('{"pid": 1234}')
    with LockedNtfsFile(path, writable=True):
        admission.verify_lease_file_locked(path)
    with pytest.raises(ValueError, match="not held"):
        admission.verify_lease_file_locked(path)
    assert path.read_text() == '{"pid": 1234}'


@pytest.mark.skipif(os.name != "nt", reason="native priority applies to the actual worker")
def test_native_worker_sets_its_own_below_normal_priority():
    import sys
    result = subprocess.run([sys.executable, "-c",
        "from weather.operations.replay_cache_compression_admission import "
        "set_current_process_below_normal,current_process_priority; "
        "set_current_process_below_normal(); print(current_process_priority())"],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "16384"


def test_capture_admission_reads_real_status_contract_and_checks_process_generation(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(admission, "datetime", Clock)
    monkeypatch.setattr(admission, "observe_process_identity",
                        lambda pid: {"state": "running", "creation_time_token": "win32-filetime:123"})
    monkeypatch.setattr(admission, "available_memory_bytes", lambda: 8 * admission.GIB)
    monkeypatch.setattr(admission, "host_commit_percent", lambda: 50)
    monkeypatch.setattr(admission.shutil, "disk_usage", lambda root: type("Usage", (), {"free": 30 * admission.GIB})())
    monkeypatch.setattr(admission, "process_memory_bytes", lambda: {"private": MIB, "working": MIB})
    monkeypatch.setattr(admission, "current_process_priority", lambda: 0x4000)
    specs = admission.default_loop_specs(tmp_path / "data/snapshots")
    specs[0].status_path.parent.mkdir(parents=True)
    for spec in specs:
        spec.status_path.write_text(json.dumps({"pid": 1234, "consecutive_errors": 0, "paused": False,
            "last_heartbeat": NOW.isoformat(), "last_clean_iteration_at": NOW.isoformat()}))
        spec.status_path.with_name(f".{spec.status_path.name}.writer.lock").write_text(json.dumps({
            "pid": 1234, "managed_process": {"pid": 1234, "creation_time_token": "win32-filetime:123"}}))
    assert admission.capture_admission(tmp_path)["status"] == "PASS"
    monkeypatch.setattr(admission, "observe_process_identity",
                        lambda pid: {"state": "running", "creation_time_token": "win32-filetime:999"})
    result = admission.capture_admission(tmp_path)
    assert result["status"] == "BLOCK"
    assert not result["capture_loops"][0]["process_identity_matches_lock"]
