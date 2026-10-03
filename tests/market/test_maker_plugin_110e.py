"""Real weather-provider output through the offline core proposal kernel."""
from decimal import Decimal as D

from maker_core.contracts import OutcomeView
from maker_core.quoting.policy import Book, DecisionInputs, Portfolio, RewardTerms, decide
from weather.market.maker_plugin.fair_value import WeatherFairValue
from tests.market.test_maker_plugin import NOW, bulletin, fixture


def test_uncalibrated_weather_view_quotes_both_legs_symmetrically():
    universe, _, spec, target, _, _ = fixture()
    market = universe.discover(NOW, 2).markets[1]
    view = WeatherFairValue(universe, bulletins=[bulletin(spec, target)]).evaluate(market, NOW)
    assert isinstance(view, OutcomeView)
    assert view.calibration_grade == "none"
    assert view.p_yes != .5  # Exercise the old skew/leg-drop path, not a neutral mock.
    bids, asks = ((D('.46'), D(75)),), ((D('.54'), D(75)),)
    frame = DecisionInputs(
        market, NOW, Book(NOW, bids, asks, bids, asks),
        RewardTerms(NOW, D(20), D(5), D(100)), view,
        Portfolio(D(200), D(0), D(75), D(60), D(0), D(200), D(0), D(150)),
        1, hazard_per_minute=.001,
    )
    decision = decide(frame)
    assert decision.action == "QUOTE", decision.reasons
    assert tuple(leg.outcome for leg in decision.legs) == ("YES", "NO")
    yes, no = decision.legs
    assert decision.centre - yes.price == 1 - decision.centre - no.price
    assert yes.size == no.size == D(30)
