"""Run plans, day sources and the lockstep driver: one parse of each day drives several engines.

A day is parsed once (two-pass stream reader for v0.2, or the frozen in-memory reader for v0.1), each
record is decoded once, v0.2 coverage-group records are expanded to the group's members that have a
descriptor so far that day (exactly as ``compaction.expand`` does), and every engine instance — the
base passes, or one matched-clock round — receives the same instants in ``(captured_at, sequence)``
order. Engines carry their state across days; nothing is reset between dates except blind RE-1's
one-session-per-UTC-day rule, which the kernel owns.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from types import MappingProxyType

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import Bundle, BundleError, CapturedRecord, Condition, _freeze, timestamp
from maker_core.replay.bundle_v02 import GroupRecord, StreamBundle
from maker_core.replay.payloads import decode
from maker_core.replay.v2.kernel import group_by_instant

MAX_DAYS = 366


@dataclass(frozen=True)
class Item:
    """One decoded record for one condition at one instant (a group record yields one per member)."""
    condition_id: str
    kind: str
    payload_sha256: str
    value: object
    error: str | None
    sequence: int
    derived: str | None = None  # "local_midnight" for a day-roll descriptor (``day_roll``); None when captured


@dataclass(frozen=True)
class DayPlan:
    day: date
    conditions: tuple[Condition, ...]
    windows: Mapping  # condition_id -> ((start, end), ...)
    groups: Mapping  # group_id -> (condition_id, ...)
    provenance: str
    input_hashes: Mapping
    declared: bool = False  # the windows come from declared active intervals, not the envelope

    def __post_init__(self):
        # A-defender M3 / U1 Defender MF2: the invariant lives on the plan itself, so no constructor, alias
        # or hand-built plan can make every envelope of a captured day active.
        if self.provenance != "synthetic" and not self.declared:
            raise BundleError("captured_bundle_requires_declared_intervals")

    @property
    def start(self):
        return datetime.combine(self.day, datetime.min.time(), tzinfo=timezone.utc)


@dataclass(frozen=True)
class RunPlan:
    days: tuple[DayPlan, ...]

    def __post_init__(self):
        days = [d.day for d in self.days]
        if not days or len(days) > MAX_DAYS or len(set(days)) != len(days) or days != sorted(days):
            raise BundleError("duplicate_or_unbounded_days")
        if (days[-1] - days[0]).days >= MAX_DAYS:
            raise BundleError("calendar_span_cap")

    @property
    def declared(self):
        """v1: any bundle's ``active_intervals`` declared, so a print at an interval start is excluded."""
        return any(d.declared for d in self.days)

    @property
    def horizon(self):
        return self.days[-1].start + timedelta(days=1)


@dataclass(frozen=True)
class DaySource:
    plan: DayPlan
    records: Callable[[], Iterable]  # a fresh ``(captured_at, sequence)``-ordered iterator per call


def windows_of(conditions, active_intervals):
    if active_intervals is None:
        return MappingProxyType({c.condition_id: ((c.active_from, c.active_until),) for c in conditions})
    result = {}
    for cid, start, end in active_intervals:
        result.setdefault(cid, []).append((start, end))
    return MappingProxyType({cid: tuple(v) for cid, v in result.items()})


def stream_source(bundle: StreamBundle, active_intervals=None) -> DaySource:
    """A v0.2 day source. A captured bundle needs declared intervals (A-defender M3): without them every
    condition would be active over its whole envelope, owner-excluded market-dates included. Only a
    synthetic fixture may fall back to the envelope."""
    if active_intervals is None and bundle.provenance != "synthetic":
        raise BundleError("captured_bundle_requires_declared_intervals")
    groups = MappingProxyType({g.group_id: g.condition_ids for g in bundle.coverage_groups})
    plan = DayPlan(bundle.day, bundle.conditions, windows_of(bundle.conditions, active_intervals), groups,
                   bundle.provenance, bundle.input_hashes, active_intervals is not None)
    return DaySource(plan, bundle.records)


