"""Bounded, strict, byte-bound records shared by qualification producers/readers.

The expected digest comes from the caller's trusted predecessor, never from
the record being validated. Downloaded records cannot supply executable paths.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import BinaryIO, Iterator


MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 100_000
MAX_DEPTH = 32
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_ID = re.compile(r"[0-9a-f]{40}\Z")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)


class QualificationError(ValueError):
    """Evidence is missing, inconsistent, unsafe, stale or unsupported."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationError(message)


def fields(value: object, required: set[str], optional: set[str] = frozenset(), *, label="record") -> dict:
    require(type(value) is dict, f"{label}: expected object")
    require(required <= value.keys() <= required | optional, f"{label}: unsupported or missing fields")
    return value


def integer(value: object, *, minimum=0, maximum=2**63 - 1, label="integer") -> int:
    require(type(value) is int and minimum <= value <= maximum, f"{label}: invalid integer")
    return value


def digest(value: object, *, git=False, label="digest") -> str:
    require(type(value) is str and (GIT_ID if git else SHA256).fullmatch(value) is not None,
            f"{label}: invalid lowercase digest")
    return value


def identifier(value: object, *, label="identifier") -> str:
    require(type(value) is str and SAFE_ID.fullmatch(value) is not None, f"{label}: invalid identifier")
    return value


def timestamp(value: object) -> datetime:
    require(type(value) is str and len(value) <= 40 and value.endswith("Z"), "timestamp: UTC Z required")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise QualificationError("timestamp: invalid UTC instant") from exc
    require(parsed.utcoffset().total_seconds() == 0, "timestamp: invalid UTC offset")
    return parsed


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def relative_path(value: object) -> str:
    require(type(value) is str and 0 < len(value) <= 1024, "path: invalid length/type")
    require(not any(ord(c) < 32 or c in '\\:*?"<>|' for c in value), "path: unsupported character")
    pieces = value.split("/")
    require(all(p and p not in {".", ".."} and not p.endswith((".", " ")) and not RESERVED.fullmatch(p)
                for p in pieces), "path: unsafe segment")
    require(not PurePosixPath(value).is_absolute(), "path: absolute path forbidden")
    return value


def distinct_paths(values: object) -> list[str]:
    require(type(values) is list and len(values) <= MAX_ITEMS, "paths: invalid list")
    paths = [relative_path(value) for value in values]
    require(len({path.casefold() for path in paths}) == len(paths), "paths: duplicate/case-fold collision")
    return paths


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON: duplicate key")
        result[key] = value
    return result


def _reject_number(value):
    raise QualificationError("JSON: floating point and non-finite numbers are forbidden")


def decode(raw: bytes, *, maximum=MAX_RECORD_BYTES) -> dict:
    require(type(raw) is bytes and 0 < len(raw) <= maximum, "JSON: invalid byte length")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_reject_number, parse_constant=_reject_number)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise QualificationError(f"JSON: invalid strict record ({type(exc).__name__})") from exc
    todo = [(value, 0)]
    count = 0
    while todo:
        item, depth = todo.pop()
        count += 1
        require(depth <= MAX_DEPTH and count <= MAX_ITEMS, "JSON: structure limit exceeded")
        if isinstance(item, dict):
            require(all(type(key) is str and len(key) <= 256 for key in item), "JSON: invalid key")
            todo.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            todo.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            require(len(item) <= 8192 and "\x00" not in item, "JSON: invalid string")
        elif type(item) is int:
            integer(item, minimum=-(2**63))
        else:
            require(item is None or type(item) is bool, "JSON: unsupported type")
    require(type(value) is dict, "JSON: object required")
    return value


def encode(value: dict) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    decode(raw)
    return raw


def _regular(info, *, directory=False):
    require(not getattr(info, "st_file_attributes", 0) & 0x400, "path: reparse point forbidden")
    require((stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode), "path: wrong file type")


def checked_root(root: Path) -> Path:
    root = Path(root)
    require(root.is_absolute(), "root: absolute path required")
    for path in reversed((root, *root.parents)):
        _regular(path.lstat(), directory=True)
    return root


def _posix_retained_digest(descriptor: int, size: int) -> bytes:
    # Linux filesystem timestamps may have coarser update resolution than their
    # nanosecond representation. pread bypasses Python's existing read buffer
    # and leaves the caller's position unchanged. This is sealed-file evidence,
    # never a live-input staging reader.
    hasher, offset = hashlib.sha256(), 0
    while part := os.pread(descriptor, min(1024 * 1024, size + 1 - offset), offset):
        offset += len(part)
        require(offset <= size, "evidence changed while open")
        hasher.update(part)
    require(offset == size, "evidence changed while open")
    return hasher.digest()


