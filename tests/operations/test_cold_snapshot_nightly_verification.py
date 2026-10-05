"""Read-only verification closes an unfinished file in a failed nightly batch.

The production shape (as a fixture only): attempt nightly-20261004-0430019896438Z
stopped on capture admission inside batch-0150 after compressing ordinal 002 and
before its after-journal.
"""
from argparse import Namespace
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest

from weather.operations import cold_snapshot_compression as compression
from weather.operations import cold_snapshot_nightly as nightly
from weather.operations import cold_snapshot_nightly_resolution as resolution
from weather.operations import cold_snapshot_nightly_verification as subject
from weather.operations.ntfs_file_compression import LockedNtfsFile
from weather.paths import repo_path
from weather.schema_registry import schema_version

NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
NAME = "nightly-20261004-0430019896438Z"
BATCH = "batch-0150"
FOLDER = "snapshots/highest-temperature-in-atlanta-on-july-13-2026"
TARGET = FOLDER + "/clob_tokens.jsonl"
DIGEST = "1dd66126" + "7" * 56
OLD_SHA, NEW_SHA, HOST = "a" * 40, "b" * 40, "c" * 64


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native(index, *, now=NOW, size=1048576, allocation=1048576, compressed=False):
    return {"size_bytes": size, "allocation_bytes": allocation, "volume_serial": 7, "file_index": index,
            "mtime_ns": int((now - timedelta(days=10)).timestamp()) * 10**9, "creation_filetime": 133,
            "attributes": 0x820 if compressed else 0x20, "compression_format": 2 if compressed else 0}


def selected(path, before):
    return {"path": path, "size_bytes": before["size_bytes"], "allocated_bytes": before["allocation_bytes"],
            "mtime_ns": str(before["mtime_ns"]), "device": str(before["volume_serial"]),
            "file_id": str(before["file_index"]), "attributes": before["attributes"]}


def finished(batch, ordinal, path, before):
    preimage = {"path": path, "before": before, "sha256": f"{ordinal % 10}" * 64,
                "action": "COMPRESS_AND_RETAIN"}
    save(batch / f"{ordinal:03d}-before.json", preimage)
    after = {**before, "allocation_bytes": 4096, "attributes": 0x820, "compression_format": 2}
    save(batch / f"{ordinal:03d}-after.json", {**preimage, "after": after, "status": "VERIFIED",
                                                "reclaimed_bytes": before["allocation_bytes"] - 4096})


