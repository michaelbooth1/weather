"""Create-only workstation staging for one provisional archive source file.

This adapter is deliberately narrower than the fixture-only market-day archive
foundation.  It accepts one already-rotated mirror copy, creates one normalized
single-file archive, encrypts it through one configured local rclone crypt
remote, verifies it with ``cryptcheck``, and writes immutable evidence.  It has
no production mode and no source cleanup, move, rename, truncate, or delete
surface.
"""

from __future__ import annotations

import argparse
import calendar
import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import gzip

from weather.operations.release_manifest import capture_code_identity
from weather.paths import DATA_ROOT, REPO_ROOT
from weather.schema_registry import schema_version


MANIFEST_SCHEMA_VERSION = schema_version("workstation_cold_archive_stage_manifest")
RECEIPT_SCHEMA_VERSION = schema_version("workstation_cold_archive_stage_receipt")
TOOL = "weather.operations.workstation_cold_archive_stage"
ARCHIVE_FORMAT = "normalized-single-file-ustar-gzip-v1"
ARCHIVE_FILENAME = "archive.tar.gz"
ARCHIVE_MEMBER_NAME = "payload"
WRAPPER_ENV = "WEATHER_WORKSTATION_WRAPPER_ACTIVE"
CONFIG_PASS_ENV = "RCLONE_CONFIG_PASS"
HASH_BLOCK_SIZE = 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024 * 1024
MAX_CIPHERTEXT_ENTRIES = 10_000
MAX_CAPTURED_CHILD_BYTES = 64 * 1024
CHILD_KILL_WAIT_SECONDS = 5
RCLONE_PARTIAL_SUFFIX = ".partial.cold-stage"
RCLONE_TIMEOUT_SECONDS = {
    "version": 15,
    "config_encryption_check": 30,
    "config_redacted": 30,
    "cryptdecode": 30,
    "destination_absence": 30,
    "copy": 3600,
    "cryptcheck": 3600,
}
ALLOWED_RCLONE_COMMANDS = frozenset(
    {
        ("version",),
        ("config", "encryption", "check"),
        ("config", "redacted"),
        ("cryptdecode",),
        ("lsjson",),
        ("copy",),
        ("cryptcheck",),
    }
)
FORBIDDEN_RCLONE_VERBS = frozenset(
    {
        "sync",
        "move",
        "moveto",
        "delete",
        "deletefile",
        "purge",
        "cleanup",
        "dedupe",
        "rmdir",
        "rmdirs",
    }
)
ARCHIVE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")
MTIME_UTC_RE = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?Z$"
)


