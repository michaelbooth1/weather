"""Streaming reader for bundle format v0.2 (and sorted v0.1): hash first, then parse one record at a time.

Maker replay v2 registration draft §6. v0.2 extends v0.1 without changing it; ``bundle.load_bundle``
still owns in-memory v0.1 admission and is not edited. Here:

- Pass one hashes every stream's raw bytes in bounded chunks, checks size, record count and the
  trailing newline, and admits nothing on a mismatch.
- Pass two (``records()``) parses one line at a time, re-hashes as it goes and merges the streams in
  ``(captured_at, sequence)`` order. Each stream must already be strictly in that order. A stream that
  changed between the passes raises at its end; a consumer must then discard everything it read.
- v0.2 coverage records name a manifest ``coverage_groups`` entry instead of a condition; a
  condition's coverage is its group's latest record. ``maker_core.replay.v2.compaction`` owns the
  expansion back to per-condition v0.1 rows.

Hashes bind bytes, not their truth or author. No source path in a record is opened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import heapq
from pathlib import Path
import re
import stat
import time
from typing import Iterator

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import (FORMAT as FORMAT_V01, KINDS, MAX_CONDITIONS, MAX_LINE_BYTES,
                                      MAX_MANIFEST_BYTES, MAX_STREAMS, BundleError, CapturedRecord, Condition,
                                      Limits, _Reader, _freeze, _hash, _identity, _integer, _json, _keys,
                                      load_bundle, regular_path, sha256, timestamp)

FORMAT_V02 = "maker_core.replay.bundle.v0.2"
FORMATS = (FORMAT_V01, FORMAT_V02)
MAX_GROUPS = MAX_CONDITIONS
# Global sequence uniqueness is a bitmap, so a sequence is bounded: at most 256 MiB of bitmap.
MAX_SEQUENCE = 2**31 - 1
CHUNK_BYTES = 1024**2
_V01_FIELDS = "sequence captured_at condition_id kind payload payload_sha256 source_hashes"
_GROUP_FIELDS = "sequence captured_at group_id kind payload payload_sha256 source_hashes"


@dataclass(frozen=True)
class CoverageGroup:
    group_id: str
    condition_ids: tuple[str, ...]


@dataclass(frozen=True)
class GroupRecord:
    """A v0.2 coverage record: one per coverage group per capture."""
    sequence: int
    captured_at: datetime
    group_id: str
    kind: str
    payload: object
    payload_sha256: str
    source_hashes: object


@dataclass(frozen=True)
class StreamRef:
    name: str
    sha256: str
    bytes: int
    records: int
    identity: tuple  # (inode, size, mtime_ns) observed in pass one


@dataclass(frozen=True)
class StreamBundle:
    format: str
    day: date
    sealed_at: datetime
    provenance: str
    conditions: tuple[Condition, ...]
    coverage_groups: tuple[CoverageGroup, ...]
    streams: tuple[StreamRef, ...]
    input_hashes: object
    input_bytes: int
    root: Path
    _reader: _Reader = field(repr=False, compare=False)

    def records(self) -> Iterator[CapturedRecord | GroupRecord]:
        """Pass two: every stream merged in ``(captured_at, sequence)`` order, one record at a time."""
        seen = bytearray()
        conditions = {c.condition_id for c in self.conditions}
        groups = {g.group_id for g in self.coverage_groups}
        streams = [_stream(self, ref, conditions, groups, seen) for ref in self.streams]
        last = None
        for record in heapq.merge(*streams, key=_order):
            key = _order(record)
            if last is not None and key <= last:
                raise BundleError("unsorted_or_duplicate_merged_record")
            last = key
            yield record


def _order(record):
    return record.captured_at, record.sequence


def _day_bounds(manifest):
    try:
        day = date.fromisoformat(manifest["day"])
    except (TypeError, ValueError) as exc:
        raise BundleError("invalid_day") from exc
    if day.isoformat() != manifest["day"]:
        raise BundleError("noncanonical_day")
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    return day, start, start + timedelta(days=1)


def _conditions(raw, start, end, reader):
    """The v0.1 condition rules, unchanged."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CONDITIONS:
        raise BundleError("condition_count_cap")
    conditions, ids = [], set()
    for value in raw:
        reader.check()
        _keys(value, "condition_id market_id domain_id active_from active_until")
        cid = _identity(value["condition_id"])
        active_from, active_until = timestamp(value["active_from"]), timestamp(value["active_until"])
        if (cid in ids or not start <= active_from <= active_until <= end
                or active_from.second or active_from.microsecond
                or active_until.second or active_until.microsecond):
            raise BundleError("duplicate_condition_or_invalid_active_window")
        ids.add(cid)
        conditions.append(Condition(cid, _identity(value["market_id"]), _identity(value["domain_id"]),
                                    active_from, active_until))
    return tuple(sorted(conditions, key=lambda c: c.condition_id))