@contextmanager
def open_record(root: Path, name: str, *, maximum=512 * 1024**2, _check_posix_bytes=True, _native_installation=False) -> Iterator[BinaryIO]:
    """Open regular evidence without following redirects, before reading bytes."""
    integer(maximum, maximum=64 * 1024**3)
    root = checked_root(root)
    name = relative_path(name)
    target = root / name
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        for parent in target.parents:
            _regular(parent.lstat(), directory=True)
            if parent == root:
                break
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        # Retained evidence is sealed, not a live writer's source. FILE_SHARE_READ
        # rejects concurrent write/delete handles, including an already-open
        # writer, instead of trusting timestamp granularity to notice a rewrite.
        # Mutable-input staging uses a separate shared-prefix reader.
        handle = create(str(target), 0x80000000, 1, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "Cannot open qualification evidence")
        descriptor = None
        try:
            final = kernel.GetFinalPathNameByHandleW
            final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            final.restype = wintypes.DWORD
            buffer = ctypes.create_unicode_buffer(32768)
            length = final(handle, buffer, len(buffer), 0)
            require(0 < length < len(buffer), "path: final handle identity unavailable")
            observed = buffer.value.removeprefix("\\\\?\\")
            require(os.path.normcase(observed) == os.path.normcase(str(target)), "path: handle escaped expected path")
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        finally:
            if descriptor is None:
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle(handle)
    else:
        directory_fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = name.split("/")
            for part in (*root.parts[1:], *parts[:-1]):
                child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child_fd
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        _regular(before)
        require(before.st_size <= maximum, "evidence exceeds byte bound before reading")
        # Records are regular retained files, not aliases into mutable sources.
        require(before.st_nlink == 1 or _native_installation, "path: hard-linked evidence forbidden")
        initial_digest = _posix_retained_digest(handle.fileno(), before.st_size) if os.name != "nt" and _check_posix_bytes else None
        yield handle
        if initial_digest is not None:
            require(_posix_retained_digest(handle.fileno(), before.st_size) == initial_digest,
                    "evidence changed while open")
        after = os.fstat(handle.fileno())
        _regular(after)
        require(after.st_nlink == before.st_nlink and (after.st_nlink == 1 or _native_installation), "path: hard-linked evidence forbidden")
        current = target.lstat()
        _regular(current)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "evidence changed while open")
        require((after.st_dev, after.st_ino) == (current.st_dev, current.st_ino), "evidence path replaced")


@dataclass(frozen=True)
class Record:
    path: str
    sha256: str
    size: int
    value: dict


def reference(value: object) -> dict:
    ref = fields(value, {"path", "sha256", "size"}, label="reference")
    relative_path(ref["path"])
    digest(ref["sha256"])
    integer(ref["size"], minimum=1, maximum=MAX_RECORD_BYTES, label="reference size")
    return ref


def read(root: Path, ref: dict) -> Record:
    ref = reference(ref)
    with open_record(root, ref["path"], maximum=ref["size"]) as handle:
        raw = handle.read(ref["size"] + 1)
    require(len(raw) == ref["size"], "record byte count mismatch")
    require(hashlib.sha256(raw).hexdigest() == ref["sha256"], "record digest mismatch")
    return Record(ref["path"], ref["sha256"], len(raw), decode(raw))


def _flush_directory(path: Path) -> None:
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _publish_no_replace(temporary: Path, target: Path) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        # MOVEFILE_WRITE_THROUGH; deliberately omit REPLACE_EXISTING.
        if not move(str(temporary), str(target), 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        # Same-volume create-only link publishes all bytes atomically. The
        # transient two-link state cannot validate as retained evidence.
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()
        _flush_directory(target.parent)


def publish(root: Path, name: str, value: dict) -> dict:
    return publish_raw(root, name, encode(value))


def publish_raw(root: Path, name: str, raw: bytes) -> dict:
    """Create a durable claim, then atomically publish one complete record.

    The OS lock remains held through final readback. A crash or failed write
    permanently spends the claim and retains partial files for reconciliation;
    no path is automatically reused, replaced, removed or reported as PASS.
    """
    root = checked_root(root)
    name = relative_path(name)
    target = root / name
    checked_root(target.parent)
    decode(raw)  # Validate while preserving the exact original response bytes.
    claim = target.with_name(target.name + ".claim")
    relative_path(claim.relative_to(root).as_posix())
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(claim, flags, 0o600), "w+b") as claim_handle:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(claim_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(claim_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim_handle.write(b"qualification publication claim v2\n")
        claim_handle.flush()
        os.fsync(claim_handle.fileno())
        _flush_directory(claim.parent)
        require(not target.exists(), "publication destination already exists")
        fd, temporary_name = tempfile.mkstemp(prefix=".qualification-", suffix=".partial", dir=target.parent)
        temporary = Path(temporary_name)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        checked_root(target.parent)
        _publish_no_replace(temporary, target)
        ref = {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
        read(root, ref)
        return ref
