"""Guards: global routine-METAR settlement, exact rounding, revision bounds and fallbacks."""

import csv
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from weather.market.metar_reports import parse_metar, parse_metar_text, resolve_observation_time
from weather.market.metar_settlement import MetarSettlementAdapter, possible_bins
from weather.market.venue_settlement_rules import settlement_bucket
from weather.market.weather_universe import load_weather_universe, parse_bin_label
from weather.paths import repo_path

U = load_weather_universe()
START = datetime(2026, 11, 5, tzinfo=timezone.utc)
END = datetime(2026, 11, 10, tzinfo=timezone.utc)
DAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 22, tzinfo=timezone.utc)
FIXTURE = repo_path("tests", "fixtures", "weather_expansion", "inputs", "metar-72h")
SUMMARY = list(csv.DictReader((FIXTURE / "summary.csv").read_text().splitlines()))


def report(raw, **kwargs):
    return parse_metar(raw, START, END, **kwargs)


def evaluate(raws, city="toronto", **kwargs):
    return MetarSettlementAdapter().evaluate(U[city], DAY, [report(raw) for raw in raws], as_of=kwargs.pop("as_of", NOW), **kwargs)


@pytest.mark.parametrize("row", SUMMARY, ids=lambda row: row["icao"])
def test_all_station_raw_fixtures(row):
    station = row["icao"]
    raw = (FIXTURE / "per-station" / f"{station}.txt").read_text(encoding="utf-8")
    records, flags = parse_metar_text(raw, START, END)
    assert len(records) == int(row["reports"])
    assert sum(not r.routine for r in records) == int(row["speci"])
    assert sum(r.routine and r.t_group_c is not None for r in records) == int(row["tgroup_routine"])
    malformed = [r for r in records if any(key.startswith(("malformed", "ambiguous")) for key in r.flags)]
    # The UUWW TAF-shaped report has no observed temperature; validity ranges
    # are unrelated tokens, not malformed temperature groups.
    assert not malformed
    if not station.startswith("K"):
        assert all(r.t_group_c is None for r in records)
    if float(row["per_hour"]) >= 1.8:
        assert len({r.observation_time.minute for r in records if r.observation_time}) >= 2


@pytest.mark.parametrize("c,unit,expected", [
    ("13.9", "C", 14), ("17.4", "C", 17), ("16.5", "C", 17),
    ("-1.7", "C", -2), ("-8.5", "C", -8), ("18.3", "F", 65),
    ("17.8", "F", 64), ("19", "F", 66), ("-22.5", "F", -8),
    ("2.5", "F", 37), ("2.499", "F", 36), ("-22.501", "F", -9),
])
def test_verbatim_rule_rounding(c, unit, expected):
    assert settlement_bucket(Decimal(c), unit) == expected


def test_speci_ignored_unlabelled_and_off_hour_count():
    result = evaluate(["METAR CYYZ 081800Z 14/04", "SPECI CYYZ 081815Z 30/04",
                       "CYYZ 081837Z 16/04", "METAR CYYZ 081900Z AUTO 15/04"])
    assert (result.maximum, result.minimum, result.observation_count) == (16, 14, 3)
    assert result.maximum_observation.report_kind == "unlabelled"
    bins = [parse_bin_label(label) for label in ("14°C or below", "15°C", "16°C", "17°C or higher")]
    possibilities = possible_bins(result, "highest", bins)
    assert [p.interval.label for p in possibilities if p.possible] == ["16°C", "17°C or higher"]
    assert all(p.observation == result.maximum_observation for p in possibilities)
    low = possible_bins(result, "lowest", bins)
    assert [p.interval.label for p in low if p.possible] == ["14°C or below"]


def test_unordered_distinct_revisions_without_receipts_are_unavailable():
    originals = ["METAR CYYZ 081800Z 20/04", "METAR COR CYYZ 081800Z 18/04", "CYYZ 081800Z 16/04"]
    result = evaluate(originals)
    assert result.status == "source_unavailable"
    assert "ambiguous_routine_revision" in result.notes


def test_correction_receipt_after_next_day_first_metar_is_rejected():
    records = [report("METAR CYYZ 081800Z 14/04"),
               report("METAR CYYZ 081800Z COR 20/04", receipt_time=datetime(2026, 11, 9, 6, tzinfo=timezone.utc)),
               report("METAR CYYZ 090500Z 10/04")]
    result = MetarSettlementAdapter().evaluate(U["toronto"], DAY, records, as_of=END)
    assert result.maximum == 14
    assert result.status == "final"
    assert "rejected_late_revisions=1" in result.notes


