"""The registration §4 horizon clause: active intervals follow the latest captured or derived descriptor (owner Q2(a)).

Owner decision 2026-10-08 (Q2, option (a) full). A condition is in the universe at instant t only while the latest
**captured or derived** descriptor at or before t has ``horizon_days`` in ``ELIGIBLE`` (1 or 2). Derived descriptors
are exactly the engine's (``day_roll.DayRoll``, registration C13): this module replays the run's descriptor records
through the same ``DayRoll`` the engine is driven with, so a band leaves the universe at the same local midnight at
which the engine's ``horizon_days`` becomes 0, and the interval end wakes the band and withdraws its resting legs
(``kernel.tick``: ``OUTSIDE_ACTIVE_INTERVAL``).

- ``timelines`` is the per-condition sequence of ``(instant, horizon_days)`` the engine reads (``None`` before the
  first descriptor or after an invalid one, which the engine treats as ``MISSING_DESCRIPTOR``);
- ``day_windows`` cuts one day's condition envelopes (``active_from``/``active_until``) into the eligible runs and
  the ineligible runs with their exclusion reason (``horizon_outside_1_2`` or ``missing_descriptor``);
- ``lead_window`` is the single-day form an exporter can compute without the run's earlier days: the UTC span of
  local leads 1..2 of a target date, ``[local midnight of target-2, local midnight of target)``. Every captured
  descriptor's ``horizon_days`` equals the local lead at its capture (``execution_manifest._inventory`` checks it)
  and every derived one equals the local lead at its midnight, so after a condition's first descriptor the two
  rules agree; they differ only before it, where the exporter cannot know the run's earlier days.

Pure functions of the records and the market time zones; no clock, no I/O.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from maker_core.quoting.policy import informed_v0
from maker_core.replay.bundle import BundleError

ELIGIBLE = informed_v0.eligible_horizons  # (1, 2): the same gate the engine's informed-v0 decide() applies
OUTSIDE = "horizon_outside_1_2"
MISSING = "missing_descriptor"


def timelines(sources, time_zones):
    """condition_id -> [(instant, horizon_days | None), ...] in record order, over every day of ``sources``.

    The run's descriptor records go through a fresh ``DayRoll`` (the engine's reader) day by day, so the derived
    local-midnight descriptors are the ones the engine sees, including its day-boundary and lead-0..2 scope rules.
    Within one instant derived items precede captured ones, so the last entry at an instant is the one that holds.
    """
    from maker_core.replay.v2.day_roll import DayRoll
    from maker_core.replay.v2.lockstep import DaySource

    roll = DayRoll(time_zones)
    result = {}
    for source in sorted(sources, key=lambda s: s.plan.day):
        records = source.records
        only = DaySource(source.plan, lambda records=records: (r for r in records() if r.kind == "descriptor"))
        for at, batch in roll.items(only):
            for item in batch:
                if item.kind == "descriptor":
                    value = None if item.error is not None else item.value.horizon_days
                    result.setdefault(item.condition_id, []).append((at, value))
    return result


def _state(timeline, at):
    """(seen, horizon) of the latest entry at or before ``at``."""
    seen, horizon = False, None
    for when, value in timeline:
        if when > at:
            break
        seen, horizon = True, value
    return seen, horizon


def _reason(seen, horizon):
    return None if horizon in ELIGIBLE else OUTSIDE if seen and horizon is not None else MISSING


def runs(timeline, start, end):
    """[(start, end, reason | None), ...] covering ``[start, end)``: reason None while eligible."""
    if not start < end:
        return []
    seen, horizon = _state(timeline, start)
    cuts, current = [], _reason(seen, horizon)
    cursor = start
    for when, value in timeline:
        if when <= start:
            continue
        if when >= end:
            break
        reason = _reason(True, value)
        if reason != current:
            cuts.append((cursor, when, current))
            cursor, current = when, reason
    cuts.append((cursor, end, current))
    merged = []
    for low, high, reason in cuts:
        if low >= high:
            continue  # superseded within one instant (the last entry at an instant holds)
        if merged and merged[-1][2] == reason:
            merged[-1] = (merged[-1][0], high, reason)
        else:
            merged.append((low, high, reason))
    return merged


def day_windows(plan, lines):
    """One day's eligible windows (condition_id -> ((start, end), ...)) and its ineligible runs with reasons.

    Each condition's envelope is its ``active_from``/``active_until``; the clause only narrows it.
    """
    windows, excluded = {}, []
    for c in plan.conditions:
        timeline = lines.get(c.condition_id, ())
        for low, high, reason in runs(timeline, c.active_from, c.active_until):
            if reason is None:
                windows.setdefault(c.condition_id, []).append((low, high))
            else:
                excluded.append((c.condition_id, low, high, reason))
    return {cid: tuple(v) for cid, v in windows.items()}, excluded


def _midnight(zone, local: date) -> datetime:
    """A local midnight in UTC, built as ``day_roll.next_local_midnight`` builds it (a nonexistent one by fold 0)."""
    value = datetime.combine(local, time(), tzinfo=zone).astimezone(timezone.utc)
    if value.second or value.microsecond:
        raise BundleError("local_midnight_not_on_a_minute")
    return value


def lead_window(zone, target: date, day_start: datetime, day_end: datetime):
    """``(active_from, active_until)``: local leads 1..2 of ``target`` clipped to ``[day_start, day_end]``.

    An empty span is returned as ``from == until`` (at the nearer day edge), the bundle format's empty envelope.
    """
    low = _midnight(zone, target - timedelta(days=max(ELIGIBLE)))
    high = _midnight(zone, target - timedelta(days=min(ELIGIBLE) - 1))
    low, high = min(max(low, day_start), day_end), min(max(high, day_start), day_end)
    return low, max(low, high)
