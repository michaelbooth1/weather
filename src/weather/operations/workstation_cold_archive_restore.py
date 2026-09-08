"""Restore one independently downloaded provisional archive on the workstation.

Drive facts are supplied by a separately reviewed controller receipt. This
module has no cloud client, production mode, credential provisioning, or delete
executor. Every output belongs to a fresh, create-only restore attempt.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import tarfile
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from weather.operations import workstation_cold_archive_stage as stage
from weather.paths import DATA_ROOT, REPO_ROOT
from weather.schema_registry import schema_version


TOOL = "weather.operations.workstation_cold_archive_restore"
RECEIPT_SCHEMA_VERSION = schema_version("workstation_cold_archive_restore_receipt")
DOWNLOAD_SCHEMA_VERSION = schema_version("workstation_cold_archive_download_receipt")
MAX_EVIDENCE_BYTES = 64 * 1024
MAX_ARCHIVE_BYTES = stage.MAX_SOURCE_BYTES + 2 * 1024 * 1024
MAX_CIPHERTEXT_BYTES = MAX_ARCHIVE_BYTES + 2 * 1024 * 1024
RESTORE_TIMEOUT_SECONDS = 3600
SHA256_RE = re.compile(r"[0-9a-f]{64}")
STAGE_CHECKS = frozenset(
    {
        "source_size_pin", "source_mtime_pin", "source_initial_hash_stable",
        "deterministic_compression", "rclone_config_encrypted",
        "rclone_local_ciphertext_root", "rclone_destination_absent",
        "rclone_create_only_copy", "rclone_cryptcheck", "ciphertext_exact_delta",
        "ciphertext_post_check_stable", "source_post_hash_stable",
        "supporting_inputs_stable",
    }
)
PATH_ARGUMENTS = (
    "stage_manifest", "stage_receipt", "download_receipt", "downloaded_ciphertext",
    "source_root", "source_file", "staging_root", "staging_ciphertext_root",
    "retained_archive", "restore_ciphertext_root", "restore_output_root",
    "receipt_root", "rclone_config", "dpapi_secret", "rclone_executable",
)
ROOT_ARGUMENTS = (
    "source_root", "staging_root", "staging_ciphertext_root",
    "restore_ciphertext_root", "restore_output_root", "receipt_root",
)


class ArchiveRestoreError(stage.ArchiveStageError):
    """A sanitized restore refusal, with no child output or secret material."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ArchiveRestoreError(code, code.replace("_", " "))


def _deadline(deadline: float) -> None:
    _require(time.monotonic() < deadline, "restore_deadline_exceeded")


def _sha(value: Any) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None,
             "evidence_sha256_invalid")
    return value


def _size(value: Any, maximum: int, *, allow_empty: bool = False) -> int:
    _require(type(value) is int and (0 if allow_empty else 1) <= value <= maximum,
             "evidence_size_invalid")
    return value


def _relative(value: Any, *, parts: int | None = None) -> str:
    _require(isinstance(value, str), "evidence_path_invalid")
    segments = value.split("/")
    _require(
        bool(segments) and (parts is None or len(segments) == parts)
        and all(re.fullmatch(r"[A-Za-z0-9._-]{1,255}", part)
                and part not in {".", ".."} for part in segments),
        "evidence_path_invalid",
    )
    return value


