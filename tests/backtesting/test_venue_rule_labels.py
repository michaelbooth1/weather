"""Venue-rule (routine METAR) settlement labels for target dates from 2026-10-23.

Guards: the venue-rule label contract (docs/operations/venue-rule-labels.md; EF 10x): routine
reports only, T-group tenths with an explicit body fallback, half-up rounding in the native unit,
local-day keying across DST, corrections, WU fallback, the single cutover constant and the dated
per-market station override (Denver KDEN from 2026-10-23, lane F).
"""

import csv
import json
import math
from datetime import date
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest

from weather.backtesting import settlement_ledger, venue_rule_labels as vrl
from weather.calibration.forecast_error_model import load_daily_summary as training_daily_summary
from weather.market.market_registry import spec_for_id
from weather.sources import metar_history
from weather.sources.metar_history import (
    classify_report_type,
    filter_report_type,
    is_corrected_report,
    parse_t_group,
    report_temperature_c,
)

NYC = spec_for_id("nyc")
DENVER = spec_for_id("denver")
TORONTO = spec_for_id("toronto")
REPO_STATION_CONFIG = Path(__file__).resolve().parents[2] / "config" / "venue_rule_stations.json"


def _csv(rows):
    lines = ["station,valid,tmpf,tmpc,metar"]
    for valid, raw in rows:
        lines.append(f"X,{valid},50.00,10.00,{raw}")
    return "\n".join(lines) + "\n"


def _metar(station, ddhhmm, body_temp, t_group=None, prefix="", cor=False):
    head = f"{prefix}{station} {ddhhmm}Z" + (" COR" if cor else "")
    rmk = f" RMK AO2 SLP115 {t_group}" if t_group else " RMK AO2 SLP115"
    return f"{head} 22003KT 10SM FEW021 {body_temp}/10 A2987{rmk} $"


def _reports(rows, spec=NYC, station="KLGA", declared=3):
    return vrl.reports_from_csv(_csv(rows), spec, station, declared_report_type=declared)


# --- report type --------------------------------------------------------------


def test_report_type_prefix_wins_over_declaration():
    assert classify_report_type("SPECI KLGA 241512Z 27/10", declared=3) == "special"
    assert classify_report_type("METAR KLGA 241551Z 27/10", declared=4) == "routine"
    assert classify_report_type("KLGA 241551Z 27/10", declared=3) == "routine"
    assert classify_report_type("KLGA 241551Z 27/10", declared="4") == "special"
    assert classify_report_type("KLGA 241551Z 27/10") == "unknown"


def test_filter_report_type_keeps_routine_and_does_not_mutate():
    records = [{"source_quality": "SPECI KLGA 241512Z 27/10"}, {"source_quality": "KLGA 241551Z 26/10"}]
    kept = filter_report_type(records, declared=3)
    assert [row["source_quality"] for row in kept] == ["KLGA 241551Z 26/10"]
    assert kept[0]["metar_report_type"] == "routine"
    assert "metar_report_type" not in records[1]


def test_speci_excluded_from_daily_max():
    reports = _reports([
        ("2026-10-24 14:51", _metar("KLGA", "241451", "20", "T02000100")),
        ("2026-10-24 15:12", _metar("KLGA", "241512", "25", "T02500100", prefix="SPECI ")),
        ("2026-10-25 14:51", _metar("KLGA", "251451", "18", "T01800100")),
    ])
    labels = vrl.venue_daily_labels(reports, NYC)
    assert labels["2026-10-24"]["max_temp_bucket"] == 68  # 20.0 C, not the 25.0 C SPECI
    assert labels["2026-10-24"]["label_routine_report_count"] == 1


def test_undeclared_unprefixed_reports_are_not_counted():
    reports = _reports([
        ("2026-10-24 14:51", _metar("KLGA", "241451", "20", "T02000100")),
        ("2026-10-25 14:51", _metar("KLGA", "251451", "18", "T01800100")),
    ], declared=None)
    assert vrl.venue_daily_labels(reports, NYC) == {}


# --- temperature parsing --------------------------------------------------------


def test_t_group_positive_negative_and_temperature_only():
    assert parse_t_group("KLGA 241451Z 23/19 RMK AO2 T02280194") == (Fraction(228, 10), "ok")
    assert parse_t_group("KDEN 241451Z M12/M16 RMK AO2 T11231156") == (Fraction(-123, 10), "ok")
    assert parse_t_group("KDEN 241451Z M00/M01 RMK AO2 T1005") == (Fraction(-5, 10), "ok")
    assert parse_t_group("KLGA 241451Z 23/19 RMK AO2 SLP115") == (None, "missing")


