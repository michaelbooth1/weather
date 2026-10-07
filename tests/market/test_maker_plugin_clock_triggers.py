"""Observation triggers in the maker plugin clock: supporting sources pull, only WU history decides.

Fictional fixtures only (target dates in 2030).
"""
from datetime import timedelta

import pytest

from weather.market.maker_plugin.clock import WeatherInformationClock
from tests.market.test_maker_plugin import NOW, fixture

# (reason, source) pairs the producer (weather.operations.observation_trigger) emits with an
# increasing numeric value. Each must cause a pull and must never decide.
SUPPORTING = (
    ("metar_temp_bucket_crossed", "metar"),
    ("eccc_swob_latest_temp_bucket_crossed", "eccc_swob"),
    ("wu_current_temp_bucket_crossed", "wu_current"),
    ("wu_current_max_since_7am_bucket_crossed", "wu_current"),
    ("metar_temp_above_wu_floor", "metar"),
    ("eccc_swob_max_above_wu_floor", "eccc_swob"),
    ("eccc_swob_latest_temp_above_wu_floor", "eccc_swob"),
)


def trigger(rows, spec, target, *, reason="wu_history_high_increased", source="wu_history",
            previous=74., current=80.):
    return {"reason": reason, "source": source, "previous_value": previous, "current_value": current,
            "previous_bucket": None if previous is None else round(previous), "current_bucket": round(current),
            "observed_at": (NOW-timedelta(minutes=1)).isoformat(), "detail": "Synthetic.",
            "market_id": spec.id, "event_slug": rows[0]["event_slug"], "target_date": target.isoformat(),
            "unit": spec.unit, "current_captured_at_utc": NOW.isoformat(),
            "previous_captured_at_utc": (NOW-timedelta(minutes=2)).isoformat()}


def kinds(events):
    return sorted(e.kind for e in events)


@pytest.mark.parametrize("reason,source", SUPPORTING)
def test_supporting_increase_pulls_but_never_decides(reason, source):
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    # 80 lands in the top (gte 80) band: a WU print with this value decides every band.
    row = trigger(rows, spec, target, reason=reason, source=source)
    clock = WeatherInformationClock(universe, triggers=[row])
    assert clock.observe(markets, NOW-timedelta(seconds=1)) == ()
    events = clock.observe(markets, NOW)
    assert kinds(events) == ["new_high"] * 3
    assert {e.affects for e in events} == {(m.condition_id,) for m in markets}
    assert all(e.action_hint == "pull" and e.decided is None for e in events)
    assert all(e.detected_at_utc == NOW and e.observed_at_utc == NOW-timedelta(minutes=1) for e in events)


def test_supporting_increase_with_no_previous_value_pulls():
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    row = trigger(rows, spec, target, reason="metar_temp_above_wu_floor", source="metar", previous=None)
    assert kinds(WeatherInformationClock(universe, triggers=[row]).observe(markets, NOW)) == ["new_high"] * 3


def test_wu_history_increase_still_decides():
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    events = WeatherInformationClock(universe, triggers=[trigger(rows, spec, target)]).observe(markets, NOW)
    assert kinds(events) == ["decided"] * 3 + ["new_high"] * 3
    # A WU print inside the middle band pulls but decides only the band it has passed.
    events = WeatherInformationClock(universe, triggers=[trigger(rows, spec, target, current=75.)]).observe(
        markets, NOW)
    assert kinds(events) == ["decided"] + ["new_high"] * 3


@pytest.mark.parametrize("reason,source", SUPPORTING + (("wu_history_high_increased", "wu_history"),))
@pytest.mark.parametrize("previous,current", [(80., 80.), (81., 80.)])
def test_non_increase_is_ignored(reason, source, previous, current):
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    row = trigger(rows, spec, target, reason=reason, source=source, previous=previous, current=current)
    assert WeatherInformationClock(universe, triggers=[row]).observe(markets, NOW) == ()


@pytest.mark.parametrize("change", [
    {"market_id": "chicago"}, {"unit": "C"}, {"target_date": "2030-01-11"},
    {"current_captured_at_utc": (NOW+timedelta(seconds=1)).isoformat()},
    {"observed_at": (NOW+timedelta(seconds=1)).isoformat()},
    {"current_value": float("inf")}, {"current_value": None}, {"event_slug": "other-slug"},
])
def test_supporting_rows_keep_every_other_filter(change):
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    row = trigger(rows, spec, target, reason="metar_temp_bucket_crossed", source="metar")
    row.update(change)
    try:
        assert WeatherInformationClock(universe, triggers=[row]).observe(markets, NOW) == ()
    except ValueError:
        assert change.get("current_value") == float("inf")  # records() refuses non-JSON numbers.


@pytest.mark.parametrize("reason,source", [
    ("wu_history_high_increased", "metar"),           # a WU reason under a supporting source
    ("metar_temp_bucket_crossed", "wu_history"),      # a supporting reason under the WU source
    ("metar_became_fresh", "metar"),                  # carries no value
    ("wu_current_max_since_7am_source_revision_down", "wu_current"),
    ("invented_reason", "metar"),
])
def test_unknown_or_mismatched_pairs_are_ignored(reason, source):
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    row = trigger(rows, spec, target, reason=reason, source=source)
    assert WeatherInformationClock(universe, triggers=[row]).observe(markets, NOW) == ()
