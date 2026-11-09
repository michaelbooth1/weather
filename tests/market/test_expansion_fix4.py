"""Guards: T046 F3-1/F3-2 hidden temperatures and the FIX4 unreadable-time ruling."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from weather.market.metar_reports import parse_metar, parse_metar_text
from weather.market.metar_settlement import MetarSettlementAdapter, possible_bins, unreadable_time_dates
from weather.market.settlement_public import PublicSettlementClient
from weather.market.weather_universe import load_weather_universe, parse_bin_label

UTC = timezone.utc
START = datetime(2026, 11, 7, 12, tzinfo=UTC)
END = datetime(2026, 11, 9, 6, tzinfo=UTC)
DAY = date(2026, 11, 8)
U = load_weather_universe()
ADAPTER = MetarSettlementAdapter()
F_BINS = [parse_bin_label(label) for label in ("63°F or below", "64-65°F", "66-67°F", "68-69°F", "70°F or higher")]


def report(raw, receipt=None, **kwargs):
    return parse_metar(raw, START, END, receipt_time=receipt, **kwargs)


def nyc_day(warm, with_receipt=False):
    return [report("METAR KLGA 081500Z 18/04 RMK T01780040",
                   datetime(2026, 11, 8, 15, 3, tzinfo=UTC) if with_receipt else None),
            warm,
            report("METAR KLGA 090500Z 10/04",
                   datetime(2026, 11, 9, 5, 3, tzinfo=UTC) if with_receipt else None)]


@pytest.mark.parametrize("token", ["210/04", "21/100", "21//04", "21//", "MM21/04", "21-04", "XX/XX"])
@pytest.mark.parametrize("with_receipt", [False, True])
def test_corrupted_body_cannot_finalize_the_wrong_fahrenheit_bin(token, with_receipt):
    receipt = datetime(2026, 11, 8, 18, 5, tzinfo=UTC) if with_receipt else None
    warm = report(f"METAR KLGA 081800Z {token}", receipt)
    assert warm.has_parse_defect and "malformed_body_temperature" in warm.flags
    result = ADAPTER.evaluate(U["nyc"], DAY, nyc_day(warm, with_receipt), as_of=END)
    assert (result.status, result.maximum) == ("parse_incomplete", 64)
    assert [p.possible for p in possible_bins(result, "highest", F_BINS)] == [False, True, True, True, True]


@pytest.mark.parametrize("token", ["210/04", "21/100", "21//04", "21//"])
def test_valid_t_group_still_governs_every_malformed_body_shape(token):
    warm = report(f"METAR KLGA 081800Z {token} RMK T02060040")
    assert warm.temperature_c == Decimal("20.6") and not warm.has_parse_defect
    result = ADAPTER.evaluate(U["nyc"], DAY, nyc_day(warm), as_of=END)
    assert (result.status, result.maximum) == ("final", 69)


def test_a_second_malformed_body_is_not_silently_ignored_without_a_t_group():
    warm = report("METAR KLGA 081800Z 18/04 210/04")
    assert warm.temperature_c is None and warm.has_parse_defect
    assert ADAPTER.evaluate(U["nyc"], DAY, nyc_day(warm), as_of=END).status == "parse_incomplete"


@pytest.mark.parametrize("token", ["0703/0803", "1/2SM", "M1/4SM", "R24/290045", "R01/////",
                                    "R24/0900V1200U", "05R/2800FT", "TX01/0712Z", "TNM02/0704Z",
                                    "330//KT", "///04MPS", "BKN020///", "SCT023///", "VV///",
                                    "W15/S4", "W15/H7", "WM01/S3", "W///S4", "W15/H12", "W15/H123",
                                    "WM02/H007", "W///H7", "88/290050", "01/123456"])
def test_each_known_non_temperature_shape_is_explicitly_excluded(token):
    absent = report(f"METAR KLGA 081800Z {token}")
    assert absent.temperature_c is None and not absent.has_parse_defect
    present = report(f"METAR KLGA 081800Z {token} 21/04")
    assert present.temperature_c == 21 and not present.has_parse_defect


@pytest.mark.parametrize("token", ["W15/S4", "W15/H7", "88/290050"])
def test_fix5_sea_and_old_runway_groups_preserve_finality(token):
    observation = report(f"METAR LTFM 081800Z 04010KT 9999 FEW030 15/10 Q1018 {token}")
    close = report("METAR LTFM 090000Z 10/04")
    result = ADAPTER.evaluate(U["istanbul"], DAY, [observation, close], as_of=END)
    assert observation.temperature_c == 15 and not observation.has_parse_defect
    assert (result.status, result.maximum, result.minimum) == ("final", 15, 15)


@pytest.mark.parametrize("token", ["W1/S4", "W15/S44", "W15/H1234", "8/290050", "888/290050",
                                    "88/29005", "88/2900500"])
def test_fix5_nearby_corruptions_still_block_finality(token):
    warm = report(f"METAR KLGA 081800Z 21/04 {token}")
    assert warm.temperature_c is None and warm.has_parse_defect
    assert ADAPTER.evaluate(U["nyc"], DAY, nyc_day(warm), as_of=END).status == "parse_incomplete"


@pytest.mark.parametrize("header,flag", [
    ("MTAR KLGA 081800Z", "malformed_report_type"),
    ("METARR KLGA 081800Z", "malformed_report_type"),
    ("METAR C0R KLGA 081800Z", "malformed_correction_marker"),
    ("METAR KLGA COR0 081800Z", "malformed_correction_marker"),
    ("METAR KLGA 081800Z C0R", "malformed_correction_marker"),
])
@pytest.mark.parametrize("with_receipt", [False, True])
@pytest.mark.parametrize("station_ids", [None, ("CYYZ", "KLGA")])
def test_header_corruption_is_attributed_and_blocks_finality(header, flag, with_receipt, station_ids):
    receipt = datetime(2026, 11, 8, 18, 5, tzinfo=UTC) if with_receipt else None
    warm = report(f"{header} 21/04 RMK T02060040", receipt, station_ids=station_ids)
    assert warm.station == "KLGA" and warm.observation_time == datetime(2026, 11, 8, 18, tzinfo=UTC)
    assert flag in warm.flags and warm.has_parse_defect and warm.temperature_c is None
    result = ADAPTER.evaluate(U["nyc"], DAY, nyc_day(warm, with_receipt), as_of=END)
    assert (result.status, result.maximum) == ("parse_incomplete", 64)
    toronto = [report("METAR CYYZ 081800Z 14/04"), report("METAR CYYZ 090500Z 10/04")]
    assert ADAPTER.evaluate(U["toronto"], DAY, toronto + [warm], as_of=END) == ADAPTER.evaluate(
        U["toronto"], DAY, toronto, as_of=END)


@pytest.mark.parametrize("header", ["MTAR KLGA", "METAR C0R KLGA", "METAR KLGA COR0"])
def test_public_batches_recover_the_requested_station_from_a_bad_header(header):
    raw = "\n".join(r.raw for r in nyc_day(report(f"{header} 081800Z 21/04 RMK T02060040")))
    reports, diagnostic = PublicSettlementClient(get=lambda url: raw).metars(["KLGA", "CYYZ"], END)
    assert len(reports) == 3 and not diagnostic["parse_flags"].get("unattributed_lines")
    assert ADAPTER.evaluate(U["nyc"], DAY, reports, as_of=END).status == "parse_incomplete"


def test_requested_station_recovery_is_also_enforced_in_direct_evaluation():
    # The shape-only parser cannot know which of these two four-letter tokens
    # is the requested ICAO. The evaluator must honor the known station token.
    warm = report("MTAR KLGA XXXX 081800Z 21/04 RMK T02060040")
    assert warm.station == "XXXX"
    result = ADAPTER.evaluate(U["nyc"], DAY, nyc_day(warm), as_of=END)
    assert (result.status, result.maximum) == ("parse_incomplete", 64)


def test_station_recovery_keeps_a_preexisting_source_revision_guard():
    warm = report("MTAR KLGA XXXX 081800Z 21/04 RMK T02060040")
    warm = replace(warm, flags=warm.flags + ("ambiguous_source_revision",))
    result = ADAPTER.evaluate(U["nyc"], DAY, nyc_day(warm), as_of=END)
    assert result.status == "source_unavailable" and "ambiguous_routine_revision" in result.notes


def test_unreadable_time_without_receipt_blocks_only_station_dates_in_fetch_window():
    raw = "CYYZ 3X1800Z 25/04"
    bad = report(raw)
    zone = ZoneInfo("America/Toronto")
    assert (bad.fetch_start, bad.fetch_end) == (START, END)
    dates = unreadable_time_dates(bad, zone)
    assert dates == {date(2026, 11, 7), DAY, date(2026, 11, 9)}
    for day in (date(2026, 11, 6), date(2026, 11, 7), DAY, date(2026, 11, 9), date(2026, 11, 10)):
        for city in ("toronto", "nyc"):
            station = U[city].station_id
            # Good observations deliberately use a different, broad fetch window.
            good = parse_metar(f"METAR {station} {day.day:02d}1800Z 14/04",
                               START - timedelta(days=2), END + timedelta(days=3))
            result = ADAPTER.evaluate(U[city], day, [good, bad], as_of=END + timedelta(days=3))
            assert result.status == ("parse_incomplete" if city == "toronto" and day in dates else "final")


def test_no_receipt_unreadable_time_cannot_trigger_a_missing_day_fallback():
    bad = report("CYYZ 3X1800Z 25/04")
    result = ADAPTER.evaluate(U["toronto"], DAY, [bad], as_of=END + timedelta(days=2),
                              wu_values=(Decimal(14), Decimal(3)))
    assert result.status == "source_unavailable"


def test_public_no_receipt_unreadable_time_retains_the_exact_requested_window():
    raw = "METAR CYYZ 081800Z 14/04\nCYYZ 3X1800Z 25/04\nMETAR CYYZ 090500Z 10/04"
    records, diagnostic = PublicSettlementClient(get=lambda url: raw).metars(["CYYZ"], END)
    bad = next(r for r in records if r.has_unreadable_time)
    assert (bad.fetch_start, bad.fetch_end) == (END - timedelta(hours=30), END)
    assert diagnostic["parse_flags"]["unreadable_time_without_receipt"] == 1
    assert ADAPTER.evaluate(U["toronto"], DAY, records, as_of=END).status == "parse_incomplete"


@pytest.mark.parametrize("remark", ["T0206004", "TO2060040", "T0183ABC"])
def test_t_remark_corruption_without_a_body_is_not_true_absence(remark):
    warm = report(f"METAR KLGA 081800Z A3012 RMK {remark}")
    assert warm.has_parse_defect
    assert ADAPTER.evaluate(U["nyc"], DAY, nyc_day(warm), as_of=END).status == "parse_incomplete"


def test_report_without_any_station_token_remains_unattributed():
    parsed, diagnostic = parse_metar_text("MTAR 081800Z 21/04", START, END, station_ids=("KLGA", "CYYZ"))
    assert parsed[0].station is None and diagnostic["unattributed_lines"] == 1


@pytest.mark.parametrize("header", ["MTAR KLGA", "METAR C0R KLGA", "METAR KLGA COR0"])
def test_bad_next_day_header_cannot_close_the_previous_day_before_a_valid_revision(header):
    original = report("METAR KLGA 081800Z 20/04", datetime(2026, 11, 8, 18, 5, tzinfo=UTC))
    correction = report("METAR COR KLGA 081800Z 15/04", datetime(2026, 11, 9, 5, 30, tzinfo=UTC))
    bad_close = report(f"{header} 090500Z 10/04", datetime(2026, 11, 9, 5, 3, tzinfo=UTC))
    records = [original, correction, bad_close]
    result = ADAPTER.evaluate(U["nyc"], DAY, records, as_of=END)
    assert (result.status, result.maximum) == ("running", 59)
    assert result.cutoff == result.fallback_deadline
    valid_close = report("METAR KLGA 090545Z 10/04", datetime(2026, 11, 9, 5, 48, tzinfo=UTC))
    result = ADAPTER.evaluate(U["nyc"], DAY, records + [valid_close], as_of=END)
    assert (result.status, result.maximum, result.cutoff) == ("final", 59, valid_close.receipt_time)
