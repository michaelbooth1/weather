"""Bounded local byte-preserving staging; no transport or cleanup authority.

The measured selection is metadata, not a hash inventory or closure proof.
Every staged member receives its first content hash under a native read pin.
The caller owns the host lease and Job deadline; admission is mandatory.
"""
from __future__ import annotations

from contextlib import ExitStack
import ctypes
import gzip
import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import time
from typing import Callable, Mapping

from weather.operations.ntfs_file_compression import (
    LockedNtfsFile, PinnedNtfsDirectory, _FileInformation,
    _StandardInformation, _ticks, FILETIME_EPOCH, COMPRESSED,
)
from weather.schema_registry import schema_version

MIB = 1024**2
MAX_CHUNK_BYTES = 1024 * MIB
MAX_MEMBERS = 256
MAX_METADATA_BYTES = 16 * MIB
MAX_FILES = 10000
FORMAT = "production_sorted_ustar_gzip_level1_v1"
LEGACY_GROUPING = "sorted_whole_files_v1"
SELECTIVE_GROUPING = "market_day_file_family_v1"
MARKET_DAY_GROUPING = "market_day_v1"
PARTITIONED_GROUPING = "whole_files_with_isolated_events_v1"
CHUNK_GROUPINGS = (LEGACY_GROUPING, SELECTIVE_GROUPING, MARKET_DAY_GROUPING, PARTITIONED_GROUPING)
RETENTION = {"source_retained": True, "cleanup_eligible": False,
             "deletion_authorized": False, "upload_performed": False,
             "restore_performed": False, "consumer_closure_proved": False}