def _groups(raw, condition_ids, reader):
    """Unique group IDs; each group a non-empty sorted list of known conditions; a condition in one group."""
    if not isinstance(raw, list) or len(raw) > MAX_GROUPS:
        raise BundleError("coverage_group_count_cap")
    groups, ids, members = [], set(), set()
    for value in raw:
        reader.check()
        _keys(value, "group_id condition_ids")
        gid, cids = _identity(value["group_id"]), value["condition_ids"]
        if gid in ids or not isinstance(cids, list) or not cids:
            raise BundleError("duplicate_or_empty_coverage_group")
        for cid in cids:
            if not isinstance(cid, str) or cid not in condition_ids or cid in members:
                raise BundleError("unknown_or_shared_coverage_group_member")
            members.add(cid)
        if cids != sorted(cids):
            raise BundleError("noncanonical_coverage_group_order")
        ids.add(gid)
        groups.append(CoverageGroup(gid, tuple(cids)))
    return tuple(sorted(groups, key=lambda g: g.group_id))


def _hash_stream(reader, path, size):
    """Pass one: raw-byte SHA-256, newline count and file identity, in bounded chunks."""
    path = regular_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise BundleError("input_not_regular_file")
    if before.st_size != size or size > reader.limits.max_bytes - reader.bytes_read:
        raise BundleError("input_byte_cap_or_size_mismatch")
    digest, lines, read, last = hashlib.sha256(), 0, 0, b""
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            reader.check()
            read += len(chunk)
            if read > size:
                raise BundleError("input_byte_cap_or_size_mismatch")
            digest.update(chunk)
            lines += chunk.count(b"\n")
            last = chunk[-1:]
    after = path.stat()
    identity = (before.st_ino, before.st_size, before.st_mtime_ns)
    if identity != (after.st_ino, after.st_size, after.st_mtime_ns) or read != size:
        raise BundleError("input_changed_during_read")
    if size and last != b"\n":
        raise BundleError("record_too_large_or_unterminated")
    reader.bytes_read += size
    return digest.hexdigest(), lines, identity


def open_stream_bundle(directory: Path, *, limits: Limits | None = None, clock=time.monotonic) -> StreamBundle:
    """Pass one: verify the manifest and every stream's bytes before any record is parsed.

    The seal must be after the UTC day's end. This checks the export's assertion, not producer
    authenticity or the workstation wall clock.
    """
    reader = _Reader(limits or Limits(), clock)
    root = regular_path(directory)
    manifest_bytes = reader.read(root / "bundle.json", MAX_MANIFEST_BYTES)
    manifest = _json(manifest_bytes)
    if not isinstance(manifest, dict) or manifest.get("format") not in FORMATS:
        raise BundleError("unsupported_bundle_format")
    v02 = manifest["format"] == FORMAT_V02
    _keys(manifest, "format day sealed_at provenance conditions streams" + (" coverage_groups" if v02 else ""))
    day, start, end = _day_bounds(manifest)
    sealed_at = timestamp(manifest["sealed_at"])
    if sealed_at < end:
        raise BundleError("day_not_closed_at_seal")
    if manifest["provenance"] not in ("synthetic", "captured"):
        raise BundleError("invalid_provenance")
    conditions = _conditions(manifest["conditions"], start, end, reader)
    groups = _groups(manifest["coverage_groups"], {c.condition_id for c in conditions}, reader) if v02 else ()
    streams = manifest["streams"]
    if not isinstance(streams, list) or not 1 <= len(streams) <= MAX_STREAMS:
        raise BundleError("stream_count_cap")
    hashes, refs, records = {"bundle.json": sha256(manifest_bytes)}, [], 0
    for stream in streams:
        reader.check()
        _keys(stream, "path sha256 bytes records")
        name = stream["path"]
        if (not isinstance(name, str) or re.fullmatch(r"[a-zA-Z0-9_-]+\.jsonl", name) is None
                or name.casefold() in {p.casefold() for p in hashes}):
            raise BundleError("invalid_or_duplicate_stream_path")
        size = _integer(stream["bytes"], reader.limits.max_bytes)
        count = _integer(stream["records"], reader.limits.max_records)
        records += count
        if records > reader.limits.max_records:
            raise BundleError("record_count_cap")
        expected = _hash(stream["sha256"])
        digest, lines, identity = _hash_stream(reader, root / name, size)
        if digest != expected:
            raise BundleError("stream_hash_or_size_mismatch")
        if lines != count:
            raise BundleError("stream_record_count_mismatch")
        hashes[name] = expected
        refs.append(StreamRef(name, expected, size, count, identity))
    reader.check()
    return StreamBundle(manifest["format"], day, sealed_at, manifest["provenance"], conditions, groups,
                        tuple(refs), _freeze(hashes), reader.bytes_read, root, reader)


