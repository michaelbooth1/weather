"""Bounded, hash-verified closed-day inputs for any domain plugin.

Hashes bind bytes, not their truth or author. No source path in a record is
opened. Manifest paths are flat JSONL filenames beneath the supplied directory.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import time
from types import MappingProxyType

from maker_core.contracts import utc_time
from maker_core.evidence.journal import canonical_bytes

FORMAT = "maker_core.replay.bundle.v0.1"
KINDS = frozenset({"descriptor", "book", "terms", "trade", "plugin_input",
                   "outcome_view", "info_event", "settlement"})
MAX_BYTES = 64 * 1024**2
MAX_MANIFEST_BYTES = 1024**2
MAX_LINE_BYTES = 1024**2
MAX_RECORDS = 100_000
MAX_STREAMS = 64
MAX_CONDITIONS = 2_000
MAX_SECONDS = 300.0


class BundleError(ValueError):
    """Invalid, changed, redirected or over-budget input; no partial admission."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise BundleError("timestamp_requires_utc_text")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        utc_time(result)
    except (ValueError, TypeError) as exc:
        raise BundleError("timestamp_requires_utc_text") from exc
    return result


def _hash(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise BundleError("invalid_sha256")
    return value


def _identity(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 200
            or any(ord(c) < 32 for c in value)):
        raise BundleError("invalid_identity")
    return value


def _keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required.split()):
        raise BundleError("unexpected_fields")


def _integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise BundleError("invalid_or_unbounded_integer")
    return value


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise BundleError("nonfinite_json_number")


def _json(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant)
        canonical_bytes(value)  # Also rejects overflow such as 1e999.
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BundleError("invalid_json") from exc


