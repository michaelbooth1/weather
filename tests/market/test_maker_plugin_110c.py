"""110c: explicit expiry, release-method provenance and tracked parser controls."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import runpy

import pytest

from maker_core.contracts import OutcomeView, Unavailable
from maker_core.quoting.policy import Book, DecisionInputs, Portfolio, RewardTerms, decide
from decimal import Decimal as D
from weather.market.maker_plugin.clock import WeatherInformationClock
from weather.market.maker_plugin.fair_value import WeatherFairValue
from weather.market.maker_plugin.nbp import parse, parse_pair_row, PERCENTILE_ROWS
from tests.market.test_maker_plugin import NOW, ORACLE, bulletin, fixture, served_inputs

FIXTURES = Path(__file__).parents[1] / "fixtures"
ROW_ORACLE = runpy.run_path(str(FIXTURES / "maker_plugin/row_parser_oracle.py"))["_parse_pair_row"]
BLOCKS = sorted((FIXTURES / "nbm_target_fix").glob("*.txt"))


def test_copied_parser_fixture_provenance():
    hashes = json.loads((FIXTURES / "nbm_target_fix/sha256.json").read_text())
    assert len(BLOCKS) == len(hashes) == 44
    for path in BLOCKS:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == hashes[path.name]


@pytest.mark.parametrize("path", BLOCKS, ids=lambda p: p.stem)
def test_row_parser_differential_on_integration_fixtures(path):
    compared = 0
    for line in path.read_text().splitlines():
        if line[:6].strip() in ("FHR", *PERCENTILE_ROWS, "TXNMN", "TXNSD"):
            assert parse_pair_row(line) == ROW_ORACLE(line)
            compared += 1
    assert compared == 8


@pytest.mark.parametrize("path", BLOCKS, ids=lambda p: p.stem)
@pytest.mark.parametrize("target", [date(2026, 9, 18), date(2026, 9, 19)])
def test_extracted_percentiles_match_integration_rows_and_slot(path, target):
    text = path.read_text()
    stamp, station = path.stem.split("-")
    issue = datetime.strptime(stamp, "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)
    rows = {line[:6].strip(): ROW_ORACLE(line) for line in text.splitlines()
            if line[:6].strip() in ("FHR", *PERCENTILE_ROWS, "TXNMN", "TXNSD")}
    slot, reason = ORACLE["_slot_for_target_v2"](rows, issue, target, station)
    raw = dict(text=text, station_id=station, target_date=target.isoformat(),
               fetched_at=(issue+timedelta(hours=1)).isoformat(), payload_hash=hashlib.sha256(text.encode()).hexdigest())
    if slot is None:
        with pytest.raises(ValueError, match=reason):
            parse(raw, station, target)
        return
    group, token, _, _ = slot
    expected = tuple(rows[code][group][token] for code in PERCENTILE_ROWS)
    if any(v is None or v == -99 for v in expected):
        with pytest.raises(ValueError, match="incomplete"):
            parse(raw, station, target)
    elif any(a >= b for a, b in zip(expected, expected[1:])):
        with pytest.raises(ValueError, match="nonincreasing"):
            parse(raw, station, target)
    else:
        actual_issue, knots, actual_slot = parse(raw, station, target)
        assert (actual_issue, knots, actual_slot) == (issue, expected, slot)


def test_row_parser_keeps_missing_slots_and_refuses_extra_tokens():
    line = "TXNP1  -99 | 20 -99 | | 30"
    assert parse_pair_row(line) == ROW_ORACLE(line) == [(-99., None), (20., -99.), (None, None), (30., None)]
    with pytest.raises(ValueError, match="ambiguous_nbp_pair"):
        parse_pair_row("TXNP1  1 2 3")  # Deliberately stricter than legacy truncation.


def test_two_old_bulletins_do_not_widen_today():
    universe, _, spec, target, _, _ = fixture()
    markets = universe.discover(NOW, 2).markets
    assert all(m.group_relation == "partition" for m in markets)
    raws = [bulletin(spec, target, issue=NOW.replace(hour=h), fetched=NOW.replace(hour=h)+timedelta(minutes=30))
            for h in (7, 13)]
    clock = WeatherInformationClock(universe, bulletins=raws)
    old_events = clock.observe(markets, NOW)
    assert len(old_events) == 6
    assert all(e.active_until_utc == e.detected_at_utc+timedelta(minutes=10) < NOW for e in old_events)
    market = markets[1]
    view = OutcomeView(market.condition_id, .5, .015, None, NOW, NOW+timedelta(hours=1), "synthetic", "test", "scored")
    bids, asks = ((D('.49'), D(100)),), ((D('.51'), D(100)),)
    frame = DecisionInputs(market, NOW, Book(NOW, bids, asks, bids, asks),
                           RewardTerms(NOW, D(20), D(5), D(100)), view,
                           Portfolio(D(200), D(0), D(75), D(60), D(0), D(200), D(0), D(150)),
                           1, hazard_per_minute=.001)
    baseline = decide(frame)
    assert baseline.action == "QUOTE"
    assert decide(replace(frame, events=old_events)).legs == baseline.legs
    fresh = bulletin(spec, target, fetched=NOW)
    fresh_events = WeatherInformationClock(universe, bulletins=[fresh]).observe(markets, NOW)
    widened = decide(replace(frame, events=fresh_events))
    assert widened.action == "QUOTE" and widened.legs != baseline.legs


def test_metar_and_model_schedules_have_bounded_windows():
    universe, _, _, _, _, _ = fixture()
    markets = universe.discover(NOW, 2).markets
    events = WeatherInformationClock(universe).upcoming(markets, NOW, NOW+timedelta(hours=6))
    assert {e.action_hint for e in events} == {"pull", "widen"}
    assert all(e.active_until_utc == e.scheduled_at_utc+timedelta(minutes=10) for e in events)


@pytest.mark.parametrize("p", [0., 1.])
@pytest.mark.parametrize("served", [False, True])
def test_decided_weather_views_have_exact_zero_stdev(p, served):
    universe, rows, spec, target, _, _ = fixture(lead=0 if served else 1)
    market = universe.discover(NOW, 2).markets[0]
    if served:
        rows[0]["model_probability"] = p
        explanation, source = served_inputs(rows)
        result = WeatherFairValue(universe, snapshots=rows, explanations=[explanation], source_rows=[source]).evaluate(market, NOW)
    else:
        raw = bulletin(spec, target, shift=100 if p == 0 else -100)
        raw["text"] = "".join("TXNSD 40 8\n" if line.startswith("TXNSD") else line
                              for line in raw["text"].splitlines(keepends=True))
        raw["payload_hash"] = hashlib.sha256(raw["text"].encode()).hexdigest()
        result = WeatherFairValue(universe, bulletins=[raw]).evaluate(market, NOW)
    assert isinstance(result, OutcomeView)
    assert result.p_yes == p and result.stdev == 0


@pytest.mark.parametrize("method", ["identity", "temperature", "market_shrink", None])
def test_served_release_calibration_method(method):
    universe, rows, _, _, _, _ = fixture(lead=0)
    explanation, source = served_inputs(rows)
    source["release_calibration_method"] = method
    market = universe.discover(NOW, 2).markets[1]
    result = WeatherFairValue(universe, snapshots=rows, explanations=[explanation], source_rows=[source]).evaluate(market, NOW)
    if method == "market_shrink":
        assert result == Unavailable("market_informed_release", NOW, kind="out_of_scope")
    elif method is None:
        assert isinstance(result, Unavailable) and result.reason == "served_release_calibration_unavailable"
    else:
        assert isinstance(result, OutcomeView) and f"calibration:{method}:" in result.model_id
        source["release_calibration_method"] = "platt"
        other = WeatherFairValue(universe, snapshots=rows, explanations=[explanation], source_rows=[source]).evaluate(market, NOW)
        assert other.inputs_hash != result.inputs_hash and other.model_id != result.model_id


def test_conflicting_release_methods_fail_closed():
    universe, rows, _, _, _, _ = fixture(lead=0)
    explanation, source = served_inputs(rows)
    other = dict(source, release_calibration_method="market_shrink")
    result = WeatherFairValue(universe, snapshots=rows, explanations=[explanation], source_rows=[source, other]).evaluate(
        universe.discover(NOW, 2).markets[1], NOW)
    assert isinstance(result, Unavailable) and result.reason == "served_release_calibration_ambiguous"
