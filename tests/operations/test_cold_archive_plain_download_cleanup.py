"""Plain download cleanup requires a complete retained copy and exact receipt."""
from contextlib import nullcontext
import copy
import hashlib
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from weather import cold_archive_locations as locations
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import cold_archive_catalog as catalog
from weather.operations import production_cold_archive_stage as archive
from weather.operations import workstation_cold_archive_cleanup as cleanup
from weather.schema_registry import schema_version
from test_cold_archive_catalog import FixturePin
from test_workstation_cold_archive_cleanup import Removal, put


@pytest.fixture
def ready(tmp_path, monkeypatch):
    native_file, native_directory = bridge._file_pin, archive._directory_pin
    monkeypatch.setattr(bridge, "_file_pin", FixturePin)
    monkeypatch.setattr(archive, "_directory_pin", lambda path: nullcontext())
    specs, sources, downloads, proofs = [], [], [], {}
    for aid in ("p11test1", "p11test2"):
        uid = aid + "u1"
        raw = ("verified complete archive " + aid).encode()
        source = put(tmp_path / "scratch" / "ac-in" / aid / "archive.tar.gz", raw)
        download = put(tmp_path / "scratch" / "ac-backup" / uid / "downloaded-archive.tar.gz", raw)
        proof = {"schema_version": schema_version("cold_archive_plain_upload"),
                 "status": "PASS", "attempt_id": uid, "payload_encryption": "none",
                 "independent_download_verified": True, "originals_deleted": 0,
                 "execution_host_id": "b" * 64, "source_path": str(source),
                 "downloaded_path": str(download), "bytes": len(raw),
                 "bundle_sha256": hashlib.sha256(raw).hexdigest()}
        receipt_path = download.parent / "receipt.json"
        _, digest = catalog._write_record(receipt_path, proof)
        specs.append({"path": str(receipt_path), "sha256": digest})
        proofs[receipt_path] = receipt_path.read_bytes()
        sources.append(source)
        downloads.append(download)
    failed = put(tmp_path / "scratch" / "ac-backup" / "failed1" / "partial.bin", b"keep")
    credential = put(tmp_path / "scratch" / "control" / "credential.txt", b"synthetic keep")
    proofs[failed], proofs[credential] = failed.read_bytes(), credential.read_bytes()
    args = dict(upload_receipts=specs, attempt_id="plainclean1", repo_root=tmp_path,
                backup_host_id="b" * 64, admission=lambda: True,
                deadline_monotonic=time.monotonic() + 60, removal_factory=Removal)
    Removal.removed = []
    return SimpleNamespace(args=args, specs=specs, sources=sources, downloads=downloads,
                           proofs=proofs, native_file=native_file, native_directory=native_directory)


def retained(f):
    assert all(path.exists() for path in f.sources)
    assert all(path.read_bytes() == raw for path, raw in f.proofs.items())


def test_only_download_duplicates_removed_and_attempt_spent(ready):
    result = cleanup.cleanup_plain_downloads(**ready.args)
    assert result["status"] == "PASS" and result["deleted_files"] == 2
    assert set(Removal.removed) == set(ready.downloads)
    assert all(not path.exists() and path.parent.is_dir() for path in ready.downloads)
    assert result["originals_deleted"] == result["remote_objects_deleted"] == 0
    assert result["archive_source_reclaimed_bytes"] == 0
    assert len(result["retained_copied_archives"]) == 2
    retained(ready)
    assert locations.read_record(result["receipt_path"], result["receipt_sha256"])[0]["status"] == "PASS"
    with pytest.raises(FileExistsError):
        cleanup.cleanup_plain_downloads(**ready.args)


@pytest.mark.parametrize("fault", ["source_content", "download_content", "missing_source",
                                  "receipt_hash", "receipt_status", "host", "layout",
                                  "encryption", "unverified", "duplicate"])
def test_second_bad_proof_prevents_every_deletion(ready, fault):
    spec = ready.specs[1]
    path = Path(spec["path"])
    proof = locations.read_record(path)[0]
    if fault in ("source_content", "download_content"):
        target = ready.sources[1] if fault == "source_content" else ready.downloads[1]
        target.write_bytes(b"x" * target.stat().st_size)
    elif fault == "missing_source":
        ready.sources[1].unlink()
    elif fault == "receipt_hash":
        spec["sha256"] = "0" * 64
    elif fault == "duplicate":
        ready.specs[1] = copy.deepcopy(ready.specs[0])
    else:
        key, value = {"receipt_status": ("status", "FAILED"), "host": ("execution_host_id", "a" * 64),
                      "layout": ("source_path", str(ready.sources[0])),
                      "encryption": ("payload_encryption", "rclone_crypt"),
                      "unverified": ("independent_download_verified", False)}[fault]
        proof[key] = value
        path.unlink()
        _, spec["sha256"] = catalog._write_record(path, proof)
    with pytest.raises((locations.CatalogIntegrityError, OSError)):
        cleanup.cleanup_plain_downloads(**ready.args)
    assert Removal.removed == [] and all(path.exists() for path in ready.downloads)
    failure = ready.args["repo_root"] / "scratch" / "ac-clean" / "plainclean1" / "failure.json"
    assert locations.read_record(failure)[0]["confirmed_deleted_files"] == 0


def test_lost_admission_after_both_hashes_prevents_all_deletion(ready):
    def refuse():
        raise ValueError("lost reviewed source")
    ready.args["before_deletion"] = refuse
    with pytest.raises(ValueError, match="lost reviewed source"):
        cleanup.cleanup_plain_downloads(**ready.args)
    assert Removal.removed == [] and all(path.exists() for path in ready.downloads)
    retained(ready)


def test_partial_native_failure_retains_exact_journal(ready):
    class FailSecond(Removal):
        def remove(self):
            if self.removed:
                raise OSError("synthetic native refusal")
            super().remove()
    ready.args["removal_factory"] = FailSecond
    with pytest.raises(OSError):
        cleanup.cleanup_plain_downloads(**ready.args)
    assert not ready.downloads[0].exists() and ready.downloads[1].exists()
    failure = ready.args["repo_root"] / "scratch" / "ac-clean" / "plainclean1" / "failure.json"
    assert locations.read_record(failure)[0]["confirmed_deleted_files"] == 1
    retained(ready)


@pytest.mark.skipif(os.name != "nt", reason="native NTFS identity and same-handle deletion")
def test_real_native_pins_and_removal(ready, monkeypatch):
    monkeypatch.setattr(bridge, "_file_pin", ready.native_file)
    monkeypatch.setattr(archive, "_directory_pin", ready.native_directory)
    ready.args.pop("removal_factory")
    result = cleanup.cleanup_plain_downloads(**ready.args)
    assert result["deleted_files"] == 2
    assert all(not path.exists() for path in ready.downloads)
    retained(ready)


@pytest.mark.parametrize("extra", [
    ["--plain-downloads"], ["--upload-receipt", "/tmp/x", "a" * 64],
    ["--plain-downloads", "--upload-receipt", "/tmp/x", "a" * 64, "--entry-path", "/tmp/y"],
])
def test_cli_rejects_incomplete_or_mixed_modes_before_execution(monkeypatch, extra):
    monkeypatch.setattr(cleanup, "run_cleanup", lambda args: pytest.fail("must reject first"))
    with pytest.raises(SystemExit) as exc:
        cleanup.main(["--attempt-id", "clean1", "--expected-source-tip", "a" * 40, *extra])
    assert exc.value.code == 2