def failed_attempt(root, *, before=None, now=NOW, batches=151, ordinal=2, names=None):
    """A failed attempt whose last batch stopped after compressing ``ordinal``.

    ``before`` is the unfinished file's preimage metadata. Earlier batches hold
    one finished file each; earlier files of the last batch are finished.
    """
    attempt = root / "scratch/cold_snapshot_compression" / NAME
    names = names or [f"{FOLDER}/a{i}.jsonl" for i in range(ordinal)] + [TARGET, FOLDER + "/z.jsonl"]
    before = before or native(ordinal, now=now)
    rows = [selected(name, native(i, now=now) if i != ordinal else before) for i, name in enumerate(names)]
    early = [selected(f"{FOLDER}/early-{i:04d}.jsonl", native(1000 + i, now=now)) for i in range(batches - 1)]
    policy_sha = save(attempt / "request.json", {"execution_host_id": HOST, "operation": "compress_and_retain"})
    manifest_sha = save(attempt / "inventory-0000.json", {"status": "PASS", "files": early + rows})
    for number, row in enumerate(early):
        batch = attempt / f"batch-{number:04d}"
        save(batch / "selection.json", {"inventory": "inventory-0000.json", "inventory_sha256": manifest_sha,
                                        "files": [row]})
        finished(batch, 0, row["path"], native(1000 + number, now=now))
        save(batch / "result.json", {"status": "PASS", "results": []})
    batch = attempt / f"batch-{batches - 1:04d}"
    save(batch / "selection.json", {"inventory": "inventory-0000.json", "inventory_sha256": manifest_sha,
                                    "files": rows})
    for index in range(ordinal):
        finished(batch, index, names[index], native(index, now=now))
    preimage = {"path": TARGET, "before": before, "sha256": DIGEST, "action": "COMPRESS_AND_RETAIN"}
    preimage_sha = save(batch / f"{ordinal:03d}-before.json", preimage)
    common = {"source_git_sha": OLD_SHA, "request_sha256": policy_sha, "execution_host_id": HOST,
              "apply": True, "deleted_files": 0, "cleanup_eligible": False}
    save(attempt / "result.json", {**common, "schema_version": schema_version("cold_snapshot_nightly_receipt"),
                                   "status": "FAILED_RETAIN_AND_INSPECT",
                                   "error": "nightly capture admission refused: capture_unhealthy:snapshot"})
    wrapper_sha = save(attempt / "wrapper-result.json", {**common, "status": "FAILED", "hard_stop": False,
                                                         "teardown_proved": True})
    request = {"schema_version": schema_version("cold_snapshot_verification_request"),
               "production_repo_root": str(root), "execution_host_id": HOST,
               "operation": "verify_retained_nightly", "approved_by": "production agent",
               "approved_at_utc": (now - timedelta(minutes=1)).isoformat(),
               "expires_at_utc": (now + timedelta(hours=1)).isoformat(), "attempt": NAME,
               "batch": f"batch-{batches - 1:04d}", "ordinal": ordinal, "preimage_sha256": preimage_sha,
               "predecessor_wrapper_sha256": wrapper_sha}
    return attempt, request, preimage


@pytest.fixture
def unpinned(monkeypatch):
    monkeypatch.setattr(subject, "PinnedNtfsDirectory", lambda p: nullcontext())


class FakeFile:
    def __init__(self, observed, *, digest=DIGEST):
        self.observed, self.digest_value, self.reads = dict(observed), digest, 0
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def metadata(self): return dict(self.observed)
    def compress(self): raise AssertionError("verification must never compress")
    def digest(self, **kwargs):
        kwargs["guard"]()
        self.reads += 1
        return self.digest_value


def check(request, row, preimage, fake):
    def opener(path, *, writable):
        assert writable is False
        if fake is None:
            raise FileNotFoundError(path)
        return fake
    return subject.verify_candidate(Path("unused"), request, row, preimage, guard=lambda: None, opener=opener)


def compressed_state(before, allocation=262144):
    return {**before, "allocation_bytes": allocation, "attributes": 0x820, "compression_format": 2}


def verification_attempt(root, request, proof, *, status="PASS", name="verify-nightly-20261004-a"):
    """The receipts compression.run plus the wrapper write for a read-only PASS."""
    folder = root / "scratch/cold_snapshot_compression" / name
    request_sha = save(folder / "request.json", request)
    common = {"source_git_sha": NEW_SHA, "request_sha256": request_sha, "execution_host_id": HOST,
              "apply": False, "deleted_files": 0, "cleanup_eligible": False, "reclaimed_bytes": 0,
              "verify_retained": True, "source_files_changed": 0}
    result_sha = save(folder / "result.json", {
        **common, "schema_version": schema_version("cold_snapshot_verification_receipt"), "status": status,
        "attempt": request["attempt"], "batch": request["batch"], "ordinal": request["ordinal"],
        "preimage_sha256": request["preimage_sha256"],
        "predecessor_wrapper_sha256": request["predecessor_wrapper_sha256"], "results": [proof],
        "verified_reclaimed_bytes": proof["verified_reclaimed_bytes"]})
    wrapper = folder / "wrapper-result.json"
    return wrapper, save(wrapper, {**common, "status": status, "hard_stop": False, "teardown_proved": True,
                                   "child_result_sha256": result_sha})


