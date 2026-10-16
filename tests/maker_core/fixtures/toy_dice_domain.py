"""A second, non-weather reference plugin: two fair dice, "does the sum reach 8?".

It is a toy for the item-330 frontier end-to-end test. It imports only maker_core.contracts and the
standard library, uses no venue, weather, price or live input, and every value is synthetic. The roll is
drawn from a seeded ``random.Random``, so the settlement is reproducible.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import random

from maker_core.contracts import MarketDescriptor, OutcomeView, Pending, SettlementFact, Unavailable

T0 = datetime(2030, 3, 4, tzinfo=timezone.utc)
P_SUM_AT_LEAST_8 = 15 / 36


class ToyDiceDomain:
    def __init__(self, seed: int = 8):
        self.seed = seed
        self.market = MarketDescriptor(
            "toy_dice", "roll-1", "dice-sum-8", {"YES": "dice-yes-token", "NO": "dice-no-token"},
            Decimal(".01"), Decimal(20), None, T0 + timedelta(hours=6), T0 + timedelta(hours=6, minutes=5),
            "pips", "0.1", {"rules": "two-fair-dice"})

    def describe(self, condition_id, as_of_utc):
        if condition_id != self.market.condition_id:
            raise KeyError(condition_id)
        return self.market

    def evaluate(self, market, as_of_utc):
        if as_of_utc < T0:
            return Unavailable("dice not yet described", as_of_utc)
        return OutcomeView(market.condition_id, P_SUM_AT_LEAST_8, .01,
                           {"sum>=8": P_SUM_AT_LEAST_8, "sum<8": 1 - P_SUM_AT_LEAST_8},
                           as_of_utc, as_of_utc + timedelta(hours=1), "dice-combinatorics", "exact", "none")

    def roll(self):
        rng = random.Random(self.seed)
        return rng.randint(1, 6) + rng.randint(1, 6)

    def resolve(self, market, as_of_utc):
        if as_of_utc < market.settle_at_utc:
            return Pending("dice not rolled", as_of_utc)
        return SettlementFact(market.condition_id, 1.0 if self.roll() >= 8 else 0.0, market.settle_at_utc,
                              {"roll": "seeded"}, "reconciled")