def test_t_group_outside_remarks_is_ignored():
    # A T-shaped body token is not a remark T-group.
    assert parse_t_group("KLGA 241451Z T02280194 23/19") == (None, "missing")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("KDEN 241451Z 23/19 RMK AO2 T0228019", (Fraction(23), "body_t_group_malformed")),
        ("KDEN 241451Z 23/19 RMK AO2 T02X80194", (Fraction(23), "body_t_group_malformed")),
        ("KDEN 241451Z 23/19 RMK AO2 SLP115", (Fraction(23), "body")),
        ("KDEN 241451Z M05/M09 RMK AO2", (Fraction(-5), "body")),
        ("KDEN 241451Z 23/19 RMK AO2 TSNO", (Fraction(23), "body")),
        ("KDEN 241451Z ////KT RMK AO2", (None, None)),
    ],
)
def test_body_fallback_for_missing_or_malformed_t_group(raw, expected):
    assert report_temperature_c(raw) == expected


def test_body_fallback_reaches_the_daily_label_basis():
    reports = _reports([
        ("2026-10-24 13:51", _metar("KDEN", "241351", "21", "T0215010")),  # malformed
        ("2026-10-24 14:51", _metar("KDEN", "241451", "20", "T02040100")),
        ("2026-10-25 14:51", _metar("KDEN", "251451", "18", "T01800100")),
    ], spec=DENVER, station="KDEN")
    row = vrl.venue_daily_labels(reports, DENVER)["2026-10-24"]
    assert row["max_temp_bucket"] == 70  # body 21 C = 69.8 F beats T-group 20.4 C = 68.72 F
    assert row["label_value_basis"] == "body_t_group_malformed|t_group"


def test_corrected_indicator():
    assert is_corrected_report("KLGA 311451Z COR 05004KT 27/19 RMK AO2 T02670189")
    assert is_corrected_report("METAR COR KLGA 311451Z 05004KT 27/19")
    assert not is_corrected_report("KLGA 311451Z 05004KT 27/19 RMK AO2 COR 1455")


# --- rounding -------------------------------------------------------------------


def test_fahrenheit_half_up_matches_exact_integer_arithmetic():
    for tenths in range(-600, 601):
        exact = math.floor(Fraction(18 * tenths + 3200 + 50, 100))  # floor(F + 1/2), F = C*9/5+32
        value = vrl.native_value(Fraction(tenths, 10), "F")
        assert vrl.round_half_up(value) == exact, tenths


@pytest.mark.parametrize(
    "tenths, unit, bucket",
    [
        (25, "F", 37),  # 36.5 F -> 37
        (-25, "F", 28),  # 27.5 F -> 28
        (24, "F", 36),  # 36.32 F
        (275, "F", 82),  # 81.5 F
        (155, "C", 16),
        (154, "C", 15),
        (-5, "C", 0),  # -0.5 C -> 0 (floor(x + 0.5))
        (-25, "C", -2),
        (-26, "C", -3),
    ],
)
def test_half_up_edges(tenths, unit, bucket):
    assert vrl.round_half_up(vrl.native_value(Fraction(tenths, 10), unit)) == bucket


def test_celsius_market_label_in_whole_celsius():
    reports = _reports([
        ("2026-10-24 18:00", "CYYZ 241800Z 24010KT 15SM FEW040 15/05 A3001 RMK SC1 T01550050"),
        ("2026-10-24 19:00", "CYYZ 241900Z 24010KT 15SM FEW040 15/05 A3001 RMK SC1"),
        ("2026-10-25 18:00", "CYYZ 251800Z 24010KT 15SM FEW040 12/05 A3001 RMK SC1"),
    ], spec=TORONTO, station="CYYZ")
    row = vrl.venue_daily_labels(reports, TORONTO)["2026-10-24"]
    assert row["temperature_unit"] == "C"
    assert row["max_temp_bucket"] == 16


# --- local day, DST, corrections, closure ------------------------------------


