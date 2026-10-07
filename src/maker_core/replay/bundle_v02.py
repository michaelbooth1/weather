"""Streaming reader for bundle formats v0.3 and v0.2 (and sorted v0.1): hash first, then parse one record at a time.

Maker replay v2 registration draft §6. v0.2 extends v0.1 without changing it; ``bundle.load_bundle``
still owns in-memory v0.1 admission and is not edited. v0.3 is v0.2 with every stream stored as one
deterministic gzip member (owner decision 8): streams are named ``<kind>.jsonl.gz``, each manifest stream
entry binds the stored ``sha256``/``bytes`` AND the ``decoded_sha256``/``decoded_bytes``/``records``, and
``bundle.json`` carries a ``compression`` object. One format string, one shape: v0.2 streams are always
plain ``.jsonl``, v0.3 streams are always gzip. Here:

- Pass one hashes every stream's stored bytes in bounded chunks and, for v0.3, inflates them beneath that
  hash (``v2.gzip_stream``), checking decoded size, decoded SHA-256, record count and the trailing newline.
  Decoding stops as soon as it would exceed the declared decoded size (bomb cap); every zlib failure, a
  truncated or multi-member stream and a non-canonical header are ``BundleError``. Nothing is admitted on
  a mismatch.
- Pass two (``records()``) parses one line at a time, re-hashes stored and decoded bytes as it goes and
  merges the streams in ``(captured_at, sequence)`` order. Each stream must already be strictly in that
  order. A stream that changed between the passes raises at its end; a consumer must then discard
  everything it read.
- Limits are ``v2.limits`` (bytes AND time): pass one and every ``records()`` call get their own pass
  clock, so a re-read never inherits the first open's time; an optional ``RunBudget`` bounds the whole
  run's deadline and stored input across bundles. A frozen ``bundle.Limits`` is still accepted.
- v0.2 coverage records name a manifest ``coverage_groups`` entry instead of a condition; a
  condition's coverage is its group's latest record. ``maker_core.replay.v2.compaction`` owns the
  expansion back to per-condition v0.1 rows.

Hashes bind bytes, not their truth or author. No source path in a record is opened.
"""
from __future__ import annotations

from collections.abc import Mapping
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
from maker_core.replay.v2 import gzip_stream
from maker_core.replay.v2.limits import PassReader, RunBudget, V2Limits, coerce

FORMAT_V02 = "maker_core.replay.bundle.v0.2"
FORMAT_V03 = "maker_core.replay.bundle.v0.3"
FORMATS = (FORMAT_V01, FORMAT_V02, FORMAT_V03)
GROUPED_FORMATS = (FORMAT_V02, FORMAT_V03)
PLAIN = "identity"
MAX_GROUPS = MAX_CONDITIONS
# Global sequence uniqueness is a bitmap, so a sequence is bounded: at most 256 MiB of bitmap.
MAX_SEQUENCE = 2**31 - 1
CHUNK_BYTES = 1024**2
_V01_FIELDS = "sequence captured_at condition_id kind payload payload_sha256 source_hashes"
_GROUP_FIELDS = "sequence captured_at group_id kind payload payload_sha256 source_hashes"
_STREAM_FIELDS = {FORMAT_V01: "path sha256 bytes records", FORMAT_V02: "path sha256 bytes records",
                  FORMAT_V03: "path sha256 bytes decoded_sha256 decoded_bytes records"}
_STREAM_NAMES = {FORMAT_V01: r"[a-zA-Z0-9_-]+\.jsonl", FORMAT_V02: r"[a-zA-Z0-9_-]+\.jsonl",
                 FORMAT_V03: r"[a-zA-Z0-9_-]+\.jsonl\.gz"}


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
    sha256: str  # stored bytes: transport integrity (not portable across zlib builds for gzip)
    bytes: int  # stored bytes
    records: int
    identity: tuple  # (inode, size, mtime_ns) observed in pass one
    encoding: str = PLAIN  # "identity" (v0.1/v0.2) or "gzip" (v0.3)
    decoded_sha256: str | None = None  # the cross-host identity; equals ``sha256`` for plain streams
    decoded_bytes: int | None = None


@dataclass(frozen=True)
class StreamBundle:
    format: str
    day: date
    sealed_at: datetime
    provenance: str
    conditions: tuple[Condition, ...]
    coverage_groups: tuple[CoverageGroup, ...]
    streams: tuple[StreamRef, ...]
    input_hashes: object  # file name -> stored SHA-256 (bundle.json included)
    input_bytes: int  # stored bytes read in pass one (bundle.json included)
    root: Path
    _limits: V2Limits = field(repr=False, compare=False)
    _clock: object = field(repr=False, compare=False)
    _run: RunBudget | None = field(repr=False, compare=False)
    decoded_hashes: Mapping | None = field(default=None, compare=False)  # stream name -> decoded SHA-256
    compression: Mapping | None = field(default=None, compare=False)  # the v0.3 manifest's ``compression``

    def pass_reader(self) -> PassReader:
        """A fresh pass clock (and the run's deadline, when the bundle was opened under a ``RunBudget``)."""
        return PassReader(self._limits, self._clock, self._run)

    def records(self) -> Iterator[CapturedRecord | GroupRecord]:
        """Pass two: every stream merged in ``(captured_at, sequence)`` order, one record at a time.

        Each call is its own pass with its own clock (B-def D1); the run budget, if any, still binds.
        """
        reader = self.pass_reader()
        seen = bytearray()
        conditions = {c.condition_id for c in self.conditions}
        groups = {g.group_id for g in self.coverage_groups}
        streams = [_stream(self, ref, conditions, groups, seen, reader) for ref in self.streams]
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


