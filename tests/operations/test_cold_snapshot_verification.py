"""Retained-file verification closes interrupted compression without new writes."""
from argparse import Namespace
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

from weather.operations import cold_snapshot_compression as compression
from weather.operations import cold_snapshot_verification as subject
from weather.operations import storage_recovery_inventory as metadata
from weather.operations.ntfs_file_compression import LockedNtfsFile, MIB
from weather.paths import repo_path
from weather.schema_registry import schema_version

NOW = datetime(2026, 9, 9, 5, tzinfo=timezone.utc)
FOLDER = "snapshots/highest-temperature-in-toronto-on-july-1-2026"
RELATIVE = FOLDER + "/replay_inputs.jsonl"
OLD_SHA, NEW_SHA, HOST = "a" * 40, "b" * 40, "c" * 64


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def native():
    return {"size_bytes": 100, "allocation_bytes": 4096, "attributes": 32,
            "mtime_ns": int((NOW - timedelta(days=45)).timestamp()) * 10**9,
            "file_index": 4, "volume_serial": 3, "creation_filetime": 123,
            "compression_format": 0}


def row(value):
    return {"path": RELATIVE, "size_bytes": value["size_bytes"],
            "allocated_bytes": value["allocation_bytes"], "attributes": value["attributes"],
            "mtime_ns": str(value["mtime_ns"]), "file_id": str(value["file_index"]),
            "device": str(value["volume_serial"])}


def base(root, rows, now=NOW):
    return {"schema_version": schema_version("cold_snapshot_compression_request"),
            "production_repo_root": str(root), "execution_host_id": HOST,
            "operation": "compress_and_retain", "approved_by": "fixture owner",
            "approved_at_utc": (now - timedelta(minutes=1)).isoformat(),
            "expires_at_utc": (now + timedelta(hours=1)).isoformat(), "files": rows,
            "inventory_wrapper_receipt": str(root / "scratch/storage_recovery_inventory/current/wrapper-result.json"),
            "inventory_wrapper_sha256": "d" * 64}


def chain(root, *, before=None, observed=None, now=NOW, digest="e" * 64,
          preimage_mutation=None, wrapper_mutation=None):
    before = before or native()
    observed = observed or {**before, "attributes": 2080, "compression_format": 2, "allocation_bytes": 1024}
    old = base(root, [row(before)], now)
    old_dir = root / "scratch/cold_snapshot_compression/failed"
    old_hash = save(old_dir / "request.json", old)
    preimage = {"schema_version": schema_version("cold_snapshot_compression_receipt"),
                "source_git_sha": OLD_SHA, "request_sha256": old_hash, "execution_host_id": HOST,
                "inventory_wrapper_sha256": old["inventory_wrapper_sha256"], "apply": True,
                "deleted_files": 0, "cleanup_eligible": False, "reclaimed_bytes": 0,
                "path": RELATIVE, "before": before, "sha256": digest, "action": "COMPRESS_AND_RETAIN"}
    wrapper = {"status": "FAILED", "source_git_sha": OLD_SHA, "request_sha256": old_hash,
               "execution_host_id": HOST, "apply": True, "teardown_proved": True,
               "hard_stop": False, "deleted_files": 0, "cleanup_eligible": False}
    if preimage_mutation: preimage_mutation(preimage)
    if wrapper_mutation: wrapper_mutation(wrapper)
    ph = save(old_dir / "000-before.json", preimage)
    wh = save(old_dir / "wrapper-result.json", wrapper)
    request = base(root, [row(observed)], now)
    request.update(schema_version=schema_version("cold_snapshot_verification_request"),
                   operation="verify_retained", preimage_receipt=str(old_dir / "000-before.json"),
                   preimage_sha256=ph, predecessor_wrapper_sha256=wh)
    return request, preimage, observed


@pytest.mark.parametrize("compressed", [False, True])
def test_exact_read_only_request_accepts_retained_file_without_mutating_request(tmp_path, compressed):
    observed = native()
    if compressed: observed.update(attributes=2080, compression_format=2, allocation_bytes=1024)
    request, _, _ = chain(tmp_path, observed=observed)
    original = deepcopy(request)
    assert subject.validate_request(request, production_root=tmp_path, now=NOW) == request["files"]
    assert request == original
    with pytest.raises(ValueError):
        compression.validate_request(request, production_root=tmp_path, now=NOW)


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(operation="compress_and_retain"),
    lambda r: r.update(preimage_sha256="bad"),
    lambda r: r.update(predecessor_wrapper_sha256="bad"),
    lambda r: r.update(extra=True),
    lambda r: r.update(expires_at_utc=NOW.isoformat()),
    lambda r: r["files"].append(dict(r["files"][0])),
    lambda r: r["files"][0].update(size_bytes=64 * MIB + 1),
    lambda r: r["files"][0].update(attributes=2080 | 0x200),
    lambda r: r["files"][0].update(attributes=True),
    lambda r: r["files"][0].update(path=FOLDER + "/../bad.json"),
    lambda r: r["files"][0].update(mtime_ns=str(int(NOW.timestamp()) * 10**9)),
])
def test_verification_preserves_approval_path_age_size_and_one_file_bounds(tmp_path, mutation):
    request, _, _ = chain(tmp_path)
    mutation(request)
    with pytest.raises(ValueError):
        subject.validate_request(request, production_root=tmp_path, now=NOW)


