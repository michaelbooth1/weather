"""Bounded metadata inventory for reviewed storage-recovery selections.

This module never reads payload contents, follows links, compresses or deletes.
Inventory bytes are candidate capacity, not proven reclaim or archive eligibility.
The command is available only through the dedicated capture recovery wrapper.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, timedelta
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
from typing import Callable

from weather.schema_registry import schema_version

MIB = 1024**2
MAX_FOLDERS = 12
MAX_ENTRIES = 25000
MAX_DIRECTORY_ENTRIES = 15000
MAX_DEPTH = 8
MAX_SECONDS = 120
MAX_OUTPUT_BYTES = 24 * MIB
REPARSE_POINT = 0x400
EVENT = re.compile(
    r"highest-temperature-in-(atlanta|austin|chicago|dallas|denver|houston|"
    r"los-angeles|miami|nyc|san-francisco|seattle|toronto)-on-"
    r"(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)-([1-9]|[12][0-9]|3[01])-([0-9]{4})\Z"
)
MONTHS = ("january february march april may june july august september "
          "october november december").split()


class InventoryRefused(ValueError):
    """Incomplete or unsafe inventory; never a cleanup permission."""


class InventoryLimit(InventoryRefused):
    """A declared metadata bound was reached."""


@dataclass(frozen=True)
class Limits:
    entries: int = MAX_ENTRIES
    directory_entries: int = MAX_DIRECTORY_ENTRIES
    depth: int = MAX_DEPTH
    seconds: float = MAX_SECONDS
    output_bytes: int = MAX_OUTPUT_BYTES

    def validate(self):
        for name, ceiling in (("entries", MAX_ENTRIES),
                              ("directory_entries", MAX_DIRECTORY_ENTRIES),
                              ("depth", MAX_DEPTH), ("output_bytes", MAX_OUTPUT_BYTES)):
            value = getattr(self, name)
            if type(value) is not int or not 0 < value <= ceiling:
                raise InventoryRefused("invalid inventory limit: " + name)
        if type(self.seconds) not in (int, float) or not 0 < self.seconds <= MAX_SECONDS:
            raise InventoryRefused("invalid inventory time limit")


def event_date(slug: str) -> date:
    match = EVENT.fullmatch(slug)
    if not match:
        raise InventoryRefused("unrecognized built-in event folder")
    _, month, day, year = match.groups()
    try:
        return date(int(year), MONTHS.index(month) + 1, int(day))
    except ValueError as exc:
        raise InventoryRefused("invalid event date") from exc


def validate_folders(folders, *, as_of: date):
    if not isinstance(folders, list) or not 1 <= len(folders) <= MAX_FOLDERS:
        raise InventoryRefused("name one to twelve exact folders")
    seen = set()
    result = []
    for name in folders:
        if not isinstance(name, str) or "\\" in name or ":" in name or "\x00" in name:
            raise InventoryRefused("folder must be an exact relative POSIX path")
        parts = PurePosixPath(name).parts
        if name != PurePosixPath(name).as_posix() or any(p in (".", "..") for p in parts):
            raise InventoryRefused("noncanonical folder path")
        if len(parts) == 2 and parts[0] == "snapshots":
            target = event_date(parts[1])
        elif len(parts) == 3 and parts[:2] == ("backtest", "replay_cache"):
            target = event_date(parts[2])
        elif parts == ("backtest",):
            target = None  # Root files only; never includes replay_cache again.
        else:
            raise InventoryRefused("folder is outside the recovery inventory contract")
        if target is not None and target >= as_of - timedelta(days=30):
            raise InventoryRefused("event is inside the thirty-day hot window")
        if name.casefold() in seen:
            raise InventoryRefused("duplicate folder")
        seen.add(name.casefold())
        result.append((name, target))
    return result


def identity(info):
    return (int(info.st_dev), int(info.st_ino), int(info.st_mode),
            int(info.st_size), int(info.st_mtime_ns), int(info.st_nlink),
            int(getattr(info, "st_file_attributes", 0)))


def checked_stat(path, *, directory):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
        raise InventoryRefused("link or reparse point: " + str(path))
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise InventoryRefused("unexpected filesystem type: " + str(path))
    if not directory and info.st_nlink != 1:
        raise InventoryRefused("hardlinked file: " + str(path))
    return info


def validate_root(root):
    root = Path(root)
    if not root.is_absolute() or root != Path(os.path.abspath(root)):
        raise InventoryRefused("data root must be absolute and normalized")
    for ancestor in reversed((root, *root.parents)):
        checked_stat(ancestor, directory=True)
    return root


def native_allocation(path, expected):
    """Read actual NTFS allocation from a metadata handle without opening data."""
    if os.name != "nt":
        raise InventoryRefused("native allocation requires Windows")
    import ctypes
    from ctypes import wintypes
    from weather.operations.ntfs_file_compression import _StandardInformation, _FileInformation
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInformation)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                   ctypes.c_void_p, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    # FILE_READ_ATTRIBUTES, full sharing and OPEN_REPARSE_POINT. No data reads
    # or writer exclusion. Reconcile identities, then re-stat after the call.
    handle = kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        standard, info = _StandardInformation(), _FileInformation()
        if (not kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
                or not kernel.GetFileInformationByHandleEx(
                    handle, 1, ctypes.byref(standard), ctypes.sizeof(standard))):
            raise ctypes.WinError(ctypes.get_last_error())
        file_index = (int(info.index_high) << 32) | int(info.index_low)
        logical = (int(info.size_high) << 32) | int(info.size_low)
        written = ((int(info.written.dwHighDateTime) << 32) | int(info.written.dwLowDateTime))
        written_ns = (written - 116444736000000000) * 100
        if (int(info.volume) != expected.st_dev or file_index != expected.st_ino
                or logical != expected.st_size
                or written_ns != expected.st_mtime_ns or info.links != 1
                or standard.links != 1 or standard.directory or standard.delete_pending
                or info.attributes & REPARSE_POINT or standard.allocation < 0):
            raise InventoryRefused("native allocation identity mismatch")
        if info.attributes & (0x800 | 0x200):  # NTFS compressed or sparse.
            class CompressionInfo(ctypes.Structure):
                _fields_ = [("size", ctypes.c_int64), ("format", wintypes.WORD),
                            ("unit", ctypes.c_ubyte), ("chunk", ctypes.c_ubyte),
                            ("cluster", ctypes.c_ubyte), ("reserved", ctypes.c_ubyte * 3)]
            compression = CompressionInfo()
            if not kernel.GetFileInformationByHandleEx(
                    handle, 8, ctypes.byref(compression), ctypes.sizeof(compression)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not 0 <= compression.size <= standard.allocation:
                raise InventoryRefused("invalid physical allocation for compressed or sparse file")
            return int(compression.size)
        return int(standard.allocation)
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def _pinned(path):
    if os.name != "nt":
        return nullcontext()
    from weather.operations.ntfs_file_compression import PinnedNtfsDirectory
    return PinnedNtfsDirectory(path)


def inventory(data_root, folders, *, as_of, guard: Callable[[], None],
              limits=Limits(), allocation=native_allocation, clock=time.monotonic):
    """Inventory exact cold folders; partial or drifted folders supply no budget."""
    limits.validate()
    selected = validate_folders(folders, as_of=as_of)
    guard()
    root = validate_root(data_root)
    started = clock()
    entries = 0
    output_size = 0
    rows = []
    summaries = []
    stops = []

    def checkpoint():
        guard()
        if clock() - started >= limits.seconds:
            raise InventoryLimit("elapsed_seconds_limit")
        if entries >= limits.entries:
            raise InventoryLimit("entry_count_limit")

    for name, target in selected:
        initial_row = len(rows)
        folder = root.joinpath(*PurePosixPath(name).parts)
        folder_summary = {"path": name, "target_date": target.isoformat() if target else None,
                          "status": "PENDING", "files": 0, "logical_bytes": 0,
                          "allocated_bytes": 0, "cleanup_eligible": False}
        summaries.append(folder_summary)
        directories = []
        pending = [(folder, 0)]
        try:
            while pending:
                checkpoint()
                current, depth = pending.pop()
                if depth > limits.depth:
                    raise InventoryLimit("directory_depth_limit")
                with _pinned(current):
                    before_dir = checked_stat(current, directory=True)
                    children = []
                    with os.scandir(current) as iterator:
                        for child in iterator:
                            checkpoint()
                            entries += 1
                            if len(children) >= limits.directory_entries:
                                raise InventoryLimit("directory_entry_limit")
                            children.append(child.name)
                    children.sort()
                    for child_name in children:
                        checkpoint()
                        path = current / child_name
                        raw = path.lstat()
                        if stat.S_ISDIR(raw.st_mode):
                            checked_stat(path, directory=True)
                            if name != "backtest":
                                pending.append((path, depth + 1))
                            continue
                        info = checked_stat(path, directory=False)
                        allocated = allocation(path, info)
                        if type(allocated) is not int or allocated < 0:
                            raise InventoryRefused("invalid native allocation")
                        if identity(checked_stat(path, directory=False)) != identity(info):
                            raise InventoryRefused("file_metadata_changed")
                        relative = path.relative_to(root).as_posix()
                        row = {"path": relative, "size_bytes": int(info.st_size),
                               "allocated_bytes": allocated, "mtime_ns": str(info.st_mtime_ns),
                               "device": str(info.st_dev), "file_id": str(info.st_ino),
                               "attributes": int(getattr(info, "st_file_attributes", 0))}
                        output_size += len(json.dumps(row).encode()) + 2
                        if output_size > limits.output_bytes:
                            raise InventoryLimit("output_byte_limit")
                        rows.append(row)
                    if identity(checked_stat(current, directory=True)) != identity(before_dir):
                        raise InventoryRefused("directory_metadata_changed")
                    directories.append((current, identity(before_dir)))
            for current, expected in directories:
                checkpoint()
                if identity(checked_stat(current, directory=True)) != expected:
                    raise InventoryRefused("directory_changed_after_inventory")
            own = rows[initial_row:]
            folder_summary.update(status="COMPLETE", files=len(own),
                                  logical_bytes=sum(r["size_bytes"] for r in own),
                                  allocated_bytes=sum(r["allocated_bytes"] for r in own))
        except (OSError, InventoryRefused) as exc:
            folder_summary.update(status="PARTIAL" if isinstance(exc, InventoryLimit) else "BLOCK",
                                  reason=str(exc), observed_files=len(rows) - initial_row)
            # Keep bounded observations as evidence, but never add an incomplete
            # folder to capacity totals or imply that it is eligible for removal.
            stops.append({"folder": name, "reason": str(exc)})
            if isinstance(exc, InventoryLimit):
                break
    complete = [s for s in summaries if s["status"] == "COMPLETE"]
    return {"schema_version": schema_version("storage_recovery_inventory"),
            "status": "PARTIAL" if stops else "PASS", "payload_bytes_read": 0,
            "source_files_changed": 0, "deleted_files": 0, "reclaimed_bytes": 0,
            "cleanup_eligible": False, "as_of": as_of.isoformat(),
            "data_root": str(root), "requested_folders": folders,
            "not_visited_folders": folders[len(summaries):], "entries_observed": entries,
            "elapsed_seconds": clock() - started, "stop_reasons": stops,
            "complete_folder_logical_bytes": sum(s["logical_bytes"] for s in complete),
            "complete_folder_allocated_bytes": sum(s["allocated_bytes"] for s in complete),
            "folders": summaries, "files": rows}