def test_local_midnight_and_observation_not_fetch_date():
    result = evaluate(["METAR CYYZ 080459Z 29/04", "METAR CYYZ 080500Z M02/M05",
                       "METAR CYYZ 090459Z M01/M05", "METAR CYYZ 090500Z 28/04"], as_of=END)
    assert (result.maximum, result.minimum) == (-1, -2)
    assert result.observation_count == 2
    assert result.status == "final"


@pytest.mark.parametrize("day,instants", [
    (date(2027, 3, 14), ("2027-03-14T06:30:00+00:00", "2027-03-14T07:30:00+00:00")),
    (date(2027, 11, 7), ("2027-11-07T05:30:00+00:00", "2027-11-07T06:30:00+00:00")),
])
def test_synthetic_dst_skipped_and_repeated_hours(day, instants):
    records = []
    for n, instant in enumerate(instants):
        observed = datetime.fromisoformat(instant)
        raw = f"METAR CYYZ {observed:%d%H%M}Z {10+n}/04"
        records.append(parse_metar(raw, observed-timedelta(hours=1), observed+timedelta(hours=1)))
    result = MetarSettlementAdapter().evaluate(U["toronto"], day, records, as_of=records[-1].observation_time)
    assert (result.maximum, result.minimum, result.observation_count) == (11, 10, 2)


@pytest.mark.parametrize("token", ["T0165010", "T016X0100", "T21650100", "T016501009"])
def test_malformed_t_group_is_counted_and_body_governs(token):
    record = report(f"METAR CYYZ 081800Z 20/04 RMK {token}")
    assert "malformed_t_group" in record.flags
    assert record.body_temperature_c == 20
    assert record.temperature_c == 20
    assert record.value_basis == "body_t_group_malformed"


def test_t_group_negative_body_minus_and_invalid_groups():
    assert report("METAR KDEN 081800Z M09/M10 RMK T10850100").temperature_c == Decimal("-8.5")
    assert report("METAR CYYZ 081800Z M11/M17").temperature_c == -11
    assert report("METAR CYYZ 081800Z 2X/10").temperature_c is None
    assert report("METAR CYYZ 081800Z 12/10 RMK T01200100 T01300100").temperature_c is None
    assert report("METAR CYYZ 089999Z 12/10").temperature_c is None