def bundle_source(bundle: Bundle) -> DaySource:
    """A frozen v0.1 in-memory bundle (its ``active_intervals`` declare the windows when present)."""
    if bundle.active_intervals is None and bundle.provenance != "synthetic":
        raise BundleError("captured_bundle_requires_declared_intervals")
    plan = DayPlan(bundle.day, bundle.conditions, windows_of(bundle.conditions, bundle.active_intervals),
                   MappingProxyType({}), bundle.provenance, bundle.input_hashes, bundle.active_intervals is not None)
    return DaySource(plan, lambda: iter(bundle.records))


def record_from_row(value) -> CapturedRecord | GroupRecord:
    """An exporter-shaped dict row as a reader record (fixtures and benchmarks; no hash re-check)."""
    kind = GroupRecord if "group_id" in value else CapturedRecord
    owner = value["group_id"] if kind is GroupRecord else value["condition_id"]
    return kind(value["sequence"], timestamp(value["captured_at"]), owner, value["kind"],
                _freeze(value["payload"]), value["payload_sha256"], _freeze(value["source_hashes"]))


def run_plan(sources) -> RunPlan:
    return RunPlan(tuple(s.plan for s in sorted(sources, key=lambda s: s.plan.day)))


def decode_record(record):
    try:
        return decode(record), None
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        return None, type(exc).__name__


def items(source: DaySource) -> Iterable[tuple[datetime, list[Item]]]:
    """The day's instants with decoded items; group records expanded to seen members, once."""
    seen, groups = set(), source.plan.groups

    def expand():
        for record in source.records():
            value, error = decode_record(record)
            if isinstance(record, GroupRecord):
                members = groups.get(record.group_id)
                if members is None:
                    raise BundleError("unknown_coverage_group")
                present = [cid for cid in members if cid in seen]
                if not present:
                    raise BundleError("coverage_group_without_seen_member")
                for cid in present:
                    yield record, Item(cid, record.kind, record.payload_sha256, value, error, record.sequence)
                continue
            if record.kind == "descriptor":
                seen.add(record.condition_id)
            yield record, Item(record.condition_id, record.kind, record.payload_sha256, value, error,
                               record.sequence)

    for at, batch in group_by_instant(expand()):
        yield at, [item for _, item in batch]


def _materialise(record, extra=None):
    """``(identity_bytes, identity, rebuilt)`` for one reader record (R155 defender-3 R1, defender-4 D-1).

    ``identity_bytes`` is the canonical JSON of the record's identity (``record_identity``, plus ``extra``);
    ``identity`` is those bytes parsed back. ``rebuilt`` is a fresh, frozen ``CapturedRecord`` or ``GroupRecord``
    made from exactly the bytes that were hashed: the identity bytes and the payload's canonical bytes, through
    ``json.loads`` and ``record_from_row``. The payload's sha is compared, on those plain types, with the
    ``payload_sha256`` the identity carries; a mismatch, or a payload with no canonical form, refuses
    ``replay_payload_hash_mismatch``. So whatever object the caller handed in (a mapping subclass whose ``items()``
    and ``[]`` disagree, a ``datetime`` where the canonical text is a string, a ``str`` subclass with its own
    ``__eq__``), the engine reads only plain JSON types whose bytes are the ones digested."""
    try:
        payload = canonical_bytes(record.payload)
    except (TypeError, ValueError) as exc:
        raise BundleError("replay_payload_hash_mismatch") from exc
    owner = "group_id" if isinstance(record, GroupRecord) else "condition_id"
    fields = {"sequence": record.sequence, "captured_at": record.captured_at, owner: getattr(record, owner),
              "kind": record.kind, "payload_sha256": record.payload_sha256, "source_hashes": record.source_hashes}
    raw = canonical_bytes(dict(fields, **(extra or {})))
    identity = json.loads(raw)
    if hashlib.sha256(payload).hexdigest() != identity["payload_sha256"]:
        raise BundleError("replay_payload_hash_mismatch")
    return raw, identity, record_from_row(dict(identity, payload=json.loads(payload)))


