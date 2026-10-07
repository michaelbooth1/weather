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


def real_observed_at(source, spec, when):
    """The producer's observed_at format per source. SWOB is the station's local time WITH its UTC
    offset (model_sources.parse_swob_xml ``local_time``); the others are ISO instants."""
    return when.astimezone(spec.tz).isoformat() if source == "eccc_swob" else when.isoformat()


@pytest.mark.parametrize("reason,source", SUPPORTING)
def test_supporting_increase_pulls_but_never_decides(reason, source):
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    # 80 lands in the top (gte 80) band: a WU print with this value decides every band.
    row = trigger(rows, spec, target, reason=reason, source=source)
    row["observed_at"] = real_observed_at(source, spec, NOW-timedelta(minutes=1))
    clock = WeatherInformationClock(universe, triggers=[row])
    assert clock.observe(markets, NOW-timedelta(seconds=1)) == ()
    events = clock.observe(markets, NOW)
    assert kinds(events) == ["new_high"] * 3
    assert {e.affects for e in events} == {(m.condition_id,) for m in markets}
    assert all(e.action_hint == "pull" and e.decided is None for e in events)
    assert all(e.detected_at_utc == NOW and e.observed_at_utc == NOW-timedelta(minutes=1) for e in events)


def test_bare_hhmm_swob_row_makes_the_clock_raise_at_every_minute():
    """Current behaviour for a bare local "HH:MM" (the eccc_swob_history CSV shape; no live trigger
    producer writes it), pinned until the SWOB follow-up lands: the observed_at parse runs before the
    as_of filter, so one such row makes observe raise even before that row was detected."""
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    swob = trigger(rows, spec, target, reason="eccc_swob_latest_temp_bucket_crossed", source="eccc_swob")
    swob["observed_at"] = (NOW-timedelta(minutes=1)).astimezone(spec.tz).strftime("%H:%M")
    metar = trigger(rows, spec, target, reason="metar_temp_bucket_crossed", source="metar")
    clock = WeatherInformationClock(universe, triggers=[metar, swob])
    for as_of in (NOW-timedelta(hours=3), NOW):
        with pytest.raises(ValueError):
            clock.observe(markets, as_of)


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


def test_trigger_table_is_the_documented_rule():
    from weather.market.maker_plugin.clock import DECIDING_TRIGGER, SUPPORTING_TRIGGERS
    assert DECIDING_TRIGGER == ("wu_history_high_increased", "wu_history")
    assert SUPPORTING_TRIGGERS == frozenset(SUPPORTING)
    assert DECIDING_TRIGGER not in SUPPORTING_TRIGGERS


def test_every_producer_increase_reason_is_classified():
    """Ratchet against the producer: every (reason, source) it emits with a rising value is either the
    deciding WU pair or a supporting pull pair. A new producer reason fails here until it is classified."""
    from weather.market.maker_plugin.clock import DECIDING_TRIGGER, SUPPORTING_TRIGGERS
    from weather.operations.observation_trigger import detect_observation_triggers

    def state(values, fresh):
        return {"market_id": "nyc", "event_slug": "fictional", "target_date": "2030-01-10", "unit": "F",
                "captured_at_utc": NOW.isoformat(), "values": values,
                "source_status": {s: {"ok": fresh, "stale": not fresh, "status": "ok" if fresh else "failed"}
                                  for s in ("wu_history", "wu_current", "metar", "eccc_swob")}}

    keys = ("wu_current_temp", "wu_current_max_since_7am", "metar_temp", "eccc_swob_latest_temp", "eccc_swob_max")
    previous = state(dict({k: 70.2 for k in keys}, wu_history_high=70.), False)
    rising = state(dict({k: 75.6 for k in keys}, wu_history_high=72.), True)
    falling = state(dict({k: 60.2 for k in keys}, wu_history_high=72.), True)
    seen = set()
    for current in (rising, falling):
        for row in detect_observation_triggers(previous, current):
            pair = (row["reason"], row["source"])
            value, before = row["current_value"], row["previous_value"]
            increases = value is not None and (before is None or value > before)
            classified = pair == DECIDING_TRIGGER or pair in SUPPORTING_TRIGGERS
            assert classified or not increases, (pair, before, value)
            seen.add((pair, classified))
    assert {DECIDING_TRIGGER, *SUPPORTING_TRIGGERS} == {pair for pair, classified in seen if classified}
    # Everything unclassified is value-less (became_fresh) or a revision down: never an increase.
    assert {pair[0] for pair, classified in seen if not classified} == {
        "wu_history_became_fresh", "wu_current_became_fresh", "metar_became_fresh", "eccc_swob_became_fresh",
        "wu_current_max_since_7am_source_revision_down"}


def test_mutant_restoring_the_old_continue_fails_the_supporting_test():
    """Restore the pre-fix filter (WU pair only, before new_high) in a copy of clock.py: the supporting
    pull test must then fail, so the new tests detect the original bug."""
    import importlib.util
    import sys
    from pathlib import Path
    import weather.market.maker_plugin.clock as fixed

    source = Path(fixed.__file__).read_text(encoding="utf-8")
    anchor = "if pair != DECIDING_TRIGGER and pair not in SUPPORTING_TRIGGERS:"
    assert source.count(anchor) == 1
    spec = importlib.util.spec_from_loader("clock_mutant", loader=None)
    mutant = importlib.util.module_from_spec(spec)
    exec(compile(source.replace(anchor, "if pair != DECIDING_TRIGGER:"), "clock_mutant", "exec"), mutant.__dict__)
    universe, rows, spec_, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    row = trigger(rows, spec_, target, reason="metar_temp_bucket_crossed", source="metar")
    assert mutant.WeatherInformationClock(universe, triggers=[row]).observe(markets, NOW) == ()  # old bug
    with pytest.raises(AssertionError):
        _supporting_assertions(mutant.WeatherInformationClock, universe, markets, row)
    _supporting_assertions(fixed.WeatherInformationClock, universe, markets, row)
    # The WU path is identical under both.
    wu = trigger(rows, spec_, target)
    assert (mutant.WeatherInformationClock(universe, triggers=[wu]).observe(markets, NOW)
            == fixed.WeatherInformationClock(universe, triggers=[wu]).observe(markets, NOW))
    assert "clock_mutant" not in sys.modules


def _supporting_assertions(clock_type, universe, markets, row):
    events = clock_type(universe, triggers=[row]).observe(markets, NOW)
    assert kinds(events) == ["new_high"] * 3
