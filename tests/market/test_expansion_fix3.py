"""Guards: T046 R2-1 station isolation and R2-2 temperature/time defect scope."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from weather.market.metar_reports import parse_metar, parse_metar_text
from weather.market.metar_settlement import MetarSettlementAdapter, unreadable_time_dates
from weather.market.settlement_public import PublicSettlementClient
from weather.market.weather_universe import load_weather_universe
from weather.paths import repo_path

UTC = timezone.utc
START = datetime(2026, 11, 5, tzinfo=UTC)
END = datetime(2026, 11, 13, tzinfo=UTC)
DAY = date(2026, 11, 8)
U = load_weather_universe()
ADAPTER = MetarSettlementAdapter()


def report(raw, receipt=None):
    return parse_metar(raw, START, END, receipt_time=receipt)


def normal_day(city, day=DAY):
    spec = U[city]
    zone = ZoneInfo(spec.timezone)
    noon = datetime.combine(day, time(12), zone).astimezone(UTC)
    next_day = datetime.combine(day + timedelta(days=1), time(3), zone).astimezone(UTC)
    return [report(f"METAR {spec.station_id} {noon:%d%H%MZ} 14/04"),
            report(f"METAR {spec.station_id} {next_day:%d%H%MZ} 10/04")]


@pytest.mark.parametrize("junk", ["METAR 081500Z 18/04", "METAR ??? 081500Z 18/04", "junk"])
def test_unattributed_line_cannot_change_a_multicity_fetch(junk):
    cities = ("toronto", "nyc", "tokyo", "moscow", "london")
    text = "\n".join(r.raw for city in cities for r in normal_day(city))
    now = datetime(2026, 11, 9, 9, tzinfo=UTC)
    clean, _ = PublicSettlementClient(get=lambda url: text).metars([U[c].station_id for c in cities], now)
    dirty, diagnostic = PublicSettlementClient(get=lambda url: text + "\n" + junk).metars(
        [U[c].station_id for c in cities], now)
    assert dirty == clean
    assert diagnostic["parse_flags"]["unattributed_lines"] == 1
    for city in cities:
        before = ADAPTER.evaluate(U[city], DAY, clean, as_of=now)
        after = ADAPTER.evaluate(U[city], DAY, dirty, as_of=now)
        assert after == before
        assert after.status == "final"


@pytest.mark.parametrize("city", [s.slug for s in U.values() if s.settlement_kind == "metar_routine"])
def test_direct_evaluation_ignores_unattributed_lines_for_every_station(city):
    records = normal_day(city)
    before = ADAPTER.evaluate(U[city], DAY, records, as_of=END)
    for junk in (report("METAR 081500Z 18/04"), report("METAR ??? 081500Z 18/04", START)):
        assert ADAPTER.evaluate(U[city], DAY, records + [junk], as_of=END) == before


@pytest.mark.parametrize("tokens", ["0703/0803", "0712/0715", "TX01/0712Z TNM02/0704Z",
                                    "R24/290045", "1/2SM", "31005MPS"])
def test_unrelated_tokens_are_true_temperature_absence(tokens):
    parsed = report(f"METAR UUWW 070209Z {tokens}")
    assert parsed.temperature_c is None
    assert not parsed.has_parse_defect
    assert not any(f.startswith(("malformed_", "ambiguous_")) for f in parsed.flags)


def test_real_uuww_day_finalizes_without_discarding_observed_extrema():
    raw = repo_path("tests", "fixtures", "weather_expansion", "inputs", "metar-72h", "per-station", "UUWW.txt").read_text()
    records, diagnostic = parse_metar_text(raw, START, END)
    taf = next(r for r in records if "0703/0803" in r.raw)
    assert taf.temperature_c is None and not taf.has_parse_defect
    assert not diagnostic.get("malformed_body_temperature")
    result = ADAPTER.evaluate(U["moscow"], date(2026, 11, 7), records, as_of=END)
    assert (result.status, result.maximum, result.minimum) == ("final", 1, -1)
    assert "routine_day_parse_defect" not in result.notes


@pytest.mark.parametrize("tokens", ["2X/10", "12/X0", "M2X/M10", "12/10 13/11",
                                    "RMK T02000000 T02100000", "RMK T0X"])
def test_temperature_defects_still_prevent_final_single_bin_collapse(tokens):
    defective = report(f"METAR CYYZ 081800Z {tokens}")
    assert defective.has_parse_defect
    result = ADAPTER.evaluate(U["toronto"], DAY, normal_day("toronto") + [defective], as_of=END)
    assert (result.status, result.maximum) == ("parse_incomplete", 14)


def test_unreadable_time_without_receipt_guards_its_station_on_fetched_dates():
    raw = "METAR CYYZ 3X1800Z 14/04"
    reports, diagnostic = parse_metar_text(raw, START, END)
    assert diagnostic["unreadable_time_lines"] == diagnostic["unreadable_time_without_receipt"] == 1
    for day in (date(2026, 11, 7), DAY, date(2026, 11, 9)):
        records = normal_day("toronto", day)
        assert ADAPTER.evaluate(U["toronto"], day, records + reports, as_of=END).status == "parse_incomplete"
        other = normal_day("nyc", day)
        assert ADAPTER.evaluate(U["nyc"], day, other + reports, as_of=END) == ADAPTER.evaluate(
            U["nyc"], day, other, as_of=END)


@pytest.mark.parametrize("seconds,previous", [(0, True), (7199, True), (7200, True), (7201, False), (10800, False)])
def test_unreadable_time_receipt_limits_station_and_dates(seconds, previous):
    receipt = datetime(2026, 11, 9, 5, tzinfo=UTC) + timedelta(seconds=seconds)
    bad = report("METAR CYYZ 3X1800Z 20/04", receipt)
    for day, affected in ((date(2026, 11, 7), False), (DAY, previous),
                          (date(2026, 11, 9), True), (date(2026, 11, 10), False)):
        for city in ("toronto", "nyc"):
            result = ADAPTER.evaluate(U[city], day, normal_day(city, day) + [bad], as_of=END)
            # At 03:00 the previous day's next report is also its cutoff.
            expected = "parse_incomplete" if city == "toronto" and affected else "final"
            assert result.status == expected


def test_unreadable_time_future_or_at_cutoff_receipt_cannot_affect_the_day():
    records = normal_day("toronto")
    cutoff = records[1].observation_time
    for receipt in (cutoff, END + timedelta(seconds=1)):
        bad = report("METAR CYYZ 3X1800Z 20/04", receipt)
        assert ADAPTER.evaluate(U["toronto"], DAY, records + [bad], as_of=END).status == "final"


def test_unreadable_time_with_no_temperature_or_speci_does_not_block():
    receipt = datetime(2026, 11, 9, 5, 30, tzinfo=UTC)
    for raw in ("METAR CYYZ 3X1800Z NIL", "SPECI CYYZ 3X1800Z 20/04"):
        result = ADAPTER.evaluate(U["toronto"], DAY, normal_day("toronto") + [report(raw, receipt)], as_of=END)
        assert result.status == "final"


@pytest.mark.parametrize("second,previous", [(0, True), (1, False)])
def test_receipt_scope_uses_elapsed_hours_across_fall_dst(second, previous):
    zone = ZoneInfo("America/Toronto")
    bad = report("METAR CYYZ BAD 20/04", datetime(2026, 11, 1, 6, 0, second, tzinfo=UTC))
    dates = unreadable_time_dates(bad, zone)
    assert date(2026, 11, 1) in dates
    assert (date(2026, 10, 31) in dates) == previous
