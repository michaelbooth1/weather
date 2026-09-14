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


@contextmanager
def open_record(root: Path, name: str) -> Iterator[BinaryIO]:
    """Open regular evidence without following redirects, before reading bytes."""
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
        handle = create(str(target), 0x80000000, 7, None, 3, 0x00200000, None)
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
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = name.split("/")
            for part in parts[:-1]:
                child_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child_fd
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        _regular(before)
        # Records are regular retained files, not aliases into mutable sources.
        require(before.st_nlink == 1, "path: hard-linked evidence forbidden")
        yield handle
        after = os.fstat(handle.fileno())
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
    with open_record(root, ref["path"]) as handle:
        raw = handle.read(ref["size"] + 1)
    require(len(raw) == ref["size"], "record byte count mismatch")
    require(hashlib.sha256(raw).hexdigest() == ref["sha256"], "record digest mismatch")
    return Record(ref["path"], ref["sha256"], len(raw), decode(raw))


def publish(root: Path, name: str, value: dict) -> dict:
    """Publish once. A failed write leaves its destination spent, never reusable.

    The final handle is create-new and is durably flushed before its digest is
    returned to a parent. Until then no predecessor can legitimately bind it.
    Compound evidence becomes visible through its create-once final root record.
    """
    root = checked_root(root)
    name = relative_path(name)
    target = root / name
    checked_root(target.parent)
    raw = encode(value)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(target, flags, 0o600), "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if os.name != "nt":
        fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    ref = {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    read(root, ref)
    return ref
