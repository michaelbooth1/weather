import csv
from dataclasses import dataclass
from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import pytest


@dataclass(frozen=True)
class FixtureSpec:
    id: str = "fixture"
    icao: str = "KZZZ"
    wu_history_id: str = "KZZZ"
    city_label: str = "fixture"
    display_unit: str = "F"
    tz: ZoneInfo = ZoneInfo("America/New_York")


@pytest.fixture
def build(tmp_path, monkeypatch):
    monkeypatch.setenv("WEATHER_MARKET_REGISTRY", str(tmp_path / "absent.json"))
    from weather.backtesting import venue_rule_labels as labels
    monkeypatch.setattr(labels, "BUILTIN_MARKET_IDS", {"fixture"})
    metar = tmp_path / "metar"
    folder = metar / "kzzz" / "routine"
    folder.mkdir(parents=True)
    config = tmp_path / "stations.json"
    config.write_text(json.dumps({"schema_version": labels.STATION_CONFIG_SCHEMA, "markets": {}}))

    def run(files, wu_dates, cutover=date(2025, 1, 1)):
        for name, times in files.items():
            with (folder / name).open("w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["station", "valid", "tmpc", "metar"])
                for stamp in times:
                    instant = datetime.fromisoformat(stamp)
                    writer.writerow(["KZZZ", stamp, 20, f"METAR KZZZ {instant:%d%H%M}Z 20/08"])
        wu = tmp_path / "wu.csv"
        with wu.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["local_date", "max_temp", "max_temp_bucket"])
            writer.writerows((d, 74, 74) for d in wu_dates)
        out = tmp_path / "labels.csv"
        manifest = labels.build_market_labels(
            FixtureSpec(), wu_daily_summary=wu, metar_root=metar, station_config_path=config,
            out=out, manifest=tmp_path / "manifest.json", cutover=cutover,
        )
        with out.open(encoding="utf-8") as f:
            sources = {r["local_date"]: r["label_source"] for r in csv.DictReader(f)}
        return sources, manifest["skipped_dates"]
    return run


@pytest.mark.parametrize("split", [False, True])
def test_interior_date_requires_one_connected_file_window(build, split):
    first = ["2025-01-06 12:00", "2025-01-12 12:00"]
    second = ["2025-01-25 12:00", "2025-01-31 12:00"]
    if split:
        files = {"asos_routine_2025-01-06_2025-01-12.csv": first,
                 "asos_routine_2025-01-25_2025-01-31.csv": second}
    else:
        files = {"asos_routine_2025-01-06_2025-01-31.csv": first + second}
    sources, skipped = build(files, ["2025-01-05", "2025-01-08", "2025-01-18", "2025-01-27", "2025-01-31"],
                             cutover=date(2025, 1, 6))
    assert sources["2025-01-05"] == "wu_history"
    assert sources["2025-01-12"] == "metar_routine"
    assert sources["2025-01-08"] == sources["2025-01-27"] == "wu_fallback_no_routine_metar"
    assert skipped["2025-01-31"] == "metar_stream_does_not_close_KZZZ"
    if split:
        assert skipped["2025-01-18"] == "routine_file_coverage_unproven_KZZZ"
        assert "2025-01-18" not in sources
    else:
        assert sources["2025-01-18"] == "wu_fallback_no_routine_metar"


def test_undated_reports_and_header_only_request_do_not_establish_absence(build):
    sources, skipped = build({
        "legacy.csv": ["2025-01-06 12:00", "2025-01-31 12:00"],
        "asos_routine_2025-01-06_2025-01-31.csv": [],
    }, ["2025-01-18"])
    assert sources["2025-01-06"] == "metar_routine"
    assert skipped["2025-01-18"] == "routine_file_coverage_unproven_KZZZ"


@pytest.mark.parametrize("second_start", ["2025-03-09", "2025-03-10"])
def test_adjacent_utc_windows_cover_a_spring_forward_local_date(build, second_start):
    sources, skipped = build({
        "asos_routine_2025-03-08_2025-03-08.csv": ["2025-03-08 12:00"],
        f"asos_routine_{second_start}_2025-03-11.csv": ["2025-03-11 12:00"],
    }, ["2025-03-09"])
    if second_start == "2025-03-09":
        assert sources["2025-03-09"] == "wu_fallback_no_routine_metar"
    else:
        assert skipped["2025-03-09"] == "routine_file_coverage_unproven_KZZZ"


@pytest.mark.parametrize("retained", [False, True])
def test_last_named_western_local_day_can_need_actual_padded_date_observations(build, retained):
    first = ["2025-01-06 12:00"]
    if retained:
        first.append("2025-01-13 05:00")  # midnight at the station following Jan 12
    sources, skipped = build({
        "asos_routine_2025-01-06_2025-01-12.csv": first,
        "asos_routine_2025-01-25_2025-01-31.csv": ["2025-01-31 12:00"],
    }, ["2025-01-12"])
    if retained:
        assert sources["2025-01-12"] == "wu_fallback_no_routine_metar"
    else:
        assert skipped["2025-01-12"] == "routine_file_coverage_unproven_KZZZ"
