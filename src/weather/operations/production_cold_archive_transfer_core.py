"""Bounded encrypted archive upload and independent Drive download.

The caller must own production admission and child-tree containment. This module
never opens a production source tape and never deletes a local or remote file.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from weather.operations import production_cold_archive_stage as archive
from weather.operations import workstation_cold_archive_stage as crypt
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.schema_registry import schema_version

MIB = 1024**2
MAX_CIPHERTEXT_BYTES = archive.MAX_CHUNK_BYTES + archive.MAX_CHUNK_BYTES // 100 + 4 * MIB
MAX_CLIENT_OUTPUT = 65536
MAX_CONFIG_BYTES = MIB
REMOTE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")
ID_RE = re.compile(r"[A-Za-z0-9_-]{10,160}")


class TransferError(ValueError):
    """Refuse without exposing credentials or removing retained evidence."""


def _require(condition, message):
    if not condition:
        raise TransferError(message)


def _seal(value):
    return archive._seal(value, "receipt_hash")


def _read_bound(path, digest):
    archive._require_sha256(digest)
    return archive._load(Path(path), digest)[0]


def _sha_file(path, admit, deadline, maximum=MAX_CIPHERTEXT_BYTES):
    digest = hashlib.sha256()
    count = 0
    guard = archive._Guard(admit, deadline, 16 * MIB)
    with Path(path).open("rb", buffering=0) as stream:
        reader = archive._Reader(stream, guard)
        while True:
            guard.admit()
            block = reader.read(MIB)
            if not block:
                break
            count += len(block)
            _require(count <= maximum, "input exceeds transfer byte bound")
            digest.update(block)
    return count, digest.hexdigest()


def required_transfer_seconds(total_bytes, *, initial_hash_done=False):
    """Conservative rate budget plus bounded metadata/client startup allowance."""
    _require(type(total_bytes) is int and total_bytes >= 0, "invalid transfer byte budget")
    hash_passes = 1 if initial_hash_done else 2
    return hash_passes * total_bytes / (16 * MIB) + 2 * total_bytes / (8 * MIB) + 45


def _client_memory_ok(process):
    if os.name != "nt":
        return True  # Non-native clients exist only in portable fixtures.

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "peak_working", "working", "peak_paged", "paged", "peak_nonpaged",
                "nonpaged", "pagefile", "peak_pagefile", "private")]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    api.restype = wintypes.BOOL
    return bool(api(int(process._handle), ctypes.byref(counters), counters.cb)
                and max(counters.working, counters.private) <= 384 * MIB)


class GuardedClient:
    """Small allowlisted rclone surface, pinned to one explicit Drive folder."""

    def __init__(self, executable, config, remote, root_folder_id, environment, admission, deadline):
        _require(REMOTE_RE.fullmatch(remote) is not None, "invalid Drive remote")
        _require(ID_RE.fullmatch(root_folder_id) is not None, "invalid Drive folder ID")
        self.executable, self.config = Path(executable), Path(config)
        self.remote, self.root_folder_id = remote, root_folder_id
        self.environment = environment
        self.admission, self.deadline = admission, deadline

    def guard(self):
        _require(time.monotonic() < self.deadline and self.admission(), "transfer admission ended")

    def run(self, tokens, *, capture=False):
        self.guard()
        allowed = {("config", "encryption", "check"), ("config", "redacted"),
                   ("lsjson",), ("copyto",)}
        signature = tuple(tokens[:3]) if tokens[:3] == ["config", "encryption", "check"] else (
            tuple(tokens[:2]) if tokens[:2] == ["config", "redacted"] else tuple(tokens[:1]))
        _require(signature in allowed, "rclone command is outside the transfer allowlist")
        arguments = [str(self.executable), "--config", str(self.config), "--ask-password=false",
                     "--log-level", "ERROR", "--stats", "0", "--contimeout", "15s",
                     "--timeout", "30s", "--retries", "1", "--low-level-retries", "1",
                     "--drive-root-folder-id", self.root_folder_id, *tokens]
        process = subprocess.Popen(
            arguments, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=self.environment, shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        output, overflow = bytearray(), threading.Event()

        def drain():
            try:
                while True:
                    block = process.stdout.read(4096)
                    if not block:
                        return
                    if len(output) + len(block) > MAX_CLIENT_OUTPUT:
                        overflow.set()
                        return
                    output.extend(block)
            except (OSError, ValueError):
                overflow.set()

        reader = threading.Thread(target=drain, daemon=True) if capture else None
        if reader:
            reader.start()
        try:
            while process.poll() is None:
                self.guard()
                _require(_client_memory_ok(process), "client memory unavailable or over 384 MiB")
                _require(not overflow.is_set(), "client output exceeds metadata bound")
                try:
                    process.wait(timeout=min(0.25, max(0.001, self.deadline - time.monotonic())))
                except subprocess.TimeoutExpired:
                    pass
            if reader:
                reader.join(timeout=2)
                _require(not reader.is_alive() and not overflow.is_set(), "client output was not bounded")
            self.guard()
            return process.returncode, bytes(output)
        finally:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired as exc:
                    raise TransferError("client teardown unproved") from exc
            if process.stdout:
                process.stdout.close()

    def preflight(self):
        code, _ = self.run(["config", "encryption", "check"])
        _require(code == 0, "encrypted client configuration check failed")
        code, raw = self.run(["config", "redacted", self.remote], capture=True)
        _require(code == 0, "Drive configuration check failed")
        fields, section = {}, None
        for line in raw.decode("utf-8", errors="strict").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                _require(section is None, "ambiguous Drive configuration")
                section = line[1:-1]
            else:
                _require(section is not None and "=" in line, "invalid Drive configuration")
                key, value = (part.strip() for part in line.split("=", 1))
                _require(key not in fields, "duplicate Drive configuration field")
                fields[key] = value
        _require(section == self.remote and fields.get("type") == "drive"
                 and fields.get("scope") == "drive.file", "restricted app-created-files Drive access required")
        # Every invocation supplies the approved folder ID explicitly. Redacted
        # config deliberately hides this sensitive field, so it is not authority.

    def object(self, key, *, absent=False):
        _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,190}", key) is not None,
                 "noncanonical remote object key")
        code, raw = self.run(["lsjson", f"{self.remote}:{key}", "--stat", "--hash"], capture=True)
        if absent:
            _require(code == 3 and not raw.strip(), "remote object absence not proved")
            return None
        _require(code == 0, "remote object metadata unavailable")
        obj = json.loads(raw, object_pairs_hook=archive._pairs)
        _require(isinstance(obj, dict) and obj.get("Name") == key
                 and obj.get("IsDir") is False and type(obj.get("Size")) is int
                 and ID_RE.fullmatch(str(obj.get("ID", ""))) is not None, "remote object identity invalid")
        return {"object_id": obj["ID"], "remote_key": key, "bytes": obj["Size"],
                "hashes": obj.get("Hashes", {})}

    def copy(self, source, destination, maximum):
        code, _ = self.run([
            "copyto", str(source), str(destination), "--immutable", "--ignore-times",
            "--error-on-no-transfer", "--transfers", "1", "--checkers", "1",
            "--multi-thread-streams", "0", "--buffer-size", "1M", "--drive-chunk-size", "8M",
            "--bwlimit", "8M", "--max-transfer", str(maximum + 1), "--cutoff-mode", "HARD",
            "--max-size", str(maximum), "--partial-suffix", ".partial.cold"])
        _require(code == 0, "create-only transfer failed")


def validate_crypt_receipt(receipt, *, plan_sha256, archive_id, manifest_sha256, production_receipt_sha256):
    archive._check_seal(receipt, "receipt_hash")
    _require(receipt.get("schema_version") == schema_version("production_cold_archive_crypt_receipt")
             and receipt.get("status") == "PASS", "crypt receipt is not a qualified PASS")
    expected = {"plan_sha256": plan_sha256, "archive_id": archive_id,
                "production_manifest_sha256": manifest_sha256,
                "production_receipt_sha256": production_receipt_sha256,
                **bridge.RETENTION}
    _require(receipt.get("checks") == dict.fromkeys(bridge.ENCRYPT_CHECKS, "PASS"),
             "crypt verification checks are incomplete")
    bridge._identity(receipt.get("tool_identity"))
    for key, value in expected.items():
        _require(receipt.get(key) == value and type(receipt.get(key)) is type(value),
                 "crypt receipt binding mismatch")
    _require(re.fullmatch(r"chunk-[0-9]{5}", str(receipt.get("chunk_id", ""))) is not None,
             "crypt chunk identity invalid")
    cipher = receipt.get("ciphertext", {})
    _require(isinstance(cipher, dict) and type(cipher.get("bytes")) is int
             and 32 <= cipher["bytes"] <= MAX_CIPHERTEXT_BYTES, "ciphertext size invalid")
    archive._require_sha256(cipher.get("sha256"))
    bridge.restore._relative(cipher.get("path_relative_to_ciphertext_root"), parts=2)
    file_identity = cipher.get("file_identity")
    _require(isinstance(file_identity, dict)
             and set(file_identity) == {"device", "inode", "mode", "bytes", "mtime_ns"}
             and all(type(value) is int and value >= 0 for value in file_identity.values())
             and file_identity["bytes"] == cipher["bytes"], "ciphertext file identity invalid")
    return cipher


def transfer_chunk(*, ciphertext_path, crypt_receipt_path, crypt_receipt_sha256,
                   production_manifest_path, production_manifest_sha256,
                   production_receipt_path, production_receipt_sha256,
                   plan_sha256, archive_id, rclone_executable, rclone_config, dpapi_secret,
                   drive_remote_name, drive_root_folder_id, output_root, protected_root,
                   admission, deadline_monotonic, free_space_reserve_bytes,
                   client_factory=GuardedClient, secret_loader=crypt._load_dpapi_secret):
    """Upload one encrypted chunk + recovery metadata, then download each afresh."""
    archive._require_sha256(plan_sha256)
    _require(crypt.ARCHIVE_ID_RE.fullmatch(archive_id) is not None, "invalid archive ID")
    inputs = {name: archive._safe_path(Path(value)) for name, value in {
        "ciphertext": ciphertext_path, "crypt_receipt": crypt_receipt_path,
        "production_manifest": production_manifest_path, "production_receipt": production_receipt_path,
        "executable": rclone_executable, "config": rclone_config, "secret": dpapi_secret}.items()}
    protected = archive._safe_path(Path(protected_root), directory=True)
    output = Path(output_root)
    archive._safe_path(output.parent, directory=True)
    _require(output.is_absolute() and not output.exists(), "transfer attempt must be new")
    for path in [*inputs.values(), output]:
        _require(path != protected and protected not in path.parents and path not in protected.parents,
                 "transfer must not access production source data")
    _require(all(output != path and output not in path.parents for path in inputs.values()),
             "transfer inputs and outputs overlap")
    _require(inputs["config"].stat().st_size <= MAX_CONFIG_BYTES, "client configuration too large")
    evidence = _read_bound(inputs["crypt_receipt"], crypt_receipt_sha256)
    cipher = validate_crypt_receipt(evidence, plan_sha256=plan_sha256, archive_id=archive_id,
                                   manifest_sha256=production_manifest_sha256,
                                   production_receipt_sha256=production_receipt_sha256)
    manifest = bridge._production(
        {"production_manifest": inputs["production_manifest"],
         "production_receipt": inputs["production_receipt"]},
        {"production_manifest_sha256": production_manifest_sha256,
         "production_receipt_sha256": production_receipt_sha256}, plan_sha256)
    _require(manifest.get("source_proof") == "native_pinned_bytes_during_staging"
             and manifest["chunk_id"] == evidence["chunk_id"]
             and manifest["archive_sha256"] == evidence.get("archive_sha256")
             and manifest["archive_bytes"] == evidence.get("archive_bytes"),
             "production evidence differs from encrypted archive")
    reserve = archive._integer(free_space_reserve_bytes, "disk reserve")
    needed = cipher["bytes"] + sum(inputs[name].stat().st_size for name in
                                  ("crypt_receipt", "production_manifest", "production_receipt"))
    _require(shutil.disk_usage(output.parent).free >= reserve + needed + 2 * MIB,
             "download would breach capture reserve")

    _require(deadline_monotonic - time.monotonic() >= required_transfer_seconds(needed),
             "chunk cannot fit the remaining transfer deadline")

    result = {"schema_version": schema_version("production_cold_archive_transport_receipt"),
              "status": "FAIL_CLOSED", "archive_id": archive_id, "chunk_id": evidence["chunk_id"],
              "plan_sha256": plan_sha256, "crypt_receipt_sha256": crypt_receipt_sha256,
              "production_manifest_sha256": production_manifest_sha256,
              "production_receipt_sha256": production_receipt_sha256,
              "ciphertext": {"bytes": cipher["bytes"], "sha256": cipher["sha256"]},
              "drive": {"root_folder_id": drive_root_folder_id}, "metadata_objects": [],
              "source_retained": True, "cleanup_eligible": False, "deletion_authorized": False,
              "deleted_files": 0, "reclaimed_bytes": 0, "upload_performed": False,
              "independent_download": False, "remote_side_effect_possible": False}
    secret, environment = None, None
    with ExitStack() as stack:
        stack.enter_context(archive._directory_pin(output.parent))
        pins = {name: stack.enter_context(bridge._file_pin(path)) for name, path in inputs.items()}
        identities = {name: pin.metadata() for name, pin in pins.items()}
        # Re-read small pinned authority after native pins are held.
        _read_bound(inputs["crypt_receipt"], crypt_receipt_sha256)
        _read_bound(inputs["production_manifest"], production_manifest_sha256)
        _read_bound(inputs["production_receipt"], production_receipt_sha256)
        output.mkdir()
        stack.enter_context(archive._directory_pin(output))
        archive._write(output / "claim.json", _seal(dict(result)))
        try:
            _require(admission() is True and time.monotonic() < deadline_monotonic, "transfer admission ended")
            secret = secret_loader(inputs["secret"])
            environment = {name: value for name, value in os.environ.items()
                           if not name.upper().startswith("RCLONE_")}
            environment[crypt.CONFIG_PASS_ENV] = secret.text()
            # The per-attempt encrypted copy is immutable during every child.
            # OAuth refresh persistence may therefore be refused; credential
            # preparation is a separate operation, never an unpinned network call.
            active_config = output / "client.conf"
            config_bytes = crypt._read_stable_bytes(
                inputs["config"], label="encrypted client configuration",
                maximum_bytes=MAX_CONFIG_BYTES)
            try:
                with active_config.open("xb") as target:
                    _require(target.write(config_bytes) == len(config_bytes), "short config copy")
                    target.flush()
                    os.fsync(target.fileno())
                pins["active_config"] = stack.enter_context(bridge._file_pin(active_config))
                identities["active_config"] = pins["active_config"].metadata()
                _require(crypt._read_stable_bytes(
                    active_config, label="active encrypted client configuration",
                    maximum_bytes=MAX_CONFIG_BYTES) == config_bytes,
                    "active encrypted config readback mismatch")
            finally:
                config_bytes.clear()

            def guard():
                _require(time.monotonic() < deadline_monotonic, "transfer deadline reached")
                _require(shutil.disk_usage(output).free >= reserve, "capture disk reserve breached")
                _require(admission() is True, "capture admission refused")
                _require(all(pin.metadata() == identities[name] for name, pin in pins.items()),
                         "pinned transfer file changed")
                return True

            client = client_factory(inputs["executable"], active_config, drive_remote_name,
                                    drive_root_folder_id, environment, guard, deadline_monotonic)
            client.preflight()
            with inputs["ciphertext"].open("rb") as source:
                _require(source.read(8) == b"RCLONE\x00\x00", "plaintext or invalid ciphertext refused")
            count, digest = _sha_file(inputs["ciphertext"], guard, deadline_monotonic)
            _require((count, digest) == (cipher["bytes"], cipher["sha256"]), "ciphertext input mismatch")
            files = [
                ("ciphertext", f"{archive_id}.rclone.bin", cipher["sha256"], cipher["bytes"]),
                ("production_manifest", f"{archive_id}.manifest.json", production_manifest_sha256,
                 inputs["production_manifest"].stat().st_size),
                ("production_receipt", f"{archive_id}.stage.json", production_receipt_sha256,
                 inputs["production_receipt"].stat().st_size),
                ("crypt_receipt", f"{archive_id}.crypt.json", crypt_receipt_sha256,
                 inputs["crypt_receipt"].stat().st_size)]
            # Prove every fresh name absent before publishing the first byte.
            for _, key, _, _ in files:
                client.object(key, absent=True)
            _require(deadline_monotonic - time.monotonic() >=
                     required_transfer_seconds(needed, initial_hash_done=True),
                     "remaining transfer cannot fit deadline before upload")
            for name, key, expected_sha, expected_bytes in files:
                guard()
                result["remote_side_effect_possible"] = True
                result["upload_performed"] = None
                client.copy(inputs[name], f"{drive_remote_name}:{key}", expected_bytes)
                remote = client.object(key)
                _require(remote["bytes"] == expected_bytes, "uploaded object size mismatch")
                downloaded = output / ("downloaded-" + key)
                _require(not downloaded.exists(), "download destination collision")
                client.copy(f"{drive_remote_name}:{key}", downloaded, expected_bytes)
                archive._safe_path(downloaded)
                pin_name = "downloaded_" + name
                pins[pin_name] = stack.enter_context(bridge._file_pin(downloaded))
                identities[pin_name] = pins[pin_name].metadata()
                actual = _sha_file(downloaded, guard, deadline_monotonic,
                                   maximum=max(expected_bytes, 1))
                _require(actual == (expected_bytes, expected_sha), "independent download mismatch")
                after = client.object(key)
                _require(after == remote, "remote object changed across download")
                detail = {**remote, "sha256": expected_sha,
                          "downloaded_path": str(downloaded)}
                if name == "ciphertext":
                    result["drive"].update(object_id=remote["object_id"], remote_key=key)
                    result["downloaded_file"] = {"path": str(downloaded), "bytes": actual[0],
                                                 "sha256": actual[1]}
                else:
                    result["metadata_objects"].append({"kind": name, **detail})
            client.preflight()
            _require(all(pin.metadata() == identities[name] for name, pin in pins.items()),
                     "pinned transfer input changed")
            guard()
            result.update(status="PASS", upload_performed=True, independent_download=True,
                          completed_at_utc=datetime.now(timezone.utc).isoformat())
        except BaseException as exc:
            result.update(status="FAIL_CLOSED", error_type=type(exc).__name__)
            archive._write(output / "receipt.json", _seal(result))
            raise
        finally:
            if environment is not None:
                environment.pop(crypt.CONFIG_PASS_ENV, None)
            if secret is not None:
                secret.wipe()
        archive._write(output / "receipt.json", _seal(result))
        return result

