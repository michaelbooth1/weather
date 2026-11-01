"""Open-Meteo training readers: ported a399941e cases and the non-uniform-series refusal (item 340, R26).

Guards: EF 10w (Open-Meteo hourly labels are fixed-offset per response) and the R26 item-340 re-tip (step 1:
a usable offset over naive labels that repeat, gap, or hold an unparseable label mid-series is refused with
REFUSED_NOT_FIXED_OFFSET and counted; step 4: a399941e's spring-forward case ported unchanged, its
unparseable-label case ported with the expectation reversed; step 5 option (b): partial days outside the
archive's named range are dropped and counted, DST days inside it keep 23/25 rows). Every reader is checked:
forecast_history (historical forecast and previous runs), open_meteo_archives (global models and air quality)
and reanalysis_history. Synthetic payloads only.
"""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from weather.market.market_registry import NYC
from weather.sources.forecast_history import historical_forecast_rows, previous_run_rows
from weather.sources.open_meteo_archives import (
    normalize_open_meteo_air_quality_archive,
    normalize_open_meteo_global_model_archive,
)
from weather.sources.open_meteo_label_times import (
    REFUSED_NOT_FIXED_OFFSET,
    payload_local_times,
    payload_refused_row_count,
    refused_row_count,
)
from weather.sources.reanalysis_history import ReanalysisStore, normalize_payload


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


# Ported from a399941e (tests/sources/test_training_reader_dst_labels.py l.127), unchanged.
@pytest.mark.parametrize("reader", READERS)
def test_winter_download_read_across_spring_forward_uses_response_offset(reader):
    times = contiguous_labels("2026-03-07T00:00", 72)
    rows = reader(payload_for(times, -18000), NYC)

    assert rows == expected_rows([fixed_offset_local(label, -18000, NYC.tz) for label in times])
    assert rows[times.index("2026-03-09T14:00")][0] == "2026-03-09T15:00:00-04:00"
    # The 23:00 label after the change is truly 00:00 the next date.
    assert rows[times.index("2026-03-09T23:00")] == ("2026-03-10T00:00:00-04:00", "2026-03-10")
    assert rows[times.index("2026-03-07T14:00")][0] == "2026-03-07T14:00:00-05:00"


# Each count adapter: (payload, spec, tmp_path) -> the refused-row count that reader's own caller reports.
def count_historical_forecast(payload, spec, _tmp_path):
    refused = {}
    historical_forecast_rows(payload, spec, refused_rows=refused)
    return refused["historical_forecast"]


def count_previous_runs(payload, spec, _tmp_path):
    hourly = payload["hourly"]
    renamed = dict(payload, hourly={"time": hourly["time"], "temperature_2m_previous_day1": hourly["temperature_2m"]})
    refused = {}
    previous_run_rows(renamed, spec, leads=(1,), refused_rows=refused)
    return refused["previous_runs"]


def count_global_models(payload, spec, _tmp_path):
    return normalize_open_meteo_global_model_archive(
        payload, spec, model_members=("ecmwf_ifs025",))["offset_refused_row_count"]


def count_air_quality(payload, spec, _tmp_path):
    hourly = payload["hourly"]
    renamed = dict(payload, hourly={"time": hourly["time"], "pm2_5": hourly["temperature_2m"]})
    return normalize_open_meteo_air_quality_archive(renamed, spec, fields=("pm2_5",))["offset_refused_row_count"]


def count_reanalysis(payload, spec, tmp_path):
    store = ReanalysisStore(spec, tmp_path / "reanalysis")
    store.write_payload(date(2025, 11, 1), date(2025, 11, 3), payload)
    return store.offset_refused_row_count()


COUNTED_READERS = [
    pytest.param(read_historical_forecast, count_historical_forecast, id="forecast_history.historical_forecast_rows"),
    pytest.param(read_previous_runs, count_previous_runs, id="forecast_history.previous_run_rows"),
    pytest.param(read_global_models, count_global_models, id="open_meteo_archives.global_models"),
    pytest.param(read_air_quality, count_air_quality, id="open_meteo_archives.air_quality"),
    pytest.param(read_reanalysis, count_reanalysis, id="reanalysis_history"),
]


# Ported from a399941e l.173 with the expectation reversed: the mid-series unparseable label is a gap, and a
# gapped series under a usable offset is refused and counted instead of read as zone wall time.
@pytest.mark.parametrize(("reader", "counter"), COUNTED_READERS)
def test_unparseable_label_mid_series_is_a_gap_refused_and_counted(reader, counter, tmp_path):
    times = contiguous_labels("2025-11-01T00:00", 72)
    times[5] = "not-a-time"
    payload = payload_for(times, -14400)

    assert reader(payload, NYC) == {}
    assert counter(payload, NYC, tmp_path) == len(times)
    assert payload_local_times(payload, NYC.tz)[1] == REFUSED_NOT_FIXED_OFFSET


@pytest.mark.parametrize(("reader", "counter"), COUNTED_READERS)
def test_repeated_wall_clock_labels_under_a_usable_offset_are_refused_and_counted(reader, counter, tmp_path):
    # Wall-clock labels repeat 01:00 at the fall-back: not a fixed-offset series, so no hour can be placed.
    times = contiguous_labels("2025-11-02T00:00", 2) + contiguous_labels("2025-11-02T01:00", 23)
    payload = payload_for(times, -14400)

    assert reader(payload, NYC) == {}
    assert counter(payload, NYC, tmp_path) == len(times)


@pytest.mark.parametrize(("reader", "counter"), COUNTED_READERS)
def test_a_skipped_hour_under_a_usable_offset_is_refused_and_counted(reader, counter, tmp_path):
    times = contiguous_labels("2025-11-01T00:00", 72)
    del times[30]
    payload = payload_for(times, -14400)

    assert reader(payload, NYC) == {}
    assert counter(payload, NYC, tmp_path) == len(times)