def _read_evidence(path: Path) -> tuple[dict[str, Any], str]:
    raw = stage._read_stable_bytes(path, label="restore evidence", maximum_bytes=MAX_EVIDENCE_BYTES)

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result, "evidence_duplicate_key")
            result[key] = value
        return result

    try:
        payload = json.loads(raw, object_pairs_hook=unique_pairs,
                             parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ArchiveRestoreError("evidence_json_invalid", "evidence JSON is invalid") from exc
    _require(isinstance(payload, dict), "evidence_json_invalid")
    return payload, hashlib.sha256(raw).hexdigest()


def _validate_stage_evidence(
    manifest: Mapping[str, Any], receipt: Mapping[str, Any], expected_hash: str,
) -> None:
    _require(manifest.get("schema_version") == stage.MANIFEST_SCHEMA_VERSION,
             "stage_manifest_schema_invalid")
    _require(receipt.get("schema_version") == stage.RECEIPT_SCHEMA_VERSION,
             "stage_receipt_schema_invalid")
    _require(stage.manifest_hash_valid(manifest) and manifest.get("manifest_hash") == _sha(expected_hash),
             "stage_manifest_hash_invalid")
    _require(stage.receipt_hash_valid(receipt) and receipt.get("status") == "PASS",
             "stage_receipt_invalid")
    archive_id = manifest.get("archive_id")
    _require(isinstance(archive_id, str) and stage.ARCHIVE_ID_RE.fullmatch(archive_id) is not None
             and archive_id not in {".", ".."}, "stage_archive_id_invalid")
    _require(receipt.get("archive_id") == archive_id and manifest.get("append_only") is True,
             "stage_evidence_binding_invalid")
    for payload in (manifest, receipt):
        _require(payload.get("mode") == "provisional_mirror_copy", "stage_mode_invalid")
        for name in ("source_retained", "production_identity_not_proved"):
            _require(payload.get(name) is True, "stage_authority_invalid")
        for name in ("Drive_upload_performed", "restore_performed", "cleanup_eligible", "deletion_authorized"):
            _require(payload.get(name) is False, "stage_authority_invalid")
        checks = payload.get("verification")
        _require(isinstance(checks, dict) and set(checks) == STAGE_CHECKS
                 and all(value == "PASS" for value in checks.values()), "stage_verification_invalid")
    tool = stage._validate_tool_identity(manifest.get("tool_identity") or {})
    _require(receipt.get("tool_identity") == tool, "stage_tool_binding_invalid")
    _require(receipt.get("manifest") == {
        "path": f"{archive_id}.manifest.json", "manifest_hash": expected_hash,
    }, "stage_evidence_binding_invalid")
    source, compression, ciphertext = (manifest.get(name) for name in ("source", "compression", "ciphertext"))
    _require(all(isinstance(value, dict) for value in (source, compression, ciphertext)),
             "stage_evidence_shape_invalid")
    _size(source.get("bytes"), stage.MAX_SOURCE_BYTES, allow_empty=True)
    _sha(source.get("sha256"))
    _relative(source.get("path_relative_to_source_root"))
    _require(source.get("retained") is True and type(source.get("last_write_ns")) is int,
             "stage_source_invalid")
    _require(stage._parse_mtime_utc(source.get("last_write_utc", "")) == source["last_write_ns"],
             "stage_source_time_invalid")
    _size(compression.get("bytes"), MAX_ARCHIVE_BYTES)
    _sha(compression.get("sha256"))
    _require(compression.get("format") == stage.ARCHIVE_FORMAT
             and compression.get("member_name") == stage.ARCHIVE_MEMBER_NAME
             and compression.get("normalized_mode") == "0600"
             and compression.get("normalized_uname") == ""
             and compression.get("normalized_gname") == "", "stage_compression_invalid")
    for name in ("normalized_uid", "normalized_gid", "normalized_mtime"):
        _require(type(compression.get(name)) is int and compression[name] == 0,
                 "stage_compression_invalid")
    _size(ciphertext.get("bytes"), MAX_CIPHERTEXT_BYTES)
    _sha(ciphertext.get("sha256"))
    _relative(ciphertext.get("path_relative_to_ciphertext_root"), parts=2)
    _require(receipt.get("encrypted_object") == {
        "state": "verified_retained", "relative_path": ciphertext["path_relative_to_ciphertext_root"],
        "identity": {name: ciphertext[name] for name in ("bytes", "sha256")},
    }, "stage_ciphertext_binding_invalid")


def _validate_download(
    download: Mapping[str, Any], manifest: Mapping[str, Any], stage_receipt: Mapping[str, Any],
    expected_hash: str, input_path: Path, input_identity: Mapping[str, int],
) -> None:
    _require(download.get("schema_version") == DOWNLOAD_SCHEMA_VERSION
             and download.get("status") == "PASS" and stage.receipt_hash_valid(download)
             and download.get("receipt_hash") == _sha(expected_hash), "download_receipt_invalid")
    _require(download.get("archive_id") == manifest["archive_id"]
             and download.get("stage_manifest_hash") == manifest["manifest_hash"]
             and download.get("stage_receipt_hash") == stage_receipt["receipt_hash"],
             "download_stage_binding_invalid")
    for name in ("controller_evidence", "independent_download_performed", "private_permissions_verified"):
        _require(download.get(name) is True, "download_controller_evidence_invalid")
    drive = download.get("drive")
    _require(isinstance(drive, dict) and set(drive) == {"root_folder_id", "folder_id", "file_id"},
             "download_drive_identity_invalid")
    _require(all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{10,200}", value)
                 for value in drive.values()) and len(set(drive.values())) == 3,
             "download_drive_identity_invalid")
    try:
        completed = datetime.fromisoformat(download.get("completed_at_utc", "").replace("Z", "+00:00"))
        _require(completed.tzinfo is not None and completed.utcoffset().total_seconds() == 0,
                 "download_time_invalid")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ArchiveRestoreError("download_time_invalid", "download time is invalid") from exc
    _require(download.get("ciphertext") == {
        name: manifest["ciphertext"][name] for name in ("bytes", "sha256")
    }, "download_ciphertext_binding_invalid")
    supplied = download.get("downloaded_input")
    _require(isinstance(supplied, dict) and isinstance(supplied.get("path"), str),
             "download_input_binding_invalid")
    _require(stage._path_key(stage._absolute_lexical(supplied["path"], label="downloaded input"))
             == stage._path_key(input_path) and supplied.get("identity") == dict(input_identity),
             "download_input_binding_invalid")


