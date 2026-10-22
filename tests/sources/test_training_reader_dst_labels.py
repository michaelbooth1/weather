"""Training/archive Open-Meteo readers keep the true market-local hour across DST.

Guards: EF 10w (Open-Meteo hourly labels are fixed-offset per response). The
Historical Forecast / Previous Runs reader (``forecast_history``), the global
model and air-quality archive normalizers (``open_meteo_archives``) and the
ERA5 reanalysis reader (``reanalysis_history`` plus the synoptic raw-daily
loader) read each payload's own ``utc_offset_seconds`` through
``weather.time.provider_hourly_local_times``. A summer download labels winter
hours one hour late when read as zone wall time; a winter download labels
summer hours one hour early. Wall-clock labels, a missing offset or an unusable
offset keep the old zone-local reading; summer data downloaded in summer is
unchanged.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from weather.market.market_registry import NYC, TORONTO
from weather.sources.forecast_history import historical_forecast_rows, previous_run_rows
from weather.sources.open_meteo_archives import (
    normalize_open_meteo_air_quality_archive,
    normalize_open_meteo_global_model_archive,
)
from weather.sources.reanalysis_history import ReanalysisStore, normalize_payload
from weather.sources.reanalysis_synoptic import load_raw_daily_metrics


def contiguous_labels(start, hours):
    first = datetime.fromisoformat(start)
    return [(first + timedelta(hours=step)).strftime("%Y-%m-%dT%H:%M") for step in range(hours)]


def payload_for(times, offset=None, *, key="temperature_2m", omit_offset=False):
    """One hourly series whose value at index i is i, so rows map back to labels."""
    payload = {"hourly": {"time": list(times), key: [float(i) for i in range(len(times))]}}
    if not omit_offset:
        payload["utc_offset_seconds"] = offset
    return payload


def fixed_offset_local(label, offset, zone):
    instant = (datetime.fromisoformat(label) - timedelta(seconds=offset)).replace(tzinfo=timezone.utc)
    return instant.astimezone(zone)


def zone_local(times, zone):
    seen, out = set(), []
    for label in times:
        naive = datetime.fromisoformat(label)
        out.append(naive.replace(tzinfo=zone, fold=1 if naive in seen else 0))
        seen.add(naive)
    return out


# Each reader adapter: (payload, spec) -> {label index: (valid-time ISO, target date ISO)}.
def read_historical_forecast(payload, spec):
    return {
        int(row["target_temp_native"]): (row["valid_time"], row["target_date"])
        for row in historical_forecast_rows(payload, spec)
    }


def read_previous_runs(payload, spec):
    hourly = payload["hourly"]
    renamed = dict(payload, hourly={
        "time": hourly["time"],
        "temperature_2m_previous_day1": hourly["temperature_2m"],
    })
    return {
        int(row["target_temp_native"]): (row["valid_time"], row["target_date"])
        for row in previous_run_rows(renamed, spec, leads=(1,))
    }


def read_global_models(payload, spec):
    normalized = normalize_open_meteo_global_model_archive(payload, spec, model_members=("ecmwf_ifs025",))
    return {
        int(row["ecmwf_ifs025_temp_native"]): (row["valid_time"], row["target_date"])
        for row in normalized["hourly_rows"]
    }


def read_air_quality(payload, spec):
    hourly = payload["hourly"]
    renamed = dict(payload, hourly={"time": hourly["time"], "pm2_5": hourly["temperature_2m"]})
    normalized = normalize_open_meteo_air_quality_archive(renamed, spec, fields=("pm2_5",))
    return {int(row["pm2_5"]): (row["valid_time"], row["target_date"]) for row in normalized["hourly_rows"]}


def read_reanalysis(payload, spec):
    return {
        int(row["temp_native"]): (row["valid_time_local"], row["local_date"])
        for row in normalize_payload(payload, spec)
    }


READERS = [
    pytest.param(read_historical_forecast, id="forecast_history.historical_forecast_rows"),
    pytest.param(read_previous_runs, id="forecast_history.previous_run_rows"),
    pytest.param(read_global_models, id="open_meteo_archives.global_models"),
    pytest.param(read_air_quality, id="open_meteo_archives.air_quality"),
    pytest.param(read_reanalysis, id="reanalysis_history.normalize_payload"),
]


def expected_rows(local_times):
    return {index: (value.isoformat(), value.date().isoformat()) for index, value in enumerate(local_times)}


@pytest.mark.parametrize("reader", READERS)
@pytest.mark.parametrize("spec", [NYC, TORONTO], ids=["F-nyc", "C-toronto"])
def test_summer_download_read_across_fall_back_uses_response_offset(reader, spec):
    times = contiguous_labels("2025-11-01T00:00", 72)
    rows = reader(payload_for(times, -14400), spec)

    assert rows == expected_rows([fixed_offset_local(label, -14400, spec.tz) for label in times])
    # Far side of the change: the label is one hour ahead of true EST.
    assert rows[times.index("2025-11-02T14:00")][0] == "2025-11-02T13:00:00-05:00"
    # The 00:00 label after the change is truly 23:00 on the previous date.
    assert rows[times.index("2025-11-03T00:00")] == ("2025-11-02T23:00:00-05:00", "2025-11-02")
    # Near side (still EDT) is untouched.
    assert rows[times.index("2025-11-01T14:00")][0] == "2025-11-01T14:00:00-04:00"


@pytest.mark.parametrize("reader", READERS)
def test_winter_download_read_across_spring_forward_uses_response_offset(reader):
    times = contiguous_labels("2026-03-07T00:00", 72)
    rows = reader(payload_for(times, -18000), NYC)

    assert rows == expected_rows([fixed_offset_local(label, -18000, NYC.tz) for label in times])
    assert rows[times.index("2026-03-09T14:00")][0] == "2026-03-09T15:00:00-04:00"
    # The 23:00 label after the change is truly 00:00 the next date.
    assert rows[times.index("2026-03-09T23:00")] == ("2026-03-10T00:00:00-04:00", "2026-03-10")
    assert rows[times.index("2026-03-07T14:00")][0] == "2026-03-07T14:00:00-05:00"


@pytest.mark.parametrize("reader", READERS)
def test_true_wall_clock_labels_keep_zone_local_reading(reader):
    # Wall-clock labels repeat 01:00 at the fall-back: not a fixed-offset series.
    times = contiguous_labels("2025-11-02T00:00", 2) + contiguous_labels("2025-11-02T01:00", 23)
    rows = reader(payload_for(times, -14400), NYC)

    assert rows == expected_rows(zone_local(times, NYC.tz))
    assert rows[1][0] == "2025-11-02T01:00:00-04:00"
    assert rows[2][0] == "2025-11-02T01:00:00-05:00"
    assert rows[len(times) - 1][0] == "2025-11-02T23:00:00-05:00"


@pytest.mark.parametrize("reader", READERS)
@pytest.mark.parametrize(
    "offset",
    [pytest.param(None, id="null"), pytest.param("missing", id="missing"), "abc", True, float("nan"), 86400],
)
def test_missing_or_unusable_offset_keeps_zone_local_reading(reader, offset):
    times = contiguous_labels("2025-11-01T00:00", 72)
    payload = payload_for(times, None if offset == "missing" else offset, omit_offset=offset == "missing")
    rows = reader(payload, NYC)

    assert rows == expected_rows(zone_local(times, NYC.tz))
    assert rows[times.index("2025-11-02T14:00")][0] == "2025-11-02T14:00:00-05:00"


@pytest.mark.parametrize("reader", READERS)
def test_summer_payload_downloaded_in_summer_is_unchanged(reader):
    times = contiguous_labels("2025-07-01T00:00", 72)
    rows = reader(payload_for(times, -14400), NYC)

    assert rows == expected_rows(zone_local(times, NYC.tz))


@pytest.mark.parametrize("reader", READERS)
def test_unparseable_label_is_skipped_not_raised(reader):
    times = contiguous_labels("2025-11-01T00:00", 72)
    times[5] = "not-a-time"
    rows = reader(payload_for(times, -14400), NYC)

    assert 5 not in rows
    # The dropped label leaves a gap, which the helper reads as not fixed-offset.
    assert rows[times.index("2025-11-02T14:00")][0] == "2025-11-02T14:00:00-05:00"
    assert len(rows) == len(times) - 1


def test_reanalysis_coverage_and_raw_daily_metrics_use_response_offset(tmp_path):
    store = ReanalysisStore(NYC, tmp_path / "reanalysis")
    times = contiguous_labels("2025-01-01T00:00", 48)
    payload = payload_for(times, -14400)
    payload["hourly"]["precipitation"] = [0.0] * len(times)
    payload["hourly"]["precipitation"][times.index("2025-01-02T00:00")] = 1.0
    store.write_payload(date(2025, 1, 1), date(2025, 1, 2), payload)

    # Label 2025-01-01T00:00 at -4 h is truly 2024-12-31 23:00 EST.
    assert store.raw_normalizable_dates() == {date(2024, 12, 31), date(2025, 1, 1), date(2025, 1, 2)}
    assert store.raw_variable_covered_dates(["precipitation"]) == {
        date(2024, 12, 31), date(2025, 1, 1), date(2025, 1, 2),
    }
    daily = load_raw_daily_metrics(store)
    assert daily[date(2025, 1, 1)]["precipitation"] == 1.0
    assert daily[date(2025, 1, 2)]["precipitation"] == 0.0

    summer = ReanalysisStore(NYC, tmp_path / "summer")
    summer_payload = payload_for(contiguous_labels("2025-07-01T00:00", 48), -14400)
    summer.write_payload(date(2025, 7, 1), date(2025, 7, 2), summer_payload)
    assert summer.raw_normalizable_dates() == {date(2025, 7, 1), date(2025, 7, 2)}