def test_local_day_boundaries_across_fall_back():
    # America/New_York leaves EDT at 2026-11-01 06:00Z; 11-01 has 25 local hours.
    reports = _reports([
        ("2026-11-01 03:51", _metar("KLGA", "010351", "30", "T03000100")),  # 10-31 23:51 EDT
        ("2026-11-01 05:51", _metar("KLGA", "010551", "10", "T01000050")),  # 11-01 01:51 EDT
        ("2026-11-01 06:51", _metar("KLGA", "010651", "11", "T01100050")),  # 11-01 01:51 EST
        ("2026-11-02 04:51", _metar("KLGA", "020451", "12", "T01200050")),  # 11-01 23:51 EST
        ("2026-11-02 05:51", _metar("KLGA", "020551", "29", "T02900100")),  # 11-02 00:51 EST
        ("2026-11-03 05:51", _metar("KLGA", "030551", "05", "T00500010")),
    ])
    labels = vrl.venue_daily_labels(reports, NYC)
    assert labels["2026-10-31"]["max_temp_bucket"] == 86
    assert labels["2026-11-01"]["max_temp_bucket"] == 54  # 12.0 C; neither 30 C nor 29 C
    assert labels["2026-11-01"]["label_routine_report_count"] == 3
    assert labels["2026-11-01"]["max_temp_times"] == "23:51"
    assert labels["2026-11-02"]["max_temp_bucket"] == 84


def test_last_date_of_the_stream_is_not_labelled():
    reports = _reports([("2026-10-24 14:51", _metar("KLGA", "241451", "20", "T02000100"))])
    assert vrl.venue_daily_labels(reports, NYC) == {}


def test_correction_replaces_original_at_its_observation_time():
    reports = _reports([
        ("2026-10-24 14:51", _metar("KLGA", "241451", "26", "T02610100", cor=True)),
        ("2026-10-24 14:51", _metar("KLGA", "241451", "25", "T02500100")),
        ("2026-10-25 14:51", _metar("KLGA", "251451", "18", "T01800100")),
    ])
    row = vrl.venue_daily_labels(reports, NYC)["2026-10-24"]
    assert row["max_temp"] == pytest.approx(78.98)
    assert row["label_routine_report_count"] == 1
    assert row["label_corrected_report_count"] == 1


def test_correction_received_after_next_day_first_report_is_rejected():
    text = "\n".join([
        "station,valid,tmpf,tmpc,metar,receipt_time",
        "X,2026-10-24 14:51,77,25.00," + _metar("KLGA", "241451", "25", "T02500100") + ",",
        "X,2026-10-24 14:51,79,26.10," + _metar("KLGA", "241451", "26", "T02610100", cor=True)
        + ",2026-10-25T05:00:00Z",
        "X,2026-10-25 04:51,60,15.00," + _metar("KLGA", "250451", "15", "T01500100") + ",",
        "X,2026-10-26 04:51,60,15.00," + _metar("KLGA", "260451", "15", "T01500100") + ",",
    ]) + "\n"
    reports = vrl.reports_from_csv(text, NYC, "KLGA", declared_report_type=3)
    row = vrl.venue_daily_labels(reports, NYC)["2026-10-24"]
    assert row["max_temp_bucket"] == 77  # 25.0 C; the late 26.1 C correction does not count
    assert row["label_note"] == "rejected_late_corrections=1"


# --- composite: cutover, WU fallback, station ---------------------------------


def _wu(date_bucket):
    return {
        day: {"local_date": day, "row_count": "24", "max_temp": str(bucket), "max_temp_bucket": str(bucket),
              "max_temp_times": "15:00"}
        for day, bucket in date_bucket.items()
    }


def test_cutover_is_one_named_constant():
    assert vrl.VENUE_RULE_CUTOVER_DATE == date(2026, 10, 23)
    assert not vrl.venue_rule_applies(NYC, "2026-10-22")
    assert vrl.venue_rule_applies(NYC, "2026-10-23")
    assert not vrl.venue_rule_applies(NYC, "2026-10-23", cutover=date(2026, 10, 24))


