"""Bounded encryption and independent restore of a copied production chunk.

No production source discovery, cloud client, credential provisioning, or delete
operation exists here. Each attempt remains spent, including every partial.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import time

from weather.operations import production_cold_archive_stage as core
from weather.operations import workstation_cold_archive_stage as stage
from weather.operations import workstation_cold_archive_restore as restore
from weather.paths import DATA_ROOT, REPO_ROOT
from weather.schema_registry import schema_version

TOOL = "weather.operations.bulk_cold_archive_crypt"
MAX_ARCHIVE_BYTES = core.MAX_CHUNK_BYTES + core.MAX_CHUNK_BYTES // 100 + 2 * core.MIB
MAX_CIPHER_BYTES = MAX_ARCHIVE_BYTES + 2 * core.MIB
DEADLINE_SECONDS = 600
RETENTION = {"source_retained": True, "cleanup_eligible": False,
             "deletion_authorized": False, "fresh_production_identity_proved": False}
ENCRYPT_CHECKS = ("production_evidence", "encryption_preflight", "archive_members",
                  "destination_absent", "ciphertext_copy", "cryptcheck",
                  "ciphertext_hash", "inputs_stable", "tool_identity_stable")
RESTORE_CHECKS = ("production_evidence", "encryption_preflight", "transport_evidence",
                  "independent_ciphertext", "archive_members", "restore_key_mapping",
                  "ciphertext_copy", "cryptcheck", "archive_decryption",
                  "restored_archive_members", "materialized_members",
                  "inputs_stable", "tool_identity_stable")


def _require(condition, code):
    if not condition:
        raise stage.ArchiveStageError(code, code.replace("_", " "))


def _capture_identity(repo):
    value = stage._capture_tool_identity(repo)
    info, digest = stage._hash_regular_file(Path(__file__), label="bulk archive tool")
    value.update(tool=TOOL, module_sha256=digest, module_bytes=info["bytes"])
    return value


def _identity(value):
    _require(isinstance(value, dict) and value.get("tool") == TOOL, "tool_identity_invalid")
    stage._validate_tool_identity({**value, "tool": stage.TOOL})
    return dict(value)


class _Pin(core._ArchiveSource):
    """Use the core native pin, allowing the exact bounded object overhead."""
    def metadata(self):
        info, standard = core._FileInformation(), core._StandardInformation()
        self._check(self._kernel.GetFileInformationByHandle(self.handle, ctypes.byref(info)))
        self._check(self._kernel.GetFileInformationByHandleEx(
            self.handle, 1, ctypes.byref(standard), ctypes.sizeof(standard)))
        size = (int(info.size_high) << 32) | int(info.size_low)
        _require(not info.attributes & ~(0x20 | 0x80 | core.COMPRESSED)
                 and info.links == standard.links == 1 and not standard.delete_pending
                 and not standard.directory and 0 <= size <= MAX_CIPHER_BYTES,
                 "native_file_unsupported")
        return {"size_bytes": size, "allocated_bytes": int(standard.allocation),
                "device": int(info.volume),
                "file_id": (int(info.index_high) << 32) | int(info.index_low),
                "mtime_ns": (core._ticks(info.written) - core.FILETIME_EPOCH) * 100}


def _file_pin(path):
    return _Pin(path)


def _evidence(path, digest, schema, field="receipt_hash"):
    core._require_sha256(digest)
    value, actual = core._load(path, digest)
    core._check_seal(value, field)
    _require(value.get("schema_version") == schema_version(schema), "evidence_schema_invalid")
    return value, actual


def _production(paths, hashes, plan_sha):
    core._require_sha256(plan_sha)
    manifest, _ = _evidence(paths["production_manifest"], hashes["production_manifest_sha256"],
                            "production_cold_archive_manifest", "manifest_hash")
    receipt, _ = _evidence(paths["production_receipt"], hashes["production_receipt_sha256"],
                           "production_cold_archive_receipt")
    return validate_production_evidence(manifest, receipt, plan_sha)


def validate_production_evidence(manifest, receipt, plan_sha):
    """Validate the same complete source proof from files or catalog-held bytes."""
    core._require_sha256(plan_sha)
    _require(isinstance(manifest, dict) and isinstance(receipt, dict), "production_evidence_invalid")
    core._check_seal(manifest, "manifest_hash")
    core._check_seal(receipt, "receipt_hash")
    _require(manifest.get("schema_version") == schema_version("production_cold_archive_manifest")
             and receipt.get("schema_version") == schema_version("production_cold_archive_receipt"),
             "evidence_schema_invalid")
    _require(manifest.get("format") == core.FORMAT, "production_format_invalid")
    rows = core._rows(manifest.get("files"))
    _require(len(rows) <= core.MAX_MEMBERS
             and sum(r["size_bytes"] for r in rows) <= core.MAX_CHUNK_BYTES,
             "production_chunk_unbounded")
    _require(rows == [{k: r[k] for k in rows[0]} for r in manifest["files"]],
             "production_members_unordered")
    for row in manifest["files"]:
        core._require_sha256(row.get("sha256"))
    core._require_sha256(manifest.get("archive_sha256"))
    maximum = sum(r["size_bytes"] for r in rows)
    maximum += maximum // 100 + 2 * core.MIB
    _require(type(manifest.get("archive_bytes")) is int
             and 0 < manifest["archive_bytes"] <= maximum, "production_archive_unbounded")
    _require(re.fullmatch(r"chunk-[0-9]{5}", str(manifest.get("chunk_id"))) is not None,
             "production_chunk_invalid")
    _require(receipt.get("status") == "PASS"
             and receipt.get("manifest_hash") == manifest["manifest_hash"]
             and receipt.get("verification") == {"status": "PASS", "file_count": len(rows),
                                                 "archive_sha256": manifest["archive_sha256"]},
             "production_verification_invalid")
    for item in (manifest, receipt):
        _require(item.get("plan_sha256") == plan_sha
                 and item.get("plan_hash") == manifest.get("plan_hash")
                 and item.get("chunk_id") == manifest["chunk_id"], "production_binding_invalid")
        core._require_sha256(item.get("plan_hash"))
        _require(all(item.get(k) is v for k, v in core.RETENTION.items()),
                 "production_retention_invalid")
    return manifest


class _Client(restore._RestoreClient):
    def require_local_ciphertext_root(self, root):
        super().require_local_ciphertext_root(root)
        response = self._invoke(("config", "redacted", self.remote_name),
                                timeout_key="config_redacted", capture_stdout=True)
        _require(response.returncode == 0, "rclone_config_inspection_failed")
        try:
            lines = response.stdout.decode("utf-8", errors="strict").splitlines()
        except UnicodeError:
            raise stage.ArchiveStageError("rclone_config_inspection_invalid",
                                          "rclone config inspection invalid") from None
        for line in lines:
            if "=" in line:
                key, value = (part.strip().lower() for part in line.split("=", 1))
                if key == "no_data_encryption":
                    _require(value == "false", "rclone_data_encryption_disabled")

    def encrypt_file(self, source, archive_id, expected_bytes):
        # Pass a file, never its mutable parent directory.
        result = self._invoke(("copy", str(source), f"{self.remote_name}:{archive_id}",
            "--immutable", "--ignore-times", "--error-on-no-transfer", "--no-traverse",
            "--max-depth", "1", "--max-backlog", "4", "--transfers", "1",
            "--checkers", "1", "--retries", "1", "--low-level-retries", "1",
            "--partial-suffix", stage.RCLONE_PARTIAL_SUFFIX,
            "--max-size", str(expected_bytes), "--max-transfer", str(expected_bytes + 1)),
            timeout_key="copy")
        _require(result.returncode == 0, "rclone_create_only_copy_failed")

    def check_file(self, source, logical_directory):
        result = self._invoke(("cryptcheck", str(source.parent),
            f"{self.remote_name}:{logical_directory}", "--include", "/archive.tar.gz",
            "--checkers", "1", "--max-depth", "1", "--max-backlog", "4",
            "--retries", "1", "--low-level-retries", "1"), timeout_key="cryptcheck")
        _require(result.returncode == 0, "rclone_cryptcheck_difference")


def _exact(directory, expected):
    restore._exact_entries(directory, set(expected), "attempt_inventory_invalid")


def _hash(path, expected, deadline, destination=None):
    return restore._verified_file(path, expected, deadline, destination=destination)


def _cipher_hash(path, deadline, admission):
    """Hash an encrypted object under its own overhead bound and deadline."""
    info = stage._regular_identity(path, label="ciphertext")
    _require(32 <= info["bytes"] <= MAX_CIPHER_BYTES, "ciphertext_unbounded")
    with path.open("rb") as stream:
        _require(stream.read(8) == b"RCLONE\0\0", "ciphertext_magic_invalid")
        stream.seek(0)
        count, digest = 0, hashlib.sha256()
        while True:
            admission()
            block = stream.read(core.MIB)
            if not block:
                break
            count += len(block)
            _require(count <= info["bytes"], "ciphertext_size_drift")
            digest.update(block)
    restore._deadline(deadline)
    _require(count == info["bytes"] and stage._regular_identity(path, label="ciphertext") == info,
             "ciphertext_identity_drift")
    return count, digest.hexdigest()


def _materialize(archive, output, manifest, deadline, stack):
    """Write only manifest-named regular files; never extract archive-controlled names."""
    output.mkdir()
    stack.enter_context(core._directory_pin(output))
    directories = {output}
    restored = []
    with archive.open("rb") as raw, gzip.GzipFile(fileobj=restore._DeadlineCompressedReader(
            raw, deadline, manifest["archive_bytes"]), mode="rb") as stream:
        for row in manifest["files"]:
            restore._deadline(deadline)
            name = core._relative(row["path"])
            # Additional Windows filename aliases must never become restore targets.
            for part in name.split("/"):
                _require(not any(c in part for c in '<>"|?*')
                         and part.split(".", 1)[0].upper() not in
                         {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
                          *(f"LPT{i}" for i in range(10))}, "restore_member_path_invalid")
            target = output.joinpath(*name.split("/"))
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = row["size_bytes"], 0o600, 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            _require(stream.read(512) == info.tobuf(format=tarfile.USTAR_FORMAT, encoding="utf-8"),
                     "restore_member_header_invalid")
            for directory in reversed(target.parent.parents):
                if directory != output and output in directory.parents and directory not in directories:
                    directory.mkdir()
                    stack.enter_context(core._directory_pin(directory))
                    directories.add(directory)
            if target.parent not in directories:
                target.parent.mkdir()
                stack.enter_context(core._directory_pin(target.parent))
                directories.add(target.parent)
            count, digest = 0, hashlib.sha256()
            with target.open("xb") as handle:
                while count < row["size_bytes"]:
                    restore._deadline(deadline)
                    block = stream.read(min(core.MIB, row["size_bytes"] - count))
                    _require(bool(block), "restore_member_truncated")
                    _require(handle.write(block) == len(block), "restore_member_short_write")
                    count += len(block)
                    digest.update(block)
                handle.flush()
                os.fsync(handle.fileno())
            _require(digest.hexdigest() == row["sha256"], "restore_member_hash_mismatch")
            padding = (-count) % 512
            _require(stream.read(padding) == bytes(padding), "restore_member_padding_invalid")
            pin = stack.enter_context(_file_pin(target))
            before = pin.metadata()
            _hash(target, {"bytes": count, "sha256": row["sha256"]}, deadline)
            _require(pin.metadata() == before, "restore_member_drift")
            restored.append({"path": name, "bytes": count, "sha256": row["sha256"]})
    for directory in directories:
        expected = {path for path in directories if path.parent == directory}
        expected.update(output.joinpath(*r["path"].split("/")) for r in restored
                        if output.joinpath(*r["path"].split("/")).parent == directory)
        _exact(directory, expected)
    return restored


def _upstream_restore(paths, hashes, result, manifest):
    crypt, _ = _evidence(paths["crypt_receipt"], hashes["crypt_receipt_sha256"],
                         "production_cold_archive_crypt_receipt")
    transport, _ = _evidence(paths["transport_receipt"], hashes["transport_receipt_sha256"],
                             "production_cold_archive_transport_receipt")
    for value in (crypt, transport):
        _require(value.get("status") == "PASS", "upstream_not_pass")
        for key in ("plan_sha256", "chunk_id", "archive_id", "production_manifest_sha256"):
            _require(value.get(key) == result[key], "upstream_binding_invalid")
    _require(crypt.get("production_receipt_sha256") == result["production_receipt_sha256"]
             and crypt.get("archive_bytes") == manifest["archive_bytes"]
             and crypt.get("archive_sha256") == manifest["archive_sha256"],
             "crypt_production_binding_invalid")
    _require(all(crypt.get(k) is v for k, v in RETENTION.items())
             and crypt.get("checks") == dict.fromkeys(ENCRYPT_CHECKS, "PASS"), "crypt_checks_invalid")
    _identity(crypt.get("tool_identity"))
    cipher = crypt.get("ciphertext")
    _require(isinstance(cipher, dict), "cipher_evidence_invalid")
    restore._size(cipher.get("bytes"), MAX_CIPHER_BYTES)
    core._require_sha256(cipher.get("sha256"))
    restore._relative(cipher.get("path_relative_to_ciphertext_root"), parts=2)
    _require(transport.get("crypt_receipt_sha256") == hashes["crypt_receipt_sha256"]
             and transport.get("independent_download") is True
             and transport.get("ciphertext") == {k: cipher[k] for k in ("bytes", "sha256")},
             "transport_cipher_binding_invalid")
    drive, downloaded = transport.get("drive"), transport.get("downloaded_file")
    _require(isinstance(drive, dict) and all(isinstance(drive.get(k), str) and drive[k]
             for k in ("root_folder_id", "object_id", "remote_key"))
             and drive["root_folder_id"] != drive["object_id"], "transport_drive_invalid")
    _require(isinstance(downloaded, dict) and isinstance(downloaded.get("path"), str)
             and bool(downloaded["path"])
             and all(downloaded.get(k) == cipher[k] for k in ("bytes", "sha256")),
             "transport_download_invalid")
    # Transport paths can identify a different host. Local SHA-256 is independently
    # checked; a byte-verified SCP relocation is not a new cloud provenance claim.
    result.update(crypt_receipt_sha256=hashes["crypt_receipt_sha256"],
                  transport_receipt_sha256=hashes["transport_receipt_sha256"],
                  drive=dict(drive), drive_provenance="controller_evidence_only")
    return cipher


def run(operation, *, archive_file=None, production_manifest, production_manifest_sha256,
        production_receipt, production_receipt_sha256, plan_sha256, archive_id,
        rclone_executable, rclone_config, dpapi_secret, crypt_remote_name,
        ciphertext_root, output_root, restore_id=None, crypt_receipt=None,
        crypt_receipt_sha256=None, transport_receipt=None, transport_receipt_sha256=None,
        downloaded_file=None, original_ciphertext_root=None, repo_root=REPO_ROOT,
        repo_data_root=DATA_ROOT, wrapper_active=None, tool_identity=None,
        runner=stage._subprocess_runner, secret_loader=stage._load_dpapi_secret):
    """Process one exact copied chunk under the workstation wrapper's shared Job."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    active = os.environ.get(stage.WRAPPER_ENV) == "1" if wrapper_active is None else wrapper_active
    _require(active is True, "workstation_wrapper_required")
    _require(operation in {"encrypt", "restore"}, "operation_invalid")
    _require(isinstance(archive_id, str) and stage.ARCHIVE_ID_RE.fullmatch(archive_id)
             and archive_id not in {".", ".."} and not archive_id.endswith((".", " ")),
             "archive_id_invalid")
    _require(isinstance(crypt_remote_name, str) and stage.REMOTE_NAME_RE.fullmatch(crypt_remote_name),
             "remote_name_invalid")
    namespace = restore_id if operation == "restore" else archive_id
    _require(isinstance(namespace, str) and stage.ARCHIVE_ID_RE.fullmatch(namespace)
             and namespace not in {".", ".."} and not namespace.endswith((".", " ")),
             "attempt_id_invalid")
    paths = {k: core._safe_path(v) for k, v in {
        "production_manifest": production_manifest,
        "production_receipt": production_receipt, "rclone_executable": rclone_executable,
        "rclone_config": rclone_config, "dpapi_secret": dpapi_secret}.items()}
    if operation == "encrypt" or archive_file is not None:
        paths["archive_file"] = core._safe_path(archive_file)
        _require(paths["archive_file"].name == "archive.tar.gz", "archive_filename_invalid")
    roots = {"ciphertext_root": core._safe_path(ciphertext_root, directory=True),
             "output_root": core._safe_path(output_root, directory=True)}
    hashes = {"production_manifest_sha256": production_manifest_sha256,
              "production_receipt_sha256": production_receipt_sha256}
    if operation == "restore":
        paths.update({k: core._safe_path(v) for k, v in {
            "crypt_receipt": crypt_receipt, "transport_receipt": transport_receipt,
            "downloaded_file": downloaded_file}.items()})
        if original_ciphertext_root is not None:
            roots["original_ciphertext_root"] = core._safe_path(original_ciphertext_root, directory=True)
        hashes.update(crypt_receipt_sha256=crypt_receipt_sha256,
                      transport_receipt_sha256=transport_receipt_sha256)
    for digest in (*hashes.values(), plan_sha256):
        core._require_sha256(digest)
    for path in (*paths.values(), *roots.values()):
        _require(not stage._overlaps(path, Path(repo_data_root)), "repository_data_overlap")
    for key, root in roots.items():
        _require(all(not stage._overlaps(root, other) for name, other in roots.items() if name != key),
                 "output_roots_overlap")
        # Retained upstream receipts may live under the encrypt receipt root,
        # but never under either destination root of this fresh operation.
        if key != "original_ciphertext_root":
            _require(all(not stage._contains(root, path) for path in paths.values()), "input_output_overlap")
    identity = _identity(tool_identity if tool_identity is not None else _capture_identity(Path(repo_root)))
    restore._deadline(deadline)
    attempt = roots["output_root"] / namespace
    result = {"schema_version": schema_version("production_cold_archive_crypt_receipt"
              if operation == "encrypt" else "production_cold_archive_restore_receipt"),
              "status": "FAIL_CLOSED", "plan_sha256": plan_sha256, "archive_id": archive_id,
              **hashes, **RETENTION, "tool_identity": identity,
              "checks": dict.fromkeys(ENCRYPT_CHECKS if operation == "encrypt" else RESTORE_CHECKS,
                                      "NOT_RUN"), "artifacts_retained_on_failure": True}
    if operation == "restore":
        result.update(restore_id=restore_id, original_archive_required=False,
                      original_ciphertext_required=False)
    checks = result["checks"]
    environment, secret, sink = None, None, None
    receipt_attempted = False
    with ExitStack() as stack:
        for root in roots.values():
            stack.enter_context(core._directory_pin(root))
        attempt.mkdir()  # Existence permanently spends this attempt, including failure.
        stack.enter_context(core._directory_pin(attempt))
        core._write(attempt / "claim.json", core._seal(dict(result), "receipt_hash"))
        sink = stage._CreateOnlyJsonSink(attempt / "receipt.json")
        pins = {}

        def pin_file(name, path):
            pin = stack.enter_context(_file_pin(path))
            pins[name] = (path, pin, pin.metadata(), stage._regular_identity(path, label=name))

        def stable():
            restore._deadline(deadline)
            for path, pin, metadata, regular in pins.values():
                _require(pin.metadata() == metadata
                         and stage._regular_identity(path, label="pinned input") == regular,
                         "input_identity_drift")
            return True

        def bounded_runner(arguments, child_env, timeout_seconds, capture_stdout):
            stable()
            remaining = int(deadline - time.monotonic())
            _require(remaining > 0, "archive_deadline_exceeded")
            outcome = runner(arguments, child_env, min(timeout_seconds, remaining), capture_stdout)
            stable()
            return outcome

        try:
            # Small supporting files are pinned before secret recovery. Copied
            # archive/cipher bytes are opened only after successful preflight.
            for name, path in paths.items():
                if name not in {"archive_file", "downloaded_file"}:
                    pin_file(name, path)
            for index, module in enumerate((Path(__file__), Path(core.__file__),
                                             Path(stage.__file__), Path(restore.__file__))):
                pin_file(f"tool_module_{index}", module)
            manifest = _production(paths, hashes, plan_sha256)
            result.update(chunk_id=manifest["chunk_id"], archive_bytes=manifest["archive_bytes"],
                          archive_sha256=manifest["archive_sha256"])
            checks["production_evidence"] = "PASS"
            cipher = _upstream_restore(paths, hashes, result, manifest) if operation == "restore" else None
            if operation == "restore":
                checks["transport_evidence"] = "PASS"
            secret = secret_loader(paths["dpapi_secret"])
            environment = {k: v for k, v in os.environ.items() if not k.upper().startswith("RCLONE_")}
            environment[stage.CONFIG_PASS_ENV] = secret.text()
            client = _Client(executable=paths["rclone_executable"], config=paths["rclone_config"],
                             remote_name=crypt_remote_name, environment=environment, runner=bounded_runner)

            def preflight():
                stable()
                client.check_config_encryption()
                client.require_local_ciphertext_root(roots["ciphertext_root"])
                stable()

            preflight()
            result["rclone_version"] = client.version()
            checks["encryption_preflight"] = "PASS"
            if "archive_file" in paths:
                pin_file("archive_file", paths["archive_file"])
                core.verify_archive(paths["archive_file"], manifest, admission=stable,
                                    deadline_monotonic=deadline)
                checks["archive_members"] = "PASS"
            logical = f"{archive_id}/archive.tar.gz"
            original_mapping = restore._relative(client.encrypted_relative_path(logical), parts=2)
            if operation == "restore":
                _require(original_mapping == cipher["path_relative_to_ciphertext_root"],
                         "restore_key_mapping_mismatch")
                logical = f"{restore_id}/{logical}"
            mapped = restore._relative(client.encrypted_relative_path(logical),
                                       parts=3 if operation == "restore" else 2)
            if operation == "restore":
                _require(mapped.split("/")[1:] == original_mapping.split("/"), "restore_key_mapping_mismatch")
            destination = roots["ciphertext_root"].joinpath(*mapped.split("/"))
            if os.name == "nt":
                _require(len(str(destination).encode("utf-16-le")) // 2 < 240, "ciphertext_path_too_long")
            cipher_namespace = roots["ciphertext_root"] / mapped.split("/")[0]
            preflight()
            client.require_destination_absent(namespace)
            _require(not os.path.lexists(cipher_namespace), "ciphertext_namespace_collision")
            checks["destination_absent" if operation == "encrypt" else "restore_key_mapping"] = "PASS"
            cipher_namespace.mkdir()
            stack.enter_context(core._directory_pin(cipher_namespace))
            if operation == "encrypt":
                _exact(cipher_namespace, [])
                preflight()
                client.encrypt_file(paths["archive_file"], archive_id, manifest["archive_bytes"])
                _exact(cipher_namespace, [destination])
                pin_file("ciphertext", destination)
                count, digest = _cipher_hash(destination, deadline, stable)
                _require(count <= manifest["archive_bytes"] + 2 * core.MIB, "ciphertext_unbounded")
                cipher = {"path_relative_to_ciphertext_root": mapped, "bytes": count,
                          "sha256": digest, "file_identity": pins["ciphertext"][3]}
                result["ciphertext"] = cipher
                checks["ciphertext_copy"] = checks["ciphertext_hash"] = "PASS"
                preflight()
                client.check_file(paths["archive_file"], archive_id)
                _hash(destination, cipher, deadline)
                checks["cryptcheck"] = "PASS"
            else:
                pin_file("downloaded_file", paths["downloaded_file"])
                downloaded_id = pins["downloaded_file"][3]
                original_id = cipher.get("file_identity")
                _require(isinstance(original_id, dict)
                         and set(original_id) == {"device", "inode", "mode", "bytes", "mtime_ns"}
                         and all(type(value) is int and value >= 0 for value in original_id.values())
                         and original_id["mode"] == stat.S_IFREG
                         and original_id["bytes"] == cipher["bytes"], "original_ciphertext_identity_invalid")
                _require((original_id["device"], original_id["inode"])
                         != (downloaded_id["device"], downloaded_id["inode"]), "download_not_independent")
                if "original_ciphertext_root" in roots:
                    original = roots["original_ciphertext_root"].joinpath(*original_mapping.split("/"))
                    pin_file("original_ciphertext", core._safe_path(original))
                    _require(pins["original_ciphertext"][3] == original_id,
                             "original_ciphertext_identity_drift")
                    _require(not stage._contains(roots["original_ciphertext_root"], paths["downloaded_file"]),
                             "download_original_root_overlap")
                    _hash(original, cipher, deadline)
                _hash(paths["downloaded_file"], cipher, deadline)
                _require(_cipher_hash(paths["downloaded_file"], deadline, stable)
                         == (cipher["bytes"], cipher["sha256"]), "download_ciphertext_invalid")
                checks["independent_ciphertext"] = "PASS"
                destination.parent.mkdir()
                stack.enter_context(core._directory_pin(destination.parent))
                _hash(paths["downloaded_file"], cipher, deadline, destination=destination)
                pin_file("ciphertext", destination)
                _hash(destination, cipher, deadline)
                checks["ciphertext_copy"] = "PASS"
                preflight()
                archive_output = attempt / "archive"
                archive_output.mkdir()
                stack.enter_context(core._directory_pin(archive_output))
                preflight()
                client.decrypt_archive(logical, archive_output, manifest["archive_bytes"])
                checks["archive_decryption"] = "PASS"
                restored = archive_output / "archive.tar.gz"
                _exact(archive_output, [restored])
                pin_file("restored_archive", restored)
                core.verify_archive(restored, manifest, admission=stable, deadline_monotonic=deadline)
                checks["restored_archive_members"] = checks["archive_members"] = "PASS"
                # Compare the decoded download with the manifest, then check
                # that the encrypted object encodes those verified bytes.
                preflight()
                client.check_file(restored, f"{restore_id}/{archive_id}")
                checks["cryptcheck"] = "PASS"
                members = _materialize(restored, attempt / "members", manifest, deadline, stack)
                checks["materialized_members"] = "PASS"
                result.update(restored_archive=str(restored), restored_members=members,
                              verified_file_count=len(members), restore_performed=True,
                              restore_ciphertext_relative_path=mapped, ciphertext=dict(cipher),
                              downloaded_file_identity=downloaded_id)
                _hash(destination, cipher, deadline)
                _hash(paths["downloaded_file"], cipher, deadline)
                _exact(cipher_namespace, [destination.parent])
            _exact(destination.parent, [destination])
            expected_attempt = [attempt / "claim.json", attempt / "receipt.json"]
            if operation == "restore":
                expected_attempt += [attempt / "archive", attempt / "members"]
            _exact(attempt, expected_attempt)
            if "archive_file" in paths:
                _hash(paths["archive_file"], {"bytes": manifest["archive_bytes"],
                                             "sha256": manifest["archive_sha256"]}, deadline)
            stable()
            checks["inputs_stable"] = "PASS"
            _require(tool_identity is not None or _capture_identity(Path(repo_root)) == identity,
                     "tool_identity_drift")
            checks["tool_identity_stable"] = "PASS"
            _require(all(v == "PASS" for v in checks.values()), "checks_incomplete")
            result.update(status="PASS", completed_at_utc=stage._utc_now())
            receipt_attempted = True
            sink.write(core._seal(result, "receipt_hash"))
            return result
        except BaseException as exc:
            if not receipt_attempted:
                result.update(status="FAIL_CLOSED", error_code="archive_operation_failed",
                              completed_at_utc=stage._utc_now())
                if isinstance(exc, stage.ArchiveStageError):
                    result["error_code"] = exc.code
                if isinstance(exc, stage._DpapiRecoveryError):
                    result["dpapi_winerror"] = exc.winerror
                receipt_attempted = True
                sink.write(core._seal(result, "receipt_hash"))
            # Never propagate a raw child, DPAPI, filesystem, or JSON exception.
            raise stage.ArchiveStageError("archive_operation_failed", "archive operation failed closed") from None
        finally:
            if environment is not None:
                environment.clear()
            if secret is not None:
                secret.wipe()
            sink.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    common = ("archive_file", "production_manifest", "production_manifest_sha256",
              "production_receipt", "production_receipt_sha256", "plan_sha256", "archive_id",
              "rclone_executable", "rclone_config", "dpapi_secret", "crypt_remote_name",
              "ciphertext_root", "output_root")
    for name in ("encrypt", "restore"):
        command = commands.add_parser(name)
        for flag in common + (("restore_id", "crypt_receipt", "crypt_receipt_sha256",
                "transport_receipt", "transport_receipt_sha256", "downloaded_file",
                "original_ciphertext_root") if name == "restore" else ()):
            required = name == "encrypt" or flag not in {"archive_file", "original_ciphertext_root"}
            command.add_argument("--" + flag.replace("_", "-"), required=required)
    try:
        result = run(**vars(parser.parse_args(argv)))
    except Exception:
        print(json.dumps({"status": "FAIL_CLOSED", "error_code": "archive_operation_failed"}))
        return 2
    print(json.dumps({"status": result["status"], "archive_id": result["archive_id"],
                      "receipt_hash": result["receipt_hash"], "cleanup_eligible": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
