"""Trigger ``observed_at`` parsing in the maker plugin clock.

The producer (weather.operations.observation_trigger) copies each source's own
observation time into ``observed_at``. For ECCC SWOB that is
``latest_swob["local_time"] or latest_swob["time"]`` from
``SourceFetchMixin.parse_swob_xml``: an ISO-8601 local time WITH its UTC offset
(``2030-07-03T14:00:00-04:00``), never a bare ``"HH:MM"``. The offset makes the
DST fall-back hour unambiguous, so the clock never has to guess it.

A bare local ``"HH:MM"`` (the ``weather.sources.eccc_swob_history`` CSV shape; no
trigger producer writes it today) is read as wall time on the row's target date in the
market's zone. In the repeated fall-back hour, or the skipped spring-forward hour, it has
no single instant: that row is refused (``observed_at_local_dst_ambiguous``), never
guessed. Anything else unparseable (a naive ISO string, garbage) is refused as
``observed_at_unparseable``. A refused row is skipped and counted; it never makes the
clock unavailable for the rest of the event-day.

Fictional fixtures only (dates in 2030).
"""
from datetime import datetime, timedelta, timezone

import pytest

from weather.market.maker_plugin.clock import WeatherInformationClock
from weather.market.maker_plugin_runner import run
from weather.model.model_base import ModelUtilsMixin
from weather.model.model_sources import SourceFetchMixin
from weather.operations.observation_trigger import detect_observation_triggers
from tests.market.test_maker_plugin import fixture
from tests.market.test_maker_plugin_clock_triggers import kinds, trigger
from tests.market.test_maker_plugin_dry_run import NOW as RUN_NOW, jsonl, layout, report

UNPARSEABLE = "observed_at_unparseable"  # Counted once per refused row per market observed.
AMBIGUOUS = "observed_at_local_dst_ambiguous"


class SwobParser(SourceFetchMixin, ModelUtilsMixin):
    """The production SWOB XML parser, bound to a market spec and nothing else."""

    def __init__(self, spec):
        self.spec = spec


def swob_xml(utc_time, temp):
    return ('<om:Observation xmlns:om="urn:om">'
            f'<element name="date_tm" value="{utc_time}" />'
            f'<element name="air_temp" value="{temp}" /></om:Observation>')


def swob_trigger_rows(rows, spec, target, captured, observations):
    """Real producer path: parse_swob_xml -> observation values -> detect_observation_triggers.

    ``observations`` is ``[(swob date_tm, air temp), ...]``; each consecutive pair yields the
    triggers the production watcher would write when the later observation arrives.
    """
    parser = SwobParser(spec)
    states = []
    for minute, (utc_time, temp) in enumerate(observations):
        latest = parser.parse_swob_xml(swob_xml(utc_time, temp))
        assert latest["local_date"] == target.isoformat()
        values = {"eccc_swob_latest_temp": latest["air_temp_native"],
                  # Verbatim from observation_state_from_sources.
                  "eccc_swob_latest_time": latest.get("local_time") or latest.get("time")}
        states.append({"market_id": spec.id, "event_slug": rows[0]["event_slug"],
                       "target_date": target.isoformat(), "unit": spec.unit,
                       "captured_at_utc": (captured + timedelta(minutes=minute)).isoformat(),
                       "values": values, "source_status": {}})
    found = []
    for previous, current in zip(states, states[1:]):
        found.extend(detect_observation_triggers(previous, current))
    return found


def skipped(clock):
    # getattr: the realistic-row tests also run unchanged against the pre-fix clock.
    return getattr(clock, "last_skipped", {})


def toronto(now):
    universe, rows, spec, target, _, _ = fixture(city="toronto", lead=0, now=now)
    return universe, rows, spec, target, universe.discover(now, 2).markets


def test_real_swob_trigger_parses_to_the_right_utc():
    now = datetime(2030, 7, 3, 18, 10, tzinfo=timezone.utc)
    universe, rows, spec, target, markets = toronto(now)
    found = swob_trigger_rows(rows, spec, target, now - timedelta(minutes=5),
                              [("2030-07-03T17:00:00.000Z", 20.4), ("2030-07-03T18:00:00.000Z", 21.6)])
    assert [(r["reason"], r["source"]) for r in found] == [("eccc_swob_latest_temp_bucket_crossed", "eccc_swob")]
    assert found[0]["observed_at"] == "2030-07-03T14:00:00-04:00"  # The producer's exact format.
    clock = WeatherInformationClock(universe, triggers=found)
    events = clock.observe(markets, now)
    assert kinds(events) == ["new_high"] * 3
    assert {e.observed_at_utc for e in events} == {datetime(2030, 7, 3, 18, tzinfo=timezone.utc)}
    assert all(e.decided is None for e in events)  # SWOB pulls, never decides.
    assert not skipped(clock)