def test_dates_before_cutover_keep_wu_and_from_cutover_take_metar():
    reports = _reports([
        ("2026-10-22 18:51", _metar("KLGA", "221851", "25", "T02500100")),
        ("2026-10-23 18:51", _metar("KLGA", "231851", "25", "T02500100")),
        ("2026-10-24 18:51", _metar("KLGA", "241851", "20", "T02000100")),
    ])
    rows, skipped = vrl.build_label_rows(NYC, _wu({"2026-10-22": 79, "2026-10-23": 79}), {"KLGA": reports})
    by_date = {row["local_date"]: row for row in rows}
    assert by_date["2026-10-22"]["max_temp_bucket"] == 79
    assert by_date["2026-10-22"]["label_source"] == "wu_history"
    assert by_date["2026-10-23"]["max_temp_bucket"] == 77
    assert by_date["2026-10-23"]["label_source"] == "metar_routine"
    assert by_date["2026-10-23"]["label_station"] == "KLGA"
    assert by_date["2026-10-23"]["label_rule_version"] == vrl.VENUE_RULE_VERSION
    assert "2026-10-24" not in by_date  # stream's last date: not closed


def test_wu_fallback_only_when_the_stream_spans_a_day_without_routine_metar():
    reports = _reports([
        ("2026-10-23 18:51", _metar("KLGA", "231851", "25", "T02500100")),
        ("2026-10-25 18:51", _metar("KLGA", "251851", "20", "T02000100")),
        ("2026-10-27 18:51", _metar("KLGA", "271851", "20", "T02000100")),
    ])
    wu = _wu({"2026-10-24": 81, "2026-10-28": 70})
    rows, skipped = vrl.build_label_rows(NYC, wu, {"KLGA": reports})
    by_date = {row["local_date"]: row for row in rows}
    assert by_date["2026-10-24"]["label_source"] == "wu_fallback_no_routine_metar"
    assert by_date["2026-10-24"]["max_temp_bucket"] == 81
    assert skipped["2026-10-28"].startswith("metar_stream_does_not_close")


def test_wu_fallback_refused_when_wu_station_is_not_the_venue_station():
    config = vrl.load_station_config(REPO_STATION_CONFIG)
    reports = _reports([
        ("2026-10-23 18:51", _metar("KDEN", "231851", "25", "T02500100")),
        ("2026-10-25 18:51", _metar("KDEN", "251851", "20", "T02000100")),
    ], spec=DENVER, station="KDEN")
    rows, skipped = vrl.build_label_rows(
        DENVER, _wu({"2026-10-24": 81}), {"KDEN": reports}, station_config=config
    )
    assert [row["local_date"] for row in rows] == ["2026-10-23"]
    assert rows[0]["label_station"] == "KDEN"
    assert skipped["2026-10-24"] == "no_routine_metar_and_wu_station_is_not_KDEN"


def test_denver_station_override_is_dated_and_wins_over_event_and_registry():
    config = vrl.load_station_config(REPO_STATION_CONFIG)
    assert config["denver"] == [(date(2026, 10, 23), "KDEN")]
    before = vrl.resolve_station(DENVER, "2026-10-22", config)
    assert (before["icao"], before["basis"]) == ("KBKF", "registry")
    on = vrl.resolve_station(
        DENVER, "2026-10-23", config,
        event_resolution_source="https://aviationweather.gov/api/data/metar?ids=KBKF&format=raw",
    )
    assert (on["icao"], on["basis"], on["event_icao"]) == ("KDEN", "config_override", "KBKF")


def test_station_override_selects_per_date_without_code_change(tmp_path):
    path = tmp_path / "stations.json"
    path.write_text(json.dumps({
        "schema_version": vrl.STATION_CONFIG_SCHEMA,
        "markets": {"nyc": [
            {"effective_from": "2026-11-01", "station_icao": "KJFK"},
            {"effective_from": "2026-12-01", "station_icao": "KLGA"},
        ]},
    }), encoding="utf-8")
    config = vrl.load_station_config(path)
    assert vrl.resolve_station(NYC, "2026-10-31", config)["icao"] == "KLGA"
    assert vrl.resolve_station(NYC, "2026-10-31", config)["basis"] == "registry"
    assert vrl.resolve_station(NYC, "2026-11-01", config)["icao"] == "KJFK"
    assert vrl.resolve_station(NYC, "2026-11-30", config)["icao"] == "KJFK"
    assert vrl.resolve_station(NYC, "2026-12-01", config)["icao"] == "KLGA"
    assert vrl.resolve_station(NYC, "2026-12-01", config)["basis"] == "config_override"


def test_event_station_used_when_no_config_entry():
    got = vrl.resolve_station(NYC, "2026-10-23", {}, "https://aviationweather.gov/api/data/metar?ids=KJFK&format=raw")
    assert (got["icao"], got["basis"]) == ("KJFK", "event_resolution_source")