def test_production_shape_verifies_and_resolves_the_unfinished_compressed_file(tmp_path, unpinned):
    root = tmp_path.resolve()
    attempt, request, preimage = failed_attempt(root)
    subject.validate_request(request, production_root=root, now=NOW)
    row, bound = subject.read_preimage(request, production_root=root, now=NOW)
    assert row["path"] == TARGET and bound == preimage
    fake = FakeFile(compressed_state(preimage["before"]))
    proof = check(request, row, preimage, fake)
    assert proof["status"] == "VERIFIED_RETAINED" and proof["sha256"] == DIGEST
    assert proof["verified_reclaimed_bytes"] == 1048576 - 262144 and fake.reads == 1
    with pytest.raises(ValueError, match="unfinished"):
        resolution.resolve(root, NAME, "production agent")
    wrapper, wrapper_sha = verification_attempt(root, request, proof)
    record = resolution.resolve(root, NAME, "production agent", verified_retained=str(wrapper),
                                verified_retained_sha256=wrapper_sha)
    assert record["status"] == "RESOLVED" and record["files_verified"] == 150 + 3
    assert record["files"][-1] == {"batch": BATCH, "ordinal": 2, "path": TARGET, "sha256": DIGEST,
                                   "reclaimed_bytes": 1048576 - 262144, "verified_by": "retained_verification",
                                   "verification_wrapper_sha256": wrapper_sha}
    assert record["retained_verifications"] == [wrapper_sha]
    assert record["wrapper_result_sha256"] == sha(attempt / "wrapper-result.json")
    assert record["deleted_files"] == 0 and record["cleanup_eligible"] is False


def test_uncompressed_untouched_file_also_verifies_with_zero_savings(tmp_path, unpinned):
    attempt, request, preimage = failed_attempt(tmp_path.resolve(), batches=1, ordinal=0)
    row, _ = subject.read_preimage(request, production_root=tmp_path.resolve(), now=NOW)
    assert check(request, row, preimage, FakeFile(preimage["before"]))["verified_reclaimed_bytes"] == 0


@pytest.mark.parametrize("case", ["hash_mismatch", "format_unsupported", "compressed_without_attribute",
                                  "uncompressed_allocation_changed", "attribute_changed", "identity_changed",
                                  "missing_file"])
def test_mismatch_wrong_state_or_missing_file_produces_no_verified_record(tmp_path, unpinned, case):
    root = tmp_path.resolve()
    _, request, preimage = failed_attempt(root, batches=2)
    row, _ = subject.read_preimage(request, production_root=root, now=NOW)
    before = preimage["before"]
    observed = {
        "hash_mismatch": compressed_state(before),
        "format_unsupported": {**compressed_state(before), "compression_format": 3},
        "compressed_without_attribute": {**compressed_state(before), "attributes": 0x20},
        "uncompressed_allocation_changed": {**before, "allocation_bytes": 4096},
        "attribute_changed": {**compressed_state(before), "attributes": 0x821},
        "identity_changed": {**compressed_state(before), "mtime_ns": before["mtime_ns"] + 1},
        "missing_file": None,
    }[case]
    fake = None if observed is None else FakeFile(observed, digest="f" * 64 if case == "hash_mismatch" else DIGEST)
    with pytest.raises((ValueError, FileNotFoundError)):
        check(request, row, preimage, fake)
    if fake is not None and case != "hash_mismatch":
        assert fake.reads == 0
    with pytest.raises(ValueError, match="unfinished"):
        resolution.resolve(root, NAME, "production agent")
    assert not (root / "scratch/cold_snapshot_compression/resolved-nightly").exists()