def test_dst_fall_back_repeated_hour_is_disambiguated_by_the_producer_offset():
    """2030-11-03 01:30 happens twice in Toronto. The producer writes the offset, so the two
    observations stay one hour apart in UTC; the clock never guesses."""
    now = datetime(2030, 11, 3, 6, 45, tzinfo=timezone.utc)  # 01:45 EST, after the fall-back.
    universe, rows, spec, target, markets = toronto(now)
    found = swob_trigger_rows(rows, spec, target, now - timedelta(minutes=10), [
        ("2030-11-03T04:30:00.000Z", 18.4),   # 00:30 EDT
        ("2030-11-03T05:30:00.000Z", 19.6),   # 01:30 EDT (first 01:30)
        ("2030-11-03T06:30:00.000Z", 20.6),   # 01:30 EST (repeated 01:30)
    ])
    assert [r["observed_at"] for r in found] == ["2030-11-03T01:30:00-04:00", "2030-11-03T01:30:00-05:00"]
    clock = WeatherInformationClock(universe, triggers=found)
    observed = sorted({e.observed_at_utc for e in clock.observe(markets, now)})
    assert observed == [datetime(2030, 11, 3, 5, 30, tzinfo=timezone.utc),
                        datetime(2030, 11, 3, 6, 30, tzinfo=timezone.utc)]
    assert not skipped(clock)


def swob_hhmm_row(rows, spec, target, observed, captured):
    row = trigger(rows, spec, target, reason="eccc_swob_latest_temp_bucket_crossed", source="eccc_swob",
                  previous=19.6, current=20.6)
    row.update(observed_at=observed, current_captured_at_utc=captured.isoformat())
    return row


def test_bare_local_hhmm_is_read_on_the_target_date_in_the_market_zone():
    now = datetime(2030, 7, 3, 18, 10, tzinfo=timezone.utc)
    universe, rows, spec, target, markets = toronto(now)
    clock = WeatherInformationClock(universe, triggers=[swob_hhmm_row(rows, spec, target, "14:00", now)])
    events = clock.observe(markets, now)
    assert kinds(events) == ["new_high"] * 3
    assert {e.observed_at_utc for e in events} == {datetime(2030, 7, 3, 18, tzinfo=timezone.utc)}  # EDT
    assert not clock.last_skipped


@pytest.mark.parametrize("now,wall,expected", [
    (datetime(2030, 11, 3, 6, 45, tzinfo=timezone.utc), "01:30", None),        # repeated hour: refused
    (datetime(2030, 11, 3, 6, 45, tzinfo=timezone.utc), "00:59", datetime(2030, 11, 3, 4, 59, tzinfo=timezone.utc)),
    (datetime(2030, 11, 3, 7, 45, tzinfo=timezone.utc), "02:00", datetime(2030, 11, 3, 7, 0, tzinfo=timezone.utc)),
    (datetime(2030, 3, 10, 8, 45, tzinfo=timezone.utc), "02:30", None),        # skipped hour: refused
    (datetime(2030, 3, 10, 8, 45, tzinfo=timezone.utc), "03:00", datetime(2030, 3, 10, 7, 0, tzinfo=timezone.utc)),
])
def test_bare_local_hhmm_in_a_dst_transition_hour_is_refused_not_guessed(now, wall, expected):
    universe, rows, spec, target, markets = toronto(now)
    clock = WeatherInformationClock(universe, triggers=[swob_hhmm_row(rows, spec, target, wall, now)])
    events = clock.observe(markets, now)
    if expected is None:
        assert events == ()
        assert clock.last_skipped == {AMBIGUOUS: len(markets)}
    else:
        assert {e.observed_at_utc for e in events} == {expected}
        assert not clock.last_skipped


@pytest.mark.parametrize("bad", ["24:00", "9:59", "2030-01-10T14:59:00", "not a time", 1894287540])
def test_unparseable_observed_at_skips_only_that_row_and_counts_it(bad):
    from tests.market.test_maker_plugin import NOW
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    broken = trigger(rows, spec, target, reason="eccc_swob_latest_temp_bucket_crossed", source="eccc_swob")
    broken["observed_at"] = bad
    good = trigger(rows, spec, target, reason="metar_temp_bucket_crossed", source="metar")
    good["observed_at"] = (NOW - timedelta(minutes=3)).isoformat()
    wu_broken = trigger(rows, spec, target)  # A deciding WU row with a broken time decides nothing.
    wu_broken["observed_at"] = bad
    clock = WeatherInformationClock(universe, triggers=[broken, good, wu_broken])
    events = clock.observe(markets, NOW)
    assert kinds(events) == ["new_high"] * 3  # The later, valid row still works.
    assert {e.observed_at_utc for e in events} == {NOW - timedelta(minutes=3)}
    assert clock.last_skipped == {UNPARSEABLE: 2 * len(markets)}
    # The count is per observe call, not cumulative, and the clock keeps working afterwards.
    assert clock.observe(markets, NOW) == events
    assert clock.last_skipped == {UNPARSEABLE: 2 * len(markets)}


