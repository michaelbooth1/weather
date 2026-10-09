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
from types import MappingProxyType

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
    groups = MappingProxyType({g.group_id: g.condition_ids for g in bundle.coverage_groups})
    plan = DayPlan(bundle.day, bundle.conditions, windows_of(bundle.conditions, active_intervals), groups,
                   bundle.provenance, bundle.input_hashes, active_intervals is not None)
    return DaySource(plan, bundle.records)


def bundle_source(bundle: Bundle) -> DaySource:
    """A frozen v0.1 in-memory bundle (its ``active_intervals`` declare the windows when present)."""
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


def drive(sources, engines, *, time_zones, observers=()):
    """Parse each day once and feed every engine and observer the same instants; then finish engines.

    ``time_zones`` (market_id -> IANA zone) drives the local-midnight descriptor refresh (``day_roll``,
    registration C13). It is required; ``day_roll.NO_REFRESH`` turns the refresh off and exists only for the
    attribution re-run of the pre-F3 engine.
    """
    from maker_core.replay.v2.day_roll import NO_REFRESH, DayRoll
    roll = None if time_zones is NO_REFRESH else DayRoll(time_zones)
    sources = sorted(sources, key=lambda s: s.plan.day)
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
