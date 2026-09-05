from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tarfile
import time
from pathlib import Path

import pytest

from weather.operations import workstation_cold_archive_restore as restore
from weather.operations import workstation_cold_archive_stage as stage
from tests.operations.test_workstation_cold_archive_stage import (
    TOOL_IDENTITY, _layout, _run,
)
from tests.operations.test_workstation_cold_archive_rclone_native import (
    NativeCrypt, native_crypt,  # noqa: F401 -- imported pytest fixture
)


RESTORE_TOOL_IDENTITY = {
    **TOOL_IDENTITY, "tool": restore.TOOL, "supporting_stage_module_sha256": "4" * 64,
}


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path, *, empty: bool = False):
    layout = _layout(tmp_path)
    if empty:
        layout["source"].write_bytes(b"")
    _run(layout)
    manifest_path = layout["receipts"] / f"{layout['archive_id']}.manifest.json"
    stage_receipt_path = layout["receipts"] / f"{layout['archive_id']}.receipt.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stage_receipt = json.loads(stage_receipt_path.read_text(encoding="utf-8"))
    for name in ("restore_ciphertext", "restore_output", "restore_receipts", "inbox"):
        layout[name] = tmp_path / name
        layout[name].mkdir()
    download = layout["inbox"] / "independent-download.bin"
    original = layout["ciphertext"] / manifest["ciphertext"]["path_relative_to_ciphertext_root"]
    download.write_bytes(original.read_bytes())
    downloaded_receipt_path = layout["inbox"] / "download.json"
    downloaded_receipt = {
        "schema_version": restore.DOWNLOAD_SCHEMA_VERSION,
        "status": "PASS", "archive_id": layout["archive_id"],
        "stage_manifest_hash": manifest["manifest_hash"],
        "stage_receipt_hash": stage_receipt["receipt_hash"],
        "controller_evidence": True, "independent_download_performed": True,
        "private_permissions_verified": True,
        "drive": {"root_folder_id": "synthetic-root-id", "folder_id": "synthetic-folder-id",
                  "file_id": "synthetic-file-id"},
        "ciphertext": {name: manifest["ciphertext"][name] for name in ("bytes", "sha256")},
        "downloaded_input": {"path": str(download),
                             "identity": stage._regular_identity(download, label="fixture")},
        "completed_at_utc": "2026-09-05T12:00:00Z",
    }
    downloaded_receipt["receipt_hash"] = stage.receipt_content_hash(downloaded_receipt)
    _write_json(downloaded_receipt_path, downloaded_receipt)
    arguments = {
        "provisional_mirror_copy": True, "stage_manifest": manifest_path,
        "stage_manifest_hash": manifest["manifest_hash"], "stage_receipt": stage_receipt_path,
        "download_receipt": downloaded_receipt_path,
        "download_receipt_hash": downloaded_receipt["receipt_hash"],
        "downloaded_ciphertext": download, "source_root": layout["source_root"],
        "source_file": layout["source"], "staging_root": layout["staging"],
        "staging_ciphertext_root": layout["ciphertext"],
        "retained_archive": layout["staging"] / layout["archive_id"] / stage.ARCHIVE_FILENAME,
        "restore_ciphertext_root": layout["restore_ciphertext"],
        "restore_output_root": layout["restore_output"], "receipt_root": layout["restore_receipts"],
        "rclone_config": layout["config"], "dpapi_secret": layout["secret"],
        "rclone_executable": layout["rclone"], "crypt_remote_name": "fixture_restore_crypt",
        "restore_id": "r1", "repo_root": layout["repo"], "repo_data_root": layout["repo_data"],
        "tool_identity": RESTORE_TOOL_IDENTITY, "wrapper_active": True,
    }
    material = stage.SecretMaterial.from_text("fixture-passphrase")
    arguments["secret_loader"] = lambda _path: material
    fake = FakeRestore(arguments)
    arguments["runner"] = fake
    return arguments, fake, material


