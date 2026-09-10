"""Verified scratch cleanup keeps originals, recovery proof and failed outputs."""
from datetime import datetime, timedelta, timezone
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import time
from types import SimpleNamespace

import pytest

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_catalog as catalog
from weather.operations import cold_archive_recovery_publication as publication
from weather.operations import workstation_cold_archive_cleanup as cleanup
from weather.operations import production_cold_archive_stage as archive
from weather.schema_registry import schema_version
from test_cold_archive_catalog import corpus, CIPHER_BYTES, metadata, recovery, save, sha


def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def regular(path):
    return {**locations.file_identity(path), "mode": stat.S_IFREG}


class Removal:
    removed = []

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def metadata(self):
        return metadata(self.path)

    def digest(self, *, guard):
        guard.admit()
        return sha(self.path)

    def remove(self):
        self.path.unlink()
        self.removed.append(self.path)


@pytest.fixture
def ready(corpus):
    c = corpus
    repo = c.tmp
    aid = c.bound["archive_id"]
    cipher_root = repo / "scratch" / "production_cold_archive_ciphertext" / "c"
    encrypted = put(cipher_root / "directory" / "object", CIPHER_BYTES)
    c.cipher["file_identity"] = regular(encrypted)
    crypt = json.loads(Path(c.args["crypt_receipt"]).read_text())
    crypt["ciphertext"] = copy.deepcopy(c.cipher)
    crypt_path = repo / "crypt-v2.json"
    crypt_sha = save(crypt_path, crypt)
    c.args.update(crypt_receipt=crypt_path, crypt_receipt_sha256=crypt_sha)
    c.bound["crypt_receipt_sha256"] = crypt_sha
    c.uploaded["crypt_receipt_sha256"] = crypt_sha
    for item in c.uploaded["metadata_objects"]:
        if item["kind"] == "crypt_receipt":
            item.update(bytes=crypt_path.stat().st_size, sha256=crypt_sha)
    uploaded_path = repo / "upload-v2.json"
    uploaded_sha = save(uploaded_path, c.uploaded)
    c.args.update(upload_receipt=uploaded_path, upload_receipt_sha256=uploaded_sha)
    args = recovery(c)
    arc = Path(c.args["production_manifest"]).parent / "archive.tar.gz"
    copied = put(repo / "scratch" / "ac-in" / aid / "archive.tar.gz", arc.read_bytes())
    downloaded = put(repo / "scratch" / "production_cold_archive_transport" / "wd1" /
                     "transfer" / ("downloaded-" + aid + ".rclone.bin"), CIPHER_BYTES)
    restored_cipher = put(cipher_root / "restore-directory" / "directory" / "object", CIPHER_BYTES)
    restored_root = repo / "scratch" / "ac-rest" / "wr1"
    restored_arc = put(restored_root / "archive" / "archive.tar.gz", arc.read_bytes())
    payloads = [copied, encrypted, downloaded, restored_cipher, restored_arc]
    for row in c.manifest["files"]:
        payloads.append(put(restored_root / "members" / row["path"], c.contents[Path(row["path"]).name]))
    transport = json.loads(Path(args["transport_receipt"]).read_text())
    transport["downloaded_file"] = {"path": str(downloaded), "bytes": len(CIPHER_BYTES),
                                   "sha256": sha(downloaded)}
    transport_path = repo / "transport-v2.json"
    transport_sha = save(transport_path, transport)
    restored = json.loads(Path(args["restore_receipt"]).read_text())
    restored.update(transport_receipt_sha256=transport_sha, restore_id="wr1",
                    restored_archive=str(restored_arc), downloaded_file_identity=regular(downloaded),
                    restore_ciphertext_relative_path="restore-directory/directory/object")
    restored_path = repo / "restore-v2.json"
    restored_sha = save(restored_path, restored)
    args.update(transport_receipt=transport_path, transport_receipt_sha256=transport_sha,
                restore_receipt=restored_path, restore_receipt_sha256=restored_sha)
    key = {"schema_version": schema_version("cold_archive_key_custody"), "confirmed": True,
           "outside_both_pcs": True, "approved_by": "synthetic owner",
           "confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
           "storage_reference": "synthetic private offline backup"}
    key_path = repo / "key-custody.json"
    key_path.write_text(json.dumps(key))
    key_sha = sha(key_path)
    recovery_root = repo / "scratch" / "production_cold_archive_recovery" / "c" / "data"
    recovery_root.mkdir(parents=True)
    published = publication.publish_recovery(
        **args, key_custody=key_path, key_custody_sha256=key_sha, recovery_data_root=recovery_root,
        attempt_id="pub1", repo_root=repo, backup_host_id="e" * 64)
    arguments = dict(
        entry_path=published["catalog_entry"]["path"], entry_sha256=published["catalog_entry"]["sha256"],
        restore_record=published["restore_record"]["path"], restore_record_sha256=published["restore_record"]["sha256"],
        custody_record=published["custody_record"]["path"], custody_record_sha256=published["custody_record"]["sha256"],
        ciphertext_root=cipher_root, attempt_id="clean1", repo_root=repo, backup_host_id="e" * 64,
        admission=lambda: True, deadline_monotonic=time.monotonic() + 60, removal_factory=Removal)
    failed = put(repo / "scratch" / "ac-rest" / "failed1" / "partial.bin", b"retained failed attempt")
    proof_paths = [Path(arguments[name]) for name in ("entry_path", "restore_record", "custody_record")]
    proof_paths += [key_path, restored_path, transport_path, uploaded_path, crypt_path]
    Removal.removed = []
    return SimpleNamespace(args=arguments, corpus=c, payloads=payloads, failed=failed,
                           proofs={path: path.read_bytes() for path in proof_paths},
                           downloaded=downloaded, cipher_root=cipher_root, restored=restored,
                           restore_path=restored_path, published=published)


