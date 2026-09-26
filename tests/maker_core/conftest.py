from decimal import Decimal as D
import pytest

from maker_core.quoting.policy import Book, RewardTerms, Portfolio, DecisionInputs
from .fixtures.fictional_domain import FictionalDomain, T0


@pytest.fixture
def inputs():
    plugin = FictionalDomain()
    bids, asks = ((D(".49"), D(100)),), ((D(".51"), D(100)),)
    return DecisionInputs(plugin.market, T0, Book(T0, bids, asks, bids, asks),
                          RewardTerms(T0, D(20), D(3), D(100)),
                          plugin.evaluate(plugin.market, T0),
                          Portfolio(D(200), D(0), D(75), D(60), D(0), D(200), D(0), D(150)),
                          2, hazard_per_minute=.001)
