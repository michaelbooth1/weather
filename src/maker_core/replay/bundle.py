"""Bounded, hash-verified closed-day inputs for any domain plugin.

Hashes bind bytes, not their truth or author. No source path in a record is
opened. Manifest paths are flat JSONL filenames beneath the supplied directory.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.metadata
import importlib.resources
import io
import json
from pathlib import Path
import re
import stat
import time
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maker_core.contracts import utc_time
from maker_core.evidence.journal import canonical_bytes

FORMAT = "maker_core.replay.bundle.v0.1"
KINDS = frozenset({"descriptor", "book", "terms", "trade", "plugin_input",
                   "outcome_view", "info_event", "settlement", "coverage"})
MAX_BYTES = 64 * 1024**2
MAX_MANIFEST_BYTES = 1024**2
MAX_LINE_BYTES = 1024**2
MAX_RECORDS = 100_000
MAX_STREAMS = 64
MAX_CONDITIONS = 2_000
MAX_SECONDS = 300.0
# Clarification 2 ceilings are derived from rehearsed calibration dates and limited
# by the 16 GB host: bytes held in memory at most 70% of RAM, four hours of runtime.
# The defaults above stay the ordinary diagnostic ceilings; only these host limits
# bound an explicitly derived ceiling. Raising a limit never truncates or samples input.
HOST_RAM_BYTES = 16 * 1024**3
HOST_MAX_BYTES = HOST_RAM_BYTES * 7 // 10
HOST_MAX_RECORDS = 2**31
HOST_MAX_SECONDS = 4 * 3600.0


class BundleError(ValueError):
    """Invalid, changed, redirected or over-budget input; no partial admission."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# Owner T1(a), 2026-10-09: zone data comes only from this pinned PyPI ``tzdata`` (pyproject.toml and
# requirements.txt pin the same version; ``tests/maker_core/test_replay_v2_run_binding.py`` checks it), never from
# the platform's TZPATH, and the version plus the sha of the zone files actually used bind into the v2 run binding.
TZDATA_VERSION = "2026.3"
ZONE_MAP_BUILDER = "maker_core.replay.execution_manifest.market_time_zones"  # ``RegisteredZones.source["builder"]``


def tzdata_package():
    """The imported ``tzdata`` module, checked against the installed distribution's metadata (owner T1(a)).

    Refuses ``tzdata_unavailable`` when either is missing, ``tzdata_version_unpinned`` when the metadata version
    is not ``TZDATA_VERSION``, and ``tzdata_package_mismatch`` when the module's own ``__version__`` differs from
    the metadata or its ``__file__`` is not in the package directory that distribution installed (a shadowing
    ``tzdata`` directory earlier on ``sys.path``). The directories are compared, not ``__init__.py``, so a sourceless
    install whose ``__file__`` is ``__init__.pyc`` is accepted (Delta-1 finding 3). Zone bytes are read through this
    module object only, so the bytes, the version and the IANA release all come from the one package the metadata
    describes. Not cached: every call re-checks."""
    try:
        version = importlib.metadata.version("tzdata")
        location = importlib.metadata.distribution("tzdata").locate_file("tzdata")
        import tzdata
    except (importlib.metadata.PackageNotFoundError, ModuleNotFoundError) as exc:
        raise BundleError("tzdata_unavailable") from exc
    if version != TZDATA_VERSION:
        raise BundleError("tzdata_version_unpinned")
    if getattr(tzdata, "__version__", None) != version:
        raise BundleError("tzdata_package_mismatch")
    try:
        same = Path(tzdata.__file__).resolve().parent == Path(location).resolve()
    except (TypeError, OSError):
        same = False
    if not same:
        raise BundleError("tzdata_package_mismatch")
    return tzdata


def _tzdata():
    return importlib.resources.files(tzdata_package())


@lru_cache(maxsize=1)
def _zone_names() -> frozenset:
    """Every zone the pinned tzdata package lists (its ``zones`` file); no platform TZPATH entry is added."""
    return frozenset(_tzdata().joinpath("zones").read_text(encoding="utf-8").split())


@lru_cache(maxsize=None)
def zone_file_bytes(name: str) -> bytes:
    """The TZif bytes of a listed zone, read from the pinned tzdata package only; an unlisted name refuses."""
    if not isinstance(name, str) or name not in _zone_names():
        raise BundleError("unknown_time_zone")
    node = _tzdata().joinpath("zoneinfo")
    for part in name.split("/"):
        node = node.joinpath(part)
    return node.read_bytes()