@pytest.mark.parametrize("mutation", [
    lambda p, r: p.update(status="FAILED"),
    lambda p, r: p.update(sha256="f" * 64),
    lambda p, r: p["after"].update(compression_format=3),
    lambda p, r: p["after"].update(attributes=0x20),
    lambda p, r: p.update(path=FOLDER + "/other.jsonl"),
    lambda p, r: p.update(ordinal=1),
    lambda p, r: p.update(verified_reclaimed_bytes=1),
    lambda p, r: r.update(preimage_sha256="e" * 64),
    lambda p, r: r.update(predecessor_wrapper_sha256="e" * 64),
    lambda p, r: r.update(batch="batch-0149"),
])
def test_resolution_refuses_verification_that_does_not_prove_this_file(tmp_path, unpinned, mutation):
    root = tmp_path.resolve()
    _, request, preimage = failed_attempt(root, batches=2)
    row, _ = subject.read_preimage(request, production_root=root, now=NOW)
    proof = check(request, row, preimage, FakeFile(compressed_state(preimage["before"])))
    mutation(proof, request)
    wrapper, wrapper_sha = verification_attempt(root, request, proof)
    with pytest.raises(ValueError, match="verification|retained file"):
        resolution.resolve(root, NAME, "production agent", verified_retained=str(wrapper),
                           verified_retained_sha256=wrapper_sha)
    assert not (root / "scratch/cold_snapshot_compression/resolved-nightly").exists()


def test_resolution_refuses_failed_or_rehashed_verification_attempt(tmp_path, unpinned):
    root = tmp_path.resolve()
    _, request, preimage = failed_attempt(root, batches=2)
    row, _ = subject.read_preimage(request, production_root=root, now=NOW)
    proof = check(request, row, preimage, FakeFile(compressed_state(preimage["before"])))
    wrapper, wrapper_sha = verification_attempt(root, request, proof, status="FAILED_RETAIN_AND_INSPECT")
    with pytest.raises(ValueError, match="read-only PASS"):
        resolution.resolve(root, NAME, "production agent", verified_retained=str(wrapper),
                           verified_retained_sha256=wrapper_sha)
    wrapper, _ = verification_attempt(root, request, proof, name="verify-nightly-20261004-b")
    with pytest.raises(ValueError, match="hash"):
        resolution.resolve(root, NAME, "production agent", verified_retained=str(wrapper),
                           verified_retained_sha256="0" * 64)
    named_like_attempt = root / "scratch/cold_snapshot_compression/nightly-20261004-x/wrapper-result.json"
    with pytest.raises(ValueError, match="exact verification attempt"):
        resolution.resolve(root, NAME, "production agent", verified_retained=str(named_like_attempt),
                           verified_retained_sha256=wrapper_sha)


def test_verification_without_an_unfinished_file_is_refused(tmp_path, unpinned):
    root = tmp_path.resolve()
    attempt, request, preimage = failed_attempt(root, batches=2)
    row, _ = subject.read_preimage(request, production_root=root, now=NOW)
    proof = check(request, row, preimage, FakeFile(compressed_state(preimage["before"])))
    wrapper, wrapper_sha = verification_attempt(root, request, proof)
    finished(attempt / "batch-0001", 2, TARGET, preimage["before"])  # Overwrites the before-journal too.
    with pytest.raises(ValueError, match="verification"):
        resolution.resolve(root, NAME, "production agent", verified_retained=str(wrapper),
                           verified_retained_sha256=wrapper_sha)


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(operation="verify_retained"),
    lambda r: r.update(extra=True),
    lambda r: r.update(attempt="resolved-nightly"),
    lambda r: r.update(batch="batch-150"),
    lambda r: r.update(ordinal=256),
    lambda r: r.update(ordinal=True),
    lambda r: r.update(preimage_sha256="bad"),
    lambda r: r.update(expires_at_utc=(NOW + timedelta(hours=80)).isoformat()),
    lambda r: r.update(expires_at_utc=NOW.isoformat()),
    lambda r: r.update(approved_by=" "),
])
def test_request_contract_is_exact(tmp_path, mutation):
    _, request, _ = failed_attempt(tmp_path.resolve(), batches=1)
    mutation(request)
    with pytest.raises(ValueError):
        subject.validate_request(request, production_root=tmp_path.resolve(), now=NOW)


