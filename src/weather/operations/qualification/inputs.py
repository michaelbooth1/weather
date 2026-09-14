"""Bounded current-input generations, separate from immutable evidence reads.

Live files are opened with writer/deletion sharing. Each fixed-length copy is
fully rehashed before it can enter a manifest; complete generations are checked
again after the audit and at mutation. No writer lock or pause is requested.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import time

from .contracts import record, sequence, text
from .records import (checked_root, digest, distinct_paths, fields, identifier, integer,
                      open_record, publish, relative_path, require, utc_now)


MAX_LINE_BYTES = 1024 * 1024
MAX_INPUT_FILES = 20_000
MAX_FILE_BYTES = 64 * 1024**3
MAX_CORPUS_BYTES = 128 * 1024**3
LINEAGE_FIELDS = ("daily_summary_path", "snapshot_tape_path", "ledger_path",
                  "weather_com_raw_payload_path", "weather_com_payload_path",
                  "market_resolution_payload_path", "gamma_event_payload_path")


def _regular(info, *, directory=False):
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    require(expected and not getattr(info, "st_file_attributes", 0) & 0x400, "redirected/nonregular current input")
    if not directory:
        require(info.st_nlink == 1, "hard-linked current input is not an independent generation")


def generation(info):
    _regular(info)
    # Filesystem IDs may exceed signed int64. Retain their exact decimal form.
    return {"device": str(info.st_dev), "file_id": str(info.st_ino), "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


@contextmanager
def open_current(root, name, *, maximum=MAX_FILE_BYTES):
    """Open the actual canonical source without excluding live writer handles."""
    root, name = checked_root(root), relative_path(name)
    integer(maximum, maximum=MAX_FILE_BYTES)
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
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        handle = kernel.CreateFileW(str(target), 0x80000000, 7, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "Current-input shared read unavailable")
        descriptor = None
        try:
            kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
            buffer = ctypes.create_unicode_buffer(32768)
            size = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
            require(0 < size < len(buffer) and
                    os.path.normcase(buffer.value.removeprefix("\\\\?\\")) == os.path.normcase(str(target)),
                    "current-input handle escaped canonical identity")
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        finally:
            if descriptor is None:
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle(handle)
    else:
        directory = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in (*root.parts[1:], *name.split("/")[:-1]):
                next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = next_directory
            descriptor = os.open(name.split("/")[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        finally:
            os.close(directory)
    with os.fdopen(descriptor, "rb", buffering=0) as handle:
        initial = generation(os.fstat(handle.fileno()))
        require(initial["size"] <= maximum, "current input exceeds declared file budget")
        yield handle, initial
        require(generation(os.fstat(handle.fileno())) == initial and generation(target.lstat()) == initial,
                "current input changed or was replaced during shared read")


@dataclass
class ReadBudget:
    maximum_bytes: int
    deadline_monotonic: float
    observed_bytes: int = 0

    def charge(self, count=0):
        integer(count)
        self.observed_bytes += count
        require(self.observed_bytes <= self.maximum_bytes, "complete input reads exceeded reviewed byte budget")
        require(time.monotonic() < self.deadline_monotonic, "complete input reads exceeded reviewed deadline")


def _hash_handle(handle, size, budget, output=None):
    hasher, remaining = hashlib.sha256(), size
    budget.charge()
    while remaining:
        block = handle.read(min(1024 * 1024, remaining))
        require(bool(block), "truncated current-input generation")
        budget.charge(len(block))
        hasher.update(block)
        if output is not None:
            output.write(block)
        remaining -= len(block)
    require(handle.read(1) == b"", "current-input generation appended during read")
    budget.charge()
    return hasher.hexdigest()


class SourceRoots:
    """Authority-supplied roots/prefixes; source rows cannot expand this set."""

    def __init__(self, roots, prefixes, *, relative_root):
        require(type(roots) is dict and 0 < len(roots) <= 8 and set(roots) == set(prefixes), "invalid source roots")
        require(relative_root in roots, "relative lineage root is undeclared")
        self.roots, self.prefixes, self.relative_root = {}, {}, relative_root
        for name, path in roots.items():
            identifier(name)
            self.roots[name] = checked_root(path)
            values = distinct_paths(prefixes[name])
            require(values, "source root needs explicit approved prefixes")
            self.prefixes[name] = values

    def locate(self, identity):
        text(identity, maximum=4096)
        # Accept native absolute paths only. Foreign-drive strings, UNC paths,
        # ADS, traversal and URL-shaped values fail canonical relative_path.
        path = Path(identity)
        if path.is_absolute():
            matches = []
            for name, root in self.roots.items():
                try:
                    matches.append((name, path.relative_to(root).as_posix()))
                except ValueError:
                    pass
            require(len(matches) == 1, "lineage path is outside or ambiguous between approved roots")
            name, relative = matches[0]
        else:
            name, relative = self.relative_root, identity.replace("\\", "/") if os.name == "nt" else identity
        relative_path(relative)
        allowed = self.prefixes[name]
        folded = relative.casefold()
        require(any(folded == prefix.casefold() or folded.startswith(prefix.casefold() + "/") for prefix in allowed),
                "lineage path is outside reviewed source prefixes")
        return name, relative


class Stager:
    """Create-once staged bytes and explicit missing optional dependencies."""

    def __init__(self, sources, output_root, budget, *, maximum_files=MAX_INPUT_FILES, maximum_bytes=MAX_CORPUS_BYTES):
        self.sources, self.root, self.budget = sources, checked_root(output_root), budget
        self.maximum_files = integer(maximum_files, minimum=1, maximum=MAX_INPUT_FILES)
        self.maximum_bytes = integer(maximum_bytes, minimum=1, maximum=MAX_CORPUS_BYTES)
        self.entries, self.by_key, self.total_bytes = [], {}, 0
        (self.root / "files").mkdir()  # a spent namespace is never reused

    def stage(self, identity, *, mandatory=False, kind="payload"):
        require(kind in {"ledger", "labels", "payload", "config"} and type(mandatory) is bool, "unknown input role")
        name, path = self.sources.locate(identity)
        key = (name, path.casefold())
        if key in self.by_key:
            entry = self.by_key[key]
            if path != entry["path"]:
                with open_current(self.sources.roots[name], path) as (_, actual):
                    require(entry["present"] and actual == entry["generation"], "case alias resolves to another input generation")
            require(entry["kind"] == kind or kind == "payload", "same input declared under incompatible roles")
            require(not mandatory or entry["present"], "required dependency was previously missing")
            if identity not in entry["identities"]:
                require(len(entry["identities"]) < 256, "input identity alias count exceeds bound")
                entry["identities"].append(identity)
            entry["mandatory"] = entry["mandatory"] or mandatory
            return entry
        require(len(self.entries) < self.maximum_files, "input dependency closure exceeds file budget")
        self.budget.charge()
        started = utc_now()
        entry = {"root": name, "path": path, "identities": [identity], "kind": kind, "mandatory": mandatory,
                 "present": False, "missing_reason": "path_not_found", "generation": None, "staged": None,
                 "started_at": started, "completed_at": None}
        opened = False
        try:
            with open_current(self.sources.roots[name], path) as (handle, initial):
                opened = True
                require(self.total_bytes + initial["size"] <= self.maximum_bytes, "input staging reservation exceeded")
                target = f"files/{len(self.entries):06d}.bin"
                with (self.root / target).open("xb") as output:
                    copied_hash = _hash_handle(handle, initial["size"], self.budget, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(self.root / target, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                # Re-read through the same retained source handle, including all
                # bytes. Timestamp granularity alone cannot establish stability.
                handle.seek(0)
                require(_hash_handle(handle, initial["size"], self.budget) == copied_hash,
                        "current-input bytes changed while staging")
                entry.update(present=True, missing_reason=None, generation=initial,
                             staged={"path": target, "sha256": copied_hash, "size": initial["size"]})
                self.total_bytes += initial["size"]
        except FileNotFoundError:
            require(not opened, "current input disappeared during staging")
            require(not mandatory, "required current input is missing")
        except OSError as exc:
            # Native CreateFile maps Win32 missing-file/path codes rather than
            # Python's errno; permission, sharing and I/O errors are never absence.
            if not opened and os.name == "nt" and exc.errno in {2, 3} and not mandatory:
                pass
            else:
                raise
        entry["completed_at"] = utc_now()
        self.entries.append(entry)
        self.by_key[key] = entry
        return entry

    def revalidate(self):
        started = utc_now()
        for entry in self.entries:
            self.budget.charge()
            root, path = self.sources.roots[entry["root"]], entry["path"]
            if not entry["present"]:
                try:
                    with open_current(root, path):
                        require(False, "previously missing lineage appeared")
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    if os.name == "nt" and exc.errno in {2, 3}:
                        continue
                    raise
            else:
                with open_current(root, path) as (handle, current):
                    require(current == entry["generation"], "current-input generation drift")
                    require(_hash_handle(handle, current["size"], self.budget) == entry["staged"]["sha256"],
                            "current-input byte drift")
        return {"started_at": started, "completed_at": utc_now(), "read_bytes": self.budget.observed_bytes}

    def seal(self, name="inputs.json"):
        require(self.entries, "empty input generation")
        validation = self.revalidate()
        pages = []
        for start in range(0, len(self.entries), 128):
            pages.append(publish(self.root, f"inputs-{start // 128:04d}.json", {
                "schema": "qualification_input_entries_v2", "entries": self.entries[start:start + 128]}))
        return publish(self.root, name, {"schema": "qualification_inputs_v2", "pages": pages,
            "file_count": len(self.entries), "staged_bytes": self.total_bytes, "validation": validation})


def _input_object(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "duplicate input JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        require(False, "nonfinite input number")

    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("malformed current JSON input") from exc
    require(type(result) is dict, "current ledger record must be an object")
    stack = [(result, 0)]
    while stack:
        value, depth = stack.pop()
        require(depth <= 32, "input object depth exceeded")
        if isinstance(value, float):
            require(math.isfinite(value), "nonfinite input number")
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)
    return result


class _VerifiedInput(io.RawIOBase):
    def __init__(self, handle, ref, budget):
        self.handle, self.ref, self.budget = handle, ref, budget
        self.hasher, self.count = hashlib.sha256(), 0

    def readable(self):
        return True

    def readinto(self, destination):
        self.budget.charge()
        count = self.handle.readinto(destination)
        self.count += count
        self.budget.charge(count)
        require(self.count <= self.ref["size"], "sealed input grew")
        self.hasher.update(memoryview(destination)[:count])
        return count


@contextmanager
def verified_input(root, ref, budget):
    fields(ref, {"path", "sha256", "size"})
    digest(ref["sha256"])
    integer(ref["size"], maximum=MAX_FILE_BYTES)
    # The sequential reader authenticates every consumed byte against the
    # independently pinned digest. Avoid two invisible full POSIX hash passes:
    # all source/staged reads must be charged to this attempt's read budget.
    with open_record(root, ref["path"], maximum=ref["size"], _check_posix_bytes=False) as handle:
        measured = _VerifiedInput(handle, ref, budget)
        buffered = io.BufferedReader(measured, 65536)
        try:
            yield buffered
            require(measured.count == ref["size"] and measured.hasher.hexdigest() == ref["sha256"],
                    "sealed input bytes differ or were not fully consumed")
        finally:
            buffered.close()


def ledger_rows(root, ref, budget):
    """Strict streaming precheck; blank lines retain their established meaning."""
    with verified_input(root, ref, budget) as handle:
        while line := handle.readline(MAX_LINE_BYTES + 1):
            require(len(line) <= MAX_LINE_BYTES and line.endswith(b"\n"), "incomplete or oversized ledger record")
            if line.strip():
                yield _input_object(line.decode("utf-8"))


def label_rows(root, ref, budget):
    with verified_input(root, ref, budget) as handle:
        old_limit = csv.field_size_limit(MAX_LINE_BYTES)
        stream = None
        try:
            stream = io.TextIOWrapper(handle, encoding="utf-8", newline="")
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            require(header and len(header) <= 2048 and all(header) and len(set(header)) == len(header),
                    "missing or duplicate labels CSV header")
            for row in reader:
                if not row:
                    continue
                require(len(row) == len(header), "malformed labels CSV row")
                yield dict(zip(header, row, strict=True))
        finally:
            if stream is not None:
                stream.detach()
            csv.field_size_limit(old_limit)