@lru_cache(maxsize=None)
def pinned_zone(name: str) -> ZoneInfo:
    """A ``ZoneInfo`` built from the pinned tzdata bytes; one object per name, as ``ZoneInfo(name)`` caches."""
    return ZoneInfo.from_file(io.BytesIO(zone_file_bytes(name)), key=name)


def time_zone(name) -> ZoneInfo:
    """A strictly named IANA zone from the pinned tzdata package, or ``BundleError("unknown_time_zone")``.

    The name must be listed verbatim by the pinned tzdata's ``zones`` file: a filesystem lookup alone is
    platform-dependent (Windows accepted ``"Europe/London "`` with a trailing space and maps case-insensitively),
    and an unlisted, mis-cased, padded or path-like name must refuse with a code on every platform. Aliases such
    as ``GB`` are listed zones and are accepted as named; equality between names stays a string compare. The zone
    is loaded from that package's bytes (``pinned_zone``), never from the platform's TZPATH (owner T1(a)).
    """
    if not isinstance(name, str) or name not in _zone_names():
        raise BundleError("unknown_time_zone")
    try:
        zone = pinned_zone(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise BundleError("unknown_time_zone") from exc
    if zone.key != name:
        raise BundleError("unknown_time_zone")
    return zone


class RegisteredZones(Mapping):
    """market_id -> zone name with its provenance (owner T2(a)/T3(a), 2026-10-09).

    Built only by ``execution_manifest.market_time_zones`` after the inventory and registry checks; ``source``
    records that builder and the digests of the inventory and registry it checked, and the v2 run binding
    (``pipeline.run_binding``) copies it into the run digest. A hand-made mapping has no ``source`` and binds as
    ``builder="caller"``, which a scored (non-synthetic) report refuses, as it refuses any source that is not the
    full record (``ZONE_MAP_BUILDER``, ``registry_checked`` and both digests). Hashes bind provenance; they do not stop
    a caller from constructing this class by hand, so a verifier recomputes it from the bound inventory and registry.
    """

    __slots__ = ("_zones", "source")

    def __init__(self, zones, source):
        self._zones = MappingProxyType(dict(sorted(dict(zones).items())))
        self.source = MappingProxyType(dict(source))

    def __getitem__(self, market):
        return self._zones[market]

    def __iter__(self):
        return iter(self._zones)

    def __len__(self):
        return len(self._zones)

    def __repr__(self):
        return f"RegisteredZones({dict(self._zones)!r})"


def tzdata_binding(names) -> dict:
    """T1(a): the pinned tzdata version, its IANA release and the sha of the zone files ``names`` resolve to.

    Refuses as ``tzdata_package`` does (unpinned version, or a module that is not the installed distribution's).
    The zone-file shas are over ``zone_file_bytes``, the same cached bytes ``pinned_zone`` loads, so they cover
    exactly the bytes the run used. ``pipeline.verify_run_binding`` recomputes this block at report time."""
    tzdata = tzdata_package()
    files = [[name, sha256(zone_file_bytes(time_zone(name).key))] for name in sorted(set(names))]
    return dict(package="tzdata", version=tzdata.__version__, iana_version=tzdata.IANA_VERSION, tzpath_used=False,
                zone_files=files, zone_files_sha256=sha256(canonical_bytes(files)))


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
        for value, maximum in ((self.max_bytes, HOST_MAX_BYTES), (self.max_records, HOST_MAX_RECORDS)):
            if _integer(value, maximum) == 0:
                raise BundleError("limit_must_be_positive")
        if (isinstance(self.max_seconds, bool)
                or not 0 < self.max_seconds <= HOST_MAX_SECONDS):
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
    # None retains legacy envelope intervals; () means settlement-only/inactive.
    # Only a verified execution manifest supplies this in the scored CLI.
    active_intervals: tuple | None = None

    def windows(self, condition):
        if self.active_intervals is None:
            return ((condition.active_from, condition.active_until),)
        return tuple((start, end) for cid, start, end in self.active_intervals if cid == condition.condition_id)


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
        if (cid in condition_ids or not start <= active_from <= active_until <= end
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
        size = _integer(stream["bytes"], reader.limits.max_bytes)
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
