"""The venue-label reader: the label of a built-in market-date is the venue's own label.

Guards: the venue-label cutover (owner 2026-10-25; docs/operations/venue-rule-labels.md "Label
reader"): WU before VENUE_RULE_CUTOVER_DATE, the venue-rule CSV from it with only the venue's own
WU fallback, no WU refill of a missing or thin venue row, the Denver KDEN model-scoring exclusion,
the explicit read_through embargo guard, and the registered venue_label_record schema family.
"""

import csv
import hashlib
from datetime import date, timedelta

import pytest

from weather.backtesting import venue_label_reader as vlr
from weather.backtesting import venue_rule_labels as vrl
from weather.schema_families import schema_version
from weather.schema_registry_families import load_families

CUTOVER = vrl.VENUE_RULE_CUTOVER_DATE
AFTER = CUTOVER + timedelta(days=1)
BEFORE = date(2026, 9, 1)
WU_COLUMNS = ["local_date", "temperature_unit", "row_count", "max_temp_native", "max_temp_bucket_native"]


def _write_wu(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WU_COLUMNS)
        writer.writeheader()
        for day, high, count in rows:
            writer.writerow({
                "local_date": day.isoformat(), "temperature_unit": "F", "row_count": count,
                "max_temp_native": high, "max_temp_bucket_native": round(high),
            })
    return path


def _venue_row(day, high, count=24, source=vrl.LABEL_SOURCE_METAR, version=vrl.VENUE_RULE_VERSION,
               cutover=CUTOVER, station="KLGA"):
    return {
        "local_date": day.isoformat(), "temperature_unit": "F", "row_count": count,
        "max_temp": high, "max_temp_bucket": round(high), "label_source": source,
        "label_station": station, "label_station_basis": vrl.STATION_BASIS_REGISTRY,
        "label_rule_version": version, "label_cutover_date": cutover.isoformat(),
        "label_value_basis": "t_group",
    }


@pytest.fixture
def files(tmp_path):
    wu = _write_wu(tmp_path / "wu.csv", [(BEFORE, 81.0, 24), (CUTOVER, 70.0, 24), (AFTER, 71.0, 24)])
    venue = vrl.write_label_csv(tmp_path / "venue.csv", [
        _venue_row(CUTOVER, 69.0),
        _venue_row(AFTER, 72.0, source=vrl.LABEL_SOURCE_WU_FALLBACK),
    ])
    return wu, venue


def _read(market, days, wu, venue, **kwargs):
    kwargs.setdefault("read_through", AFTER + timedelta(days=5))
    kwargs.setdefault("allow_reserved_window", True)
    return vlr.read_venue_labels(market, days, wu_daily_summary=wu, venue_label_csv=venue, **kwargs)


def test_before_the_cutover_the_label_is_the_wu_row_with_its_hashes(files):
    wu, venue = files
    records, refusals = _read("nyc", [BEFORE], wu, venue)
    assert refusals == {}
    record = records[BEFORE.isoformat()]
    assert (record["label_high"], record["label_bucket"], record["label_policy"]) == (81.0, 81, "wu_history")
    assert record["label_station"] == "KLGA"
    assert record["source_path"] == str(wu)
    assert record["source_sha256"] == hashlib.sha256(wu.read_bytes()).hexdigest()
    assert record["schema_version"] == "venue_label_record_v1"


def test_from_the_cutover_the_label_is_the_venue_row_never_the_wu_row(files):
    wu, venue = files
    records, refusals = _read("nyc", [CUTOVER, AFTER], wu, venue)
    assert refusals == {}
    first, second = records[CUTOVER.isoformat()], records[AFTER.isoformat()]
    # The WU row says 70 on the cutover date; the venue rule says 69 and wins.
    assert (first["label_bucket"], first["label_policy"], first["label_source"]) == (69, "venue_rule", "metar_routine")
    assert first["label_rule_version"] == vrl.VENUE_RULE_VERSION
    assert first["source_sha256"] == hashlib.sha256(venue.read_bytes()).hexdigest()
    assert (second["label_bucket"], second["label_policy"]) == (72, "venue_rule_wu_fallback")


def test_a_missing_venue_row_or_csv_is_refused_not_refilled_from_wu(files, tmp_path):
    wu, venue = files
    later = AFTER + timedelta(days=1)
    _write_wu(wu, [(later, 75.0, 24)])
    records, refusals = _read("nyc", [later], wu, venue)
    assert records == {} and refusals == {later.isoformat(): vlr.REFUSED_NO_VENUE_ROW}
    records, refusals = _read("nyc", [later], wu, tmp_path / "absent.csv")
    assert records == {} and refusals == {later.isoformat(): vlr.REFUSED_NO_VENUE_CSV}


