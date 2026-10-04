"""Fully typed, fictional replay events with controllable clocks and books."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from maker_core.contracts import MarketDescriptor, OutcomeView, SettlementFact
from maker_core.evidence.journal import canonical_bytes, plain
from maker_core.quoting.policy import Book, RewardTerms
from maker_core.replay.bundle import FORMAT, load_bundle, sha256
from .replay_bundle import seal


class Scenario:
    def __init__(self, day=date(2020, 1, 1), markets=("a", "b"), minutes=40):
        self.start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        self.day, self.markets, self.minutes = day, markets, minutes
        self.records = []
        self.descriptors = {}
        self.conditions = []
        for market in markets:
            cid = self.cid(market)
            desc = MarketDescriptor("fictional", "event-" + cid, cid, {"YES": cid+"-y", "NO": cid+"-n"},
                                    D(".01"), D(20), None, self.start+timedelta(days=2),
                                    self.start+timedelta(days=2, minutes=1), None, "fixture", {"fixture": "0"*64})
            self.descriptors[market] = desc
            self.conditions.append(dict(condition_id=cid, market_id=market, domain_id="fictional",
                                        active_from=self.start.isoformat(),
                                        active_until=self.at(minutes*60).isoformat()))
            self.add(market, "descriptor", 0, dict(market=plain(desc), horizon_days=2))
            self.add(market, "info_event", 0, {"events": []})
            self.view(market, 0)
            self.terms(market, 0)

    def at(self, seconds):
        return self.start + timedelta(seconds=seconds)

    def cid(self, market):
        return market + "-" + self.day.isoformat()

    def add(self, market, kind, seconds, payload):
        sequence = max((r["sequence"] for r in self.records), default=-1) + 1
        self.records.append(dict(sequence=sequence, captured_at=self.at(seconds).isoformat(),
                                 condition_id=self.cid(market), kind=kind, payload=plain(payload),
                                 payload_sha256=sha256(canonical_bytes(payload)),
                                 source_hashes={"fixture": sha256(b"typed-110l-synthetic")}))

    def view(self, market, seconds, p=.5, grade="none"):
        view = OutcomeView(self.cid(market), p, .015, None, self.at(seconds), self.at(seconds+3600),
                           sha256(canonical_bytes({"p": p, "seconds": seconds})), "synthetic", grade)
        self.add(market, "outcome_view", seconds, dict(available=True, value=plain(view)))

    def book(self, market, seconds, mid=D(".5"), depth=D(75)):
        self.add(market, "coverage", seconds, dict(trade_stream_ok=True,
                 valid_until_utc=self.at(seconds+60).isoformat()))
        yb, ya = ((mid-D(".01"), depth),), ((mid+D(".01"), depth),)
        nb, na = ((1-mid-D(".01"), depth),), ((1-mid+D(".01"), depth),)
        self.add(market, "book", seconds, Book(self.at(seconds), yb, ya, nb, na))

    def terms(self, market, seconds, minimum=D(20), rate=D(100), spread=D(5)):
        self.add(market, "terms", seconds, RewardTerms(self.at(seconds), minimum, spread, rate))

    def trade(self, market, seconds, price=".47", size="10", outcome="YES", side="SELL", trade_id=None):
        self.add(market, "trade", seconds, dict(trade_id=trade_id or str(len(self.records)), outcome=outcome,
                 price=price, size=size, traded_at_utc=self.at(seconds).isoformat(), aggressor_side=side))

    def settle(self, market, seconds, p=1):
        self.add(market, "settlement", seconds, SettlementFact(self.cid(market), p, self.at(seconds),
                                                              {"synthetic": "0"*64}, "reconciled"))

    def bundle(self, root):
        root.mkdir()
        manifest = dict(format=FORMAT, day=self.day.isoformat(), sealed_at=self.at(86400).isoformat(),
                        provenance="synthetic", conditions=self.conditions, streams=[])
        seal(root, manifest, self.records)
        return load_bundle(root)