def test_station_config_rejects_wrong_schema_and_duplicates(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"schema_version": "other", "markets": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        vrl.load_station_config(path)
    path.write_text(json.dumps({"schema_version": vrl.STATION_CONFIG_SCHEMA, "markets": {"nyc": [
        {"effective_from": "2026-11-01", "station_icao": "KJFK"},
        {"effective_from": "2026-11-01", "station_icao": "KLGA"},
    ]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        vrl.load_station_config(path)


@pytest.mark.parametrize(
    "url, icao",
    [
        ("https://aviationweather.gov/api/data/metar?ids=KDEN&format=raw&date=2026-10-26T09:00:00Z&hours=30", "KDEN"),
        ("https://www.weather.gov/wrh/timeseries?site=eglc", "EGLC"),
        ("https://www.wunderground.com/history/daily/us/co/aurora/KBKF", "KBKF"),
        ("", None),
        ("https://example.com/history/daily", None),
    ],
)
def test_station_from_resolution_source(url, icao):
    assert vrl.station_from_resolution_source(url) == icao


def test_non_builtin_market_never_takes_the_venue_rule():
    assert vrl.BUILTIN_MARKET_IDS >= {"nyc", "denver", "toronto"}
    assert "hong-kong" not in vrl.BUILTIN_MARKET_IDS


# --- end to end: file consumers -------------------------------------------------


def test_build_market_labels_is_read_by_ledger_and_training_readers(tmp_path):
    metar_root = tmp_path / "metar"
    routine = metar_root / "klga" / "routine"
    routine.mkdir(parents=True)
    (routine / "asos_routine_2026-10-22_2026-10-25.csv").write_text(_csv([
        ("2026-10-23 18:51", _metar("KLGA", "231851", "25", "T02500100")),
        ("2026-10-24 18:51", _metar("KLGA", "241851", "20", "T02000100")),
    ]), encoding="utf-8")
    wu = tmp_path / "wu.csv"
    pd.DataFrame([
        {"local_date": "2026-10-22", "row_count": 24, "max_temp": 79, "max_temp_bucket": 79},
        {"local_date": "2026-10-23", "row_count": 24, "max_temp": 79, "max_temp_bucket": 79},
    ]).to_csv(wu, index=False)
    out = tmp_path / "labels" / "daily_summary.csv"
    payload = vrl.build_market_labels(
        NYC, wu_daily_summary=wu, metar_root=metar_root, station_config_path=REPO_STATION_CONFIG,
        out=out, manifest=tmp_path / "labels" / "manifest.json",
    )
    assert payload["label_source_counts"] == {"metar_routine": 1, "wu_history": 1}
    assert payload["metar_inputs"][0]["station"] == "KLGA"

    ledger_index = settlement_ledger.load_daily_summary(out)
    assert ledger_index["2026-10-22"]["bucket"] == 79
    assert ledger_index["2026-10-23"]["bucket"] == 77
    assert ledger_index["2026-10-23"]["row_count"] == 1
    assert training_daily_summary(out)["2026-10-23"]["bucket"] == 77

    with out.open(encoding="utf-8", newline="") as handle:
        rows = {row["local_date"]: row for row in csv.DictReader(handle)}
    assert rows["2026-10-23"]["label_source"] == "metar_routine"
    assert rows["2026-10-23"]["label_station"] == "KLGA"
    assert rows["2026-10-23"]["label_value_basis"] == "t_group"
    assert rows["2026-10-22"]["label_source"] == "wu_history"


# --- fetch request --------------------------------------------------------------


class _Response:
    status_code = 200
    text = "station,valid\n"
    headers = {}

    def raise_for_status(self):
        return None


def test_fetch_adds_report_type_and_raw_text_only_when_asked(monkeypatch):
    calls = []
    monkeypatch.setattr(metar_history.requests, "get", lambda url, params, timeout: calls.append(params) or _Response())
    client = metar_history.MetarClient()
    client.fetch("KLGA", "2026-10-23", "2026-10-24")
    client.fetch("KLGA", "2026-10-23", "2026-10-24", report_types=(3,), include_metar_text=True)
    default, routine = calls
    assert ("report_type", 3) not in default and ("data", "metar") not in default
    assert ("report_type", 3) in routine and ("data", "metar") in routine
    assert [item for item in routine if item[0] == "report_type"] == [("report_type", 3)]