def test_month_year_rollover_and_ambiguous_windows():
    start = datetime(2026, 12, 31, 12, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
    assert resolve_observation_time("010030Z", start, end) == datetime(2027, 1, 1, 0, 30, tzinfo=timezone.utc)
    assert resolve_observation_time("311230Z", start, end).year == 2026
    with pytest.raises(ValueError):
        resolve_observation_time("010030Z", start.replace(tzinfo=None), end)


def test_missing_day_waits_then_falls_back_and_lowest_bracket():
    assert evaluate([]).status == "missing"
    result = evaluate([], as_of=END + timedelta(hours=5), wu_values=(Decimal(12), Decimal(3)))
    assert (result.status, result.maximum, result.minimum) == ("wu_fallback", 12, 3)
    assert evaluate([], as_of=END + timedelta(hours=5)).status == "awaiting_wu_fallback"
    fallback = evaluate([], as_of=END + timedelta(hours=5), wu_empty=True, wu_read_at=END + timedelta(hours=5))
    assert fallback.status == "lowest_bracket_fallback"
    bins = [parse_bin_label(label) for label in ("10°C", "9°C or below", "11°C or higher")]
    assert [p.interval.label for p in possible_bins(fallback, "lowest", bins) if p.possible] == ["9°C or below"]


def test_future_and_wrong_station_reports_cannot_fix_bounds():
    assert evaluate(["METAR KLGA 081800Z 30/04", "METAR CYYZ 082300Z 30/04"]).maximum is None


def test_speci_next_day_does_not_close_and_cutoff_is_exact():
    records = [report("METAR CYYZ 081800Z 14/04"), report("SPECI CYYZ 090500Z 30/04")]
    adapter = MetarSettlementAdapter()
    before = datetime(2026, 11, 10, 4, 58, tzinfo=timezone.utc)
    at = datetime(2026, 11, 10, 4, 59, tzinfo=timezone.utc)
    assert adapter.evaluate(U["toronto"], DAY, records, as_of=before).status == "running"
    final = adapter.evaluate(U["toronto"], DAY, records, as_of=at)
    assert final.status == "final"
    bins = [parse_bin_label(label) for label in ("14°C", "15°C or higher")]
    assert [p.possible for p in possible_bins(final, "highest", bins)] == [True, False]


def test_receipt_before_observation_is_unusable_and_negative_tie_bin_stays_possible():
    record = report("METAR CYYZ 081800Z 20/04", receipt_time=datetime(2026, 11, 8, 17, tzinfo=timezone.utc))
    assert record.temperature_c is None
    assert "malformed_receipt_time" in record.flags
    result = evaluate(["METAR CYYZ 081800Z M09/M10 RMK T10851100"])
    assert result.maximum == -8
    bins = [parse_bin_label(label) for label in ("-9°C or below", "-8°C", "-7°C or higher")]
    assert [p.possible for p in possible_bins(result, "highest", bins)] == [False, True, True]


def test_us_engine_uses_tenths_before_conversion_and_lowest_direction():
    result = evaluate(["METAR KLGA 081800Z 18/10 RMK T01830100", "METAR KLGA 081900Z 18/10 RMK T01780100"], city="nyc")
    assert (result.maximum, result.minimum) == (65, 64)
    bins = [parse_bin_label(label) for label in ("63°F or below", "64-65°F", "66°F or higher")]
    assert [p.possible for p in possible_bins(result, "highest", bins)] == [False, True, True]
    assert [p.possible for p in possible_bins(result, "lowest", bins)] == [True, True, False]


def test_review_m1_valid_t_group_governs_over_malformed_body_and_unused_dew_sign():
    for raw in ("METAR KLGA 081800Z 2X/10 RMK T01830100",
                "METAR KLGA 081800Z 2X/10 RMK T01839100"):
        record = report(raw)
        assert record.temperature_c == Decimal("18.3")
        assert record.value_basis == "t_group"
        result = evaluate([raw, "METAR KLGA 090500Z 10/04"], city="nyc", as_of=END)
        assert result.maximum == 65
        assert result.status == "final"
    assert report("METAR CYYZ 081800Z 20/04 RMK T0165010").temperature_c == 20


def test_review_m3_next_day_report_never_means_wu_is_empty():
    raws = ["METAR CYYZ 090500Z 10/04"]
    early = datetime(2026, 11, 9, 5, 10, tzinfo=timezone.utc)
    bins = [parse_bin_label(label) for label in ("9°C or below", "10°C", "11°C or higher")]
    for kwargs in ({}, {"wu_empty": True}, {"wu_values": (Decimal(12), Decimal(3))}):
        result = evaluate(raws, as_of=early, **kwargs)
        assert result.status == "awaiting_wu_fallback"
        assert all(p.possible for p in possible_bins(result, "highest", bins))
    deadline = datetime(2026, 11, 10, 4, 59, tzinfo=timezone.utc)
    result = evaluate(raws, as_of=deadline)
    assert result.status == "awaiting_wu_fallback"
    assert all(p.possible for p in possible_bins(result, "highest", bins))
    assert evaluate(raws, as_of=deadline, wu_empty=True).status == "awaiting_wu_fallback"
    assert evaluate(raws, as_of=deadline, wu_empty=True, wu_read_at=deadline).status == "lowest_bracket_fallback"
    with pytest.raises(ValueError, match="both empty"):
        evaluate(raws, as_of=deadline, wu_empty=True, wu_values=(Decimal(12), Decimal(3)))
    with pytest.raises(ValueError, match="explicit boolean"):
        evaluate(raws, as_of=deadline, wu_empty="False")


def test_bin_bound_carries_cutoff_witness_and_invalidating_events():
    result = evaluate(["METAR CYYZ 081800Z 14/04"])
    (bound,) = possible_bins(result, "highest", [parse_bin_label("13°C or below")])
    assert not bound.possible
    assert bound.conditional_until == result.cutoff
    assert bound.witness_observation_time == datetime(2026, 11, 8, 18, tzinfo=timezone.utc)
    assert set(bound.invalidating_events) == {"awc_cor_or_unmarked_replacement", "clearly_erroneous_print_correction"}


def test_legacy_shortened_t_group_divergence_is_preserved():
    from weather.sources.metar_history import report_temperature_c
    raw = "METAR KDEN 081800Z 06/M03 RMK T0056"
    legacy, _ = report_temperature_c(raw)
    strict = report(raw)
    assert settlement_bucket(legacy, "F") == 42
    assert settlement_bucket(strict.temperature_c, "F") == 43
    assert strict.value_basis == "body_t_group_malformed"


def test_supplied_raw_fixture_label_dates_have_no_shortened_t_group_divergence():
    from weather.sources.metar_history import report_temperature_c
    changed_dates = set()
    for row in SUMMARY:
        station = row["icao"]
        raw = (FIXTURE / "per-station" / f"{station}.txt").read_text(encoding="utf-8")
        reports, _ = parse_metar_text(raw, START, END)
        for item in reports:
            if not item.routine or item.temperature_c is None:
                continue
            legacy, _ = report_temperature_c(item.raw)
            if legacy is not None and settlement_bucket(legacy, "F" if station.startswith("K") else "C") != settlement_bucket(
                item.temperature_c, "F" if station.startswith("K") else "C"
            ):
                changed_dates.add((station, item.observation_time.date().isoformat()))
    assert sorted(changed_dates) == []