class ArchiveStageError(ValueError):
    """Fail closed without removing or overwriting any retained object."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _seal(value, field):
    value[field] = hashlib.sha256(_canonical(value)).hexdigest()
    return value


def _check_seal(value, field):
    unsigned = dict(value)
    expected = unsigned.pop(field, None)
    if expected != hashlib.sha256(_canonical(unsigned)).hexdigest():
        raise ArchiveStageError("evidence self-hash mismatch")


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ArchiveStageError("duplicate JSON key")
        result[key] = value
    return result


def _require_sha256(value):
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ArchiveStageError("explicit lowercase SHA-256 binding required")


def _load(path, expected_sha256=None):
    path = Path(path)
    _safe_path(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_METADATA_BYTES + 1)
    if len(raw) > MAX_METADATA_BYTES:
        raise ArchiveStageError("metadata byte limit")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ArchiveStageError("raw evidence SHA-256 mismatch")
    value = json.loads(raw, object_pairs_hook=_pairs)
    if not isinstance(value, dict):
        raise ArchiveStageError("metadata must be an object")
    return value, digest


def _write(path, value):
    path = Path(path)
    _safe_path(path.parent, directory=True)
    raw = _canonical(value) + b"\n"
    if len(raw) > MAX_METADATA_BYTES:
        raise ArchiveStageError("metadata byte limit")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    reread, digest = _load(path)
    if reread != value or digest != hashlib.sha256(raw).hexdigest():
        raise ArchiveStageError("evidence readback mismatch")


def _integer(value, label, *, maximum=None):
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArchiveStageError(f"invalid {label}")
    if maximum is not None and value > maximum:
        raise ArchiveStageError(f"{label} exceeds bound")
    return value


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ArchiveStageError("noncanonical source path")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ArchiveStageError("control characters are forbidden in source paths")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {".", "..", ""} or part.endswith((".", " ")) for part in value.split("/")
    ):
        raise ArchiveStageError("unsafe source path")
    # USTAR must represent the exact name without an implicit PAX extension.
    try:
        tarfile.TarInfo(value).tobuf(format=tarfile.USTAR_FORMAT, encoding="utf-8")
    except (ValueError, UnicodeError) as exc:
        raise ArchiveStageError("source name cannot fit USTAR") from exc
    return value


def _safe_path(path, *, directory=False):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ArchiveStageError("absolute non-traversing path required")
    for component in reversed((path, *path.parents)):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ArchiveStageError("links and reparse points are forbidden")
    if directory and not path.is_dir():
        raise ArchiveStageError("existing directory required")
    if not directory and not path.is_file():
        raise ArchiveStageError("regular file required")
    return path


def _rows(files):
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        raise ArchiveStageError("invalid selection cardinality")
    result, seen = [], set()
    for item in files:
        if not isinstance(item, dict):
            raise ArchiveStageError("invalid file record")
        path = _relative(item.get("path"))
        if path.casefold() in seen:
            raise ArchiveStageError("duplicate or case-colliding path")
        seen.add(path.casefold())
        row = {"path": path}
        for key in ("size_bytes", "mtime_ns", "device", "file_id", "allocated_bytes"):
            row[key] = _integer(item.get(key), key,
                                maximum=MAX_CHUNK_BYTES if key == "size_bytes" else None)
        result.append(row)
    return sorted(result, key=lambda row: row["path"])


def _isolated_events(values, grouping):
    if (not isinstance(values, (list, tuple)) or len(values) > MAX_MEMBERS
            or any(not isinstance(v, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,159}", v)
                   for v in values) or list(values) != sorted(set(values))
            or (values and grouping != PARTITIONED_GROUPING)):
        raise ArchiveStageError("invalid isolated event grouping")
    return tuple(values)


def _chunks(rows, limit, grouping=LEGACY_GROUPING, isolated_events=()):
    if grouping not in CHUNK_GROUPINGS:
        raise ArchiveStageError("unknown chunk grouping")
    isolated_events = _isolated_events(isolated_events, grouping)
    chunks, members, total, previous_group = [], [], 0, None
    for row in rows:
        # Preserve each original representation. CSV and gzip halves share a
        # retrieval group but remain distinct, independently verified members.
        path = PurePosixPath(_relative(row["path"]))
        group = (str(path.parent), path.name.removesuffix(".gz"))
        if grouping == MARKET_DAY_GROUPING:
            group = (str(path.parent),)
        if grouping != LEGACY_GROUPING and (len(path.parts) != 3 or path.parts[0] != "snapshots"):
            raise ArchiveStageError("selective grouping requires snapshots/event/file")
        if grouping == PARTITIONED_GROUPING:
            group = path.parts[1] if path.parts[1] in isolated_events else None
        if row["size_bytes"] > limit:
            raise ArchiveStageError("whole source file exceeds chunk limit")
        if members and (total + row["size_bytes"] > limit or len(members) >= MAX_MEMBERS
                        or (grouping != LEGACY_GROUPING and group != previous_group)):
            chunks.append({"chunk_id": f"chunk-{len(chunks):05d}",
                           "files": members, "logical_bytes": total})
            members, total = [], 0
        members.append(row)
        total += row["size_bytes"]
        previous_group = group
    if members:
        chunks.append({"chunk_id": f"chunk-{len(chunks):05d}",
                       "files": members, "logical_bytes": total})
    return chunks


def plan_selection(selection_path, expected_selection_sha256, output_path, *,
                   chunk_bytes=MAX_CHUNK_BYTES, chunk_grouping=LEGACY_GROUPING, isolated_events=()):
    """Plan from pinned measured metadata; never open source tape contents."""
    _require_sha256(expected_selection_sha256)
    selection, digest = _load(selection_path, expected_selection_sha256)
    if (selection.get("schema_version") != schema_version("large_archive_candidate_selection")
            or selection.get("status") != "MEASURED_CANDIDATE_NOT_DELETE_AUTHORITY"):
        raise ArchiveStageError("unsupported measured selection")
    root = selection.get("source_root")
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ArchiveStageError("absolute selection source root required")
    limit = _integer(chunk_bytes, "chunk_bytes", maximum=MAX_CHUNK_BYTES)
    if not limit:
        raise ArchiveStageError("positive chunk bound required")
    isolated_events = _isolated_events(isolated_events, chunk_grouping)
    rows = _rows(selection.get("files"))
    for key, actual in (("file_count", len(rows)),
                        ("logical_bytes", sum(r["size_bytes"] for r in rows)),
                        ("allocated_bytes", sum(r["allocated_bytes"] for r in rows))):
        if _integer(selection.get(key), key) != actual:
            raise ArchiveStageError("selection totals do not reconcile")
    plan = _seal({"schema_version": schema_version("production_cold_archive_plan"),
                  "source_root": root, "selection_sha256": digest,
                  "format": FORMAT, "chunk_bytes": limit,
                  "file_count": len(rows), "chunks": _chunks(rows, limit, chunk_grouping, isolated_events),
                  **({"isolated_events": list(isolated_events)} if chunk_grouping == PARTITIONED_GROUPING else {}),
                  **({"chunk_grouping": chunk_grouping} if chunk_grouping != LEGACY_GROUPING else {}),
                  "source_content_hashes_proved": False, **RETENTION}, "plan_hash")
    _write(output_path, plan)
    return plan


class _ArchiveSource(LockedNtfsFile):
    """Read-only native pin with its own archive bound; no compression IOCTL."""

    def __init__(self, path):
        super().__init__(path, writable=False)

    def metadata(self):
        info, standard = _FileInformation(), _StandardInformation()
        self._check(self._kernel.GetFileInformationByHandle(self.handle, ctypes.byref(info)))
        self._check(self._kernel.GetFileInformationByHandleEx(
            self.handle, 1, ctypes.byref(standard), ctypes.sizeof(standard)))
        size = (int(info.size_high) << 32) | int(info.size_low)
        if (info.attributes & ~(0x20 | 0x80 | COMPRESSED)
                or info.links != 1 or standard.links != 1 or standard.delete_pending
                or standard.directory or not 0 <= size <= MAX_CHUNK_BYTES):
            raise ArchiveStageError("unsupported native archive source")
        return {"size_bytes": size, "allocated_bytes": int(standard.allocation),
                "device": int(info.volume),
                "file_id": (int(info.index_high) << 32) | int(info.index_low),
                "mtime_ns": (_ticks(info.written) - FILETIME_EPOCH) * 100}


def _source_pin(path):
    return _ArchiveSource(path)


def _directory_pin(path):
    return PinnedNtfsDirectory(path)


class _Guard:
    MAX_RATE = 16 * MIB

    def __init__(self, admission, deadline, rate):
        if not callable(admission) or not math.isfinite(deadline):
            raise ArchiveStageError("admission callback and finite deadline required")
        if not isinstance(rate, int) or isinstance(rate, bool) or not 0 < rate <= self.MAX_RATE:
            raise ArchiveStageError("rate exceeds this host profile")
        self.admission, self.deadline, self.rate = admission, deadline, rate
        self.start, self.bytes = time.monotonic(), 0
        self.admit()

    def check(self):
        if time.monotonic() >= self.deadline:
            raise ArchiveStageError("archive deadline reached")

    def admit(self):
        self.check()
        if self.admission() is not True:
            raise ArchiveStageError("host admission refused")
        self.check()

    def account(self, count):
        self.bytes += count
        while True:
            self.check()
            delay = self.bytes / self.rate - (time.monotonic() - self.start)
            if delay <= 0:
                return
            time.sleep(min(delay, 0.1, max(0, self.deadline - time.monotonic())))


class _Reader:
    def __init__(self, stream, guard):
        self.stream, self.guard = stream, guard
        self.digest, self.bytes = hashlib.sha256(), 0

    def read(self, size=-1):
        self.guard.admit()
        block = self.stream.read(min(MIB, size) if size >= 0 else MIB)
        self.digest.update(block)
        self.bytes += len(block)
        self.guard.account(len(block))
        return block


class _Writer:
    def __init__(self, stream, guard, bound, root, reserve):
        self.stream, self.guard, self.bound = stream, guard, bound
        self.root, self.reserve, self.bytes = root, reserve, 0
        self.digest = hashlib.sha256()

    def write(self, data):
        self.guard.admit()
        if self.bytes + len(data) > self.bound:
            raise ArchiveStageError("archive output exceeds worst-case cap")
        if shutil.disk_usage(self.root).free < self.reserve + len(data):
            raise ArchiveStageError("disk reserve would be breached")
        count = self.stream.write(data)
        if count != len(data):
            raise ArchiveStageError("short archive write")
        self.bytes += count
        self.digest.update(data)
        return count

    def flush(self):
        self.stream.flush()


def _hash(path, guard):
    maximum = MAX_CHUNK_BYTES + MAX_CHUNK_BYTES // 100 + 2 * MIB
    with Path(path).open("rb") as stream:
        reader = _Reader(stream, guard)
        while reader.read(MIB):
            if reader.bytes > maximum:
                raise ArchiveStageError("archive object exceeds streaming byte bound")
    return reader.bytes, reader.digest.hexdigest()


def verify_archive(archive_path, manifest, *, admission, deadline_monotonic,
                   guard_factory=None):
    """Stream exact ordered member/size/hash parity; never extract files."""
    guard = (_Guard(admission, deadline_monotonic, 16 * MIB) if guard_factory is None
             else guard_factory(admission, deadline_monotonic))
    _check_seal(manifest, "manifest_hash")
    if (manifest.get("schema_version") != schema_version("production_cold_archive_manifest")
            or manifest.get("format") != FORMAT):
        raise ArchiveStageError("unsupported archive manifest")
    files = manifest.get("files")
    canonical = _rows(files)
    if canonical != [{k: row[k] for k in canonical[0]} for row in files]:
        raise ArchiveStageError("member inventory must be canonical and ordered")
    if len(files) > MAX_MEMBERS or sum(r["size_bytes"] for r in files) > MAX_CHUNK_BYTES:
        raise ArchiveStageError("archive bounds exceeded")
    path = _safe_path(archive_path)
    maximum = sum(r["size_bytes"] for r in files)
    maximum += maximum // 100 + 2 * MIB
    if path.stat().st_size > maximum:
        raise ArchiveStageError("archive object exceeds byte bound")
    count, digest = _hash(path, guard)
    if count != manifest["archive_bytes"] or digest != manifest["archive_sha256"]:
        raise ArchiveStageError("archive object hash or size mismatch")
    seen, tar_bytes = 0, 0
    with path.open("rb") as raw:
        with gzip.GzipFile(fileobj=_Reader(raw, guard), mode="rb") as decoded:
            reader = _Reader(decoded, guard)
            for expected in files:
                info = tarfile.TarInfo(expected["path"])
                info.size, info.mode, info.mtime = expected["size_bytes"], 0o600, 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                header = info.tobuf(format=tarfile.USTAR_FORMAT, encoding="utf-8")
                if reader.read(512) != header:
                    raise ArchiveStageError("archive member mismatch")
                remaining, member_digest = expected["size_bytes"], hashlib.sha256()
                while remaining:
                    block = reader.read(min(MIB, remaining))
                    if not block:
                        raise ArchiveStageError("archive member truncated")
                    remaining -= len(block)
                    member_digest.update(block)
                if member_digest.hexdigest() != expected.get("sha256"):
                    raise ArchiveStageError("archive member content mismatch")
                padding = (-expected["size_bytes"]) % 512
                if reader.read(padding) != b"\0" * padding:
                    raise ArchiveStageError("archive member padding mismatch")
                tar_bytes += 512 + expected["size_bytes"] + padding
                seen += 1
            footer_size = ((tar_bytes + 1024 + 10239) // 10240) * 10240 - tar_bytes
            if reader.read(footer_size) != b"\0" * footer_size or reader.read(1):
                raise ArchiveStageError("archive footer or trailing payload mismatch")
    if seen != len(files):
        raise ArchiveStageError("archive member missing")
    guard.admit()
    return {"status": "PASS", "file_count": seen, "archive_sha256": digest}


def stage_chunk(plan_path, expected_plan_sha256, chunk_id, attempt_root, *,
                source_root, admission: Callable[[], bool], deadline_monotonic,
                free_space_reserve_bytes, rate_bytes_per_second=16 * MIB):
    """Claim one fresh attempt and stage one chunk; retain every failure partial."""
    guard = _Guard(admission, deadline_monotonic, rate_bytes_per_second)
    reserve = _integer(free_space_reserve_bytes, "free_space_reserve_bytes")
    _require_sha256(expected_plan_sha256)
    plan, plan_digest = _load(plan_path, expected_plan_sha256)
    _check_seal(plan, "plan_hash")
    if (plan.get("schema_version") != schema_version("production_cold_archive_plan")
            or plan.get("format") != FORMAT):
        raise ArchiveStageError("unsupported plan")
    root = _safe_path(source_root, directory=True)
    if os.path.normcase(str(root)) != os.path.normcase(plan["source_root"]):
        raise ArchiveStageError("production source-root mismatch")
    chunks = plan.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise ArchiveStageError("invalid chunks")
    rows = _rows([row for chunk in chunks for row in chunk["files"]])
    limit = _integer(plan["chunk_bytes"], "chunk_bytes", maximum=MAX_CHUNK_BYTES)
    grouping = plan.get("chunk_grouping", LEGACY_GROUPING)
    if (not limit or _chunks(rows, limit, grouping, plan.get("isolated_events", ())) != chunks
            or len(rows) != plan["file_count"]):
        raise ArchiveStageError("plan chunk inventory mismatch")
    matches = [chunk for chunk in chunks if chunk["chunk_id"] == chunk_id]
    if len(matches) != 1:
        raise ArchiveStageError("unknown chunk")
    chunk = matches[0]
    attempt = Path(attempt_root)
    parent = _safe_path(attempt.parent, directory=True)
    if (not attempt.is_absolute() or ".." in attempt.parts
            or attempt == root or root in attempt.parents or attempt in root.parents):
        raise ArchiveStageError("attempt and production source must be disjoint")
    bound = chunk["logical_bytes"] + chunk["logical_bytes"] // 100 + 2 * MIB
    if shutil.disk_usage(parent).free < reserve + bound:
        raise ArchiveStageError("insufficient disk for bounded staging and reserve")
    with ExitStack() as stack:
        stack.enter_context(_directory_pin(parent))
        attempt.mkdir()  # Existing namespaces, including failed attempts, are spent.
        stack.enter_context(_directory_pin(attempt))
        receipt = {"schema_version": schema_version("production_cold_archive_receipt"),
                   "plan_sha256": plan_digest, "plan_hash": plan["plan_hash"],
                   "chunk_id": chunk_id, "attempt_root": str(attempt), **RETENTION}
        _write(attempt / "claim.json", _seal(dict(receipt), "receipt_hash"))
        try:
            records = []
            for row in chunk["files"]:
                guard.admit()
                path = _safe_path(root / row["path"])
                with _source_pin(path) as pin:
                    if pin.metadata() != {key: value for key, value in row.items() if key != "path"}:
                        raise ArchiveStageError("source metadata differs before staging: " + row["path"])
            archive_path = attempt / "archive.tar.gz"
            with archive_path.open("xb") as raw:
                writer = _Writer(raw, guard, bound, attempt, reserve)
                with gzip.GzipFile(filename="", fileobj=writer, mode="wb", mtime=0,
                                   compresslevel=1) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT,
                                      encoding="utf-8") as archive:
                        for row in chunk["files"]:
                            guard.admit()
                            path = _safe_path(root / row["path"])
                            expected = {key: value for key, value in row.items() if key != "path"}
                            with _source_pin(path) as pin:
                                before = pin.metadata()
                                if before != expected:
                                    raise ArchiveStageError("source metadata differs from measured selection")
                                info = tarfile.TarInfo(row["path"])
                                info.size, info.mode, info.mtime = row["size_bytes"], 0o600, 0
                                info.uid = info.gid = 0
                                info.uname = info.gname = ""
                                with path.open("rb", buffering=0) as source:
                                    reader = _Reader(source, guard)
                                    archive.addfile(info, reader)
                                    if reader.bytes != row["size_bytes"] or source.read(1):
                                        raise ArchiveStageError("source length drift")
                                if pin.metadata() != before:
                                    raise ArchiveStageError("source identity drift during archive read")
                                records.append({**row, "sha256": reader.digest.hexdigest()})
                raw.flush()
                os.fsync(raw.fileno())
            count, digest = writer.bytes, writer.digest.hexdigest()
            manifest = _seal({"schema_version": schema_version("production_cold_archive_manifest"),
                              "format": FORMAT, "plan_hash": plan["plan_hash"],
                              "plan_sha256": plan_digest, "chunk_id": chunk_id,
                              "source_root": str(root), "files": records,
                              "archive_bytes": count, "archive_sha256": digest,
                              "source_proof": "native_pinned_bytes_during_staging",
                              **RETENTION}, "manifest_hash")
            verification = verify_archive(archive_path, manifest, admission=admission,
                                          deadline_monotonic=deadline_monotonic)
            guard.admit()
            _write(attempt / "manifest.json", manifest)
            receipt.update(status="PASS", manifest_hash=manifest["manifest_hash"],
                           verification=verification)
        except BaseException as exc:
            receipt.update(status="FAIL_CLOSED", error_type=type(exc).__name__,
                           error_message=str(exc)[:1024])
            _write(attempt / "receipt.json", _seal(receipt, "receipt_hash"))
            raise
        _write(attempt / "receipt.json", _seal(receipt, "receipt_hash"))
        return receipt
