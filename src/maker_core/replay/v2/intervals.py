"""The §4 universe rule as declared active intervals (maker replay v2 W7; registration draft §2, §4).

A condition is **active** in UTC minute ``[t, t+1min)`` when all of these hold (owner decision 15: minute
granularity, the latest descriptor at the minute start, the hazard denominator's rule in
``maker_core.replay.calibration``):

- ``t`` is on a quote date of the panel;
- the condition is not in an owner-excluded market-date (``panel.OWNER_EXCLUSIONS``);
- its local target date is on or before the panel's last target date;
- ``t`` is outside ``panel.MAINTENANCE_UTC``;
- the latest descriptor captured at or before ``t`` has ``horizon_days`` 1 or 2 (``MISSING_DESCRIPTOR``
  before the condition's first descriptor of the day; an undecodable descriptor refuses the whole build,
  ``undecodable_descriptor``, as in v1).

Every other minute of the condition's envelope is an exclusion with exactly one reason, taken in this
precedence order (A-defender M5/N5): ``OWNER_EXCLUDED_PRIOR_READ`` > ``SETTLEMENT_ONLY`` >
``TARGET_AFTER_PANEL`` > ``MAINTENANCE_UTC`` > ``MISSING_DESCRIPTOR`` > ``HORIZON_OUTSIDE_1_2``. So for each
(date, condition) the active and excluded seconds sum to the envelope. Windows are merged runs of
active minutes, clipped to the envelope.

The panel is a fixed name, never an object (A-defender M6): ``"registered"`` resolves to the quote,
settlement-only and last-target constants and requires every owner exclusion to match whenever the
evaluated dates meet its exported span (for Austin 2026-10-03, UTC 10-01..10-04); ``"calibration"``
resolves to the three calibration dates with no target cap (reg §11 f_cal applies the §4 rule to them),
where an owner exclusion that matches nothing is expected. No function here takes a parameter that can
replace ``OWNER_EXCLUSIONS``.

The owner exclusion has two independent keys (owner decision 14, A-defender M4): the inventory key
``(market_id, target_date)`` from the weather producer, and the descriptor key (bundle
``Condition.market_id`` plus captured descriptor ``market.close_at_utc``), derived here without slug
parsing. The two condition sets must be equal (``owner_exclusion_key_disagreement``); on the registered
panel they must be non-empty (``owner_exclusion_unmatched``); and no output window may belong to an
excluded condition (``owner_excluded_market_date_active``).

Excluded records still flow through the shared parse: the bundle keeps every condition (reg §4).
"Never scored" means no decision, interval, band-day row, cell or pull candidate, which follows from
the condition having no declared window.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

from maker_core.replay.bundle import BundleError, timestamp
from maker_core.replay.v2 import panel as constants
from maker_core.replay.v2 import universe_v02
from maker_core.replay.v2.lockstep import stream_source

OWNER = "OWNER_EXCLUDED_PRIOR_READ"
SETTLEMENT_ONLY = "SETTLEMENT_ONLY"
TARGET_AFTER_PANEL = "TARGET_AFTER_PANEL"
MAINTENANCE = "MAINTENANCE_UTC"
MISSING_DESCRIPTOR = "MISSING_DESCRIPTOR"
HORIZON = "HORIZON_OUTSIDE_1_2"
REASONS = (OWNER, SETTLEMENT_ONLY, TARGET_AFTER_PANEL, MAINTENANCE, MISSING_DESCRIPTOR, HORIZON)
# Diagnostic (A-defender N2), never an exclusion: active seconds whose calendar horizon (inventory
# timezone) differs from the latest descriptor's, e.g. the minutes between local midnight and the first
# horizon-0 descriptor, which the literal rule keeps active.
STALE = "HORIZON_DESCRIPTOR_STALE_SECONDS"
ACTIVE_HORIZONS = (1, 2)
MINUTE = timedelta(minutes=1)
REFUSAL_CODES = ("unknown_panel", "owner_exclusion_constant_invalid", "owner_exclusion_key_disagreement",
                 "owner_exclusion_unmatched", "owner_excluded_market_date_active", "day_outside_panel",
                 "duplicate_panel_day", "window_outside_bundle", "intervals_require_bundles")


class Evaluation(NamedTuple):
    windows: list  # [{date, condition_id, start, end}] ISO text, sorted
    exclusions: list  # [{date, condition_id, reason, seconds}] sorted by date, condition, precedence
    owner_exclusions: list  # the constant rows with their matched condition IDs
    diagnostics: list  # [{date, condition_id, reason: STALE, seconds}]


class _Panel(NamedTuple):
    name: str
    quote_dates: tuple
    settlement_only: tuple
    last_target: date | None
    require_match: bool


def resolve(panel) -> _Panel:
    """A panel name to its constants; anything other than the two literals refuses."""
    if type(panel) is not str or panel not in constants.PANELS:
        raise BundleError("unknown_panel")
    if panel == "registered":
        return _Panel(panel, tuple(constants.QUOTE_DATES), tuple(constants.SETTLEMENT_ONLY_DATES),
                      constants.LAST_TARGET_DATE, True)
    return _Panel(panel, tuple(constants.CALIBRATION_DATES), (), None, False)


def owner_exclusions():
    """``panel.OWNER_EXCLUSIONS``, type-checked at use, so a malformed edit refuses instead of matching nothing."""
    rows = constants.OWNER_EXCLUSIONS
    if not isinstance(rows, tuple):
        raise BundleError("owner_exclusion_constant_invalid")
    for row in rows:
        if (not isinstance(row, tuple) or len(row) != 5 or not isinstance(row[0], str) or not row[0]
                or type(row[1]) is not date or type(row[2]) is not datetime or row[2].tzinfo is None
                or row[2].utcoffset() != timedelta(0) or row[2].second or row[2].microsecond
                or row[3] != OWNER or not isinstance(row[4], str) or not row[4]):
            raise BundleError("owner_exclusion_constant_invalid")
    return rows


def excluded_by_descriptor(conditions, records, rows):
    """Per owner-exclusion row, the conditions whose market and any decoded descriptor close match it."""
    markets = {c.condition_id: c.market_id for c in conditions}
    found = [set() for _ in rows]
    for record in records:
        value = universe_v02.decoded(record)
        for i, row in enumerate(rows):
            if markets.get(record.condition_id) == row[0] and value.market.close_at_utc == row[2]:
                found[i].add(record.condition_id)
    return found


def _excluded(days, by_id, rows, spec):
    by_inventory = [{cid for cid, item in by_id.items()
                     if item["market_id"] == row[0] and item["target_date"] == row[1].isoformat()} for row in rows]
    by_descriptor = [set() for _ in rows]
    for day, records in days:
        for i, found in enumerate(excluded_by_descriptor(day.conditions, records, rows)):
            by_descriptor[i] |= found
    for row, inventory_set, descriptor_set in zip(rows, by_inventory, by_descriptor):
        if inventory_set != descriptor_set:
            raise BundleError("owner_exclusion_key_disagreement")
        for cid in inventory_set:
            item = by_id[cid]
            close = datetime.combine(row[1] + timedelta(days=1), time(), tzinfo=ZoneInfo(item["local_timezone"]))
            if close.astimezone(timezone.utc) != row[2]:
                raise BundleError("owner_exclusion_key_disagreement")
        if spec.require_match and not inventory_set and any(_may_hold(day.day, row) for day, _ in days):
            raise BundleError("owner_exclusion_unmatched")
    return by_inventory


def _may_hold(day, row):
    """Whether UTC ``day`` meets the excluded market-date's exported span: horizon 2..0, i.e. from local
    midnight two days before the target (at most three days before the close) to the close."""
    start = datetime.combine(day, time(), tzinfo=timezone.utc)
    return start < row[2] and start + timedelta(days=1) > row[2] - timedelta(days=3)


def _day_list(days, spec):
    days = [(day, list(records)) for day, records in days]
    if not days:
        raise BundleError("intervals_require_bundles")
    days.sort(key=lambda item: item[0].day)
    seen = [day.day for day, _ in days]
    if len(set(seen)) != len(seen):
        raise BundleError("duplicate_panel_day")
    for day in seen:
        if day not in spec.quote_dates and day not in spec.settlement_only:
            raise BundleError("day_outside_panel")
    return days


def evaluate(days, inventory, *, panel, check=lambda: None) -> Evaluation:
    """Windows, exclusions, owner-exclusion matches and the stale-horizon diagnostic for ``days``.

    ``days`` is ``[(bundle-like, descriptor records)]`` (``universe_v02.day_inputs``); a bundle-like has
    ``day`` and ``conditions``. ``inventory`` is the weather producer's universe rows.
    """
    spec = resolve(panel)
    rows = owner_exclusions()
    days = _day_list(days, spec)
    by_id = universe_v02.check_inventory(days, inventory, check=check)
    excluded_sets = _excluded(days, by_id, rows, spec)
    excluded = set().union(*excluded_sets)
    windows, exclusions, diagnostics = [], [], []
    for day, records in days:
        start = datetime.combine(day.day, time(), tzinfo=timezone.utc)
        maintenance = tuple(datetime.combine(day.day, t, tzinfo=timezone.utc) for t in constants.MAINTENANCE_UTC)
        latest = {}
        for record in records:
            latest.setdefault(record.condition_id, []).append((record.captured_at, universe_v02.decoded(record)))
        for c in day.conditions:
            check()
            cid, item = c.condition_id, by_id[c.condition_id]
            target = date.fromisoformat(item["target_date"])
            zone = ZoneInfo(item["local_timezone"])
            history, pointer, current = latest.get(cid, []), 0, None
            counts, stale, run = Counter(), 0, None
            at = max(c.active_from, start)
            while at < min(c.active_until, start + timedelta(days=1)):
                while pointer < len(history) and history[pointer][0] <= at:
                    current = history[pointer][1]
                    pointer += 1
                if cid in excluded:
                    reason = OWNER
                elif day.day in spec.settlement_only:
                    reason = SETTLEMENT_ONLY
                elif spec.last_target is not None and target > spec.last_target:
                    reason = TARGET_AFTER_PANEL
                elif maintenance[0] <= at < maintenance[1]:
                    reason = MAINTENANCE
                elif current is None:
                    reason = MISSING_DESCRIPTOR
                elif current.horizon_days not in ACTIVE_HORIZONS:
                    reason = HORIZON
                else:
                    reason = None
                if reason is None and (target - at.astimezone(zone).date()).days != current.horizon_days:
                    stale += 60
                end = min(at + MINUTE, c.active_until)
                if reason is None:
                    if run is not None and run[1] == at:
                        run[1] = end
                    else:
                        if run is not None:
                            windows.append(_window(day.day, cid, *run))
                        run = [at, end]
                else:
                    counts[reason] += int((end - at).total_seconds())
                at = end
            if run is not None:
                windows.append(_window(day.day, cid, *run))
            for reason in REASONS:
                if counts[reason]:
                    exclusions.append(dict(date=day.day.isoformat(), condition_id=cid, reason=reason,
                                           seconds=counts[reason]))
            if stale:
                diagnostics.append(dict(date=day.day.isoformat(), condition_id=cid, reason=STALE, seconds=stale))
    if any(w["condition_id"] in excluded for w in windows):
        raise BundleError("owner_excluded_market_date_active")
    matched = [dict(market_id=row[0], target_date=row[1].isoformat(), close_at_utc=_iso(row[2]), reason=row[3],
                    source=row[4], matched_conditions=sorted(found)) for row, found in zip(rows, excluded_sets)]
    windows.sort(key=lambda w: (w["date"], w["condition_id"], w["start"]))
    return Evaluation(windows, exclusions, matched, diagnostics)


def active_intervals(days, inventory, *, panel, check=lambda: None):
    """``(windows, exclusions)`` under the §4 rule; see ``evaluate``."""
    result = evaluate(days, inventory, panel=panel, check=check)
    return result.windows, result.exclusions


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _window(day, cid, start, end):
    return dict(date=day.isoformat(), condition_id=cid, start=_iso(start), end=_iso(end))


def windows_for(windows, day):
    """One date's windows as ``stream_source`` intervals: ``((condition_id, start, end), ...)``."""
    return tuple((w["condition_id"], timestamp(w["start"]), timestamp(w["end"]))
                 for w in windows if w["date"] == day.isoformat())


def sources(bundles, windows, *, check=lambda: None):
    """Day sources with declared windows, the sanctioned path to ``stream_source`` for rehearsal.

    Re-derives each bundle's owner-excluded conditions from its own descriptors (no inventory) and
    refuses any window that names one, names a condition the bundle lacks, or leaves the bundle's day.
    """
    rows = owner_exclusions()
    bundles = sorted(bundles, key=lambda b: b.day)
    days = {b.day.isoformat() for b in bundles}
    if any(w["date"] not in days for w in windows):
        raise BundleError("window_outside_bundle")
    result = []
    for bundle in bundles:
        check()
        declared = windows_for(windows, bundle.day)
        excluded = set().union(*excluded_by_descriptor(bundle.conditions, universe_v02.descriptors(bundle), rows))
        envelopes = {c.condition_id: (c.active_from, c.active_until) for c in bundle.conditions}
        for cid, start, end in declared:
            if cid in excluded:
                raise BundleError("owner_excluded_market_date_active")
            if cid not in envelopes or not envelopes[cid][0] <= start < end <= envelopes[cid][1]:
                raise BundleError("window_outside_bundle")
        result.append(stream_source(bundle, declared))
    return result