def _validate_paths(raw: Mapping[str, Any], restore_id: str, repo: Path, repo_data: Path) -> dict[str, Path]:
    _require(stage.ARCHIVE_ID_RE.fullmatch(restore_id) is not None and restore_id not in {".", ".."},
             "restore_id_invalid")
    paths = {name: stage._absolute_lexical(raw[name], label=name) for name in PATH_ARGUMENTS}
    for name in ROOT_ARGUMENTS:
        paths[name] = stage._require_directory(paths[name], label=name)
    for index, name in enumerate(ROOT_ARGUMENTS):
        root = paths[name]
        _require(not stage._overlaps(root, repo_data), "repository_data_forbidden")
        for other in ROOT_ARGUMENTS[index + 1:]:
            _require(not stage._overlaps(root, paths[other]), "restore_roots_overlap")
    _require(not stage._contains(repo, paths["source_file"]), "repository_source_forbidden")
    _require(stage._contains(paths["source_root"], paths["source_file"]), "source_escape")
    _require(stage._contains(paths["staging_root"], paths["retained_archive"]), "retained_archive_escape")
    for name in set(PATH_ARGUMENTS) - set(ROOT_ARGUMENTS):
        stage._regular_identity(paths[name], label=name)
    for name in ("downloaded_ciphertext", "stage_manifest", "stage_receipt", "download_receipt",
                 "rclone_config", "dpapi_secret", "rclone_executable"):
        for output in ("restore_ciphertext_root", "restore_output_root"):
            _require(not stage._contains(paths[output], paths[name]), "restore_input_output_overlap")
    for original in ("source_root", "staging_root", "staging_ciphertext_root"):
        _require(not stage._contains(paths[original], paths["downloaded_ciphertext"]),
                 "download_not_independent")
    _require(paths["rclone_executable"].name.casefold() in {"rclone", "rclone.exe"},
             "rclone_executable_invalid")
    paths["attempt_directory"] = paths["restore_output_root"] / restore_id
    paths["receipt_path"] = paths["receipt_root"] / f"{restore_id}.restore.receipt.json"
    for name in ("attempt_directory", "receipt_path"):
        _require(not os.path.lexists(paths[name]), "restore_attempt_collision")
    return paths