class ArchiveStageError(RuntimeError):
    """A sanitized, fail-closed staging error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _DpapiRecoveryError(ArchiveStageError):
    """Only the numeric Windows failure is safe to retain in a receipt."""

    def __init__(self, winerror: int):
        if type(winerror) is not int:
            raise TypeError("DPAPI error code must be an integer")
        self.winerror = winerror
        super().__init__(
            "dpapi_decryption_failed",
            f"DPAPI CurrentUser recovery failed (winerror={winerror})",
        )


@dataclass(frozen=True)
class ChildResult:
    returncode: int
    stdout: bytes = b""


@dataclass
class SecretMaterial:
    """Mutable UTF-16 secret bytes that can be zeroed after child launch."""

    utf16_bytes: bytearray

    @classmethod
    def from_text(cls, value: str) -> "SecretMaterial":
        if not value or "\x00" in value:
            raise ArchiveStageError("dpapi_secret_invalid", "DPAPI secret is invalid")
        return cls(bytearray(value.encode("utf-16-le")))

    def text(self) -> str:
        try:
            value = bytes(self.utf16_bytes).decode("utf-16-le", errors="strict")
        except UnicodeError as exc:
            raise ArchiveStageError(
                "dpapi_secret_invalid", "DPAPI secret is invalid"
            ) from exc
        if not value or "\x00" in value:
            raise ArchiveStageError("dpapi_secret_invalid", "DPAPI secret is invalid")
        return value

    def wipe(self) -> None:
        for index in range(len(self.utf16_bytes)):
            self.utf16_bytes[index] = 0


RcloneRunner = Callable[[Sequence[str], Mapping[str, str], int, bool], ChildResult]
SecretLoader = Callable[[Path], SecretMaterial]


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _content_hash(payload: Mapping[str, Any], field: str) -> str:
    unsigned = dict(payload)
    unsigned.pop(field, None)
    return hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()


def manifest_content_hash(payload: Mapping[str, Any]) -> str:
    return _content_hash(payload, "manifest_hash")


def receipt_content_hash(payload: Mapping[str, Any]) -> str:
    return _content_hash(payload, "receipt_hash")


def manifest_hash_valid(payload: Mapping[str, Any]) -> bool:
    return payload.get("manifest_hash") == manifest_content_hash(payload)


def receipt_hash_valid(payload: Mapping[str, Any]) -> bool:
    return payload.get("receipt_hash") == receipt_content_hash(payload)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _absolute_lexical(value: str | Path, *, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ArchiveStageError("path_not_absolute", f"{label} must be absolute")
    return Path(os.path.abspath(os.fspath(path)))


def _is_reparse_stat(result: os.stat_result) -> bool:
    attributes = int(getattr(result, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse_flag)


def _lstat(path: Path, *, label: str) -> os.stat_result:
    try:
        result = path.lstat()
    except OSError as exc:
        raise ArchiveStageError("path_unreadable", f"{label} is not readable") from exc
    if _is_reparse_stat(result):
        raise ArchiveStageError("path_reparse", f"{label} is redirected")
    return result


def _assert_no_reparse_components(path: Path, *, label: str) -> None:
    for component in [*reversed(path.parents), path]:
        if component.exists():
            _lstat(component, label=label)


def _require_directory(value: str | Path, *, label: str) -> Path:
    path = _absolute_lexical(value, label=label)
    _assert_no_reparse_components(path, label=label)
    result = _lstat(path, label=label)
    if not stat.S_ISDIR(result.st_mode):
        raise ArchiveStageError("path_not_directory", f"{label} must be a directory")
    return path


def _regular_identity(path: Path, *, label: str) -> dict[str, int]:
    _assert_no_reparse_components(path, label=label)
    result = _lstat(path, label=label)
    if not stat.S_ISREG(result.st_mode):
        raise ArchiveStageError("path_not_regular", f"{label} must be a regular file")
    return _identity_from_stat(result)


def _identity_from_stat(result: os.stat_result) -> dict[str, int]:
    return {
        "device": int(result.st_dev),
        "inode": int(result.st_ino),
        "mode": int(stat.S_IFMT(result.st_mode)),
        "bytes": int(result.st_size),
        "mtime_ns": int(result.st_mtime_ns),
    }


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _contains(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((_path_key(root), _path_key(candidate))) == _path_key(
            root
        )
    except ValueError:
        return False


def _overlaps(left: Path, right: Path) -> bool:
    return _contains(left, right) or _contains(right, left)


def _parse_mtime_utc(value: str) -> int:
    match = MTIME_UTC_RE.fullmatch(value)
    if not match:
        raise ArchiveStageError(
            "source_mtime_pin_invalid", "source last-write pin must be UTC RFC3339"
        )
    try:
        parsed = datetime.strptime(match.group("base"), "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise ArchiveStageError(
            "source_mtime_pin_invalid", "source last-write pin must be UTC RFC3339"
        ) from exc
    fraction = (match.group("fraction") or "").ljust(9, "0")
    return calendar.timegm(parsed.timetuple()) * 1_000_000_000 + int(fraction or 0)


def _format_mtime_utc(mtime_ns: int) -> str:
    seconds, remainder = divmod(mtime_ns, 1_000_000_000)
    base = datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{remainder:09d}Z"


def _hash_open_handle(handle: Any) -> tuple[int, str]:
    handle.seek(0)
    digest = hashlib.sha256()
    total = 0
    while True:
        block = handle.read(HASH_BLOCK_SIZE)
        if not block:
            break
        total += len(block)
        digest.update(block)
    return total, digest.hexdigest()


def _hash_regular_file(path: Path, *, label: str) -> tuple[dict[str, int], str]:
    before = _regular_identity(path, label=label)
    with path.open("rb") as handle:
        if _identity_from_stat(os.fstat(handle.fileno())) != before:
            raise ArchiveStageError("file_drift", f"{label} changed before hashing")
        count, digest = _hash_open_handle(handle)
        if _identity_from_stat(os.fstat(handle.fileno())) != before:
            raise ArchiveStageError("file_drift", f"{label} changed while hashing")
    if count != before["bytes"] or _regular_identity(path, label=label) != before:
        raise ArchiveStageError("file_drift", f"{label} changed while hashing")
    return before, digest


def _write_deterministic_archive(
    source_handle: Any,
    destination: Path,
    *,
    source_bytes: int,
    expected_sha256: str,
) -> dict[str, Any]:
    try:
        raw = destination.open("xb")
    except FileExistsError as exc:
        raise ArchiveStageError(
            "archive_object_collision", "archive object create-only collision"
        ) from exc
    with raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=9,
            fileobj=raw,
            mtime=0,
        ) as compressed:
            with tarfile.open(
                mode="w", fileobj=compressed, format=tarfile.USTAR_FORMAT
            ) as archive:
                info = tarfile.TarInfo(ARCHIVE_MEMBER_NAME)
                info.size = source_bytes
                info.mtime = 0
                info.mode = 0o600
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                source_handle.seek(0)
                digesting = _HashingReader(source_handle)
                archive.addfile(info, digesting)
                if (
                    digesting.bytes_read != source_bytes
                    or digesting.hexdigest() != expected_sha256
                ):
                    raise ArchiveStageError(
                        "source_drift_during_compression",
                        "source changed during deterministic compression",
                    )
        raw.flush()
        os.fsync(raw.fileno())
    identity, digest = _hash_regular_file(destination, label="archive object")
    return {
        "format": ARCHIVE_FORMAT,
        "member_name": ARCHIVE_MEMBER_NAME,
        "normalized_mtime": 0,
        "normalized_uid": 0,
        "normalized_gid": 0,
        "normalized_uname": "",
        "normalized_gname": "",
        "normalized_mode": "0600",
        "bytes": identity["bytes"],
        "sha256": digest,
    }


class _HashingReader:
    def __init__(self, handle: Any):
        self.handle = handle
        self.digest = hashlib.sha256()
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        block = self.handle.read(size)
        self.bytes_read += len(block)
        self.digest.update(block)
        return block

    def hexdigest(self) -> str:
        return self.digest.hexdigest()


class _CreateOnlyJsonSink:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.handle = path.open("xb")
        except FileExistsError as exc:
            raise ArchiveStageError(
                "receipt_collision", "terminal receipt create-only collision"
            ) from exc
        self.written = False

    def write(self, payload: Mapping[str, Any]) -> None:
        if self.written:
            raise ArchiveStageError("receipt_rewrite", "terminal receipt is immutable")
        encoded = json.dumps(
            payload, indent=2, sort_keys=True, ensure_ascii=False
        ).encode("utf-8") + b"\n"
        self.handle.write(encoded)
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.written = True
        # A persisted but unreadable receipt is spent, never rewritten or PASS.
        _verify_written_json(self.path, encoded, hash_field="receipt_hash")

    def close(self) -> None:
        self.handle.close()


def _write_json_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    try:
        with path.open("xb") as handle:
            encoded = json.dumps(
                payload, indent=2, sort_keys=True, ensure_ascii=False
            ).encode("utf-8") + b"\n"
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ArchiveStageError(
            "manifest_collision", "manifest create-only collision"
        ) from exc
    _verify_written_json(path, encoded, hash_field="manifest_hash")


def _verify_written_json(path: Path, encoded: bytes, *, hash_field: str) -> None:
    raw = _read_stable_bytes(
        path, label="published evidence", maximum_bytes=len(encoded)
    )
    if raw != encoded:
        raise ArchiveStageError(
            "evidence_readback_mismatch", "published evidence readback does not match"
        )
    payload = json.loads(raw)
    if payload.get(hash_field) != _content_hash(payload, hash_field):
        raise ArchiveStageError(
            "evidence_hash_invalid", "published evidence self-hash is invalid"
        )


def _read_stable_bytes(path: Path, *, label: str, maximum_bytes: int) -> bytearray:
    before = _regular_identity(path, label=label)
    if before["bytes"] <= 0 or before["bytes"] > maximum_bytes:
        raise ArchiveStageError("bounded_input_invalid", f"{label} is not bounded")
    with path.open("rb") as handle:
        if _identity_from_stat(os.fstat(handle.fileno())) != before:
            raise ArchiveStageError("file_drift", f"{label} changed before read")
        raw = bytearray(handle.read(maximum_bytes + 1))
        if _identity_from_stat(os.fstat(handle.fileno())) != before:
            raise ArchiveStageError("file_drift", f"{label} changed during read")
    if len(raw) != before["bytes"] or _regular_identity(path, label=label) != before:
        raise ArchiveStageError("file_drift", f"{label} changed during read")
    return raw


def _load_dpapi_secret(path: Path) -> SecretMaterial:
    """Recover ASCII-hex CurrentUser DPAPI over UTF-16LE, with no entropy."""

    if os.name != "nt":
        raise ArchiveStageError(
            "dpapi_unavailable", "DPAPI CurrentUser recovery requires Windows"
        )
    raw = _read_stable_bytes(
        path, label="DPAPI secret", maximum_bytes=64 * 1024
    )
    encrypted = bytearray()
    decrypted = bytearray()

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.c_void_p)]

    output = DataBlob()
    try:
        try:
            text = bytes(raw).decode("ascii", errors="strict").strip()
        except UnicodeError as exc:
            raise ArchiveStageError(
                "dpapi_secret_invalid", "DPAPI secret is invalid"
            ) from exc
        if not text or len(text) % 2 or not re.fullmatch(r"[0-9A-Fa-f]+", text):
            raise ArchiveStageError("dpapi_secret_invalid", "DPAPI secret is invalid")
        encrypted.extend(bytes.fromhex(text))
        input_buffer = (ctypes.c_ubyte * len(encrypted)).from_buffer(encrypted)
        input_blob = DataBlob(len(encrypted), ctypes.addressof(input_buffer))
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = ctypes.c_int
        ctypes.set_last_error(0)
        if not crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0x1,  # CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(output),
        ):
            # Capture the use_last_error copy before cleanup or another Win32
            # call can replace it. Do not include blob bytes or an OS message.
            winerror = ctypes.get_last_error()
            raise _DpapiRecoveryError(winerror)
        if not output.pbData or output.cbData <= 0 or output.cbData > 64 * 1024:
            raise ArchiveStageError("dpapi_secret_invalid", "DPAPI secret is invalid")
        decrypted.extend(ctypes.string_at(output.pbData, output.cbData))
        if len(decrypted) % 2:
            raise ArchiveStageError("dpapi_secret_invalid", "DPAPI secret is invalid")
        material = SecretMaterial(decrypted)
        material.text()  # strict validation before ownership transfers
        decrypted = bytearray()
        return material
    finally:
        for index in range(len(raw)):
            raw[index] = 0
        for index in range(len(encrypted)):
            encrypted[index] = 0
        for index in range(len(decrypted)):
            decrypted[index] = 0
        if output.pbData:
            ctypes.memset(output.pbData, 0, output.cbData)
            kernel32.LocalFree(output.pbData)


def _subprocess_runner(
    arguments: Sequence[str],
    environment: Mapping[str, str],
    timeout_seconds: int,
    capture_stdout: bool,
) -> ChildResult:
    if not arguments:
        raise ArchiveStageError("child_contract_invalid", "child command is empty")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        list(arguments),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=dict(environment),
        shell=False,
        creationflags=creationflags,
    )
    captured = bytearray()
    overflow = threading.Event()
    reader: threading.Thread | None = None
    if capture_stdout:
        if process.stdout is None:
            process.kill()
            raise ArchiveStageError("child_output_missing", "child output pipe is absent")

        def _drain() -> None:
            assert process.stdout is not None
            while True:
                block = process.stdout.read(4096)
                if not block:
                    return
                if len(captured) + len(block) > MAX_CAPTURED_CHILD_BYTES:
                    overflow.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return
                captured.extend(block)

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=CHILD_KILL_WAIT_SECONDS)
        except subprocess.TimeoutExpired as termination_exc:
            raise ArchiveStageError(
                "rclone_termination_unproved",
                "bounded rclone child timed out and root termination was not proved",
            ) from termination_exc
        raise ArchiveStageError(
            "rclone_timeout", "bounded rclone child timed out and was killed"
        ) from exc
    finally:
        if reader is not None:
            reader.join(timeout=CHILD_KILL_WAIT_SECONDS)
        if process.stdout is not None:
            process.stdout.close()
    if overflow.is_set():
        raise ArchiveStageError(
            "rclone_output_limit", "bounded rclone child exceeded its output limit"
        )
    return ChildResult(returncode=returncode, stdout=bytes(captured))


class _RcloneClient:
    def __init__(
        self,
        *,
        executable: Path,
        config: Path,
        remote_name: str,
        environment: Mapping[str, str],
        runner: RcloneRunner,
    ):
        self.executable = executable
        self.config = config
        self.remote_name = remote_name
        self.environment = environment
        self.runner = runner

    def _invoke(
        self,
        command: Sequence[str],
        *,
        timeout_key: str,
        capture_stdout: bool = False,
    ) -> ChildResult:
        tokens = tuple(str(token) for token in command)
        verb = tokens[0].casefold() if tokens else ""
        if verb in FORBIDDEN_RCLONE_VERBS:
            raise ArchiveStageError(
                "rclone_verb_forbidden", "destructive rclone command is forbidden"
            )
        if tokens[:3] == ("config", "encryption", "check"):
            signature = tokens[:3]
        elif tokens[:2] == ("config", "redacted"):
            signature = tokens[:2]
        else:
            signature = tokens[:1]
        if signature not in ALLOWED_RCLONE_COMMANDS:
            raise ArchiveStageError(
                "rclone_command_not_allowed", "rclone command is not allowlisted"
            )
        arguments = [
            str(self.executable),
            "--config",
            str(self.config),
            "--ask-password=false",
            "--log-level",
            "ERROR",
            "--stats",
            "0",
            *tokens,
        ]
        return self.runner(
            arguments,
            self.environment,
            RCLONE_TIMEOUT_SECONDS[timeout_key],
            capture_stdout,
        )

    def check_config_encryption(self) -> None:
        result = self._invoke(
            ("config", "encryption", "check"),
            timeout_key="config_encryption_check",
        )
        if result.returncode != 0:
            raise ArchiveStageError(
                "rclone_config_encryption_failed",
                "rclone encrypted-config check failed",
            )

    def version(self) -> str:
        result = self._invoke(
            ("version",), timeout_key="version", capture_stdout=True
        )
        if result.returncode != 0:
            raise ArchiveStageError("rclone_version_failed", "rclone version failed")
        try:
            lines = result.stdout.decode("utf-8", errors="strict").splitlines()
        except UnicodeError as exc:
            raise ArchiveStageError(
                "rclone_version_invalid", "rclone version output is invalid"
            ) from exc
        version = lines[0].strip() if lines else ""
        if not re.fullmatch(r"rclone v[0-9A-Za-z.+_-]+", version):
            raise ArchiveStageError(
                "rclone_version_invalid", "rclone version output is invalid"
            )
        return version

    def require_local_ciphertext_root(self, ciphertext_root: Path) -> None:
        result = self._invoke(
            ("config", "redacted", self.remote_name),
            timeout_key="config_redacted",
            capture_stdout=True,
        )
        if result.returncode != 0:
            raise ArchiveStageError(
                "rclone_config_inspection_failed",
                "rclone redacted config inspection failed",
            )
        try:
            lines = result.stdout.decode("utf-8", errors="strict").splitlines()
        except UnicodeError as exc:
            raise ArchiveStageError(
                "rclone_config_inspection_invalid",
                "rclone redacted config inspection is invalid",
            ) from exc
        section: str | None = None
        fields: dict[str, str] = {}
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                if section is not None:
                    raise ArchiveStageError(
                        "rclone_config_inspection_invalid",
                        "rclone redacted config inspection is invalid",
                    )
                section = line[1:-1]
                continue
            if section is None or "=" not in line:
                raise ArchiveStageError(
                    "rclone_config_inspection_invalid",
                    "rclone redacted config inspection is invalid",
                )
            name, value = (part.strip() for part in line.split("=", 1))
            if not name or name in fields:
                raise ArchiveStageError(
                    "rclone_config_inspection_invalid",
                    "rclone redacted config inspection is invalid",
                )
            fields[name] = value
        if section != self.remote_name or fields.get("type") != "crypt":
            raise ArchiveStageError(
                "rclone_remote_not_local_crypt",
                "rclone remote is not the required local crypt remote",
            )
        configured_root = fields.get("remote", "")
        try:
            local_root = _absolute_lexical(
                configured_root, label="rclone local ciphertext root"
            )
        except ArchiveStageError as exc:
            raise ArchiveStageError(
                "rclone_remote_not_local_crypt",
                "rclone remote is not the required local crypt remote",
            ) from exc
        _assert_no_reparse_components(
            local_root, label="rclone local ciphertext root"
        )
        if _path_key(local_root) != _path_key(ciphertext_root):
            raise ArchiveStageError(
                "rclone_ciphertext_root_mismatch",
                "rclone local ciphertext root does not match the explicit root",
            )

    def encrypted_relative_path(self, logical_relative_path: str) -> str:
        result = self._invoke(
            ("cryptdecode", "--reverse", f"{self.remote_name}:", logical_relative_path),
            timeout_key="cryptdecode",
            capture_stdout=True,
        )
        if result.returncode != 0:
            raise ArchiveStageError(
                "rclone_mapping_failed", "rclone crypt path mapping failed"
            )
        try:
            lines = [
                line.strip()
                for line in result.stdout.decode("utf-8", errors="strict").splitlines()
                if line.strip()
            ]
        except UnicodeError as exc:
            raise ArchiveStageError(
                "rclone_mapping_invalid", "rclone crypt path mapping is invalid"
            ) from exc
        if len(lines) != 1:
            raise ArchiveStageError(
                "rclone_mapping_invalid", "rclone crypt path mapping is invalid"
            )
        parts = lines[0].split(None, 1)
        if len(parts) != 2 or parts[0] != logical_relative_path:
            raise ArchiveStageError(
                "rclone_mapping_invalid", "rclone crypt path mapping is invalid"
            )
        encrypted = parts[1].replace("\\", "/")
        candidate = Path(*encrypted.split("/"))
        if (
            not encrypted
            or candidate.is_absolute()
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ArchiveStageError(
                "rclone_mapping_invalid", "rclone crypt path mapping is invalid"
            )
        return "/".join(candidate.parts)

    def require_destination_absent(self, archive_id: str) -> None:
        result = self._invoke(
            ("lsjson", "--stat", f"{self.remote_name}:{archive_id}"),
            timeout_key="destination_absence",
        )
        if result.returncode == 0:
            raise ArchiveStageError(
                "rclone_destination_collision", "rclone archive ID already exists"
            )
        if result.returncode != 3:
            raise ArchiveStageError(
                "rclone_destination_probe_failed",
                "rclone archive destination absence could not be proved",
            )

    def copy_create_only(self, source_directory: Path, archive_id: str) -> None:
        result = self._invoke(
            (
                "copy",
                str(source_directory),
                f"{self.remote_name}:{archive_id}",
                "--immutable",
                "--ignore-times",
                "--error-on-no-transfer",
                "--no-traverse",
                "--max-depth",
                "1",
                "--max-backlog",
                "4",
                "--transfers",
                "1",
                "--checkers",
                "1",
                "--retries",
                "1",
                "--low-level-retries",
                "1",
                "--partial-suffix",
                RCLONE_PARTIAL_SUFFIX,
            ),
            timeout_key="copy",
        )
        if result.returncode != 0:
            raise ArchiveStageError(
                "rclone_create_only_copy_failed", "rclone create-only copy failed"
            )

    def cryptcheck(self, source_directory: Path, archive_id: str) -> None:
        result = self._invoke(
            (
                "cryptcheck",
                str(source_directory),
                f"{self.remote_name}:{archive_id}",
                "--checkers",
                "1",
                "--max-depth",
                "1",
                "--max-backlog",
                "4",
                "--retries",
                "1",
                "--low-level-retries",
                "1",
            ),
            timeout_key="cryptcheck",
        )
        if result.returncode != 0:
            raise ArchiveStageError(
                "rclone_cryptcheck_difference", "rclone cryptcheck found a difference"
            )


def _ciphertext_inventory(root: Path) -> dict[str, dict[str, int]]:
    records: dict[str, dict[str, int]] = {}
    entry_count = 0

    def visit(directory: Path) -> None:
        nonlocal entry_count
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise ArchiveStageError(
                "ciphertext_inventory_failed", "ciphertext inventory failed"
            ) from exc
        for entry in entries:
            entry_count += 1
            if entry_count > MAX_CIPHERTEXT_ENTRIES:
                raise ArchiveStageError(
                    "ciphertext_inventory_limit", "ciphertext inventory limit exceeded"
                )
            path = Path(entry.path)
            result = _lstat(path, label="ciphertext inventory entry")
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(result.st_mode):
                visit(path)
            elif stat.S_ISREG(result.st_mode):
                records[relative] = _identity_from_stat(result)
            else:
                raise ArchiveStageError(
                    "ciphertext_special_file",
                    "ciphertext inventory contains a special file",
                )

    visit(root)
    return records


def _stable_ciphertext_inventory(root: Path) -> dict[str, dict[str, int]]:
    first = _ciphertext_inventory(root)
    second = _ciphertext_inventory(root)
    if first != second:
        raise ArchiveStageError(
            "ciphertext_inventory_drift", "ciphertext inventory changed while scanned"
        )
    return first


def _validate_ciphertext_delta(
    before: Mapping[str, Mapping[str, int]],
    after: Mapping[str, Mapping[str, int]],
    *,
    expected_relative_path: str,
) -> dict[str, int]:
    before_names = set(before)
    after_names = set(after)
    if before_names - after_names:
        raise ArchiveStageError(
            "ciphertext_removed", "a pre-existing ciphertext file was removed"
        )
    if any(before[name] != after[name] for name in before_names):
        raise ArchiveStageError(
            "ciphertext_changed", "a pre-existing ciphertext file changed"
        )
    added = after_names - before_names
    if added != {expected_relative_path}:
        raise ArchiveStageError(
            "ciphertext_delta_invalid",
            "ciphertext inventory did not contain exactly the mapped new file",
        )
    return dict(after[expected_relative_path])


def _capture_tool_identity(repo_root: Path) -> dict[str, Any]:
    code = capture_code_identity(repo_root)
    if code.get("git_dirty") is not False:
        raise ArchiveStageError(
            "git_tree_dirty", "cold-archive staging requires a clean Git tree"
        )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
            creationflags=creationflags,
        ).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchiveStageError("git_identity_failed", "Git identity capture failed") from exc
    if not re.fullmatch(r"[0-9a-f]{40,64}", tree):
        raise ArchiveStageError("git_identity_failed", "Git identity capture failed")
    module_identity, module_sha = _hash_regular_file(Path(__file__), label="tool module")
    return {
        "tool": TOOL,
        "module_sha256": module_sha,
        "module_bytes": module_identity["bytes"],
        "git_commit": str(code["git_commit"]),
        "git_tree": tree,
        "git_branch": str(code["git_branch"]),
        "git_dirty": False,
        "python": sys.version.split()[0],
    }


def _validate_tool_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "tool",
        "module_sha256",
        "module_bytes",
        "git_commit",
        "git_tree",
        "git_branch",
        "git_dirty",
        "python",
    }
    if set(identity) != required or identity.get("tool") != TOOL:
        raise ArchiveStageError("tool_identity_invalid", "tool identity is invalid")
    if identity.get("git_dirty") is not False:
        raise ArchiveStageError("tool_identity_invalid", "tool identity is invalid")
    for name in ("module_sha256",):
        if not re.fullmatch(r"[0-9a-f]{64}", str(identity.get(name) or "")):
            raise ArchiveStageError("tool_identity_invalid", "tool identity is invalid")
    for name in ("git_commit", "git_tree"):
        if not re.fullmatch(r"[0-9a-f]{40,64}", str(identity.get(name) or "")):
            raise ArchiveStageError("tool_identity_invalid", "tool identity is invalid")
    if (
        isinstance(identity.get("module_bytes"), bool)
        or not isinstance(identity.get("module_bytes"), int)
        or int(identity["module_bytes"]) <= 0
    ):
        raise ArchiveStageError("tool_identity_invalid", "tool identity is invalid")
    return dict(identity)


def _validated_inputs(
    *,
    source_root: str | Path,
    source_file: str | Path,
    source_size: int,
    source_mtime_utc: str,
    staging_root: str | Path,
    ciphertext_root: str | Path,
    receipt_root: str | Path,
    rclone_config: str | Path,
    dpapi_secret: str | Path,
    rclone_executable: str | Path,
    crypt_remote_name: str,
    archive_id: str,
    repo_root: str | Path,
    repo_data_root: str | Path,
) -> dict[str, Any]:
    if not ARCHIVE_ID_RE.fullmatch(archive_id) or archive_id in {".", ".."}:
        raise ArchiveStageError("archive_id_invalid", "archive ID is invalid")
    if not REMOTE_NAME_RE.fullmatch(crypt_remote_name):
        raise ArchiveStageError("rclone_remote_invalid", "rclone crypt remote name is invalid")
    if (
        isinstance(source_size, bool)
        or not isinstance(source_size, int)
        or source_size < 0
        or source_size > MAX_SOURCE_BYTES
    ):
        raise ArchiveStageError("source_size_pin_invalid", "source size pin is invalid")
    pinned_mtime_ns = _parse_mtime_utc(source_mtime_utc)
    repo = _absolute_lexical(repo_root, label="repository root")
    repo_data = _absolute_lexical(repo_data_root, label="repository data root")
    source_base = _require_directory(source_root, label="source root")
    source = _absolute_lexical(source_file, label="source file")
    if source == source_base or not _contains(source_base, source):
        raise ArchiveStageError("source_escape", "source file escapes source root")
    source_identity = _regular_identity(source, label="source file")
    if _contains(repo, source):
        raise ArchiveStageError(
            "repository_source_forbidden", "repository paths cannot be archive sources"
        )
    if source_identity["bytes"] != source_size:
        raise ArchiveStageError("source_size_mismatch", "source size pin does not match")
    if source_identity["mtime_ns"] != pinned_mtime_ns:
        raise ArchiveStageError(
            "source_mtime_mismatch", "source last-write pin does not match"
        )
    roots = {
        "staging_root": _require_directory(staging_root, label="staging root"),
        "ciphertext_root": _require_directory(
            ciphertext_root, label="ciphertext root"
        ),
        "receipt_root": _require_directory(receipt_root, label="receipt root"),
    }
    for name, root in roots.items():
        if _overlaps(root, source_base):
            raise ArchiveStageError(
                "output_source_overlap", f"{name} overlaps the source root"
            )
        if _overlaps(root, repo_data):
            raise ArchiveStageError(
                "repository_data_output_forbidden",
                f"{name} overlaps repository data",
            )
    root_items = list(roots.items())
    for index, (left_name, left) in enumerate(root_items):
        for right_name, right in root_items[index + 1 :]:
            if _overlaps(left, right):
                raise ArchiveStageError(
                    "output_roots_overlap",
                    f"{left_name} overlaps {right_name}",
                )
    config = _absolute_lexical(rclone_config, label="rclone config")
    secret = _absolute_lexical(dpapi_secret, label="DPAPI secret")
    executable = _absolute_lexical(rclone_executable, label="rclone executable")
    if executable.name.casefold() not in {"rclone", "rclone.exe"}:
        raise ArchiveStageError(
            "rclone_executable_invalid", "rclone executable name is invalid"
        )
    config_identity = _regular_identity(config, label="rclone config")
    secret_identity = _regular_identity(secret, label="DPAPI secret")
    executable_identity = _regular_identity(executable, label="rclone executable")
    attempt_directory = roots["staging_root"] / archive_id
    manifest_path = roots["receipt_root"] / f"{archive_id}.manifest.json"
    receipt_path = roots["receipt_root"] / f"{archive_id}.receipt.json"
    for path, code, label in (
        (attempt_directory, "archive_id_collision", "archive ID"),
        (manifest_path, "manifest_collision", "manifest"),
        (receipt_path, "receipt_collision", "receipt"),
    ):
        if path.exists():
            raise ArchiveStageError(code, f"{label} create-only collision")
    return {
        "source_root": source_base,
        "source_file": source,
        "source_relative": source.relative_to(source_base).as_posix(),
        "source_identity": source_identity,
        "source_mtime_utc": _format_mtime_utc(pinned_mtime_ns),
        **roots,
        "rclone_config": config,
        "dpapi_secret": secret,
        "rclone_executable": executable,
        "rclone_config_identity": config_identity,
        "dpapi_secret_identity": secret_identity,
        "rclone_executable_identity": executable_identity,
        "crypt_remote_name": crypt_remote_name,
        "archive_id": archive_id,
        "attempt_directory": attempt_directory,
        "manifest_path": manifest_path,
        "receipt_path": receipt_path,
        "repo_root": repo,
    }


def _require_stable_supporting_inputs(inputs: Mapping[str, Any]) -> None:
    for name, label in (
        ("rclone_config", "rclone config"),
        ("dpapi_secret", "DPAPI secret"),
        ("rclone_executable", "rclone executable"),
    ):
        if _regular_identity(inputs[name], label=label) != inputs[f"{name}_identity"]:
            raise ArchiveStageError(
                "supporting_input_drift", "a supporting input changed during staging"
            )


def _failure_ciphertext_state(
    *,
    before: Mapping[str, Mapping[str, int]] | None,
    ciphertext_root: Path,
    expected_relative_path: str | None,
    copy_attempted: bool,
    copy_succeeded: bool,
    cryptcheck_passed: bool,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "state": "copy_not_attempted" if not copy_attempted else "creation_unknown",
        "relative_path": expected_relative_path,
        "identity": None,
    }
    if not copy_attempted or before is None or expected_relative_path is None:
        return state
    try:
        after = _stable_ciphertext_inventory(ciphertext_root)
        identity = _validate_ciphertext_delta(
            before, after, expected_relative_path=expected_relative_path
        )
        path = ciphertext_root.joinpath(*expected_relative_path.split("/"))
        final_identity, digest = _hash_regular_file(path, label="retained ciphertext")
        if final_identity != identity:
            raise ArchiveStageError(
                "ciphertext_drift", "retained ciphertext changed while hashed"
            )
        state["identity"] = {
            "bytes": identity["bytes"],
            "sha256": digest,
        }
        if cryptcheck_passed:
            state["state"] = "verified_retained"
        elif copy_succeeded:
            state["state"] = "created_retained_unverified"
        else:
            state["state"] = "created_after_failed_copy_retained_unverified"
    except Exception:
        state["state"] = "creation_state_ambiguous_retained"
    return state


def stage_provisional_mirror_copy(
    *,
    provisional_mirror_copy: bool,
    source_root: str | Path,
    source_file: str | Path,
    source_size: int,
    source_mtime_utc: str,
    staging_root: str | Path,
    ciphertext_root: str | Path,
    receipt_root: str | Path,
    rclone_config: str | Path,
    dpapi_secret: str | Path,
    rclone_executable: str | Path,
    crypt_remote_name: str,
    archive_id: str,
    repo_root: str | Path = REPO_ROOT,
    repo_data_root: str | Path = DATA_ROOT,
    runner: RcloneRunner = _subprocess_runner,
    secret_loader: SecretLoader = _load_dpapi_secret,
    tool_identity: Mapping[str, Any] | None = None,
    wrapper_active: bool | None = None,
) -> dict[str, Any]:
    """Stage one source without granting production identity or deletion authority."""

    # Never let a caller's ambient password escape to Git identity probes or any
    # other child.  The recovered value is supplied only in a private rclone env.
    os.environ.pop(CONFIG_PASS_ENV, None)
    if provisional_mirror_copy is not True:
        raise ArchiveStageError(
            "provisional_mode_required", "explicit provisional mirror-copy mode is required"
        )
    active = os.environ.get(WRAPPER_ENV) == "1" if wrapper_active is None else wrapper_active
    if active is not True:
        raise ArchiveStageError(
            "workstation_wrapper_required", "canonical workstation-heavy wrapper is required"
        )
    inputs = _validated_inputs(
        source_root=source_root,
        source_file=source_file,
        source_size=source_size,
        source_mtime_utc=source_mtime_utc,
        staging_root=staging_root,
        ciphertext_root=ciphertext_root,
        receipt_root=receipt_root,
        rclone_config=rclone_config,
        dpapi_secret=dpapi_secret,
        rclone_executable=rclone_executable,
        crypt_remote_name=crypt_remote_name,
        archive_id=archive_id,
        repo_root=repo_root,
        repo_data_root=repo_data_root,
    )
    identity = _validate_tool_identity(
        tool_identity or _capture_tool_identity(inputs["repo_root"])
    )
    receipt_sink = _CreateOnlyJsonSink(inputs["receipt_path"])
    secret_material: SecretMaterial | None = None
    child_environment: dict[str, str] | None = None
    passphrase = ""
    ciphertext_before: dict[str, dict[str, int]] | None = None
    expected_ciphertext_relative: str | None = None
    copy_attempted = False
    copy_succeeded = False
    cryptcheck_passed = False
    checks: dict[str, str] = {
        "source_size_pin": "PASS",
        "source_mtime_pin": "PASS",
        "source_initial_hash_stable": "NOT_RUN",
        "deterministic_compression": "NOT_RUN",
        "rclone_config_encrypted": "NOT_RUN",
        "rclone_local_ciphertext_root": "NOT_RUN",
        "rclone_destination_absent": "NOT_RUN",
        "rclone_create_only_copy": "NOT_RUN",
        "rclone_cryptcheck": "NOT_RUN",
        "ciphertext_exact_delta": "NOT_RUN",
        "ciphertext_post_check_stable": "NOT_RUN",
        "source_post_hash_stable": "NOT_RUN",
        "supporting_inputs_stable": "NOT_RUN",
    }
    try:
        # Prove access to encryption before reading source content or creating
        # plaintext staging. A matching Windows principal alone does not prove
        # that this logon session can recover its CurrentUser DPAPI material.
        os.environ.pop(CONFIG_PASS_ENV, None)
        secret_material = secret_loader(inputs["dpapi_secret"])
        passphrase = secret_material.text()
        # Ambient remote/backend/logging overrides must not redirect this
        # config-bound local-only operation or expose decrypted material.
        child_environment = {
            name: value
            for name, value in os.environ.items()
            if not name.upper().startswith("RCLONE_")
        }
        child_environment[CONFIG_PASS_ENV] = passphrase
        client = _RcloneClient(
            executable=inputs["rclone_executable"],
            config=inputs["rclone_config"],
            remote_name=inputs["crypt_remote_name"],
            environment=child_environment,
            runner=runner,
        )
        client.check_config_encryption()
        checks["rclone_config_encrypted"] = "PASS"
        rclone_version = client.version()
        client.require_local_ciphertext_root(inputs["ciphertext_root"])
        checks["rclone_local_ciphertext_root"] = "PASS"

        inputs["attempt_directory"].mkdir()
        archive_path = inputs["attempt_directory"] / ARCHIVE_FILENAME
        with inputs["source_file"].open("rb") as source_handle:
            opened_identity = _identity_from_stat(os.fstat(source_handle.fileno()))
            if opened_identity != inputs["source_identity"]:
                raise ArchiveStageError(
                    "source_drift_before_hash", "source changed before initial hash"
                )
            source_bytes, source_sha256 = _hash_open_handle(source_handle)
            if (
                source_bytes != source_size
                or _identity_from_stat(os.fstat(source_handle.fileno()))
                != opened_identity
                or _regular_identity(inputs["source_file"], label="source file")
                != opened_identity
            ):
                raise ArchiveStageError(
                    "source_drift_initial_hash", "source changed during initial hash"
                )
            checks["source_initial_hash_stable"] = "PASS"
            compression = _write_deterministic_archive(
                source_handle,
                archive_path,
                source_bytes=source_size,
                expected_sha256=source_sha256,
            )
            if (
                _identity_from_stat(os.fstat(source_handle.fileno())) != opened_identity
                or _regular_identity(inputs["source_file"], label="source file")
                != opened_identity
            ):
                raise ArchiveStageError(
                    "source_drift_after_compression",
                    "source changed during deterministic compression",
                )
            checks["deterministic_compression"] = "PASS"

            # Compression can be long. Do not reuse its earlier config/root
            # proof for a client that will reopen mutable supporting paths.
            _require_stable_supporting_inputs(inputs)
            checks["rclone_config_encrypted"] = "NOT_RUN"
            checks["rclone_local_ciphertext_root"] = "NOT_RUN"
            client.check_config_encryption()
            checks["rclone_config_encrypted"] = "PASS"
            client.require_local_ciphertext_root(inputs["ciphertext_root"])
            checks["rclone_local_ciphertext_root"] = "PASS"
            _require_stable_supporting_inputs(inputs)

            logical_relative = f"{archive_id}/{ARCHIVE_FILENAME}"
            expected_ciphertext_relative = client.encrypted_relative_path(logical_relative)
            expected_ciphertext_path = inputs["ciphertext_root"].joinpath(
                *expected_ciphertext_relative.split("/")
            )
            if not _contains(inputs["ciphertext_root"], expected_ciphertext_path):
                raise ArchiveStageError(
                    "ciphertext_mapping_escape", "mapped ciphertext path escapes its root"
                )
            _assert_no_reparse_components(
                expected_ciphertext_path.parent, label="mapped ciphertext parent"
            )
            if expected_ciphertext_path.exists():
                raise ArchiveStageError(
                    "ciphertext_collision", "mapped ciphertext path already exists"
                )
            client.require_destination_absent(archive_id)
            checks["rclone_destination_absent"] = "PASS"
            ciphertext_before = _stable_ciphertext_inventory(inputs["ciphertext_root"])
            if any(
                Path(relative).name.endswith(RCLONE_PARTIAL_SUFFIX)
                for relative in ciphertext_before
            ):
                raise ArchiveStageError(
                    "rclone_partial_collision",
                    "ciphertext root contains a pre-existing rclone partial file",
                )
            copy_attempted = True
            client.copy_create_only(inputs["attempt_directory"], archive_id)
            copy_succeeded = True
            checks["rclone_create_only_copy"] = "PASS"
            ciphertext_after_copy = _stable_ciphertext_inventory(inputs["ciphertext_root"])
            ciphertext_identity = _validate_ciphertext_delta(
                ciphertext_before,
                ciphertext_after_copy,
                expected_relative_path=expected_ciphertext_relative,
            )
            checks["ciphertext_exact_delta"] = "PASS"
            client.cryptcheck(inputs["attempt_directory"], archive_id)
            cryptcheck_passed = True
            checks["rclone_cryptcheck"] = "PASS"
            ciphertext_after_check = _stable_ciphertext_inventory(inputs["ciphertext_root"])
            if ciphertext_after_check != ciphertext_after_copy:
                raise ArchiveStageError(
                    "ciphertext_post_check_drift",
                    "ciphertext changed during cryptcheck",
                )
            checks["ciphertext_post_check_stable"] = "PASS"
            ciphertext_path = inputs["ciphertext_root"].joinpath(
                *expected_ciphertext_relative.split("/")
            )
            hashed_cipher_identity, ciphertext_sha256 = _hash_regular_file(
                ciphertext_path, label="new ciphertext"
            )
            if hashed_cipher_identity != ciphertext_identity:
                raise ArchiveStageError(
                    "ciphertext_hash_drift", "ciphertext changed while hashed"
                )
            final_source_bytes, final_source_sha256 = _hash_open_handle(source_handle)
            if (
                final_source_bytes != source_size
                or final_source_sha256 != source_sha256
                or _identity_from_stat(os.fstat(source_handle.fileno()))
                != opened_identity
                or _regular_identity(inputs["source_file"], label="source file")
                != opened_identity
            ):
                raise ArchiveStageError(
                    "source_post_drift", "source changed after staging"
                )
            checks["source_post_hash_stable"] = "PASS"

        _require_stable_supporting_inputs(inputs)
        checks["supporting_inputs_stable"] = "PASS"
        manifest: dict[str, Any] = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "manifest_hash": "",
            "archive_id": archive_id,
            "mode": "provisional_mirror_copy",
            "source": {
                "path_relative_to_source_root": inputs["source_relative"],
                "bytes": source_size,
                "sha256": source_sha256,
                "last_write_utc": inputs["source_mtime_utc"],
                "last_write_ns": inputs["source_identity"]["mtime_ns"],
                "retained": True,
            },
            "compression": compression,
            "ciphertext": {
                "path_relative_to_ciphertext_root": expected_ciphertext_relative,
                "bytes": ciphertext_identity["bytes"],
                "sha256": ciphertext_sha256,
            },
            "rclone": {
                "version": rclone_version,
                "crypt_remote_name": inputs["crypt_remote_name"],
                "logical_archive_destination": f"{inputs['crypt_remote_name']}:{archive_id}",
                "copy_semantics": "copy+immutable+ignore-times+error-on-no-transfer",
                "transfers": 1,
                "checkers": 1,
            },
            "tool_identity": identity,
            "wrapper": {
                "required_environment": f"{WRAPPER_ENV}=1",
                "expected_kind": "weather_heavy",
                "expected_module": TOOL,
                "host_global_mutex_expected": True,
                "kill_on_close_job_expected": True,
            },
            "verification": dict(checks),
            "source_retained": True,
            "Drive_upload_performed": False,
            "restore_performed": False,
            "production_identity_not_proved": True,
            "cleanup_eligible": False,
            "deletion_authorized": False,
            "append_only": True,
        }
        manifest["manifest_hash"] = manifest_content_hash(manifest)
        _write_json_create_only(inputs["manifest_path"], manifest)
        receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "receipt_hash": "",
            "status": "PASS",
            "archive_id": archive_id,
            "mode": "provisional_mirror_copy",
            "manifest": {
                "path": inputs["manifest_path"].name,
                "manifest_hash": manifest["manifest_hash"],
            },
            "encrypted_object": {
                "state": "verified_retained",
                "relative_path": expected_ciphertext_relative,
                "identity": {
                    "bytes": ciphertext_identity["bytes"],
                    "sha256": ciphertext_sha256,
                },
            },
            "verification": dict(checks),
            "tool_identity": identity,
            "terminal_at_utc": _utc_now(),
            "source_retained": True,
            "Drive_upload_performed": False,
            "restore_performed": False,
            "production_identity_not_proved": True,
            "cleanup_eligible": False,
            "deletion_authorized": False,
        }
        receipt["receipt_hash"] = receipt_content_hash(receipt)
        receipt_sink.write(receipt)
        return {
            "status": "PASS",
            "archive_id": archive_id,
            "manifest_path": str(inputs["manifest_path"]),
            "receipt_path": str(inputs["receipt_path"]),
            "manifest_hash": manifest["manifest_hash"],
            "receipt_hash": receipt["receipt_hash"],
        }
    except Exception as exc:
        if not receipt_sink.written:
            error_code = (
                exc.code if isinstance(exc, ArchiveStageError) else "unexpected_failure"
            )
            failure: dict[str, Any] = {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "receipt_hash": "",
                "status": "FAIL_CLOSED",
                "archive_id": archive_id,
                "mode": "provisional_mirror_copy",
                "error_code": error_code,
                "encrypted_object": _failure_ciphertext_state(
                    before=ciphertext_before,
                    ciphertext_root=inputs["ciphertext_root"],
                    expected_relative_path=expected_ciphertext_relative,
                    copy_attempted=copy_attempted,
                    copy_succeeded=copy_succeeded,
                    cryptcheck_passed=cryptcheck_passed,
                ),
                "verification": dict(checks),
                "tool_identity": identity,
                "terminal_at_utc": _utc_now(),
                "source_retained": True,
                "Drive_upload_performed": False,
                "restore_performed": False,
                "production_identity_not_proved": True,
                "cleanup_eligible": False,
                "deletion_authorized": False,
            }
            if isinstance(exc, _DpapiRecoveryError):
                failure["dpapi_winerror"] = exc.winerror
            failure["receipt_hash"] = receipt_content_hash(failure)
            try:
                receipt_sink.write(failure)
            except Exception as receipt_exc:
                raise ArchiveStageError(
                    "failure_receipt_write_failed",
                    "staging failed and the create-only failure receipt could not be written",
                ) from receipt_exc
        if isinstance(exc, ArchiveStageError):
            raise
        raise ArchiveStageError(
            "unexpected_failure", "cold-archive staging failed closed"
        ) from exc
    finally:
        if child_environment is not None and CONFIG_PASS_ENV in child_environment:
            child_environment[CONFIG_PASS_ENV] = "0" * len(passphrase)
            child_environment.pop(CONFIG_PASS_ENV, None)
        passphrase = ""
        if secret_material is not None:
            secret_material.wipe()
        os.environ.pop(CONFIG_PASS_ENV, None)
        receipt_sink.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provisional-mirror-copy", action="store_true", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--source-size", required=True, type=int)
    parser.add_argument("--source-mtime-utc", required=True)
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--ciphertext-root", required=True)
    parser.add_argument("--receipt-root", required=True)
    parser.add_argument("--rclone-config", required=True)
    parser.add_argument("--dpapi-secret", required=True)
    parser.add_argument("--rclone-executable", required=True)
    parser.add_argument("--crypt-remote-name", required=True)
    parser.add_argument("--archive-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = stage_provisional_mirror_copy(
            provisional_mirror_copy=args.provisional_mirror_copy,
            source_root=args.source_root,
            source_file=args.source_file,
            source_size=args.source_size,
            source_mtime_utc=args.source_mtime_utc,
            staging_root=args.staging_root,
            ciphertext_root=args.ciphertext_root,
            receipt_root=args.receipt_root,
            rclone_config=args.rclone_config,
            dpapi_secret=args.dpapi_secret,
            rclone_executable=args.rclone_executable,
            crypt_remote_name=args.crypt_remote_name,
            archive_id=args.archive_id,
        )
    except ArchiveStageError as exc:
        print(f"FAIL_CLOSED: {exc.code}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