@pytest.mark.parametrize("damage", ["after_exists", "not_last_batch", "journal_rehashed", "wrapper_passed",
                                    "earlier_unfinished", "selection_differs", "batch_finished"])
def test_preimage_binding_refuses_a_different_or_finished_journal(tmp_path, unpinned, damage):
    root = tmp_path.resolve()
    attempt, request, preimage = failed_attempt(root, batches=2)
    batch = attempt / BATCH.replace("0150", "0001")
    if damage == "after_exists":
        save(batch / "002-after.json", {"status": "VERIFIED"})
    elif damage == "not_last_batch":
        (attempt / "batch-0002").mkdir()
    elif damage == "journal_rehashed":
        save(batch / "002-before.json", {**preimage, "sha256": "f" * 64})
    elif damage == "wrapper_passed":
        wrapper = json.loads((attempt / "wrapper-result.json").read_text())
        request["predecessor_wrapper_sha256"] = save(attempt / "wrapper-result.json", {**wrapper, "status": "PASS"})
    elif damage == "earlier_unfinished":
        (batch / "001-after.json").unlink()
    elif damage == "selection_differs":
        selection = json.loads((batch / "selection.json").read_text())
        selection["files"][2]["size_bytes"] += 1
        save(batch / "selection.json", selection)
    else:
        save(batch / "result.json", {"status": "PASS"})
    with pytest.raises(ValueError):
        subject.read_preimage(request, production_root=root, now=NOW)


def test_wrapper_routes_nightly_requests_through_the_attended_read_only_mode():
    text = (repo_path() / "scripts/ops/cold_snapshot_compression_run.ps1").read_text()
    assert "if ($Nightly -and ($VerifyRetained" in text  # Nightly scheduling never verifies.
    source = (repo_path() / "src/weather/operations/cold_snapshot_compression.py").read_text()
    assert "nightly.is_request(request)" in source and "nightly.read_preimage(" in source