def test_exact_failed_attempt_preimage_can_be_verified_by_new_reviewed_source(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda p: nullcontext())
    request, preimage, _ = chain(tmp_path)
    assert subject.read_preimage(request, request["files"][0], production_root=tmp_path) == preimage


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(source_git_sha=NEW_SHA),
    lambda p: p.update(request_sha256="f" * 64),
    lambda p: p.update(execution_host_id="f" * 64),
    lambda p: p.update(path=FOLDER + "/other.jsonl"),
    lambda p: p.update(sha256="not-a-digest"),
    lambda p: p.update(apply=False),
    lambda p: p.update(reclaimed_bytes=1),
    lambda p: p["before"].update(size_bytes=101),
    lambda p: p["before"].update(creation_filetime=0),
])
def test_rehashed_mismatched_preimage_is_rejected(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda p: nullcontext())
    request, _, _ = chain(tmp_path, preimage_mutation=mutation)
    with pytest.raises(ValueError):
        subject.read_preimage(request, request["files"][0], production_root=tmp_path)


@pytest.mark.parametrize("mutation", [
    lambda w: w.update(status="PASS"),
    lambda w: w.update(teardown_proved=False),
    lambda w: w.update(apply=False),
    lambda w: w.update(execution_host_id="f" * 64),
    lambda w: w.update(source_git_sha=NEW_SHA),
])
def test_failed_wrapper_must_bind_terminal_cleanup_host_and_preimage(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda p: nullcontext())
    request, _, _ = chain(tmp_path, wrapper_mutation=mutation)
    with pytest.raises(ValueError):
        subject.read_preimage(request, request["files"][0], production_root=tmp_path)


