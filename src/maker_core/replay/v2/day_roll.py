"""The day-roll reader: a derived descriptor at each market's local midnight (engine ruling F3, registration C13).

Shadow-gate spec v3.2 §4.3 and v3.3 §1, §3.1, §4. A captured descriptor carries the lead the plugin computed at
capture (``horizon_days``, ``universe.py:149``), and the next one may follow 15-120 minutes after the market's
local date has changed. At each local midnight this reader therefore synthesises one ``descriptor`` item for
every condition of that market whose latest descriptor precedes the midnight:

- it equals that latest descriptor except ``horizon_days = local_lead(zone, target, midnight)``, where the target
  date is the local date of the latest captured descriptor plus its ``horizon_days`` (the plugin's rule inverted);
- it is flagged ``derived = "local_midnight"`` and its payload hash is
  ``sha256(canonical_bytes({"derived": "local_midnight", "from": <prior payload hash>, "horizon_days": n}))``;
- a condition whose new lead is outside 0..2 gets no refresh (it is out of scope);
- within one instant it precedes every regular record (v3.3 §3.1: trades, reopen, derived, regular), so a
  captured descriptor at the same instant overrides it. (This engine applies no reopen records.)

Descriptors are not wake sources (``kernel.record_signature``), so a refresh changes the horizon read at the
next wake and adds no decision of its own. The reader is a pure function of the day's records and the market
time zones; the time-zone map is required (``lockstep.drive``) and ``NO_REFRESH`` exists only for the
attribution re-run of the pre-F3 engine (``tools.research.maker_replay_v2.attribution``).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import heapq
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay.bundle import BundleError, sha256

DERIVED = "local_midnight"
SCOPE = range(0, 3)  # leads 0..2


class _NoRefresh:
    def __repr__(self):
        return "NO_REFRESH"


NO_REFRESH = _NoRefresh()


def _zone(name) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise BundleError("unknown_time_zone") from exc


def local_lead(zone, target_date: date, instant: datetime) -> int:
    """The only lead function: ``(target_date - the local date at instant).days`` (v3.3 §1)."""
    return (target_date - instant.astimezone(_zone(zone) if isinstance(zone, str) else zone).date()).days


def next_local_midnight(zone, instant: datetime) -> datetime:
    """The first local midnight strictly after ``instant``, in UTC (a nonexistent midnight maps by fold 0)."""
    tz = _zone(zone) if isinstance(zone, str) else zone
    local = instant.astimezone(tz).date() + timedelta(days=1)
    return datetime.combine(local, time(), tzinfo=tz).astimezone(timezone.utc)


def derived_sha(prior_sha: str, horizon: int) -> str:
    return sha256(canonical_bytes({"derived": DERIVED, "from": prior_sha, "horizon_days": horizon}))


def _instant(derived, regular):
    """Items of one instant: derived local-midnight descriptors before regular records (v3.3 §3.1)."""
    return [*derived, *regular]


class DayRoll:
    """Stateful across the days of one run: feed it each day's source in date order (``lockstep.drive``)."""

    def __init__(self, time_zones: Mapping):
        self.zones = {market: _zone(name) for market, name in dict(time_zones).items()}
        self.tracked = {}  # condition_id -> [zone, target, value, sha, next_midnight]
        self.emitted = []  # (instant, condition_id, horizon_days, payload_sha256)
        self.soonest = None  # the earliest pending midnight of a condition of the current day

    def _track(self, cid, market, item, at):
        if item.error is not None:
            self.tracked.pop(cid, None)
            return
        zone = self.zones.get(market)
        if zone is None:
            raise BundleError("market_time_zone_unknown")
        target = at.astimezone(zone).date() + timedelta(days=item.value.horizon_days)
        self.tracked[cid] = entry = [zone, target, item.value, item.payload_sha256, next_local_midnight(zone, at)]
        if self.soonest is None or entry[4] < self.soonest:
            self.soonest = entry[4]

    def _due(self, until, inclusive, day_end, present):
        """Derived items for midnights before ``until`` (or at it), grouped by instant, in instant order."""
        heap = [(entry[4], cid) for cid, entry in self.tracked.items() if cid in present]
        heapq.heapify(heap)
        groups = {}
        while heap and (heap[0][0] < until or (inclusive and heap[0][0] == until)) and heap[0][0] < day_end:
            midnight, cid = heapq.heappop(heap)
            entry = self.tracked[cid]
            zone, target, value, sha = entry[:4]
            lead = local_lead(zone, target, midnight)
            entry[4] = next_local_midnight(zone, midnight)
            heapq.heappush(heap, (entry[4], cid))
            if lead not in SCOPE:
                continue
            new = replace(value, horizon_days=lead)
            new_sha = derived_sha(sha, lead)
            entry[2], entry[3] = new, new_sha
            groups.setdefault(midnight, []).append((cid, new, new_sha))
        self.soonest = heap[0][0] if heap else None
        return sorted(groups.items())

    def items(self, source):
        from maker_core.replay.v2.lockstep import Item, items
        plan = source.plan
        start = plan.start
        day_end = start + timedelta(days=1)
        markets = {c.condition_id: c.market_id for c in plan.conditions}
        present = set(markets)
        for entry in self.tracked.values():  # no midnight is emitted outside a planned day
            while entry[4] < start:
                entry[4] = next_local_midnight(entry[0], entry[4])
        self.soonest = min((e[4] for c, e in self.tracked.items() if c in present), default=None)

        def derived(group):
            return [Item(cid, "descriptor", sha, value, None, -1, DERIVED) for cid, value, sha in sorted(group)]

        for at, batch in items(source):
            extra = []
            if self.soonest is None or self.soonest > at:
                for item in batch:
                    if item.kind == "descriptor":
                        self._track(item.condition_id, markets.get(item.condition_id), item, at)
                yield at, batch
                continue
            for midnight, group in self._due(at, False, day_end, present):
                self._emit(midnight, group)
                yield midnight, derived(group)
            same = self._due(at, True, day_end, present)
            if same:
                (midnight, group), = same
                self._emit(midnight, group)
                extra = derived(group)
            for item in batch:
                if item.kind == "descriptor":
                    self._track(item.condition_id, markets.get(item.condition_id), item, at)
            yield at, _instant(extra, batch)
        for midnight, group in self._due(day_end, False, day_end, present):
            self._emit(midnight, group)
            yield midnight, derived(group)

    def _emit(self, midnight, group):
        self.emitted.extend((midnight, cid, value.horizon_days, sha) for cid, value, sha in sorted(group))