class FakeRestore:
    def __init__(self, arguments):
        self.arguments = arguments
        self.calls = []
        self.fail_cryptcheck = False
        self.bad_mapping = False
        self.corrupt_archive = False
        self.config_fails = False
        self.config_root = arguments["restore_ciphertext_root"]
        self.after_cryptcheck = lambda: None

    def __call__(self, argv, environment, timeout_seconds, capture_stdout):
        assert environment[stage.CONFIG_PASS_ENV] == "fixture-passphrase"
        assert not any(name.upper().startswith("RCLONE_") and name != stage.CONFIG_PASS_ENV
                       for name in environment)
        assert 0 < timeout_seconds <= restore.RESTORE_TIMEOUT_SECONDS
        command = list(argv)[8:]
        self.calls.append(command)
        if command[:3] == ["config", "encryption", "check"]:
            return stage.ChildResult(1 if self.config_fails else 0)
        if command[:2] == ["config", "redacted"]:
            return stage.ChildResult(0, (
                f"[{self.arguments['crypt_remote_name']}]\ntype = crypt\n"
                f"remote = {self.config_root}\npassword = XXX\n"
            ).encode())
        if command[0] == "version":
            return stage.ChildResult(0, b"rclone v1.75.1\n")
        if command[0] == "cryptdecode":
            logical = command[-1]
            mapped = "encrypted-dir/encrypted-object"
            if logical.count("/") == 2:
                mapped = "restore-id/" + mapped
            if self.bad_mapping:
                mapped = mapped.replace("encrypted-object", "wrong-object")
            return stage.ChildResult(0, f"{logical}\t{mapped}\n".encode())
        if command[0] == "lsjson":
            return stage.ChildResult(3)
        if command[0] == "cryptcheck":
            self.after_cryptcheck()
            return stage.ChildResult(1 if self.fail_cryptcheck else 0)
        if command[0] == "copy":
            assert command[1] == "fixture_restore_crypt:r1/archive-001/archive.tar.gz"
            for flag in ("--immutable", "--ignore-times", "--error-on-no-transfer", "--no-traverse",
                         "--max-size", "--max-transfer"):
                assert flag in command
            archived = self.arguments["retained_archive"].read_bytes()
            output = Path(command[2]) / stage.ARCHIVE_FILENAME
            with output.open("xb") as handle:
                handle.write(b"bad" if self.corrupt_archive else archived)
            return stage.ChildResult(0)
        raise AssertionError(command)