def regular_path(path: Path) -> Path:
    """Refuse symlinks, junctions, ADS and noncanonical paths before any IO."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part != Path(part.anchor) and ":" in part.name:
            raise BundleError("alternate_stream_path")
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise BundleError("redirected_path")
    if path.resolve() != path:
        raise BundleError("noncanonical_path")
    return path


@dataclass(frozen=True)
class Limits:
    max_bytes: int = MAX_BYTES
    max_records: int = MAX_RECORDS
    max_seconds: float = MAX_SECONDS

    def __post_init__(self):
        for value, maximum in ((self.max_bytes, MAX_BYTES), (self.max_records, MAX_RECORDS)):
            if _integer(value, maximum) == 0:
                raise BundleError("limit_must_be_positive")
        if (isinstance(self.max_seconds, bool)
                or not 0 < self.max_seconds <= MAX_SECONDS):
            raise BundleError("invalid_time_limit")


class _Reader:
    def __init__(self, limits, clock):
        self.limits, self.clock = limits, clock
        self.started, self.bytes_read = clock(), 0

    def check(self):
        if self.clock() - self.started >= self.limits.max_seconds:
            raise BundleError("time_cap")

    def read(self, path, maximum):
        self.check()
        path = regular_path(path)
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise BundleError("input_not_regular_file")
        remaining = self.limits.max_bytes - self.bytes_read
        if before.st_size > maximum or before.st_size > remaining:
            raise BundleError("input_byte_cap")
        with path.open("rb") as handle:
            chunks, size = [], 0
            while True:
                self.check()
                chunk = handle.read(min(65536, maximum - size + 1, remaining - size + 1))
                size += len(chunk)
                if size > maximum or size > remaining:
                    raise BundleError("input_byte_cap")
                if not chunk:
                    break
                chunks.append(chunk)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns):
            raise BundleError("input_changed_during_read")
        self.bytes_read += size
        self.check()
        return b"".join(chunks)


@dataclass(frozen=True)
class Condition:
    condition_id: str
    market_id: str
    domain_id: str
    active_from: datetime
    active_until: datetime


@dataclass(frozen=True)
class CapturedRecord:
    sequence: int
    captured_at: datetime
    condition_id: str
    kind: str
    payload: Mapping
    payload_sha256: str
    source_hashes: Mapping[str, str]


@dataclass(frozen=True)
class Bundle:
    day: date
    sealed_at: datetime
    provenance: str
    conditions: tuple[Condition, ...]
    records: tuple[CapturedRecord, ...]
    input_hashes: Mapping[str, str]
    input_bytes: int


def load_bundle(directory: Path, *, limits: Limits | None = None,
                clock=time.monotonic) -> Bundle:
    """Verify all streams before admission; sort by capture time then sequence.

    The seal must be after the UTC day's end. This checks the export's assertion,
    not producer authenticity or the workstation wall clock.
    """
    reader = _Reader(limits or Limits(), clock)
    root = regular_path(directory)
    manifest_bytes = reader.read(root / "bundle.json", MAX_MANIFEST_BYTES)
    manifest = _json(manifest_bytes)
    _keys(manifest, "format day sealed_at provenance conditions streams")
    if manifest["format"] != FORMAT:
        raise BundleError("unsupported_bundle_format")
    try:
        day = date.fromisoformat(manifest["day"])
    except (TypeError, ValueError) as exc:
        raise BundleError("invalid_day") from exc
    if day.isoformat() != manifest["day"]:
        raise BundleError("noncanonical_day")
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    sealed_at = timestamp(manifest["sealed_at"])
    if sealed_at < end:
        raise BundleError("day_not_closed_at_seal")
    if manifest["provenance"] not in ("synthetic", "captured"):
        raise BundleError("invalid_provenance")
    raw_conditions, streams = manifest["conditions"], manifest["streams"]
    if not isinstance(raw_conditions, list) or not 1 <= len(raw_conditions) <= MAX_CONDITIONS:
        raise BundleError("condition_count_cap")
    if not isinstance(streams, list) or not 1 <= len(streams) <= MAX_STREAMS:
        raise BundleError("stream_count_cap")
    conditions, condition_ids = [], set()
    for value in raw_conditions:
        reader.check()
        _keys(value, "condition_id market_id domain_id active_from active_until")
        cid = _identity(value["condition_id"])
        active_from, active_until = timestamp(value["active_from"]), timestamp(value["active_until"])
        if (cid in condition_ids or not start <= active_from < active_until <= end
                or active_from.second or active_from.microsecond
                or active_until.second or active_until.microsecond):
            raise BundleError("duplicate_condition_or_invalid_active_window")
        condition_ids.add(cid)
        conditions.append(Condition(cid, _identity(value["market_id"]),
                                    _identity(value["domain_id"]), active_from, active_until))
    records, sequences = [], set()
    hashes = {"bundle.json": sha256(manifest_bytes)}
    for stream in streams:
        reader.check()
        _keys(stream, "path sha256 bytes records")
        name = stream["path"]
        if (not isinstance(name, str) or re.fullmatch(r"[a-zA-Z0-9_-]+\.jsonl", name) is None
                or name.casefold() in {p.casefold() for p in hashes}):
            raise BundleError("invalid_or_duplicate_stream_path")
        size = _integer(stream["bytes"], MAX_BYTES)
        count = _integer(stream["records"], reader.limits.max_records)
        if len(records) + count > reader.limits.max_records:
            raise BundleError("record_count_cap")
        expected_hash = _hash(stream["sha256"])
        raw = reader.read(root / name, size)
        if len(raw) != size or sha256(raw) != expected_hash:
            raise BundleError("stream_hash_or_size_mismatch")
        hashes[name] = expected_hash
        lines = raw.splitlines(keepends=True)
        if len(lines) != count:
            raise BundleError("stream_record_count_mismatch")
        for line in lines:
            reader.check()
            if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                raise BundleError("record_too_large_or_unterminated")
            value = _json(line)
            _keys(value, "sequence captured_at condition_id kind payload payload_sha256 source_hashes")
            sequence = _integer(value["sequence"], 2**53 - 1)
            captured = timestamp(value["captured_at"])
            if sequence in sequences or not start <= captured < end:
                raise BundleError("duplicate_sequence_or_capture_outside_day")
            sequences.add(sequence)
            cid, kind = _identity(value["condition_id"]), _identity(value["kind"])
            if cid not in condition_ids or kind not in KINDS:
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
            records.append(CapturedRecord(sequence, captured, cid, kind, _freeze(payload),
                                          payload_hash, _freeze(source_hashes)))
    records.sort(key=lambda record: (record.captured_at, record.sequence))
    reader.check()
    return Bundle(day, sealed_at, manifest["provenance"],
                  tuple(sorted(conditions, key=lambda c: c.condition_id)), tuple(records),
                  _freeze(hashes), reader.bytes_read)