def _stored_chunks(reader, handle, size, mismatch):
    """Stored bytes in bounded chunks, never more than ``size``; the caller hashes them."""
    read = 0
    while chunk := handle.read(CHUNK_BYTES):
        reader.check()
        read += len(chunk)
        if read > size:
            raise BundleError(mismatch)
        yield chunk
    if read != size:
        raise BundleError(mismatch)


def _tee(chunks, digest):
    """Hash the stored bytes beneath the decompressor."""
    for chunk in chunks:
        digest.update(chunk)
        yield chunk


def _decoded(reader, encoding, chunks, decoded_limit):
    if encoding == gzip_stream.CODEC:
        return gzip_stream.decode(chunks, decoded_limit, check=reader.check)
    return chunks


def _hash_stream(reader, path, size, encoding=PLAIN, decoded_size=None):
    """Pass one: stored SHA-256, decoded SHA-256, decoded size, newline count and file identity, bounded."""
    path = regular_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise BundleError("input_not_regular_file")
    if before.st_size != size:
        raise BundleError("input_byte_cap_or_size_mismatch")
    reader.charge(size)
    decoded_size = size if decoded_size is None else decoded_size
    stored, decoded = hashlib.sha256(), hashlib.sha256()
    lines, total, last = 0, 0, b""
    with path.open("rb") as handle:
        chunks = _tee(_stored_chunks(reader, handle, size, "input_changed_during_read"), stored)
        for block in _decoded(reader, encoding, chunks, decoded_size):
            decoded.update(block)
            total += len(block)
            lines += block.count(b"\n")
            last = block[-1:]
    after = path.stat()
    identity = (before.st_ino, before.st_size, before.st_mtime_ns)
    if identity != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise BundleError("input_changed_during_read")
    if total != decoded_size:
        raise BundleError("stream_decoded_size_mismatch")
    if total and last != b"\n":
        raise BundleError("record_too_large_or_unterminated")
    return stored.hexdigest(), decoded.hexdigest(), lines, identity


def _compression(value):
    """The v0.3 manifest's ``compression``: gzip, a fixed level and MTIME 0; the zlib version is a record."""
    _keys(value, "codec level mtime zlib_runtime_version")
    if (value["codec"] != gzip_stream.CODEC or type(value["level"]) is not int or not 1 <= value["level"] <= 9
            or type(value["mtime"]) is not int or value["mtime"] != gzip_stream.MTIME):
        raise BundleError("unsupported_compression")
    _identity(value["zlib_runtime_version"])
    return _freeze(value)


def open_stream_bundle(directory: Path, *, limits: Limits | V2Limits | None = None, clock=time.monotonic,
                       run: RunBudget | None = None) -> StreamBundle:
    """Pass one: verify the manifest and every stream's bytes before any record is parsed.

    The seal must be after the UTC day's end. This checks the export's assertion, not producer
    authenticity or the workstation wall clock. ``limits`` bound this bundle (a frozen ``Limits`` keeps
    its meaning, see ``v2.limits.coerce``); ``run``, if given, is shared by every bundle of one run.
    """
    v2_limits = coerce(limits)
    reader = PassReader(v2_limits, clock, run)
    root = regular_path(directory)
    manifest_bytes = reader.read(root / "bundle.json", MAX_MANIFEST_BYTES)
    manifest = _json(manifest_bytes)
    if not isinstance(manifest, dict) or manifest.get("format") not in FORMATS:
        raise BundleError("unsupported_bundle_format")
    form = manifest["format"]
    v02, gz = form in GROUPED_FORMATS, form == FORMAT_V03
    _keys(manifest, "format day sealed_at provenance conditions streams" + (" coverage_groups" if v02 else "")
          + (" compression" if gz else ""))
    compression = _compression(manifest["compression"]) if gz else None
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
    hashes, decoded_hashes, refs, records = {"bundle.json": sha256(manifest_bytes)}, {}, [], 0
    for stream in streams:
        reader.check()
        _keys(stream, _STREAM_FIELDS[form])
        name = stream["path"]
        if (not isinstance(name, str) or re.fullmatch(_STREAM_NAMES[form], name) is None
                or name.casefold() in {p.casefold() for p in hashes}):
            raise BundleError("invalid_or_duplicate_stream_path")
        size = _integer(stream["bytes"], v2_limits.max_bundle_stored_bytes)
        count = _integer(stream["records"], v2_limits.max_bundle_records)
        records += count
        if records > v2_limits.max_bundle_records:
            raise BundleError("record_count_cap")
        expected = _hash(stream["sha256"])
        if gz:
            decoded_size = _integer(stream["decoded_bytes"], v2_limits.max_bundle_decoded_bytes)
            decoded_expected = _hash(stream["decoded_sha256"])
            if decoded_size > count * MAX_LINE_BYTES:
                raise BundleError("stream_decoded_size_unbounded")
        else:
            decoded_size, decoded_expected = size, expected
        reader.admit_decoded(decoded_size)
        encoding = gzip_stream.CODEC if gz else PLAIN
        digest, decoded, lines, identity = _hash_stream(reader, root / name, size, encoding, decoded_size)
        if digest != expected or decoded != decoded_expected:
            raise BundleError("stream_hash_or_size_mismatch")
        if lines != count:
            raise BundleError("stream_record_count_mismatch")
        hashes[name] = expected
        decoded_hashes[name] = decoded_expected
        refs.append(StreamRef(name, expected, size, count, identity, encoding, decoded_expected, decoded_size))
    reader.check()
    return StreamBundle(form, day, sealed_at, manifest["provenance"], conditions, groups, tuple(refs),
                        _freeze(hashes), reader.bytes_read, root, v2_limits, clock, run,
                        _freeze(decoded_hashes), compression)