def _record(value, bundle, start, conditions, groups):
    grouped = bundle.format == FORMAT_V02 and isinstance(value, dict) and value.get("kind") == "coverage"
    _keys(value, _GROUP_FIELDS if grouped else _V01_FIELDS)
    sequence = _integer(value["sequence"], MAX_SEQUENCE)
    captured = timestamp(value["captured_at"])
    if not start <= captured < start + timedelta(days=1):
        raise BundleError("duplicate_sequence_or_capture_outside_day")
    kind = _identity(value["kind"])
    if grouped:
        owner = _identity(value["group_id"])
        if owner not in groups:
            raise BundleError("unknown_coverage_group")
    else:
        owner = _identity(value["condition_id"])
        if owner not in conditions or kind not in KINDS:
            raise BundleError("unknown_condition_or_record_kind")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise BundleError("payload_not_object")
    payload_hash = _hash(value["payload_sha256"])
    if sha256(canonical_bytes(payload)) != payload_hash:
        raise BundleError("payload_hash_mismatch")
    source_hashes = value["source_hashes"]
    if not isinstance(source_hashes, dict) or not 1 <= len(source_hashes) <= 64:
        raise BundleError("missing_or_unbounded_source_hashes")
    for source_name, source_hash in source_hashes.items():
        _identity(source_name)
        _hash(source_hash)
    kind_type = GroupRecord if grouped else CapturedRecord
    return kind_type(sequence, captured, owner, kind, _freeze(payload), payload_hash, _freeze(source_hashes))


def _mark(seen, sequence):
    index, bit = divmod(sequence, 8)
    if index >= len(seen):
        seen.extend(bytes(max(index + 1 - len(seen), len(seen))))
    if seen[index] >> bit & 1:
        raise BundleError("duplicate_sequence_or_capture_outside_day")
    seen[index] |= 1 << bit


def _stream(bundle, ref, conditions, groups, seen):
    """Pass two for one stream: parse, check order and uniqueness, re-hash, and verify at the end."""
    reader = bundle._reader
    start = datetime.combine(bundle.day, datetime.min.time(), tzinfo=timezone.utc)
    path = regular_path(bundle.root / ref.name)
    digest, count, size, last = hashlib.sha256(), 0, 0, None
    with path.open("rb") as handle:
        info = path.stat()
        if (info.st_ino, info.st_size, info.st_mtime_ns) != ref.identity:
            raise BundleError("input_changed_between_passes")
        while line := handle.readline(MAX_LINE_BYTES + 1):
            reader.check()
            if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                raise BundleError("record_too_large_or_unterminated")
            digest.update(line)
            size += len(line)
            count += 1
            if size > ref.bytes or count > ref.records:
                raise BundleError("input_changed_between_passes")
            record = _record(_json(line), bundle, start, conditions, groups)
            key = _order(record)
            if last is not None and key <= last:
                raise BundleError("unsorted_stream")
            last = key
            _mark(seen, record.sequence)
            yield record
    info = path.stat()
    if ((info.st_ino, info.st_size, info.st_mtime_ns) != ref.identity or digest.hexdigest() != ref.sha256
            or size != ref.bytes or count != ref.records):
        raise BundleError("input_changed_between_passes")


def read_format(directory: Path) -> str:
    """The manifest's declared format, read under the manifest cap only."""
    value = _json(_Reader(Limits(), time.monotonic).read(regular_path(directory) / "bundle.json",
                                                          MAX_MANIFEST_BYTES))
    if not isinstance(value, dict) or value.get("format") not in FORMATS:
        raise BundleError("unsupported_bundle_format")
    return value["format"]


def load_any(directory: Path, *, limits: Limits | None = None, clock=time.monotonic):
    """Admit both formats: v0.1 through the frozen in-memory reader, v0.2 through the stream reader."""
    if read_format(directory) == FORMAT_V01:
        return load_bundle(directory, limits=limits, clock=clock)
    return open_stream_bundle(directory, limits=limits, clock=clock)