def test_runner_counts_the_skip_and_keeps_the_clock_available(tmp_path):
    args, _, _ = layout(tmp_path, lead=0)
    _, rows, spec, target, _, _ = fixture(lead=0, now=RUN_NOW)
    row = trigger(rows, spec, target, reason="metar_temp_bucket_crossed", source="metar")
    row.update(observed_at="2030-01-10T15:14:00", current_captured_at_utc=(RUN_NOW - timedelta(minutes=5)).isoformat(),
               previous_captured_at_utc=(RUN_NOW - timedelta(minutes=6)).isoformat())
    jsonl(args.data_root / "snapshots" / "observation_triggers.jsonl", [row])
    summary = run(args)
    assert not [key for key in summary["unavailable"] if key.startswith("clock:")]
    assert summary["coverage"]["triggers.rows"] == 1
    outcomes = [o for r in report(args)["records"] for o in r["outcomes"] if "clock_events" in o]
    assert outcomes
    assert summary["coverage"]["clock.trigger_rows_skipped." + UNPARSEABLE] == len(outcomes)
    # Coverage restored: before the fix every one of these band-minutes was "clock:" unavailable.
    assert len(outcomes) == sum(len(r["outcomes"]) for r in report(args)["records"]) == 3


def test_mutant_restoring_the_unguarded_parse_fails():
    """Restore the pre-fix unguarded parse in a copy of clock.py: the skip test must then fail."""
    import importlib.util
    import sys
    from pathlib import Path
    import weather.market.maker_plugin.clock as fixed
    from tests.market.test_maker_plugin import NOW

    source = Path(fixed.__file__).read_text(encoding="utf-8")
    anchor = "observed, refused = observed_time(row, spec.tz)"
    assert source.count(anchor) == 1
    mutated = source.replace(anchor, 'observed, refused = (timestamp(row["observed_at"]) if row.get("observed_at") else None), None')
    spec = importlib.util.spec_from_loader("clock_observed_mutant", loader=None)
    mutant = importlib.util.module_from_spec(spec)
    exec(compile(mutated, "clock_observed_mutant", "exec"), mutant.__dict__)
    universe, rows, spec_, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    broken = trigger(rows, spec_, target, reason="eccc_swob_latest_temp_bucket_crossed", source="eccc_swob")
    broken["observed_at"] = "not a time"
    good = trigger(rows, spec_, target, reason="metar_temp_bucket_crossed", source="metar")
    with pytest.raises(ValueError):  # The old behaviour: one row kills the whole clock.
        mutant.WeatherInformationClock(universe, triggers=[broken, good]).observe(markets, NOW)
    assert kinds(fixed.WeatherInformationClock(universe, triggers=[broken, good]).observe(markets, NOW)) == [
        "new_high"] * 3
    # Valid rows are identical under both.
    assert (mutant.WeatherInformationClock(universe, triggers=[good]).observe(markets, NOW)
            == fixed.WeatherInformationClock(universe, triggers=[good]).observe(markets, NOW))
    assert "clock_observed_mutant" not in sys.modules


def test_naive_metar_report_time_skips_that_row_only():
    """N5: if AWC ever served a naive reportTime, it would reach observed_at unchanged. It must not
    take the clock down for the market; the row is refused, not read as UTC or local."""
    from tests.market.test_maker_plugin import NOW
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    naive = trigger(rows, spec, target, reason="metar_temp_bucket_crossed", source="metar")
    naive["observed_at"] = (NOW - timedelta(minutes=2)).replace(tzinfo=None).isoformat()
    wu = trigger(rows, spec, target)
    clock = WeatherInformationClock(universe, triggers=[naive, wu])
    assert kinds(clock.observe(markets, NOW)) == ["decided"] * 3 + ["new_high"] * 3
    assert clock.last_skipped == {UNPARSEABLE: len(markets)}


def test_a_bad_row_affects_only_minutes_at_or_after_its_detection():
    """Point in time: the exporter keeps rows detected up to the end of the UTC day. A row with a bad
    observed_at, detected later, must not change (or be counted in) any earlier minute."""
    from tests.market.test_maker_plugin import NOW
    universe, rows, spec, target, _, _ = fixture(lead=0)
    markets = universe.discover(NOW, 2).markets
    early = trigger(rows, spec, target, reason="metar_temp_bucket_crossed", source="metar")
    early.update(current_captured_at_utc=(NOW - timedelta(hours=2)).isoformat(),
                 observed_at=(NOW - timedelta(hours=2, minutes=3)).isoformat())
    late = trigger(rows, spec, target, reason="eccc_swob_latest_temp_bucket_crossed", source="eccc_swob")
    late["observed_at"] = "not a time"  # detected at NOW
    clock = WeatherInformationClock(universe, triggers=[early, late])
    before = clock.observe(markets, NOW - timedelta(minutes=1))
    assert kinds(before) == ["new_high"] * 3 and not clock.last_skipped
    assert WeatherInformationClock(universe, triggers=[early]).observe(markets, NOW - timedelta(minutes=1)) == before
    assert clock.observe(markets, NOW) == before
    assert clock.last_skipped == {UNPARSEABLE: len(markets)}
