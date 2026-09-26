from dataclasses import replace, fields
from datetime import timedelta, timezone
from decimal import Decimal
import pytest

from maker_core.contracts import CONTRACTS_VERSION, OutcomeView, InfoEvent
from maker_core.contracts.conformance import check_conformance, FixtureClock
from .fixtures.fictional_domain import FictionalDomain, T0


def test_reference_plugin_conforms():
    plugin = FictionalDomain()
    check_conformance(universe=plugin, fair_value=plugin, information=plugin, settlement=plugin,
                      clock=FixtureClock(T0, T0 - timedelta(seconds=1), T0 + timedelta(days=3)),
                      advance_inputs=plugin.ingest_future)
    assert CONTRACTS_VERSION == "0.1"
    assert not {"mid", "market_price", "price"} & {f.name for f in fields(OutcomeView)}


@pytest.mark.parametrize("changes", [
    {"p_yes": -1}, {"p_yes": float("nan")}, {"p_yes": float("inf")},
    {"stdev": 0}, {"stdev": float("nan")}, {"stdev": -1},
    {"valid_until_utc": T0}, {"as_of_utc": T0.replace(tzinfo=None)},
    {"as_of_utc": T0.astimezone(timezone(timedelta(hours=1)))},
    {"joint": {"heads": .5, "tails": .6}}, {"joint": {"heads": .6, "tails": .4}},
    {"joint": {"heads": float("nan")}}, {"calibration_grade": "trusted"},
])
def test_bad_views_fail(changes):
    p = FictionalDomain()
    with pytest.raises(ValueError):
        replace(p.evaluate(p.market, T0), **changes)


def test_maps_are_deeply_frozen():
    p = FictionalDomain()
    with pytest.raises(TypeError):
        p.market.outcome_tokens["YES"] = "other"
    with pytest.raises(TypeError):
        p.evaluate(p.market, T0).joint["heads"] = .7
    for changes in ({"tick": Decimal("NaN")}, {"min_order_size": Decimal(0)},
                    {"outcome_tokens": {"YES": "same", "NO": "same"}}):
        with pytest.raises(ValueError):
            replace(p.market, **changes)


def test_event_probability_and_clock_checks():
    with pytest.raises(ValueError):
        InfoEvent("x", T0, None, None, ("heads",), 2, None, "pull")
    with pytest.raises(ValueError):
        InfoEvent("x", None, T0, T0 - timedelta(seconds=1), ("heads",), 1, None, "pull")


def test_conformance_catches_price_leak_and_future_leak():
    class Leaky(FictionalDomain):
        def evaluate(self, market, as_of_utc, market_price=None):
            original = super().evaluate(market, as_of_utc)
            if market_price is not None:
                return replace(original, p_yes=market_price, joint=None)
            return original
    p = Leaky()
    with pytest.raises(AssertionError, match="market price"):
        check_conformance(universe=p, fair_value=p, information=p, settlement=p,
                          clock=FixtureClock(T0, T0 - timedelta(seconds=1), T0 + timedelta(days=3)))

    class FutureLeaky(FictionalDomain):
        def ingest_future(self):
            self.records[0] = (T0, .7)
    p = FutureLeaky()
    with pytest.raises(AssertionError):
        check_conformance(universe=p, fair_value=p, information=p, settlement=p,
                          clock=FixtureClock(T0, T0 - timedelta(seconds=1), T0 + timedelta(days=3)),
                          advance_inputs=p.ingest_future)