def _capture_tool_identity(repo: Path) -> dict[str, Any]:
    _require(Path(__file__).resolve() == (repo / "src/weather/operations/workstation_cold_archive_restore.py").resolve()
             and Path(stage.__file__).resolve() == (repo / "src/weather/operations/workstation_cold_archive_stage.py").resolve(),
             "restore_import_identity_invalid")
    helper = stage._capture_tool_identity(repo)
    identity, digest = stage._hash_regular_file(Path(__file__), label="restore module")
    return {**helper, "tool": TOOL, "module_bytes": identity["bytes"], "module_sha256": digest,
            "supporting_stage_module_sha256": helper["module_sha256"]}


def _validate_tool_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(identity)
    _require(result.get("tool") == TOOL, "restore_tool_identity_invalid")
    _sha(result.get("supporting_stage_module_sha256"))
    compatible = {name: value for name, value in result.items() if name != "supporting_stage_module_sha256"}
    stage._validate_tool_identity({**compatible, "tool": stage.TOOL})
    return result


def _verified_file(
    path: Path, expected: Mapping[str, Any], deadline: float, *, destination: Path | None = None,
) -> dict[str, int]:
    """Bounded stable hash, optionally copying into a new regular output."""
    before = stage._regular_identity(path, label="restore input")
    _require(before["bytes"] == expected["bytes"], "restore_size_mismatch")
    digest, count = hashlib.sha256(), 0
    with ExitStack() as stack:
        source = stack.enter_context(path.open("rb"))
        _require(stage._identity_from_stat(os.fstat(source.fileno())) == before, "restore_input_drift")
        output = None
        if destination is not None:
            stage._assert_no_reparse_components(destination.parent, label="restore output parent")
            output = stack.enter_context(destination.open("xb"))
        while True:
            _deadline(deadline)
            block = source.read(min(stage.HASH_BLOCK_SIZE, expected["bytes"] - count + 1))
            if not block:
                break
            count += len(block)
            _require(count <= expected["bytes"], "restore_size_mismatch")
            digest.update(block)
            if output is not None:
                output.write(block)
        _require(count == expected["bytes"] and digest.hexdigest() == expected["sha256"],
                 "restore_hash_mismatch")
        _require(stage._identity_from_stat(os.fstat(source.fileno())) == before, "restore_input_drift")
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
    _require(stage._regular_identity(path, label="restore input") == before, "restore_input_drift")
    return before


class _RestoreClient(stage._RcloneClient):
    def decrypt_archive(self, logical_file: str, destination: Path, expected_bytes: int) -> None:
        # Native crypt-to-local copy may accept an identical existing output.
        # Require an empty destination before any child can touch that directory.
        _exact_entries(destination, set(), "restore_destination_not_empty")
        result = self._invoke(
            (
                "copy", f"{self.remote_name}:{logical_file}", str(destination),
                "--immutable", "--ignore-times", "--error-on-no-transfer", "--no-traverse",
                "--max-depth", "1", "--max-backlog", "4", "--transfers", "1",
                "--checkers", "1", "--retries", "1", "--low-level-retries", "1",
                "--partial-suffix", stage.RCLONE_PARTIAL_SUFFIX,
                "--max-size", str(expected_bytes), "--max-transfer", str(expected_bytes + 1),
            ),
            timeout_key="copy",
        )
        _require(result.returncode == 0, "rclone_restore_copy_failed")


class _DeadlineCompressedReader:
    """Keep gzip's internal header/member reads under the outer byte/time budget."""

    def __init__(self, raw: Any, deadline: float, maximum_bytes: int):
        self.raw, self.deadline, self.remaining = raw, deadline, maximum_bytes

    def read(self, size: int = -1) -> bytes:
        _deadline(self.deadline)
        limit = self.remaining + 1 if size < 0 else min(size, self.remaining + 1)
        block = self.raw.read(limit)
        self.remaining -= len(block)
        _require(self.remaining >= 0, "restore_compressed_size_exceeded")
        _deadline(self.deadline)
        return block