def record_identity(record) -> dict:
    """One reader record's identity, as plain JSON (R155 defender-3 R1): ``sequence``, ``captured_at`` (ISO text),
    ``condition_id`` (v0.1) or ``group_id`` (v0.2 group record), ``kind``, ``payload_sha256`` and
    ``source_hashes``. The record digest binds each one together with its day (``RecordDigest.add``). The payload is
    re-hashed first: a payload whose canonical-JSON sha is not its ``payload_sha256`` refuses
    ``replay_payload_hash_mismatch`` (the sealed readers check the same at load; an in-memory ``Bundle.records`` or
    ``DaySource.records`` is not a sealed reader). The sha binds the payload's canonical bytes, not the in-memory
    object: a digested drive feeds the engine the record rebuilt from those bytes (``_materialise``, R155
    defender-4 D-1), so the sha stands for the payload actually consumed there."""
    return _materialise(record)[1]


class RecordDigest:
    """The records one ``drive`` actually read, digested as they stream (R155 defender-2 D2, defender-3 R1).

    ``hexdigest()`` equals ``journal.digest([dict(record_identity(r), day=d.isoformat()) for d, r in records])``
    over every record read with its plan day, in consumption order: day order and, within a day, reader order.
    That is the shape of the execution manifest's ``record_identity_sha256`` (``build_manifest`` feeds every
    bundle's records, in day order and with the bundle's day, through this class). Each element binds the record's
    day (R155 defender-4 N-1: a record moved to an adjacent day changes the digest even though the flat sequence is
    kept), sequence, capture time, condition or group, kind, payload sha (re-hashed against the payload,
    ``replay_payload_hash_mismatch``) and sources, so a substituted, re-ordered, duplicated or re-priced record
    changes the digest even when the count and every ``source_hashes`` are kept (records of one sealed segment share
    their ``source_hashes``). ``add`` returns the record rebuilt from the digested bytes, which is what a digested
    drive consumes (R155 defender-4 D-1). It is accumulated incrementally, element by element of that canonical
    JSON list, so no record is retained. Raw reader records only: a v0.2 group record counts once (not once per
    member), and the day roll's derived descriptors are not records."""

    def __init__(self):
        self._sha = hashlib.sha256(b"[")
        self.records = 0

    def add(self, record, *, day):
        raw, _, rebuilt = _materialise(record, {"day": day.isoformat()})
        self._sha.update((b"," if self.records else b"") + raw[:-1])  # raw ends with "\n"; a list element does not
        self.records += 1
        return rebuilt

    def hexdigest(self):
        sha = self._sha.copy()
        sha.update(b"]\n")
        return sha.hexdigest()

    def summary(self):
        return dict(record_identity_sha256=self.hexdigest(), records=self.records)


def _tapped(source: DaySource, digest: RecordDigest) -> DaySource:
    """``source`` digested as it streams; it yields each record rebuilt from its digested bytes (defender-4 D-1)."""
    def records():
        for record in source.records():
            yield digest.add(record, day=source.plan.day)
    return DaySource(source.plan, records)


def drive(sources, engines, *, time_zones, observers=(), records=None):
    """Parse each day once and feed every engine and observer the same instants; then finish engines.

    ``time_zones`` (market_id -> IANA zone) drives the local-midnight descriptor refresh (``day_roll``,
    registration C13). It is required; ``day_roll.NO_REFRESH`` turns the refresh off and exists only for the
    attribution re-run of the pre-F3 engine. ``records``, a ``RecordDigest``, digests every record the drive reads
    (``pipeline.run_passes`` keeps it as ``Run.replayed``).
    """
    from maker_core.replay.v2.day_roll import NO_REFRESH, DayRoll
    roll = None if time_zones is NO_REFRESH else DayRoll(time_zones)
    if roll is not None:
        for engine in engines:  # the engine summary carries the roll's derived-descriptor digest (R155 Fable F5)
            engine.day_roll = roll
    sources = sorted(sources, key=lambda s: s.plan.day)
    if records is not None:
        sources = [_tapped(source, records) for source in sources]
    for source in sources:
        for engine in engines:
            engine.start_day(source.plan)
        for at, batch in (items(source) if roll is None else roll.items(source)):
            for observer in observers:
                observer.instant(at, batch)
            for engine in engines:
                engine.instant(at, batch)
    for engine in engines:
        engine.finish()
    return engines