@pytest.mark.parametrize(("reader", "counter"), COUNTED_READERS)
def test_an_unparseable_label_at_the_series_edge_is_no_gap_and_only_that_row_drops(reader, counter, tmp_path):
    times = contiguous_labels("2025-11-01T00:00", 72)
    times[0] = "not-a-time"
    payload = payload_for(times, -14400)

    rows = reader(payload, NYC)
    assert 0 not in rows and len(rows) == len(times) - 1
    assert rows[times.index("2025-11-02T14:00")][0] == "2025-11-02T13:00:00-05:00"  # read by the response offset
    assert counter(payload, NYC, tmp_path) == 0
    assert payload_local_times(payload, NYC.tz)[1] is None


def test_a_uniform_series_is_not_refused_and_counts_zero():
    payload = payload_for(contiguous_labels("2025-11-01T00:00", 72), -14400)
    local_times, refusal = payload_local_times(payload, NYC.tz)
    assert refusal is None and None not in local_times
    assert refused_row_count(payload, local_times, refusal) == 0


def test_labels_with_their_own_offset_are_kept_when_naive_ones_are_refused():
    labels = ["2025-11-02T00:00", "2025-11-02T00:00", "2025-11-02T06:00-05:00"]
    payload = payload_for(labels, -14400)
    local_times, refusal = payload_local_times(payload, NYC.tz)
    assert refusal == REFUSED_NOT_FIXED_OFFSET
    assert local_times[:2] == [None, None] and local_times[2].isoformat() == "2025-11-02T06:00:00-05:00"
    assert refused_row_count(payload, local_times, refusal) == 2


def _gap(times):
    del times[30]
    return times


def _unparseable(index):
    def mutate(times):
        times[index] = "not-a-time"
        return times
    return mutate


@pytest.mark.parametrize(
    ("mutate", "offset", "expected"),
    [
        pytest.param(lambda times: times, -14400, 0, id="uniform"),
        pytest.param(lambda times: times, None, 72, id="no-offset"),
        pytest.param(_gap, -14400, 71, id="gap"),
        pytest.param(_unparseable(5), -14400, 72, id="unparseable-mid"),
        pytest.param(_unparseable(0), -14400, 0, id="unparseable-edge"),
        pytest.param(lambda times: times[:3] + times[2:], -14400, 73, id="repeat"),
        pytest.param(lambda times: times[:2] + ["", *times[2:]], -14400, 0, id="inserted-empty-label-is-no-gap"),
    ],
)
def test_the_stage_a_count_pass_equals_the_reader_count(mutate, offset, expected):
    payload = payload_for(mutate(contiguous_labels("2025-11-01T00:00", 72)), offset)
    local_times, refusal = payload_local_times(payload, NYC.tz)
    assert refused_row_count(payload, local_times, refusal) == expected
    assert payload_refused_row_count(payload) == expected


def rebuilt_store(tmp_path, start, end, payload):
    store = ReanalysisStore(NYC, tmp_path / "reanalysis")
    store.write_payload(date.fromisoformat(start), date.fromisoformat(end), payload)
    _records, daily = store.rebuild()
    return store, {row["local_date"]: row["row_count"] for row in daily}


# R26 step 5, master's option (b): a partial day outside the archive's named range is dropped and counted.
@pytest.mark.parametrize(
    ("first_label", "offset", "start", "end", "dropped"),
    [
        # Archive start at 00:00 UTC on a -05:00 market: the first five labels are the previous local evening.
        pytest.param("2025-01-01T00:00", 0, "2025-01-01", "2025-01-03", "2024-12-31", id="utc-start-on-minus-5"),
        # A summer download of a winter start (the WS Chicago 1999-12-31 case): one row before the first date.
        pytest.param("2025-01-01T00:00", -14400, "2025-01-01", "2025-01-03", "2024-12-31", id="summer-offset-start"),
        # A winter download of a summer end: the last label is 00:00 after the last date.
        pytest.param("2025-07-01T00:00", -18000, "2025-07-01", "2025-07-03", "2025-07-04", id="winter-offset-end"),
    ],
)
def test_a_partial_day_outside_the_archive_range_is_dropped_and_counted(
        first_label, offset, start, end, dropped, tmp_path):
    store, row_counts = rebuilt_store(tmp_path, start, end, payload_for(contiguous_labels(first_label, 72), offset))

    assert dropped not in row_counts
    assert min(row_counts) >= start and max(row_counts) <= end
    assert store.archive_edge_dropped_dates == [dropped]
    assert date.fromisoformat(dropped) not in store.raw_normalizable_dates()
    manifest = json.loads((store.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"]["archive_edge_days_dropped"] == 1


@pytest.mark.parametrize(
    ("first_label", "offset", "start", "end", "dst_day", "rows"),
    [
        pytest.param("2026-03-07T00:00", -18000, "2026-03-07", "2026-03-10", "2026-03-08", 23, id="spring-forward"),
        pytest.param("2025-11-01T00:00", -14400, "2025-11-01", "2025-11-04", "2025-11-02", 25, id="fall-back"),
    ],
)
def test_a_dst_day_inside_the_archive_keeps_its_23_or_25_rows(first_label, offset, start, end, dst_day, rows, tmp_path):
    store, row_counts = rebuilt_store(tmp_path, start, end, payload_for(contiguous_labels(first_label, 96), offset))

    assert row_counts[dst_day] == rows
    assert all(not start <= dropped <= end for dropped in store.archive_edge_dropped_dates)
