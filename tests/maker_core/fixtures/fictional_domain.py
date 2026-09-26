"""Reference plugin: a fictional biased coin, captured before a future toss.

Only imports maker_core.contracts. Copy this pattern to an external domain.
No venue, weather, prices or live inputs. New records are capture-time filtered.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from maker_core.contracts import (
    MarketDescriptor, UniverseSnapshot, OutcomeView, Unavailable,
    InfoEvent, SettlementFact, Pending,
)

T0 = datetime(2030, 1, 1, tzinfo=timezone.utc)


class FictionalDomain:
    def __init__(self):
        self.records = [(T0, .50)]
        self.market = MarketDescriptor(
            "fictional_coin", "toss", "heads", {"YES": "head-token", "NO": "tail-token"},
            Decimal(".01"), Decimal(20), None, T0 + timedelta(days=2),
            T0 + timedelta(days=2, minutes=1), "toss", "0.1", {"rules": "fictional-v1"})

    def ingest_future(self):
        self.records.append((T0 + timedelta(hours=2), .52))

    def discover(self, as_of_utc, horizon_days):
        return UniverseSnapshot((self.market,), as_of_utc, {"rules": "fictional-v1"})

    def describe(self, condition_id, as_of_utc):
        if condition_id != self.market.condition_id:
            raise KeyError(condition_id)
        return self.market

    def evaluate(self, market, as_of_utc):
        available = [r for r in self.records if r[0] <= as_of_utc < r[0] + timedelta(hours=1)]
        if not available:
            return Unavailable("no unexpired captured bias", as_of_utc)
        captured, bias = max(available)
        return OutcomeView(market.condition_id, bias, .015, {"heads": bias, "tails": 1 - bias},
                           captured, captured + timedelta(hours=1), "bias-fixture-v1", "known-bias", "scored")

    def upcoming(self, markets, from_utc, to_utc):
        scheduled = self.market.close_at_utc
        if from_utc <= scheduled <= to_utc:
            return (InfoEvent("toss", scheduled, None, None, ("heads",), 1, None, "pull"),)
        return ()

    def observe(self, markets, as_of_utc):
        if as_of_utc >= self.market.settle_at_utc:
            return (InfoEvent("decided", None, self.market.close_at_utc, self.market.settle_at_utc,
                              ("heads",), 1, {"heads": 1}, "pull"),)
        return ()

    def resolve(self, market, as_of_utc):
        if as_of_utc < market.settle_at_utc:
            return Pending("toss not captured", as_of_utc)
        return SettlementFact(market.condition_id, 1, market.settle_at_utc,
                              {"toss": "fixture-heads"}, "reconciled")
