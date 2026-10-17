"""89a fill predicate behind a neutral facade; price-path bounds, not own fills."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from maker_core.quoting.policy import QuoteLeg
from maker_core.replay._fill89a import filled_size
from maker_core.replay.payloads import Trade

BOUNDS = ("strictly_through", "at_price")


@dataclass(frozen=True)
class Fill:
    at: datetime  # Public print availability; decisions remain capture-ordered.
    traded_at: datetime
    condition_id: str
    market_id: str
    trade_id: str
    outcome: str
    price: Decimal
    size: Decimal
    bound: str
    in_event_window: bool

    @property
    def cost(self):
        return self.price * self.size


def match(legs: tuple[QuoteLeg, ...], trade: Trade, bound: str):
    if bound not in BOUNDS:
        raise ValueError("unknown fill bound")
    # Normalize either token's trade to a YES-axis price. A NO buy is the YES
    # ask equivalent, with complementary cost. 89a's predicate is price-path
    # based and does not claim an aggressor proves our queue position.
    price = trade.price if trade.outcome == "YES" else 1 - trade.price
    for leg in legs:
        side = 0 if leg.outcome == "YES" else 1
        quote = leg.price if side == 0 else 1 - leg.price
        size = filled_size(quote, leg.size, price, trade.size, side,
                           "conservative" if bound == "strictly_through" else "optimistic")
        if size > 0:
            return leg, size
    return None
