"""Fictional day sources for the v2 engine: W0's fixture at any band count, in v0.1 or v0.2 form, in memory.

``ScaledDay`` is W0's ``fixture170.Day`` with the market count as a parameter, so a day can have fewer
than 48 bands (S5 at B = 12 and S3 at B = 40). With 12 markets it is ``Day`` itself, row for row; the
W0 module is not edited. Every value is invented; nothing captured is read.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import hashlib
import math
import random
from types import MappingProxyType
from zoneinfo import ZoneInfo

from maker_core.replay.bundle import Condition, timestamp
from maker_core.replay.v2.compaction import compact
from maker_core.replay.v2.lockstep import DayPlan, DaySource, record_from_row, windows_of
from tools.research.maker_replay_v2.fixture170 import MARKETS, Band, Day, Event, _cid


# The fictional markets' IANA zones, for the local-midnight refresh (``maker_core.replay.v2.day_roll``).
FIXTURE_ZONES = MappingProxyType(dict(MARKETS))


def market_count(union):
    """About 3.5 bands an event, as at the real 170-band union with 12 markets x 4 events."""
    return max(1, min(len(MARKETS), round(union / (170 / len(MARKETS)))))


class ScaledDay(Day):
    def __init__(self, day, *, union=170, markets=None, trades=2000, connections=4, outages=2, book_depth=8,
                 view_minutes=10, terms_changes=6, settle_hours=6, seed=0, repeat_views=False, start_minute=0,
                 minutes=1440, mismatch_minute=None):
        self.markets = MARKETS[:markets or market_count(union)]
        if union < 4 * len(self.markets):
            raise ValueError("union_below_one_band_per_event")
        self.day, self.trades, self.connections, self.outages = day, trades, connections, outages
        self.book_depth, self.view_minutes, self.repeat_views = book_depth, view_minutes, repeat_views
        self.settle_hours, self.mismatch_minute = settle_hours, mismatch_minute
        self.rng = random.Random(f"mrv2-{day}-{union}-{trades}-{connections}-{seed}")
        self.start = datetime.combine(day, time(), tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        self.window = (self.start + timedelta(minutes=start_minute),
                       self.start + timedelta(minutes=start_minute + minutes))
        self.events, self.rolls = self._events(union)
        self.bands = {b.condition_id: b for e in self.events for b in e.bands}
        self.groups = {cid: b.group_id for cid, b in self.bands.items()}
        self.terms_change = {cid: sorted(self.rng.randrange(1440) for _ in range(terms_changes))
                             for cid in sorted(self.bands)}
        self._state = self.rng.getstate()

    def rows(self):
        """W0's rows; unlike ``Day.rows`` every call yields the same rows (the generator state is restored)."""
        self.rng.setstate(self._state)
        yield from super().rows()

    def _events(self, union):
        slots = [(m, k) for m in range(len(self.markets)) for k in range(4)]
        order = slots[:]
        self.rng.shuffle(order)
        base, extra = divmod(union, len(slots))
        sizes = {slot: base + (i < extra) for i, slot in enumerate(order)}
        events, rolls, subscriptions = [], {}, {}
        for m, (market, zone) in enumerate(self.markets):
            tz = ZoneInfo(zone)
            local0 = self.start.astimezone(tz).date()
            roll = datetime.combine(local0 + timedelta(days=1), time(), tzinfo=tz).astimezone(timezone.utc)
            rolls[market] = roll
            for k in range(4):
                target = local0 + timedelta(days=k)
                discovered = self.start if k < 3 else roll + timedelta(seconds=60 + self.rng.randrange(60))
                socket = m % self.connections
                batch = 0 if k < 3 else 1 + sum(1 for (s, b) in subscriptions if s == socket and b)
                gid = f"sub{socket}-{batch}"
                subscriptions[(socket, batch)] = gid
                n = sizes[(m, k)]
                centre = self.rng.uniform(0, n - 1)
                weights = [math.exp(-((i - centre) ** 2) / 2) for i in range(n)]
                bands = tuple(Band(_cid(market, target, i), market, target, i, round(w / sum(weights), 6), gid)
                              for i, w in enumerate(weights))
                events.append(Event(market, tz, target, discovered, bands))
        return tuple(events), rolls

    def _socket(self, event):
        return [m for m, _ in self.markets].index(event.market_id) % self.connections


def plan_of(day: Day) -> DayPlan:
    conditions = tuple(Condition(c["condition_id"], c["market_id"], c["domain_id"], timestamp(c["active_from"]),
                                 timestamp(c["active_until"])) for c in day.conditions())
    groups = MappingProxyType({g["group_id"]: tuple(g["condition_ids"]) for g in day.coverage_groups()})
    hashes = MappingProxyType({"fixture": hashlib.sha256(f"{day.day}|{len(day.bands)}".encode()).hexdigest()})
    return DayPlan(day.day, conditions, windows_of(conditions, None), groups, "synthetic", hashes)


def materialize(day: Day, form="v0.2"):
    """Records of one fictional day in memory, in exporter order; v0.2 compacts coverage into groups."""
    rows = day.rows()
    if form == "v0.2":
        rows = compact(rows, day.groups)
    elif form != "v0.1":
        raise ValueError("unknown form")
    records = [record_from_row(r) for r in rows]
    return DaySource(plan_of(day), lambda: iter(records)), len(records)


def regrouped(day: Day, groups):
    """The same day with another coverage grouping (``groups``: condition -> group); same events."""
    plan = plan_of(day)
    members = {}
    for cid, gid in sorted(groups.items()):
        members.setdefault(gid, []).append(cid)
    plan = DayPlan(plan.day, plan.conditions, plan.windows,
                   MappingProxyType({g: tuple(c) for g, c in sorted(members.items())}), plan.provenance,
                   plan.input_hashes)
    records = [record_from_row(r) for r in compact(day.rows(), groups)]
    return DaySource(plan, lambda: iter(records))
