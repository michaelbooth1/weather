"""Fictional 88a-shaped day at the real calibration density, in v0.1 and v0.2 form (maker replay v2, W0).

No captured market, wallet, calibration, panel or settlement data is read; every value is invented.
This extends #166's ``tools/research/pull_cap_precheck/fixture.py`` by a new module and leaves that
file's outputs byte-identical (``tests/maker_core/test_replay_v2_fixture.py`` pins them).

The day follows ``weather.market.maker_replay_bundle.export`` at the exam tree, row for row in kind
and order, at a 170-condition daily union:

- 12 fictional markets in 12 time zones, four target dates each (local T+0..T+3 at the day's start).
  At each market's **local midnight** the T+0 event leaves the export (horizon -1), T+1/T+2 roll to
  T+0/T+1 with a new descriptor, and the new T+2 event is discovered. Band counts are spread so the
  union is exactly ``union``; about three quarters are selected at once, two thirds of them T+1/T+2.
- One capture cycle a minute: one reward row per selected condition at its own clock (a ``terms``
  row whose ``as_of`` is that clock, with a rare body change), and ``ceil(2*D/100)`` books rows, each
  projecting descriptor (on change), book, outcome view (on change), info event (on change), first-
  sight plugin inputs and ledger settlements, then coverage for every condition with a descriptor.
- Trade-stream subscriptions on ``connections`` sockets. Each discovery batch is one subscription,
  so one **coverage group**. A print renews its subscription's 30 s health; an outage drops every
  subscription on its socket until one lifecycle row per subscription reconnects it. Each stream row
  projects coverage for every condition, exactly as the exporter does.

Deliberate simplifications, none of which changes a record kind's per-capture shape: plugin-input
rows are stamped at first sight instead of their original capture; one ledger settlement per rolled
band; books keep ``book_depth`` levels a side; the v0.1 file is written sorted (v0.1 readers sort).
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal as D
import hashlib
import heapq
import math
import random
from zoneinfo import ZoneInfo

from maker_core.contracts import MarketDescriptor, OutcomeView, SettlementFact
from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.quoting.policy import Book, RewardTerms
from maker_core.replay.bundle import sha256

MARKETS = (("city00", "America/New_York"), ("city01", "America/Chicago"), ("city02", "America/Denver"),
           ("city03", "America/Los_Angeles"), ("city04", "America/Toronto"), ("city05", "America/Sao_Paulo"),
           ("city06", "Europe/London"), ("city07", "Europe/Paris"), ("city08", "Asia/Seoul"),
           ("city09", "Asia/Tokyo"), ("city10", "Asia/Hong_Kong"), ("city11", "Asia/Kolkata"))
FICTIONAL = {"fixture": "0" * 64}
HEALTH = timedelta(seconds=30)


@dataclass(frozen=True)
class Band:
    condition_id: str
    market_id: str
    target: date
    index: int
    p_yes: float
    group_id: str


@dataclass(frozen=True)
class Event:
    market_id: str
    tz: ZoneInfo
    target: date
    discovered_at: datetime
    bands: tuple[Band, ...]

    @property
    def slug(self):
        return f"{self.market_id}-{self.target.isoformat()}"


def _cid(market, target, index):
    return "0x" + hashlib.sha256(f"{market}|{target}|{index}".encode()).hexdigest()[:40]


def _payload(value):
    payload = plain(value)
    return payload, sha256(canonical_bytes(payload))


class Day:
    """One fictional UTC day. ``rows()`` yields v0.1 rows in ``(captured_at, sequence)`` order."""

    def __init__(self, day: date, *, union=170, trades=2000, connections=4, outages=2, book_depth=8,
                 view_minutes=10, terms_changes=6, settle_hours=6, seed=0, repeat_views=False,
                 start_minute=0, minutes=1440, mismatch_minute=None):
        if union < 4 * len(MARKETS):
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

    def _events(self, union):
        slots = [(m, k) for m in range(len(MARKETS)) for k in range(4)]
        order = slots[:]
        self.rng.shuffle(order)
        base, extra = divmod(union, len(slots))
        sizes = {slot: base + (i < extra) for i, slot in enumerate(order)}
        events, rolls, subscriptions = [], {}, {}
        for m, (market, zone) in enumerate(MARKETS):
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

    def horizon(self, event, at):
        return (event.target - at.astimezone(event.tz).date()).days

    def live(self, at):
        """Events the exporter projects at ``at``: discovered, horizon 0..2, sorted by slug."""
        return sorted((e for e in self.events if e.discovered_at <= at and 0 <= self.horizon(e, at) <= 2),
                      key=lambda e: e.slug)

    def stats(self):
        """Union, instantaneous and T+1/T+2 counts, sampled every minute; no record is built."""
        counts, far = [], []
        for minute in range(1440):
            at = self.start + timedelta(minutes=minute, seconds=30)
            live = self.live(at)
            counts.append(sum(len(e.bands) for e in live))
            far.append(sum(len(e.bands) for e in live if self.horizon(e, at) >= 1))
        return dict(union=len(self.bands), events=len(self.events), coverage_groups=len(set(self.groups.values())),
                    instantaneous_min=min(counts), instantaneous_max=max(counts),
                    instantaneous_mean=round(sum(counts) / len(counts), 2),
                    t1_t2_share=round(sum(far) / sum(counts), 4),
                    local_midnight_utc={m: r.isoformat() for m, r in sorted(self.rolls.items())})

    # -- timeline -----------------------------------------------------------------------------------
    def _timeline(self):
        rng, out = self.rng, []
        for socket in range(self.connections):
            out.append((self.window[0] + timedelta(milliseconds=100 + 10 * socket), "connect", (socket, None)))
            for _ in range(self.outages):
                drop = self.start + timedelta(seconds=rng.randrange(600, 86000), microseconds=rng.randrange(10**6))
                back = drop + timedelta(seconds=rng.randrange(60, 600))
                out += [(drop, "gap", socket), (back, "connect", (socket, None))]
        for event in self.events:
            if event.discovered_at > self.start:
                out.append((event.discovered_at - timedelta(milliseconds=500), "connect",
                            (self._socket(event), event.bands[0].group_id)))
        for minute in range(1440):
            base = self.start + timedelta(seconds=minute * 60, microseconds=250_000 + rng.randrange(500_000))
            selected = [b.condition_id for e in self.live(base) for b in e.bands]
            for i, cid in enumerate(selected):
                out.append((base + timedelta(seconds=1, microseconds=15_000 * i + rng.randrange(10_000)),
                            "reward", cid))
            for k in range(max(1, math.ceil(2 * len(selected) / 100))):
                out.append((base + timedelta(seconds=3, microseconds=400_000 * k + rng.randrange(100_000)),
                            "books", [c for j, c in enumerate(selected) if j * 2 // 100 == k]))
        for _ in range(self.trades):
            out.append((self.start + timedelta(microseconds=rng.randrange(86_400 * 10**6)), "trade", None))
        out.sort(key=lambda e: e[0])
        return [e for e in out if self.window[0] <= e[0] < self.window[1]]

    # -- rows ---------------------------------------------------------------------------------------
    def rows(self) -> Iterator[dict]:
        rng, sequence, pending = self.rng, 0, []
        last, seen, fetched, terms, books = {}, set(), {}, {}, {}
        subs = {}  # group_id -> [socket, subscribed, connected, healthy_until]
        for e in self.events:
            subs.setdefault(e.bands[0].group_id, [self._socket(e), e.discovered_at == self.start, False, self.start])
        crafted = self.mismatch_minute is not None
        mismatch_at = self.start + timedelta(minutes=self.mismatch_minute or 0)

        def add(cid, kind, at, payload, digest=None, *, changed=False, emitted_at=None):
            nonlocal sequence
            if digest is None:
                payload, digest = _payload(payload)
            if changed and not (self.repeat_views and kind in ("descriptor", "outcome_view")):
                if last.get((cid, kind)) == digest:
                    return
            last[(cid, kind)] = digest
            value = dict(sequence=sequence, captured_at=at.isoformat(), condition_id=cid, kind=kind,
                         payload=payload, payload_sha256=digest, source_hashes=hashes(at))
            sequence += 1
            heapq.heappush(pending, ((at, value["sequence"]), id(value), value))

        def hashes(at):
            return {"sealed_segment": hashlib.sha256(f"segment-{self.day}-{at.hour:02d}".encode()).hexdigest()}

        def coverage(at):
            nonlocal crafted
            states = {}
            for gid, (_, _, connected, until) in subs.items():
                ok = connected and until > at
                states[gid] = _payload(dict(trade_stream_ok=ok, valid_until_utc=min(until, at + HEALTH) if ok
                                            else at + HEALTH))
            flip = None
            if crafted and at >= mismatch_at:
                group = max((g for g in states if sum(self.groups[c] == g for c in seen) >= 2),
                            key=lambda g: (sum(self.groups[c] == g for c in seen), g), default=None)
                if group is not None:
                    flip = sorted(c for c in seen if self.groups[c] == group)[1]
                    crafted = False
            for cid in sorted(seen):
                payload, digest = states[self.groups[cid]]
                if cid == flip:
                    payload, digest = _payload(dict(payload, trade_stream_ok=not payload["trade_stream_ok"]))
                add(cid, "coverage", at, payload, digest)

        def body(cid, minute):
            change = sum(1 for m in self.terms_change[cid] if m <= minute)
            return D(20 if change % 2 == 0 else 50), D("3.5") + D(change % 3), D(50 + 25 * (change % 4))

        def book(cid, at):
            bid = D("0.01") * (1 + int(self.bands[cid].p_yes * 97) + rng.randrange(-1, 2))
            bid = min(max(bid, D("0.01")), D("0.97"))
            levels = [(bid - D("0.01") * i, D(10 + rng.randrange(200))) for i in range(self.book_depth)]
            asks = [(bid + D("0.02") + D("0.01") * i, D(10 + rng.randrange(200))) for i in range(self.book_depth)]
            levels = [(p, s) for p, s in levels if p > 0]
            asks = [(p, s) for p, s in asks if p < 1]
            return _payload(Book(at, levels, asks, [(1 - p, s) for p, s in asks], [(1 - p, s) for p, s in levels]))

        def view(cid, at):
            minute = (at - self.start) // timedelta(minutes=1)
            as_of = self.start + timedelta(minutes=minute - minute % self.view_minutes)
            p = min(.999, max(.001, self.bands[cid].p_yes + .01 * math.sin((minute - minute % self.view_minutes) / 97)))
            return dict(available=True, value=OutcomeView(cid, round(p, 6), .015, None, as_of, as_of + timedelta(hours=1),
                                                          sha256(f"{cid}{as_of}".encode()), "fixture", "none"))

        for at, kind, value in self._timeline():
            while pending and pending[0][0] < (at, sequence):
                yield heapq.heappop(pending)[2]
            minute = (at - self.start) // timedelta(minutes=1)
            if kind == "reward":
                terms[value] = RewardTerms(at, *body(value, minute))
                if value in seen:
                    add(value, "terms", at, terms[value], changed=True)
                continue
            if kind == "books":
                for cid in value:
                    fetched[cid] = at
                    books[cid] = book(cid, at)
                for event in self.live(at):
                    horizon = self.horizon(event, at)
                    for band in event.bands:
                        cid = band.condition_id
                        add(cid, "descriptor", at, self._descriptor(event, band, horizon), changed=True)
                        seen.add(cid)
                        if cid not in books:
                            fetched[cid], books[cid] = at, book(cid, at)
                        add(cid, "book", at, *books[cid])
                        if cid in terms:
                            add(cid, "terms", at, terms[cid], changed=True)
                        add(cid, "outcome_view", at, view(cid, at), changed=True)
                        add(cid, "info_event", at, {"events": []}, changed=True)
                        if (cid, "plugin_input") not in last:
                            self._first_sight(add, event, band, at)
                coverage(at)
                continue
            if kind == "trade":
                candidates = sorted(seen)
                if not candidates:
                    continue
                cid = candidates[rng.randrange(len(candidates))]
                sub = subs[self.groups[cid]]
                if not sub[2]:
                    continue
                sub[3] = at + HEALTH
                add(cid, "trade", at, dict(trade_id=f"t{sequence}", outcome=rng.choice(("YES", "NO")),
                                           price=str(D("0.01") * rng.randrange(1, 100)), size=str(rng.randrange(1, 500)),
                                           traded_at_utc=(at - timedelta(milliseconds=rng.randrange(800))).isoformat(),
                                           aggressor_side=rng.choice(("BUY", "SELL"))))
                coverage(at)
                continue
            if kind == "gap":
                for sub in subs.values():
                    if sub[0] == value:
                        sub[2] = False
                coverage(at)
                continue
            socket, only = value  # a new subscription, or one lifecycle row per subscription on the socket
            if only:
                subs[only][1] = True
            for offset, gid in enumerate([only] if only else sorted(g for g, s in subs.items()
                                                                     if s[0] == socket and s[1])):
                when = at + timedelta(microseconds=offset)
                subs[gid][2:] = [True, when + HEALTH]
                coverage(when)
        while pending:
            yield heapq.heappop(pending)[2]

    def _socket(self, event):
        return [m for m, _ in MARKETS].index(event.market_id) % self.connections

    def _descriptor(self, event, band, horizon):
        close = datetime.combine(event.target + timedelta(days=1), time(), tzinfo=event.tz).astimezone(timezone.utc)
        market = MarketDescriptor("fictional", "event-" + event.slug, band.condition_id,
                                  {"YES": band.condition_id + "-y", "NO": band.condition_id + "-n"}, D(".01"), D(5),
                                  "event-" + event.slug, close, close + timedelta(minutes=1), "F", "fixture",
                                  FICTIONAL, "partition")
        return dict(market=market, horizon_days=horizon, exposure_factors={f"market:{event.market_id}": "1"})

    def _first_sight(self, add, event, band, at):
        for source in ("snapshots", "source_rows", "forecasts"):
            add(band.condition_id, "plugin_input", at,
                dict(source=source, original_captured_at=at, record=dict(event_slug=event.slug, band=band.index,
                     values=[round(band.p_yes + i / 1000, 6) for i in range(24)])))
        roll = self.rolls[event.market_id]
        recorded = roll + timedelta(hours=self.settle_hours, seconds=band.index)
        if event.target < roll.astimezone(event.tz).date() and recorded < self.end:
            winner = max(event.bands, key=lambda b: b.p_yes)
            fact = SettlementFact(band.condition_id, 1.0 if band is winner else 0.0, recorded, FICTIONAL,
                                  "reconciled", str(band.index))
            add(band.condition_id, "settlement", max(at, recorded), fact)

    def conditions(self):
        return [dict(condition_id=cid, market_id=b.market_id, domain_id="fictional",
                     active_from=self.start.isoformat(), active_until=self.end.isoformat())
                for cid, b in sorted(self.bands.items())]

    def coverage_groups(self):
        members = {}
        for cid, gid in sorted(self.groups.items()):
            members.setdefault(gid, []).append(cid)
        return [dict(group_id=g, condition_ids=c) for g, c in sorted(members.items())]