def _record(value, bundle, start, conditions, groups):
    grouped = bundle.format in GROUPED_FORMATS and isinstance(value, dict) and value.get("kind") == "coverage"
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


def _stream(bundle, ref, conditions, groups, seen, reader=None):
    """Pass two for one stream: parse, check order and uniqueness, re-hash stored and decoded bytes, and
    verify at the end. ``reader`` is the pass's ``PassReader`` (a fresh pass clock when omitted)."""
    reader = reader or bundle.pass_reader()
    start = datetime.combine(bundle.day, datetime.min.time(), tzinfo=timezone.utc)
    path = regular_path(bundle.root / ref.name)
    decoded_size = ref.bytes if ref.decoded_bytes is None else ref.decoded_bytes
    decoded_sha = ref.sha256 if ref.decoded_sha256 is None else ref.decoded_sha256
    stored, digest, count, size, last = hashlib.sha256(), hashlib.sha256(), 0, 0, None
    with path.open("rb") as handle:
        info = path.stat()
        if (info.st_ino, info.st_size, info.st_mtime_ns) != ref.identity:
            raise BundleError("input_changed_between_passes")
        chunks = _tee(_stored_chunks(reader, handle, ref.bytes, "input_changed_between_passes"), stored)
        for line in gzip_stream.lines(_decoded(reader, ref.encoding, chunks, decoded_size), MAX_LINE_BYTES):
            reader.check()
            digest.update(line)
            size += len(line)
            count += 1
            if size > decoded_size or count > ref.records:
                raise BundleError("input_changed_between_passes")
            record = _record(_json(line), bundle, start, conditions, groups)
            key = _order(record)
            if last is not None and key <= last:
                raise BundleError("unsorted_stream")
            last = key
            _mark(seen, record.sequence)
            yield record
    info = path.stat()
    if ((info.st_ino, info.st_size, info.st_mtime_ns) != ref.identity or stored.hexdigest() != ref.sha256
            or digest.hexdigest() != decoded_sha or size != decoded_size or count != ref.records):
        raise BundleError("input_changed_between_passes")


def read_format(directory: Path) -> str:
    """The manifest's declared format, read under the manifest cap only."""
    value = _json(_Reader(Limits(), time.monotonic).read(regular_path(directory) / "bundle.json",
                                                          MAX_MANIFEST_BYTES))
    if not isinstance(value, dict) or value.get("format") not in FORMATS:
        raise BundleError("unsupported_bundle_format")
    return value["format"]


def load_any(directory: Path, *, limits: Limits | V2Limits | None = None, clock=time.monotonic,
             run: RunBudget | None = None):
    """Admit every format: v0.1 through the frozen in-memory reader, v0.2/v0.3 through the stream reader.

    A ``V2Limits`` given for a v0.1 bundle becomes the frozen ``Limits`` it implies; a run budget is
    checked, then charged with the v0.1 bundle's bytes after the frozen load.
    """
    if read_format(directory) == FORMAT_V01:
        frozen = limits.frozen() if isinstance(limits, V2Limits) else limits
        if run is not None:
            run.check()
        bundle = load_bundle(directory, limits=frozen, clock=clock)
        if run is not None:
            run.charge(bundle.input_bytes)
            run.check()
        return bundle
    return open_stream_bundle(directory, limits=limits, clock=clock, run=run)