def _exact_entries(directory: Path, expected: set[Path], code: str) -> None:
    stage._require_directory(directory, label="restore directory")
    found: set[Path] = set()
    with os.scandir(directory) as entries:
        for entry in entries:
            path = Path(entry.path)
            _require(path in expected and path not in found, code)
            found.add(path)
    _require(found == expected, code)


def _restore_payload(archive_path: Path, target: Path, expected: Mapping[str, Any], deadline: float) -> None:
    """Read one bounded USTAR header; never process PAX/GNU extension records."""
    identity = stage._regular_identity(archive_path, label="restored archive")
    _size(identity["bytes"], MAX_ARCHIVE_BYTES)
    with archive_path.open("rb") as raw, gzip.GzipFile(
        fileobj=_DeadlineCompressedReader(raw, deadline, identity["bytes"]), mode="rb",
    ) as archive:
        _deadline(deadline)
        header = archive.read(tarfile.BLOCKSIZE)
        _require(len(header) == tarfile.BLOCKSIZE and header[257:265] == b"ustar\x0000"
                 and header[345:500] == bytes(155), "restore_tar_header_invalid")
        try:
            member = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        except (tarfile.HeaderError, UnicodeError, ValueError) as exc:
            raise ArchiveRestoreError("restore_tar_header_invalid", "restore tar header invalid") from exc
        _require(member.name == stage.ARCHIVE_MEMBER_NAME
                 and member.type == tarfile.REGTYPE and member.size == expected["bytes"]
                 and member.mode == 0o600 and member.uid == 0 and member.gid == 0
                 and member.mtime == 0 and member.uname == "" and member.gname == ""
                 and member.linkname == "" and not member.pax_headers,
                 "restore_tar_member_invalid")
        count, digest = 0, hashlib.sha256()
        with target.open("xb") as output:
            while count < expected["bytes"]:
                _deadline(deadline)
                block = archive.read(min(stage.HASH_BLOCK_SIZE, expected["bytes"] - count))
                _require(bool(block), "restore_payload_size_mismatch")
                count += len(block)
                _require(count <= expected["bytes"], "restore_payload_size_mismatch")
                output.write(block)
                digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        _require(count == expected["bytes"] and digest.hexdigest() == expected["sha256"],
                 "restore_payload_hash_mismatch")
        padding = (-count) % tarfile.BLOCKSIZE
        data_end = tarfile.BLOCKSIZE + count + padding
        tar_bytes = ((data_end + 2 * tarfile.BLOCKSIZE + tarfile.RECORDSIZE - 1)
                     // tarfile.RECORDSIZE) * tarfile.RECORDSIZE
        # At most one record plus the two end markers and payload padding.
        footer_bytes = padding + tar_bytes - data_end
        _deadline(deadline)
        footer = archive.read(footer_bytes)
        _require(len(footer) == footer_bytes and footer == bytes(footer_bytes),
                 "restore_tar_extra_member")
        _require(archive.read(1) == b"", "restore_tar_trailing_data")


def restore_provisional_archive(
    *, provisional_mirror_copy: bool, stage_manifest_hash: str, download_receipt_hash: str,
    crypt_remote_name: str, restore_id: str, repo_root: str | Path = REPO_ROOT,
    repo_data_root: str | Path = DATA_ROOT, runner: stage.RcloneRunner = stage._subprocess_runner,
    secret_loader: stage.SecretLoader = stage._load_dpapi_secret,
    tool_identity: Mapping[str, Any] | None = None, wrapper_active: bool | None = None,
    **path_arguments: Any,
) -> dict[str, Any]:
    os.environ.pop(stage.CONFIG_PASS_ENV, None)
    _require(provisional_mirror_copy is True, "provisional_mode_required")
    active = os.environ.get(stage.WRAPPER_ENV) == "1" if wrapper_active is None else wrapper_active
    _require(active is True, "workstation_wrapper_required")
    _require(set(path_arguments) == set(PATH_ARGUMENTS), "restore_arguments_invalid")
    _require(stage.REMOTE_NAME_RE.fullmatch(crypt_remote_name) is not None, "rclone_remote_invalid")
    repo = stage._absolute_lexical(repo_root, label="repository root")
    paths = _validate_paths(path_arguments, restore_id, repo, Path(repo_data_root))
    identity = _validate_tool_identity(tool_identity or _capture_tool_identity(repo))
    pins = {name: stage._regular_identity(path, label=name) for name, path in paths.items()
            if name in set(PATH_ARGUMENTS) - set(ROOT_ARGUMENTS)}
    sink = stage._CreateOnlyJsonSink(paths["receipt_path"])
    secret: stage.SecretMaterial | None = None
    child_environment: dict[str, str] | None = None
    receipt_write_attempted = False
    deadline = time.monotonic() + RESTORE_TIMEOUT_SECONDS
    checks = {name: "NOT_RUN" for name in (
        "stage_evidence", "controller_download_evidence", "encryption_preflight", "restore_key_mapping",
        "downloaded_ciphertext", "retained_archive", "source_initial_hash", "ciphertext_copy",
        "cryptcheck", "archive_decryption", "restored_archive_hash", "single_payload_restore",
        "restored_payload_hash", "source_post_hash", "inputs_stable", "ciphertext_exact_delta",
        "tool_identity_stable",
    )}
    result: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION, "status": "FAIL_CLOSED", "receipt_hash": "",
        "restore_id": restore_id, "mode": "provisional_mirror_copy", "tool_identity": identity,
        "verification": checks, "source_retained": True, "Drive_upload_performed": False,
        "Drive_queried": False, "drive_provenance": "controller_evidence_only",
        "restore_performed": False, "production_identity_not_proved": True,
        "cleanup_eligible": False, "deletion_authorized": False,
        "artifacts_retained_on_failure": True,
    }

    def stable_inputs() -> None:
        _deadline(deadline)
        for name in ROOT_ARGUMENTS:
            stage._require_directory(paths[name], label=name)
        for name, pin in pins.items():
            _require(stage._regular_identity(paths[name], label=name) == pin, "restore_input_drift")

    def bounded_runner(arguments, environment, timeout_seconds, capture_stdout):
        stable_inputs()
        remaining = int(deadline - time.monotonic())
        _require(remaining > 0, "restore_deadline_exceeded")
        return runner(arguments, environment, min(timeout_seconds, remaining), capture_stdout)

    try:
        manifest, manifest_sha = _read_evidence(paths["stage_manifest"])
        staged_receipt, receipt_sha = _read_evidence(paths["stage_receipt"])
        _validate_stage_evidence(manifest, staged_receipt, stage_manifest_hash)
        checks["stage_evidence"] = "PASS"
        download, download_sha = _read_evidence(paths["download_receipt"])
        _validate_download(download, manifest, staged_receipt, download_receipt_hash,
                           paths["downloaded_ciphertext"], pins["downloaded_ciphertext"])
        checks["controller_download_evidence"] = "PASS"
        archive_id = manifest["archive_id"]
        original_relative = manifest["ciphertext"]["path_relative_to_ciphertext_root"]
        original_cipher = paths["staging_ciphertext_root"].joinpath(*original_relative.split("/"))
        original_cipher_identity = stage._regular_identity(original_cipher, label="original ciphertext")
        _require((pins["downloaded_ciphertext"]["device"], pins["downloaded_ciphertext"]["inode"])
                 != (original_cipher_identity["device"], original_cipher_identity["inode"]),
                 "download_not_independent")
        _require(paths["retained_archive"] == paths["staging_root"] / archive_id / stage.ARCHIVE_FILENAME,
                 "retained_archive_binding_invalid")
        _require(paths["source_file"].relative_to(paths["source_root"]).as_posix()
                 == manifest["source"]["path_relative_to_source_root"]
                 and pins["source_file"]["mtime_ns"] == manifest["source"]["last_write_ns"],
                 "source_binding_invalid")
        _exact_entries(paths["retained_archive"].parent, {paths["retained_archive"]},
                       "retained_archive_directory_invalid")
        result.update({
            "archive_id": archive_id,
            "stage_provenance": {"manifest_hash": manifest["manifest_hash"], "manifest_file_sha256": manifest_sha,
                                 "receipt_hash": staged_receipt["receipt_hash"], "receipt_file_sha256": receipt_sha,
                                 "tool_identity": manifest["tool_identity"]},
            "controller_download": {"receipt_hash": download["receipt_hash"], "receipt_file_sha256": download_sha,
                                    "drive": download["drive"], "completed_at_utc": download["completed_at_utc"]},
            "ciphertext": dict(manifest["ciphertext"]), "compression": dict(manifest["compression"]),
            "source": dict(manifest["source"]),
        })
        secret = secret_loader(paths["dpapi_secret"])
        child_environment = {name: value for name, value in os.environ.items()
                             if not name.upper().startswith("RCLONE_")}
        child_environment[stage.CONFIG_PASS_ENV] = secret.text()
        client = _RestoreClient(executable=paths["rclone_executable"], config=paths["rclone_config"],
                                remote_name=crypt_remote_name, environment=child_environment, runner=bounded_runner)

        def encryption_preflight() -> None:
            client.check_config_encryption()
            client.require_local_ciphertext_root(paths["restore_ciphertext_root"])
            stable_inputs()

        encryption_preflight()
        result["rclone_version"] = client.version()
        checks["encryption_preflight"] = "PASS"
        logical_archive = f"{archive_id}/{stage.ARCHIVE_FILENAME}"
        _require(client.encrypted_relative_path(logical_archive) == original_relative, "restore_key_mapping_mismatch")
        logical_restore = f"{restore_id}/{logical_archive}"
        mapped = _relative(client.encrypted_relative_path(logical_restore), parts=3)
        _require(mapped.split("/")[1:] == original_relative.split("/"), "restore_key_mapping_mismatch")
        client.require_destination_absent(restore_id)
        checks["restore_key_mapping"] = "PASS"
        cipher_path = paths["restore_ciphertext_root"].joinpath(*mapped.split("/"))
        if os.name == "nt":
            _require(len(str(cipher_path).encode("utf-16-le")) // 2 < 240,
                     "restore_ciphertext_path_too_long")
        cipher_namespace = paths["restore_ciphertext_root"] / mapped.split("/")[0]
        _require(not os.path.lexists(cipher_namespace), "restore_ciphertext_collision")
        for name, expected, check in (
            ("downloaded_ciphertext", manifest["ciphertext"], "downloaded_ciphertext"),
            ("retained_archive", manifest["compression"], "retained_archive"),
            ("source_file", manifest["source"], "source_initial_hash"),
        ):
            _require(_verified_file(paths[name], expected, deadline) == pins[name], "restore_input_drift")
            checks[check] = "PASS"
        encryption_preflight()
        before_ciphertext = stage._stable_ciphertext_inventory(paths["restore_ciphertext_root"])
        cipher_namespace.mkdir()
        cipher_path.parent.mkdir()
        _verified_file(paths["downloaded_ciphertext"], manifest["ciphertext"], deadline, destination=cipher_path)
        copied_identity = _verified_file(cipher_path, manifest["ciphertext"], deadline)
        checks["ciphertext_copy"] = "PASS"
        stage._validate_ciphertext_delta(before_ciphertext, stage._stable_ciphertext_inventory(paths["restore_ciphertext_root"]),
                                         expected_relative_path=mapped)
        encryption_preflight()
        client.cryptcheck(paths["retained_archive"].parent, f"{restore_id}/{archive_id}")
        _require(_verified_file(cipher_path, manifest["ciphertext"], deadline) == copied_identity, "restore_ciphertext_drift")
        checks["cryptcheck"] = "PASS"
        paths["attempt_directory"].mkdir()
        archive_output = paths["attempt_directory"] / "archive"
        archive_output.mkdir()
        encryption_preflight()
        client.decrypt_archive(logical_restore, archive_output, manifest["compression"]["bytes"])
        checks["archive_decryption"] = "PASS"
        restored_archive = archive_output / stage.ARCHIVE_FILENAME
        _exact_entries(archive_output, {restored_archive}, "restore_archive_inventory_invalid")
        restored_archive_identity = _verified_file(restored_archive, manifest["compression"], deadline)
        checks["restored_archive_hash"] = "PASS"
        restored_payload = paths["attempt_directory"] / stage.ARCHIVE_MEMBER_NAME
        _restore_payload(restored_archive, restored_payload, manifest["source"], deadline)
        checks["single_payload_restore"] = "PASS"
        _verified_file(restored_payload, manifest["source"], deadline)
        checks["restored_payload_hash"] = "PASS"
        _require(_verified_file(restored_archive, manifest["compression"], deadline) == restored_archive_identity,
                 "restore_archive_drift")
        _require(_verified_file(paths["source_file"], manifest["source"], deadline) == pins["source_file"],
                 "restore_source_drift")
        checks["source_post_hash"] = "PASS"
        _require(_verified_file(paths["downloaded_ciphertext"], manifest["ciphertext"], deadline)
                 == pins["downloaded_ciphertext"], "restore_download_drift")
        _require(_verified_file(paths["retained_archive"], manifest["compression"], deadline)
                 == pins["retained_archive"], "retained_archive_drift")
        _require(stage._regular_identity(original_cipher, label="original ciphertext") == original_cipher_identity,
                 "original_ciphertext_drift")
        stable_inputs()
        checks["inputs_stable"] = "PASS"
        _require(_verified_file(cipher_path, manifest["ciphertext"], deadline) == copied_identity,
                 "restore_ciphertext_drift")
        stage._validate_ciphertext_delta(before_ciphertext, stage._stable_ciphertext_inventory(paths["restore_ciphertext_root"]),
                                         expected_relative_path=mapped)
        checks["ciphertext_exact_delta"] = "PASS"
        _exact_entries(archive_output, {restored_archive}, "restore_archive_inventory_invalid")
        _exact_entries(paths["attempt_directory"], {archive_output, restored_payload},
                       "restore_output_inventory_invalid")
        _require(tool_identity is not None or _capture_tool_identity(repo) == identity, "restore_tool_drift")
        checks["tool_identity_stable"] = "PASS"
        result.update({"status": "PASS", "restore_performed": True,
                       "restored_archive": str(restored_archive), "restored_payload": str(restored_payload),
                       "restore_ciphertext_relative_path": mapped})
        result["terminal_at_utc"] = stage._utc_now()
        result["receipt_hash"] = stage.receipt_content_hash(result)
        receipt_write_attempted = True
        sink.write(result)
        return result
    except Exception as exc:
        if not receipt_write_attempted:
            result["status"] = "FAIL_CLOSED"
            result["restore_performed"] = False
            result["error_code"] = exc.code if isinstance(exc, stage.ArchiveStageError) else "restore_failed"
            if isinstance(exc, stage._DpapiRecoveryError):
                result["dpapi_winerror"] = exc.winerror
            result["terminal_at_utc"] = stage._utc_now()
            result["receipt_hash"] = stage.receipt_content_hash(result)
            receipt_write_attempted = True
            sink.write(result)
        if isinstance(exc, stage.ArchiveStageError):
            raise
        raise ArchiveRestoreError("restore_failed", "restore failed closed") from exc
    finally:
        os.environ.pop(stage.CONFIG_PASS_ENV, None)
        if child_environment is not None:
            child_environment.pop(stage.CONFIG_PASS_ENV, None)
            child_environment.clear()
        if secret is not None:
            secret.wipe()
        sink.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provisional-mirror-copy", action="store_true", required=True)
    for name in (*PATH_ARGUMENTS, "stage_manifest_hash", "download_receipt_hash", "crypt_remote_name", "restore_id"):
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = vars(_parser().parse_args(argv))
    try:
        result = restore_provisional_archive(**args)
    except stage.ArchiveStageError as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error_code": exc.code}, sort_keys=True))
        return 2
    print(json.dumps({"status": result["status"], "restore_id": result["restore_id"],
                      "receipt_hash": result["receipt_hash"], "cleanup_eligible": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
