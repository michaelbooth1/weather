"""Producer contract for maker replay v2 rule 4 = option B (owner, 2026-10-05); synthetic fixtures only.

Rule 4 wakes ``informed-v0`` on a view's content without ``as_of_utc`` and ``stdev``, so a producer's
``stdev`` may change only with its inputs (pinned by ``inputs_hash``) and with time. The contract: two views
of one condition with the same ``inputs_hash``, ``p_yes``, model and ``as_of_utc`` have the same ``stdev``,
whatever else differs (call order, repeated calls on one instance, unrelated rows in the provider's pools).
Both current producers (the NBP and lead-one fallback views, and the served T+0 view) are checked, and two
mutant producers show the check failing.
"""
from dataclasses import replace
from datetime import timedelta

import pytest

from maker_core.contracts import OutcomeView
from weather.market.maker_plugin.fair_value import WeatherFairValue
from tests.market.test_maker_plugin import NOW, bulletin, fixture, forecast, served_inputs

TIMES = [NOW + timedelta(minutes=m) for m in (0, 1, 7, 30, 61)]
SERVED_TIMES = [NOW + timedelta(minutes=m) for m in (0, 1, 3, 7)]


def violations(providers, markets, times):
    """Keys (condition, inputs_hash, p_yes, model, as_of) seen with more than one stdev, and the views seen."""
    seen, views = {}, 0
    for provider in providers:
        for order in (times, list(reversed(times)), times):  # forward, reverse, and a repeat on one instance
            for at in order:
                for market in markets:
                    view = provider.evaluate(market, at)
                    if not isinstance(view, OutcomeView):
                        continue
                    views += 1
                    key = (view.condition_id, view.inputs_hash, view.p_yes, view.model_id, view.as_of_utc)
                    seen.setdefault(key, set()).add(view.stdev)
    return [key for key, values in seen.items() if len(values) > 1], views


def noise():
    """Rows of an unrelated event (another city): not inputs of any view checked here."""
    universe, rows, spec, target, _, _ = fixture(city="chicago")
    other0 = fixture(city="chicago", lead=0)[1]
    explanation, source = served_inputs(other0)
    return dict(bulletins=[bulletin(spec, target)], forecasts=[forecast(rows, spec, target)],
                snapshots=other0, explanations=[explanation], source_rows=[source])


def pools(kind):
    if kind == "served":
        universe, rows, _, _, _, _ = fixture(lead=0)
        explanation, source = served_inputs(rows)
        return universe, dict(snapshots=rows, explanations=[explanation], source_rows=[source])
    universe, rows, spec, target, _, _ = fixture()
    if kind == "nbp":
        return universe, dict(bulletins=[bulletin(spec, target)])
    return universe, dict(forecasts=[forecast(rows, spec, target)])


def providers(kind, cls=WeatherFairValue):
    universe, base = pools(kind)
    extra = noise()
    mixed = {key: list(base.get(key, [])) + extra[key] for key in extra}
    return universe, [cls(universe, **base), cls(universe, **mixed)]


@pytest.mark.parametrize("kind", ["nbp", "fallback", "served"])
def test_producer_stdev_changes_only_with_inputs_and_time(kind):
    universe, both = providers(kind)
    markets = universe.discover(NOW, 2).markets
    bad, views = violations(both, markets, SERVED_TIMES if kind == "served" else TIMES)
    assert views >= 2 * 3 * len(markets)  # the producer actually produced views
    assert bad == []
    if kind != "served":  # the time law is real: the same inputs give a larger stdev later
        first, last = (both[0].evaluate(markets[1], at) for at in (TIMES[0], TIMES[-1]))
        assert first.inputs_hash == last.inputs_hash and first.p_yes == last.p_yes and last.stdev > first.stdev


class CallCountMutant(WeatherFairValue):
    """Mutant producer: stdev drifts with hidden per-instance state (calls), not with inputs or time."""

    def evaluate(self, market, as_of_utc):
        self.calls = getattr(self, "calls", 0) + 1
        view = super().evaluate(market, as_of_utc)
        return replace(view, stdev=view.stdev * (1 + 1e-3 * self.calls)) if isinstance(view, OutcomeView) else view


class HiddenInputMutant(WeatherFairValue):
    """Mutant producer: stdev reads rows that are not among the view's inputs (pool sizes)."""

    def evaluate(self, market, as_of_utc):
        view = super().evaluate(market, as_of_utc)
        if not isinstance(view, OutcomeView):
            return view
        return replace(view, stdev=view.stdev + 1e-3 * (len(self.bulletins) + len(self.forecasts)))


@pytest.mark.parametrize("mutant", [CallCountMutant, HiddenInputMutant])
@pytest.mark.parametrize("kind", ["nbp", "served"])
def test_contract_fails_for_a_producer_that_changes_stdev_another_way(kind, mutant):
    universe, both = providers(kind, mutant)
    bad, views = violations(both, universe.discover(NOW, 2).markets, SERVED_TIMES if kind == "served" else TIMES)
    assert views and bad