@pytest.mark.parametrize("count, refused", [(vlr.COMPLETE_DAY_MIN_ROWS - 1, True), (vlr.COMPLETE_DAY_MIN_ROWS, False)])
def test_a_thin_venue_row_is_refused_at_the_complete_day_threshold(tmp_path, count, refused):
    venue = vrl.write_label_csv(tmp_path / "venue.csv", [_venue_row(CUTOVER, 69.0, count=count)])
    records, refusals = _read("nyc", [CUTOVER], tmp_path / "wu.csv", venue)
    assert (refusals == {CUTOVER.isoformat(): vlr.REFUSED_THIN_VENUE_ROW}) is refused
    assert (CUTOVER.isoformat() in records) is not refused


@pytest.mark.parametrize("row", [
    _venue_row(CUTOVER, 69.0, version="venue-metar-routine-v0"),
    _venue_row(CUTOVER, 69.0, cutover=date(2026, 10, 1)),
    _venue_row(CUTOVER, 69.0, source=vrl.LABEL_SOURCE_WU),
])
def test_a_venue_row_with_foreign_provenance_is_refused(tmp_path, row):
    venue = vrl.write_label_csv(tmp_path / "venue.csv", [row])
    records, refusals = _read("nyc", [CUTOVER], tmp_path / "wu.csv", venue)
    assert records == {} and refusals == {CUTOVER.isoformat(): vlr.REFUSED_BAD_VENUE_ROW}


def test_denver_from_the_cutover_is_excluded_from_model_scoring_only(tmp_path):
    wu = _write_wu(tmp_path / "wu.csv", [(CUTOVER - timedelta(days=1), 60.0, 24)])
    venue = vrl.write_label_csv(tmp_path / "venue.csv", [_venue_row(CUTOVER, 58.0, station="KDEN")])
    days = [CUTOVER - timedelta(days=1), CUTOVER]
    records, refusals = _read("denver", days, wu, venue)
    assert list(records) == [days[0].isoformat()]
    assert refusals == {CUTOVER.isoformat(): vlr.REFUSED_MODEL_SCORING_EXCLUDED}
    records, refusals = _read("denver", days, wu, venue, model_scoring=False)
    assert refusals == {} and records[CUTOVER.isoformat()]["label_station"] == "KDEN"


def test_read_through_is_required_and_fails_closed_after_the_development_window(files, tmp_path):
    wu, venue = files
    with pytest.raises(TypeError):
        vlr.read_venue_labels("nyc", [BEFORE], wu_daily_summary=wu, venue_label_csv=venue)
    with pytest.raises(vlr.LabelReadRefused, match="allow_reserved_window"):
        vlr.read_venue_labels("nyc", [BEFORE], read_through=vlr.DEVELOPMENT_READ_THROUGH + timedelta(days=1),
                              wu_daily_summary=wu, venue_label_csv=venue)
    records, refusals = vlr.read_venue_labels("nyc", [BEFORE], read_through=vlr.DEVELOPMENT_READ_THROUGH,
                                              wu_daily_summary=wu, venue_label_csv=venue)
    assert list(records) == [BEFORE.isoformat()] and refusals == {}


def test_rows_after_read_through_are_never_parsed_into_labels(tmp_path):
    read_through = date(2026, 9, 29)
    wu = tmp_path / "wu.csv"
    _write_wu(wu, [(read_through, 80.0, 24)])
    with wu.open("a", encoding="utf-8", newline="") as handle:
        handle.write("2026-09-30,F,24,not-a-number,not-a-number\n")
    records, refusals = vlr.read_venue_labels(
        "nyc", [read_through, read_through + timedelta(days=1)], read_through=read_through,
        wu_daily_summary=wu, venue_label_csv=tmp_path / "absent.csv",
    )
    assert list(records) == [read_through.isoformat()]
    assert refusals == {"2026-09-30": vlr.REFUSED_AFTER_READ_THROUGH}


def test_unknown_market_and_bad_read_through_are_refused(files):
    wu, venue = files
    with pytest.raises(vlr.LabelReadRefused, match="built-in"):
        vlr.read_venue_labels("hong-kong", [BEFORE], read_through=BEFORE, wu_daily_summary=wu, venue_label_csv=venue)
    with pytest.raises(vlr.LabelReadRefused, match="datetime.date"):
        vlr.read_venue_labels("nyc", [BEFORE], read_through="2026-09-01", wu_daily_summary=wu, venue_label_csv=venue)


def test_record_schema_is_a_registered_family_schema():
    registry = load_families()
    assert registry.errors == ()
    assert registry.family_of("venue_label_record") == "venue_labels"
    assert schema_version("venue_label_record") == vlr.LABEL_RECORD_SCHEMA == "venue_label_record_v1"