def assert_retained(f):
    assert f.failed.read_bytes() == b"retained failed attempt"
    assert all(path.read_bytes() == raw for path, raw in f.proofs.items())
    assert all((f.corpus.day / name).read_bytes() == raw for name, raw in f.corpus.contents.items())


def test_cleanup_removes_only_verified_working_copies(ready):
    logical = sum(path.stat().st_size for path in ready.payloads)
    parents = {path.parent for path in ready.payloads}
    result = cleanup.cleanup_payloads(**ready.args)
    assert result["status"] == "PASS"
    assert result["deleted_files"] == len(ready.payloads)
    assert result["removed_logical_bytes"] == logical
    assert result["archive_source_reclaimed_bytes"] == result["originals_deleted"] == 0
    assert result["remote_objects_deleted"] == 0
    assert set(Removal.removed) == set(ready.payloads)
    assert all(not path.exists() for path in ready.payloads)
    assert all(path.is_dir() for path in parents)
    assert_retained(ready)
    assert locations.read_record(result["receipt_path"], result["receipt_sha256"])[0]["status"] == "PASS"
    with pytest.raises(FileExistsError):
        cleanup.cleanup_payloads(**ready.args)


@pytest.mark.parametrize("index", range(7))
def test_any_changed_payload_prevents_all_deletion(ready, index):
    ready.payloads[index].write_bytes(b"changed")
    with pytest.raises(locations.CatalogIntegrityError):
        cleanup.cleanup_payloads(**ready.args)
    assert all(path.exists() for path in ready.payloads)
    assert Removal.removed == []
    assert_retained(ready)
    failure = ready.corpus.tmp / "scratch" / "ac-clean" / "clean1" / "failure.json"
    assert locations.read_record(failure)[0]["confirmed_deleted_files"] == 0


def test_changed_cipher_native_identity_refuses_even_equal_bytes(ready):
    old = ready.downloaded.with_suffix(".retained")
    ready.downloaded.rename(old)
    ready.downloaded.write_bytes(old.read_bytes())
    with pytest.raises(locations.CatalogIntegrityError, match="identity changed"):
        cleanup.cleanup_payloads(**ready.args)
    assert Removal.removed == []
    assert_retained(ready)


def test_expired_complete_restore_prevents_cleanup(ready):
    ready.args["now"] = datetime.now(timezone.utc) + timedelta(hours=25)
    with pytest.raises(locations.CatalogIntegrityError, match="within the last 24 hours"):
        cleanup.cleanup_payloads(**ready.args)
    assert all(path.exists() for path in ready.payloads)


def test_wrong_host_custody_prevents_cleanup(ready):
    ready.args["backup_host_id"] = "a" * 64
    with pytest.raises(locations.CatalogIntegrityError, match="custody"):
        cleanup.cleanup_payloads(**ready.args)
    assert Removal.removed == []
    assert_retained(ready)


def test_failed_restore_record_prevents_cleanup(ready):
    record = json.loads(Path(ready.args["restore_record"]).read_text())
    record["status"] = "FAILED"
    bad = ready.corpus.tmp / "scratch" / "failed-restore-record.json"
    ready.args["restore_record_sha256"] = save(bad, record)
    ready.args["restore_record"] = str(bad)
    with pytest.raises(locations.CatalogIntegrityError, match="complete restore"):
        cleanup.cleanup_payloads(**ready.args)
    assert Removal.removed == []
    assert_retained(ready)


def test_admission_change_prevents_deletion_after_hashing(ready):
    def refuse():
        raise ValueError("synthetic lost source admission")
    ready.args["before_deletion"] = refuse
    with pytest.raises(ValueError, match="lost source admission"):
        cleanup.cleanup_payloads(**ready.args)
    assert Removal.removed == []
    assert all(path.exists() for path in ready.payloads)


def test_partial_failure_is_journaled_and_not_retried(ready):
    class FailingRemoval(Removal):
        def remove(self):
            if len(self.removed) == 2:
                raise OSError("synthetic native refusal")
            super().remove()
    ready.args["removal_factory"] = FailingRemoval
    with pytest.raises(OSError):
        cleanup.cleanup_payloads(**ready.args)
    attempt = ready.corpus.tmp / "scratch" / "ac-clean" / "clean1"
    failure = locations.read_record(attempt / "failure.json")[0]
    assert failure["confirmed_deleted_files"] == 2
    assert failure["requires_reconciliation"] is True
    assert (attempt / "intent.json").exists()
    assert (attempt / "file-00000.json").exists() and (attempt / "file-00001.json").exists()
    assert not (attempt / "receipt.json").exists()
    assert all(path.exists() for path in ready.payloads[2:])
    assert_retained(ready)
    with pytest.raises(FileExistsError):
        cleanup.cleanup_payloads(**ready.args)


@pytest.mark.parametrize("relative", ["data/file.json", "../weather-mirror/file.json"])
def test_outside_scratch_refusal_precedes_file_read(tmp_path, monkeypatch, relative):
    monkeypatch.setattr(locations, "safe_path", lambda *a, **k: pytest.fail("must reject before stat"))
    with pytest.raises(locations.CatalogIntegrityError, match="scratch"):
        cleanup._scratch(tmp_path / relative, tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="native NTFS removal")
def test_native_cleanup_uses_verified_exact_handles(ready):
    ready.args.pop("removal_factory")
    result = cleanup.cleanup_payloads(**ready.args)
    assert result["deleted_files"] == len(ready.payloads)
    assert all(not path.exists() for path in ready.payloads)
    assert_retained(ready)