def _receipt(arguments):
    return json.loads((arguments["receipt_root"] / "r1.restore.receipt.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("empty", [False, True], ids=["ordinary", "empty-source"])
def test_independent_restore_binds_every_layer_and_retains_sources(tmp_path, monkeypatch, empty):
    arguments, fake, material = _fixture(tmp_path, empty=empty)
    monkeypatch.setenv("RCLONE_CONFIG_REMOTE", "untrusted-ambient:")
    source_before = arguments["source_file"].read_bytes()
    result = restore.restore_provisional_archive(**arguments)
    assert result == _receipt(arguments)
    assert result["status"] == "PASS" and stage.receipt_hash_valid(result)
    assert set(result["verification"].values()) == {"PASS"}
    assert Path(result["restored_payload"]).read_bytes() == source_before
    assert arguments["source_file"].read_bytes() == source_before
    assert Path(result["restored_archive"]).read_bytes() == arguments["retained_archive"].read_bytes()
    assert result["drive_provenance"] == "controller_evidence_only"
    for field in ("cleanup_eligible", "deletion_authorized", "Drive_upload_performed", "Drive_queried"):
        assert result[field] is False
    assert result["restore_performed"] and result["production_identity_not_proved"]
    assert material.utf16_bytes == bytes(len(material.utf16_bytes))
    assert stage.CONFIG_PASS_ENV not in os.environ
    assert sum(command[0] == "copy" for command in fake.calls) == 1
    with pytest.raises(stage.ArchiveStageError):
        restore.restore_provisional_archive(**arguments)
    assert _receipt(arguments) == result


@pytest.mark.parametrize("mutation", ["manifest-hash", "download-self-hash", "controller-proof", "input-identity"])
def test_unbound_evidence_fails_before_secret_or_child(tmp_path, mutation):
    arguments, fake, _ = _fixture(tmp_path)
    if mutation == "manifest-hash":
        arguments["stage_manifest_hash"] = "0" * 64
    else:
        receipt = json.loads(arguments["download_receipt"].read_text())
        if mutation == "controller-proof":
            receipt["independent_download_performed"] = False
        elif mutation == "input-identity":
            receipt["downloaded_input"]["identity"]["inode"] += 1
        if mutation != "download-self-hash":
            receipt["receipt_hash"] = stage.receipt_content_hash(receipt)
            arguments["download_receipt_hash"] = receipt["receipt_hash"]
        else:
            receipt["status"] = "FAIL"
        _write_json(arguments["download_receipt"], receipt)
    arguments["secret_loader"] = lambda _path: pytest.fail("secret must not be loaded")
    with pytest.raises(stage.ArchiveStageError):
        restore.restore_provisional_archive(**arguments)
    assert not fake.calls
    assert not list(arguments["restore_ciphertext_root"].iterdir())
    assert _receipt(arguments)["status"] == "FAIL_CLOSED"
    assert stage.receipt_hash_valid(_receipt(arguments))


def test_dpapi_failure_spends_receipt_before_any_heavy_read(tmp_path, monkeypatch):
    arguments, fake, _ = _fixture(tmp_path)
    def fail_secret(_path):
        raise stage._DpapiRecoveryError(5)
    arguments["secret_loader"] = fail_secret
    monkeypatch.setattr(restore, "_verified_file", lambda *args, **kwargs: pytest.fail("heavy read forbidden"))
    with pytest.raises(stage._DpapiRecoveryError):
        restore.restore_provisional_archive(**arguments)
    receipt = _receipt(arguments)
    assert receipt["dpapi_winerror"] == 5
    assert receipt["verification"]["downloaded_ciphertext"] == "NOT_RUN"
    assert fake.calls == []
    assert not list(arguments["restore_output_root"].iterdir())
    with pytest.raises(stage.ArchiveStageError):
        restore.restore_provisional_archive(**arguments)


@pytest.mark.parametrize("failure", ["unencrypted", "cloud-root", "different-local-root"])
def test_config_refusal_precedes_large_reads_and_outputs(tmp_path, monkeypatch, failure):
    arguments, fake, material = _fixture(tmp_path)
    fake.config_fails = failure == "unencrypted"
    if failure == "cloud-root":
        fake.config_root = "cloud:archive"
    elif failure == "different-local-root":
        fake.config_root = arguments["staging_ciphertext_root"]
    monkeypatch.setattr(restore, "_verified_file", lambda *args, **kwargs: pytest.fail("heavy read forbidden"))
    with pytest.raises(stage.ArchiveStageError):
        restore.restore_provisional_archive(**arguments)
    assert not list(arguments["restore_output_root"].iterdir())
    assert not list(arguments["restore_ciphertext_root"].iterdir())
    assert material.utf16_bytes == bytes(len(material.utf16_bytes))
    assert not any(command[0] in {"copy", "cryptcheck"} for command in fake.calls)


@pytest.mark.parametrize("collision", ["plaintext", "ciphertext", "receipt"])
def test_existing_restore_namespace_is_retained(tmp_path, collision):
    arguments, fake, _ = _fixture(tmp_path)
    if collision == "receipt":
        existing = arguments["receipt_root"] / "r1.restore.receipt.json"
        existing.write_bytes(b"retained receipt")
    else:
        root = arguments["restore_output_root" if collision == "plaintext" else "restore_ciphertext_root"]
        directory = root / ("r1" if collision == "plaintext" else "restore-id")
        directory.mkdir()
        existing = directory / "retained.bin"
        existing.write_bytes(b"retained object")
    before = existing.read_bytes()
    with pytest.raises(stage.ArchiveStageError):
        restore.restore_provisional_archive(**arguments)
    assert existing.read_bytes() == before
    assert not any(command[0] in {"copy", "cryptcheck"} for command in fake.calls)


def test_reused_original_ciphertext_file_identity_is_refused(tmp_path):
    arguments, fake, _ = _fixture(tmp_path)
    original = arguments["staging_ciphertext_root"] / "encrypted-dir/encrypted-object"
    independent = arguments["downloaded_ciphertext"]
    independent.unlink()  # Synthetic fixture only: replace its inbox copy with a hard link.
    try:
        os.link(original, independent)
    except OSError as exc:
        pytest.skip(f"fixture filesystem does not support hard links: {exc.errno}")
    receipt = json.loads(arguments["download_receipt"].read_text())
    receipt["downloaded_input"]["identity"] = stage._regular_identity(independent, label="fixture")
    receipt["receipt_hash"] = stage.receipt_content_hash(receipt)
    _write_json(arguments["download_receipt"], receipt)
    arguments["download_receipt_hash"] = receipt["receipt_hash"]
    with pytest.raises(stage.ArchiveStageError, match="download not independent"):
        restore.restore_provisional_archive(**arguments)
    assert fake.calls == []


@pytest.mark.parametrize("failure", ["wrong-key", "cryptcheck", "decrypted-hash", "config-drift", "source-drift"])
def test_crypto_or_input_failure_never_claims_restore(tmp_path, failure):
    arguments, fake, material = _fixture(tmp_path)
    fake.bad_mapping = failure == "wrong-key"
    fake.fail_cryptcheck = failure == "cryptcheck"
    fake.corrupt_archive = failure == "decrypted-hash"
    if failure in {"config-drift", "source-drift"}:
        changed = arguments["rclone_config" if failure == "config-drift" else "source_file"]
        fake.after_cryptcheck = lambda: changed.write_bytes(b"changed supporting input")
    with pytest.raises(stage.ArchiveStageError):
        restore.restore_provisional_archive(**arguments)
    receipt = _receipt(arguments)
    assert receipt["status"] == "FAIL_CLOSED" and not receipt["restore_performed"]
    assert not receipt["cleanup_eligible"] and stage.receipt_hash_valid(receipt)
    assert material.utf16_bytes == bytes(len(material.utf16_bytes))
    if failure != "decrypted-hash":
        assert not any(command[0] == "copy" for command in fake.calls)
    assert arguments["retained_archive"].is_file()


def test_same_identity_damaged_download_fails_local_hash(tmp_path):
    arguments, fake, _ = _fixture(tmp_path)
    download = arguments["downloaded_ciphertext"]
    pinned = download.stat()
    raw = download.read_bytes()
    download.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    os.utime(download, ns=(pinned.st_atime_ns, pinned.st_mtime_ns))
    with pytest.raises(stage.ArchiveStageError, match="restore hash mismatch"):
        restore.restore_provisional_archive(**arguments)
    assert not list(arguments["restore_ciphertext_root"].iterdir())
    assert not any(command[0] == "copy" for command in fake.calls)


def test_receipt_readback_failure_does_not_append_failure_or_rewrite(tmp_path, monkeypatch):
    arguments, _, _ = _fixture(tmp_path)
    original = stage._verify_written_json
    captured = []
    def fail_restore_receipt(path, encoded, *, hash_field):
        if path.name.endswith(".restore.receipt.json"):
            captured.append(path.read_bytes())
            raise stage.ArchiveStageError("evidence_readback_mismatch", "fixture refusal")
        return original(path, encoded, hash_field=hash_field)
    monkeypatch.setattr(stage, "_verify_written_json", fail_restore_receipt)
    with pytest.raises(stage.ArchiveStageError):
        restore.restore_provisional_archive(**arguments)
    assert len(captured) == 1
    path = arguments["receipt_root"] / "r1.restore.receipt.json"
    assert path.read_bytes() == captured[0]


@pytest.mark.parametrize("kind", ["traversal", "symlink", "pax", "extra-member", "trailing-data"])
def test_bounded_tar_parser_refuses_noncanonical_archive(tmp_path, kind):
    payload = b"tiny fixture"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        member = tarfile.TarInfo("../outside" if kind == "traversal" else stage.ARCHIVE_MEMBER_NAME)
        member.size, member.mode = len(payload), 0o600
        if kind == "symlink":
            member.type, member.linkname = tarfile.SYMTYPE, "../outside"
        elif kind == "pax":
            member.type = tarfile.XHDTYPE
        archive.addfile(member, io.BytesIO(payload))
        if kind == "extra-member":
            archive.addfile(tarfile.TarInfo("another"))
    raw = buffer.getvalue() + (b"trailing" if kind == "trailing-data" else b"")
    archived = tmp_path / "malformed.tar.gz"
    archived.write_bytes(gzip.compress(raw, mtime=0))
    output = tmp_path / "payload"
    with pytest.raises(stage.ArchiveStageError):
        restore._restore_payload(archived, output,
                                 {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()},
                                 time.monotonic() + 10)
    assert not (tmp_path.parent / "outside").exists()


def test_gzip_internal_reads_obey_compressed_byte_and_time_bounds(monkeypatch):
    reader = restore._DeadlineCompressedReader(io.BytesIO(b"abcd"), time.monotonic() + 10, 3)
    with pytest.raises(stage.ArchiveStageError, match="compressed size exceeded"):
        reader.read()
    reader = restore._DeadlineCompressedReader(io.BytesIO(b"abcd"), 1, 4)
    monkeypatch.setattr(restore.time, "monotonic", lambda: 2)
    with pytest.raises(stage.ArchiveStageError, match="deadline exceeded"):
        reader.read(1)


def test_native_decrypt_copy_and_payload_parity(native_crypt: NativeCrypt, tmp_path, record_testsuite_property):
    record_testsuite_property("rclone_restore_version", native_crypt.version)
    payload = b"synthetic independent restore bytes\n" * 16
    source = tmp_path / "original-payload"
    source.write_bytes(payload)
    expected = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    archived = native_crypt.source / stage.ARCHIVE_FILENAME
    with source.open("rb") as handle:
        compression = stage._write_deterministic_archive(
            handle, archived, source_bytes=len(payload), expected_sha256=expected["sha256"])
    native_crypt.client.copy_create_only(native_crypt.source, "r1/synthetic-archive")
    native_crypt.client.cryptcheck(native_crypt.source, "r1/synthetic-archive")
    client = restore._RestoreClient(
        executable=native_crypt.client.executable, config=native_crypt.client.config,
        remote_name=native_crypt.client.remote_name, environment=native_crypt.client.environment,
        runner=native_crypt.client.runner,
    )
    destination = tmp_path / "restored"
    destination.mkdir()
    client.decrypt_archive("r1/synthetic-archive/archive.tar.gz", destination, compression["bytes"])
    restored_archive = destination / stage.ARCHIVE_FILENAME
    assert restored_archive.read_bytes() == archived.read_bytes()
    restored_payload = tmp_path / "restored-payload"
    restore._restore_payload(restored_archive, restored_payload, expected, time.monotonic() + 10)
    assert restored_payload.read_bytes() == payload
    before = restored_archive.read_bytes()
    with pytest.raises(stage.ArchiveStageError):
        client.decrypt_archive("r1/synthetic-archive/archive.tar.gz", destination, compression["bytes"])
    assert restored_archive.read_bytes() == before