@pytest.mark.skipif(os.name != "nt", reason="native NTFS interrupted nightly compression")
def test_native_nightly_interruption_after_compress_is_verified_and_resolved(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    now = datetime.now(timezone.utc)
    stamp = int((now - timedelta(days=10)).timestamp()) * 10**9
    names = [FOLDER + "/a0.jsonl", FOLDER + "/a1.jsonl", TARGET]
    payloads = {}
    rows = []
    for index, name in enumerate(names):
        source = root / "data" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        payloads[name] = (b'{"token":"' + bytes([97 + index]) * 262144 + b'"}\n') * 2
        source.write_bytes(payloads[name])
        os.utime(source, ns=(stamp, stamp))
        with LockedNtfsFile(source, writable=False) as opened:
            rows.append(selected(name, opened.metadata()))
    handles, large_opener = [], nightly.LARGE_OPENER
    def recording_opener(path, *, writable):
        handles.append(large_opener(path, writable=writable))
        return handles[-1]
    monkeypatch.setattr(nightly, "LARGE_OPENER", recording_opener)
    def admission_lost_after_target_compressed():
        if handles and handles[-1].path.name == "clob_tokens.jsonl" and handles[-1].metadata()["compression_format"] == 2:
            raise ValueError("nightly capture admission refused: capture_unhealthy:snapshot")
    attempt, request, _ = failed_attempt(root, now=now, batches=2, ordinal=2, names=names + [FOLDER + "/z.jsonl"])
    batch = attempt / "batch-0001"
    for entry in list(batch.iterdir()):
        entry.unlink()
    manifest = json.loads((attempt / "inventory-0000.json").read_text())
    manifest["files"] = manifest["files"][:1] + rows
    manifest_sha = save(attempt / "inventory-0000.json", manifest)
    save(batch / "selection.json", {"inventory": "inventory-0000.json", "inventory_sha256": manifest_sha,
                                    "files": rows})
    with pytest.raises(ValueError, match="capture admission"):
        nightly.execute_batch(rows, root, batch, apply=True, guard=admission_lost_after_target_compressed)
    assert sorted(p.name for p in batch.iterdir()) == [
        "000-after.json", "000-before.json", "001-after.json", "001-before.json", "002-before.json",
        "selection.json"]
    journal = json.loads((batch / "002-before.json").read_text())
    assert journal["sha256"] == hashlib.sha256(payloads[TARGET]).hexdigest()
    request.update(batch="batch-0001", preimage_sha256=sha(batch / "002-before.json"))
    request_path = root / "scratch/handoffs/verify-nightly.json"
    request_sha = save(request_path, request)
    save(root / "data/logs/heavy_workload.lock", {"execution_host_id": HOST})
    output = root / "scratch/cold_snapshot_compression/verify-nightly-20261004-native"
    output.mkdir()
    monkeypatch.setenv(compression.ENV_PREFIX + "SOURCE_ROOT", str(repo_path()))
    monkeypatch.setenv(compression.ENV_PREFIX + "OWNER_PID", "1")
    monkeypatch.setenv(compression.ENV_PREFIX + "DEADLINE_UTC", (now + timedelta(seconds=120)).isoformat())
    monkeypatch.delenv(compression.ENV_PREFIX + "OWNER_APPROVED_EXCEPTION", raising=False)
    monkeypatch.setattr(compression, "verify_current_lease", lambda *a, **k: None)
    monkeypatch.setattr(compression, "observe_capture_admission", lambda *a: {"status": "PASS"})
    monkeypatch.setattr(compression, "set_current_process_below_normal", lambda: None)
    def forbid_compression(self): raise AssertionError("verification attempted another compression")
    monkeypatch.setattr(LockedNtfsFile, "compress", forbid_compression)
    target = root / "data" / TARGET
    with LockedNtfsFile(target, writable=False) as opened:
        retained = opened.metadata()
    assert retained["compression_format"] == 2
    args = Namespace(production_repo_root=str(root), request=str(request_path), request_sha256=request_sha,
                     output_root=str(output), source_git_sha=NEW_SHA, apply=False, verify_retained=True)
    assert compression.run(args) == 0
    result = json.loads((output / "result.json").read_text())
    assert result["status"] == "PASS" and result["reclaimed_bytes"] == result["source_files_changed"] == 0
    assert result["results"][0]["sha256"] == journal["sha256"] and (output / "000-verification.json").exists()
    common = {key: result[key] for key in ("source_git_sha", "request_sha256", "execution_host_id", "apply",
                                           "deleted_files", "cleanup_eligible", "reclaimed_bytes",
                                           "verify_retained", "source_files_changed")}
    wrapper_sha = save(output / "wrapper-result.json", {**common, "status": "PASS", "hard_stop": False,
                       "teardown_proved": True, "child_result_sha256": sha(output / "result.json")})
    record = resolution.resolve(root, NAME, "production agent", verified_retained=str(output / "wrapper-result.json"),
                                verified_retained_sha256=wrapper_sha)
    assert record["files_verified"] == 1 + 3
    assert record["files"][-1]["verified_by"] == "retained_verification"
    assert record["files"][-1]["reclaimed_bytes"] == journal["before"]["allocation_bytes"] - retained["allocation_bytes"]
    with LockedNtfsFile(target, writable=False) as opened:
        assert opened.metadata() == retained
    assert target.read_bytes() == payloads[TARGET]
    # A missing retained file fails the same read-only path without a PASS.
    target.unlink()
    second = root / "scratch/cold_snapshot_compression/verify-nightly-20261004-missing"
    second.mkdir()
    args.output_root = str(second)
    assert compression.run(args) == 1
    assert json.loads((second / "result.json").read_text())["status"] == "FAILED_RETAIN_AND_INSPECT"
