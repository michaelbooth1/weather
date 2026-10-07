"""A quoting-dense fictional day for the v2 differential tests (S5) and engine tests. Every value is invented.

W0's day (``fixture170``) is faithful to the exporter, but ``informed-v0`` almost never quotes on it
(trade-health and book-age gaps dominate), so a differential on it alone would barely exercise legs,
fills, replacements and running totals. Here every condition has a fresh book most minutes, re-projected
20 s later as the exporter repeats books; views that agree with the mid at all three calibration grades;
group-identical coverage every 20 s with outages; terms changes; pull, widen and decided events; prints
that cross resting quotes; a horizon change; last-three-hours boundaries; and settlements. Rows are
exporter-ordered v0.1 (coverage as one consecutive condition-ID run per capture), so
``maker_core.replay.v2.compaction.compact`` turns them into v0.2.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal as D
import hashlib
import random

from maker_core.contracts import InfoEvent, MarketDescriptor, OutcomeView, SettlementFact
from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.quoting.policy import Book, RewardTerms
from tools.research.maker_replay_v2.fixture170 import MARKETS

FICTIONAL = {"fixture": "0" * 64}


class DenseDay:
    def __init__(self, day, *, union=40, trades=2000, start_minute=600, minutes=60, seed=0, group_size=8):
        self.day, self.trades = day, trades
        self.rng = random.Random(f"dense-{day}-{union}-{trades}-{seed}")
        self.start = datetime.combine(day, time(), tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        self.window = (self.start + timedelta(minutes=start_minute),
                       self.start + timedelta(minutes=start_minute + minutes))
        n_markets = max(1, min(len(MARKETS), round(union / (170 / len(MARKETS)))))
        self.bands = {}
        for i in range(union):
            market = MARKETS[i % n_markets][0]
            # Condition IDs do not depend on the date, so a multi-day run carries the same bands.
            cid = "0x" + hashlib.sha256(f"dense|{union}|{i}".encode()).hexdigest()[:40]
            self.bands[cid] = dict(index=i, market=market, event=f"event-{market}-{i % 3}",
                                   mid=D("0.30") + D("0.01") * self.rng.randrange(0, 41))
        ordered = sorted(self.bands)
        self.groups = {cid: f"g{n // group_size:03d}" for n, cid in enumerate(ordered)}
        self._replay = self.rng.getstate(), {cid: b["mid"] for cid, b in self.bands.items()}

    def conditions(self):
        return [dict(condition_id=cid, market_id=b["market"], domain_id="fictional",
                     active_from=self.start.isoformat(), active_until=self.end.isoformat())
                for cid, b in sorted(self.bands.items())]

    def coverage_groups(self):
        members = {}
        for cid, gid in sorted(self.groups.items()):
            members.setdefault(gid, []).append(cid)
        return [dict(group_id=g, condition_ids=c) for g, c in sorted(members.items())]

    def stats(self):
        return dict(kind="dense", union=len(self.bands), coverage_groups=len(set(self.groups.values())))

    def _descriptor(self, cid, horizon, close):
        b = self.bands[cid]
        market = MarketDescriptor("fictional", b["event"], cid, {"YES": cid + "-y", "NO": cid + "-n"}, D(".01"), D(5),
                                  b["event"], close, close + timedelta(minutes=1), "F", "fixture", FICTIONAL,
                                  "partition")
        return dict(market=market, horizon_days=horizon,
                    exposure_factors={f"market:{b['market']}": "1", "weather:all": "1"})

    def rows(self):
        """The day's rows; every call yields the same rows (the generator state is restored first)."""
        state, mids = self._replay
        self.rng.setstate(state)
        for cid, mid in mids.items():
            self.bands[cid]["mid"] = mid
        rng, (w0, w1) = self.rng, self.window
        span = int((w1 - w0).total_seconds())
        out = []

        def add(at, cid, kind, payload):
            payload = plain(payload)
            out.append(((at, len(out)), dict(captured_at=at.isoformat(), condition_id=cid, kind=kind, payload=payload,
                                              payload_sha256=hashlib.sha256(canonical_bytes(payload)).hexdigest(),
                                              source_hashes=FICTIONAL)))

        ordered = sorted(self.bands)
        close, settle, roll = {}, {}, {}
        for i, cid in enumerate(ordered):
            # A fifth of the bands reach their last three hours inside the window; some roll or settle in it.
            close[cid] = (w0 + timedelta(hours=3, seconds=rng.randrange(span)) if i % 5 == 0
                          else self.end + timedelta(days=1))
            settle[cid] = w0 + timedelta(seconds=rng.randrange(span)) if i % 10 == 3 else None
            roll[cid] = w0 + timedelta(seconds=rng.randrange(span)) if i % 7 == 2 else None
        for cid in ordered:
            add(w0, cid, "descriptor", self._descriptor(cid, 2 if self.bands[cid]["index"] % 2 else 1, close[cid]))
            add(w0, cid, "terms", RewardTerms(w0, D(20), D("3.5"), D(100)))
            add(w0, cid, "info_event", {"events": []})
            add(w0, cid, "plugin_input", dict(source="fixture", original_captured_at=w0, record=dict(i=1)))
        health, minute, at = {}, 0, w0
        while at < w1:
            for cid in ordered:
                b = self.bands[cid]
                b["mid"] = min(D("0.70"), max(D("0.30"), b["mid"] + D("0.01") * rng.choice((-4, -1, 0, 0, 0, 0, 1, 4))))
                when = at + timedelta(seconds=2 + rng.randrange(3), microseconds=rng.randrange(10**6))
                if rng.random() < .97:
                    mid, depth = b["mid"], D(38 + rng.randrange(25))
                    for fetched in (when, when + timedelta(seconds=30)):  # two fetches a minute
                        book = Book(fetched, ((mid - D(".01"), depth), (mid - D(".02"), depth)),
                                    ((mid + D(".01"), depth), (mid + D(".02"), depth)),
                                    ((1 - mid - D(".01"), depth), (1 - mid - D(".02"), depth)),
                                    ((1 - mid + D(".01"), depth), (1 - mid + D(".02"), depth)))
                        add(fetched, cid, "book", book)
                        add(fetched + timedelta(seconds=20), cid, "book", book)  # the exporter's re-projection
                if minute % 5 == 0:
                    grade = ("none", "shadow", "scored")[(b["index"] + minute // 5) % 3]
                    view = OutcomeView(cid, float(b["mid"]) + rng.choice((-.005, 0, .005)), .02, None, when,
                                       when + timedelta(minutes=30 + rng.randrange(30)),
                                       hashlib.sha256(f"{cid}{when}".encode()).hexdigest(), "fixture", grade)
                    add(when, cid, "outcome_view", dict(available=True, value=view))
                if rng.random() < .01:
                    add(when, cid, "terms", RewardTerms(when, D(rng.choice((20, 50))), D(rng.choice(("3.5", "4.5"))),
                                                        D(rng.choice((60, 100, 150)))))
                if rng.random() < .004:
                    scheduled = when + timedelta(minutes=rng.randrange(2, 8))
                    event = InfoEvent("scheduled_print", scheduled, None, None, (cid,), .5, None,
                                      rng.choice(("pull", "widen", "observe")),
                                      active_until_utc=scheduled + timedelta(minutes=4))
                    add(when, cid, "info_event", {"events": [event]})
                if rng.random() < .0008:
                    add(when, cid, "info_event", {"events": [InfoEvent("decided", None, when, when, (cid,), 1,
                                                                       {cid: .9}, "observe")]})
                if roll[cid] is not None and at <= roll[cid] < at + timedelta(minutes=1):
                    add(roll[cid], cid, "descriptor", self._descriptor(cid, 0 if b["index"] % 2 == 0 else 1, close[cid]))
                if settle[cid] is not None and at <= settle[cid] < at + timedelta(minutes=1):
                    add(settle[cid], cid, "settlement", SettlementFact(cid, float(b["index"] % 2), settle[cid],
                                                                        FICTIONAL, "reconciled"))
            for k in range(3):  # coverage every 20 s: one row per condition, identical within a group
                capture = at + timedelta(seconds=20 * k + 10, microseconds=k)
                for gid in sorted(set(self.groups.values())):
                    if gid not in health or rng.random() < .99:
                        health[gid] = (rng.random() > .01, capture + timedelta(seconds=30))
                for cid in ordered:
                    ok, until = health[self.groups[cid]]
                    add(capture, cid, "coverage", dict(trade_stream_ok=ok,
                                                       valid_until_utc=min(until, capture + timedelta(seconds=30))))
            for _ in range(rng.randrange(2 * self.trades // 1440 + 2)):
                cid = ordered[rng.randrange(len(ordered))]
                when = at + timedelta(seconds=rng.randrange(60), microseconds=rng.randrange(10**6))
                outcome = rng.choice(("YES", "NO"))
                mid = self.bands[cid]["mid"]
                price = min(D(".99"), max(D(".01"), (mid if outcome == "YES" else 1 - mid) + D("0.01") * rng.randrange(-4, 3)))
                add(when, cid, "trade", dict(trade_id=f"t{self.day}-{len(out)}", outcome=outcome, price=str(price),
                                             size=str(rng.randrange(1, 60)),
                                             traded_at_utc=(when - timedelta(milliseconds=rng.randrange(500))).isoformat(),
                                             aggressor_side=rng.choice(("BUY", "SELL"))))
            minute += 1
            at += timedelta(minutes=1)
        out.sort(key=lambda r: r[0])
        for number, (_, value) in enumerate(out):
            value["sequence"] = number
            yield {"sequence": number, **value}


def _levels(*rows):
    return tuple((D(p), D(s)) for p, s in rows)


class OnLevelReplacementDay(DenseDay):
    """One fictional band whose resting legs sit ON public price levels when a replacement-reason CANCEL fires.

    The W2(a) attribution fixture (registration C12): before W2 the same-instant replacement decided on the
    frozen T2 book, which adds the cancelled size only at existing public levels, so on the dense days W2 alone
    changed nothing. Here ``informed-v0`` quotes YES and NO at 0.47 on ``BOOK`` (a view at 0.50, stdev 0.025,
    shadow grade; only the 0.47/0.53 levels qualify for the size-qualified mid). At minute ``MOVED`` the public
    book becomes ``MOVED_BOOK``: the mid falls to 0.49, the NO leg leaves the requote window
    (``OUTSIDE_REQUOTE_WINDOW``) and the replacement decides at the same instant, with the YES leg's 0.47 and the
    NO leg's mirror 0.53 still public levels. No trade prints, so nothing fills. Every value is invented.
    """

    MARKET = "city06"  # Europe/London: no local midnight inside the window
    MOVED = 3
    BOOK = dict(yb=_levels((".49", 5), (".47", 80)), ya=_levels((".51", 5), (".53", 80)),
                nb=_levels((".49", 5), (".47", 80)), na=_levels((".51", 5), (".53", 80)))
    MOVED_BOOK = dict(yb=_levels((".48", 5), (".47", 5), (".46", 80)), ya=_levels((".50", 5), (".52", 80), (".53", 5)),
                      nb=_levels((".50", 5), (".48", 80), (".47", 5)), na=_levels((".52", 5), (".53", 5), (".54", 80)))

    def __init__(self, day, *, start_minute=600, minutes=6):
        self.day, self.trades = day, 0
        self.start = datetime.combine(day, time(), tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        self.window = (self.start + timedelta(minutes=start_minute),
                       self.start + timedelta(minutes=start_minute + minutes))
        cid = "0x" + hashlib.sha256(b"w2-on-level").hexdigest()[:40]
        self.bands = {cid: dict(index=1, market=self.MARKET, event=f"event-{self.MARKET}-w2", mid=D("0.50"))}
        self.groups = {cid: "g000"}

    def rows(self):
        (cid,), (w0, w1) = tuple(self.bands), self.window
        out = []

        def add(at, kind, payload):
            payload = plain(payload)
            out.append(dict(captured_at=at.isoformat(), condition_id=cid, kind=kind, payload=payload,
                            payload_sha256=hashlib.sha256(canonical_bytes(payload)).hexdigest(),
                            source_hashes=FICTIONAL))

        add(w0, "descriptor", self._descriptor(cid, 1, self.end + timedelta(days=1)))
        add(w0, "terms", RewardTerms(w0, D(20), D("3.5"), D(100)))
        add(w0, "info_event", {"events": []})
        add(w0, "plugin_input", dict(source="fixture", original_captured_at=w0, record=dict(i=1)))
        seen = w0 + timedelta(seconds=1)
        add(seen, "outcome_view", dict(available=True, value=OutcomeView(
            cid, .50, .025, None, seen, seen + timedelta(hours=1), hashlib.sha256(b"w2-view").hexdigest(),
            "fixture", "shadow")))
        minute = 0
        while w0 + timedelta(minutes=minute) < w1:
            at = w0 + timedelta(minutes=minute, seconds=2)
            # Coverage may run at most 60 s past its capture (payloads.decode); the next minute's row renews it.
            add(at - timedelta(seconds=1), "coverage", dict(trade_stream_ok=True,
                                                            valid_until_utc=at + timedelta(seconds=59)))
            sides = self.BOOK if minute < self.MOVED else self.MOVED_BOOK
            add(at, "book", Book(at, sides["yb"], sides["ya"], sides["nb"], sides["na"]))
            minute += 1
        for number, row in enumerate(out):
            yield {"sequence": number, **row}