def test_changed_journal_hash_or_original_request_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda p: nullcontext())
    request, _, _ = chain(tmp_path)
    request["preimage_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="hash"):
        subject.read_preimage(request, request["files"][0], production_root=tmp_path)
    request, _, _ = chain(tmp_path)
    Path(request["preimage_receipt"]).with_name("request.json").write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        subject.read_preimage(request, request["files"][0], production_root=tmp_path)


class FakeFile:
    def __init__(self, observed, *, digest="e" * 64, drift=False):
        self.observed, self.digest_value, self.drift = dict(observed), digest, drift
        self.reads = 0
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def metadata(self): return dict(self.observed)
    def compress(self): raise AssertionError("verification must never compress")
    def digest(self, **kwargs):
        kwargs["guard"]()
        self.reads += 1
        if self.drift: self.observed["mtime_ns"] += 1
        return self.digest_value


def verify(request, preimage, fake, guard=lambda: None):
    def opener(path, *, writable):
        assert writable is False
        return fake
    return subject.verify_candidate(Path("unused"), request["files"][0], preimage,
                                    guard=guard, opener=opener)


@pytest.mark.parametrize("compressed", [False, True])
def test_verification_only_reads_and_distinguishes_prior_savings_from_new_reclaim(tmp_path, compressed):
    observed = native()
    if compressed: observed.update(attributes=2080, compression_format=2, allocation_bytes=1024)
    request, preimage, _ = chain(tmp_path, observed=observed)
    fake = FakeFile(observed)
    result = verify(request, preimage, fake)
    assert result["status"] == "VERIFIED_RETAINED"
    assert result["reclaimed_bytes"] == result["source_files_changed"] == 0
    assert result["verified_reclaimed_bytes"] == (3072 if compressed else 0)
    assert fake.reads == 1 and fake.observed == observed


@pytest.mark.parametrize("key", ["mtime_ns", "file_index", "volume_serial", "creation_filetime",
                                "allocation_bytes", "attributes", "size_bytes"])
def test_changed_native_identity_or_allocation_blocks_before_payload_read(tmp_path, key):
    request, preimage, observed = chain(tmp_path)
    fake = FakeFile(observed)
    fake.observed[key] += 1
    with pytest.raises(ValueError):
        verify(request, preimage, fake)
    assert fake.reads == 0


@pytest.mark.parametrize("options", [{"digest": "f" * 64}, {"drift": True}])
def test_wrong_hash_or_drift_cannot_produce_verification(tmp_path, options):
    request, preimage, observed = chain(tmp_path)
    with pytest.raises(ValueError, match="content or metadata"):
        verify(request, preimage, FakeFile(observed, **options))


def test_lost_admission_stops_read_only_verification(tmp_path):
    request, preimage, observed = chain(tmp_path)
    def blocked(): raise ValueError("capture admission")
    with pytest.raises(ValueError, match="admission"):
        verify(request, preimage, FakeFile(observed), guard=blocked)


@pytest.mark.skipif(os.name != "nt", reason="native NTFS interrupted-compression recovery")
def test_native_interruption_after_compression_is_verified_without_new_file_mutation(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    source = tmp_path / "data" / RELATIVE
    source.parent.mkdir(parents=True)
    original = b'{"fixture":"' + b"a" * (2 * MIB) + b'"}\n'
    source.write_bytes(original)
    stamp = int((now - timedelta(days=45)).timestamp()) * 10**9
    os.utime(source, ns=(stamp, stamp))
    with LockedNtfsFile(source, writable=False) as opened:
        before = opened.metadata()
    handles, journals = [], []
    def opener(path, *, writable):
        opened = LockedNtfsFile(path, writable=writable)
        handles.append(opened)
        return opened
    def interrupt_after_compression():
        if handles and handles[0].metadata()["compression_format"] == 2:
            raise ValueError("simulated admission loss after compression")
    with pytest.raises(ValueError, match="simulated admission"):
        compression.compress_candidate(source, row(before), apply=True,
            guard=interrupt_after_compression, journal=lambda phase, value: journals.append((phase, value)),
            opener=opener)
    assert [phase for phase, _ in journals] == ["before"]
    with LockedNtfsFile(source, writable=False) as opened:
        observed = opened.metadata()
    assert observed["compression_format"] == 2 and observed["allocation_bytes"] < before["allocation_bytes"]
    request, preimage, _ = chain(tmp_path, before=before, observed=observed, now=now,
                                 digest=hashlib.sha256(original).hexdigest())
    assert journals[0][1]["sha256"] == preimage["sha256"]
    common = {"status": "PASS", "source_git_sha": NEW_SHA, "request_sha256": "1" * 64,
              "execution_host_id": HOST, "cleanup_eligible": False}
    inventory_dir = Path(request["inventory_wrapper_receipt"]).parent
    manifest = {**common, "schema_version": schema_version("storage_recovery_inventory"),
                "data_root": str(tmp_path / "data"), "folders": [{"path": FOLDER, "status": "COMPLETE"}],
                "files": request["files"]}
    mh = save(inventory_dir / "inventory.json", manifest)
    rh = save(inventory_dir / "result.json", {**common, "inventory_sha256": mh})
    request["inventory_wrapper_sha256"] = save(inventory_dir / "wrapper-result.json",
        {**common, "hard_stop": False, "teardown_proved": True, "deleted_files": 0,
         "reclaimed_bytes": 0, "child_result_sha256": rh})
    request_path = tmp_path / "verify.json"
    request_hash = save(request_path, request)
    save(tmp_path / "data/logs/heavy_workload.lock", {"execution_host_id": HOST})
    output = tmp_path / "scratch/cold_snapshot_compression/verification"
    output.mkdir()
    monkeypatch.setenv(compression.ENV_PREFIX + "SOURCE_ROOT", str(repo_path()))
    monkeypatch.setenv(compression.ENV_PREFIX + "OWNER_PID", "1")
    monkeypatch.setenv(compression.ENV_PREFIX + "DEADLINE_UTC", (now + timedelta(seconds=60)).isoformat())
    monkeypatch.delenv(compression.ENV_PREFIX + "OWNER_APPROVED_EXCEPTION", raising=False)
    monkeypatch.setattr(compression, "verify_current_lease", lambda *a, **k: None)
    monkeypatch.setattr(compression, "observe_capture_admission", lambda *a: {"status": "PASS"})
    monkeypatch.setattr(compression, "set_current_process_below_normal", lambda: None)
    def forbid_compression(self): raise AssertionError("verification attempted another compression")
    monkeypatch.setattr(LockedNtfsFile, "compress", forbid_compression)
    args = Namespace(production_repo_root=str(tmp_path), request=str(request_path),
                     request_sha256=request_hash, output_root=str(output), source_git_sha=NEW_SHA,
                     apply=False, verify_retained=True)
    assert compression.run(args) == 0
    result = json.loads((output / "result.json").read_text())
    assert result["reclaimed_bytes"] == result["source_files_changed"] == 0
    assert result["verified_reclaimed_bytes"] == before["allocation_bytes"] - observed["allocation_bytes"]
    assert result["results"][0]["sha256"] == hashlib.sha256(original).hexdigest()
    assert (output / "000-verification.json").exists()
    assert not (output / "000-before.json").exists()
    with LockedNtfsFile(source, writable=False) as opened:
        assert opened.metadata() == observed
    assert source.read_bytes() == original


def test_normal_attribute_is_replaced_when_a_retained_file_is_compressed(tmp_path):
    before = {**native(), "attributes": 128}
    observed = {**before, "attributes": 2048, "compression_format": 2, "allocation_bytes": 1024}
    request, preimage, _ = chain(tmp_path, before=before, observed=observed)
    subject.validate_request(request, production_root=tmp_path, now=NOW)
    assert verify(request, preimage, FakeFile(observed))["verified_reclaimed_bytes"] == 3072
