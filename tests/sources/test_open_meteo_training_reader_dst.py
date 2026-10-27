"""Open-Meteo training and backfill readers place hourly labels with the response's own offset (EF §10w).

Guards: EF §10w (Open-Meteo hourly labels are fixed-offset per response) and item 340 head A. A Chicago payload
downloaded in summer (utc_offset_seconds -18000, CDT) for the standard-time date 2024-12-10 labels every hour one
hour late when read as zone wall time: label 2024-12-10T00:00 is truly 2024-12-09 23:00 CST. The archive
(global models, air quality), reanalysis and synoptic readers must put it on 12-09; a naive label without a usable
response offset is refused, never read as zone wall time; a payload whose offset matches the zone reads unchanged.
Synthetic payloads only.
"""
from __future__ import annotations

import json

import pytest

from weather.market.market_registry import spec_for_id
from weather.sources.open_meteo_archives import (
    normalize_open_meteo_air_quality_archive,
    normalize_open_meteo_global_model_archive,
)
from weather.sources.open_meteo_label_times import REFUSED_NO_OFFSET, payload_local_times, response_offset_seconds
from weather.sources.reanalysis_history import ReanalysisStore, normalize_payload
from weather.sources.reanalysis_synoptic import load_raw_daily_metrics

CHICAGO = spec_for_id("chicago")
LABELS = [f"2024-12-10T{h:02d}:00" for h in range(24)]
SUMMER_OFFSET = -18000  # CDT: the offset Open-Meteo applies to every label when the request is served in summer


def _payload(offset=SUMMER_OFFSET, labels=LABELS):
    temps = [99.0] + [40.0] * (len(labels) - 1)  # the first label carries a distinct value
    payload = {"timezone": "America/Chicago",
               "hourly": {"time": list(labels), "temperature_2m": temps, "temperature_2m_gfs_seamless": temps,
                          "precipitation": [5.0] + [0.0] * (len(labels) - 1), "pm2_5": temps}}
    if offset is not None:
        payload["utc_offset_seconds"] = offset
    return payload


def test_the_shared_helper_reads_a_summer_download_of_a_standard_time_date_one_hour_earlier():
    times, refusal = payload_local_times(_payload(), CHICAGO.tz)
    assert refusal is None
    assert times[0].isoformat() == "2024-12-09T23:00:00-06:00"
    assert times[-1].isoformat() == "2024-12-10T22:00:00-06:00"


def test_global_model_archive_puts_the_first_label_on_the_previous_day():
    out = normalize_open_meteo_global_model_archive(_payload(), CHICAGO, fetched_at="x",
                                                   model_members=("gfs_seamless",))
    first = out["hourly_rows"][0]
    assert (first["target_date"], first["valid_time"]) == ("2024-12-09", "2024-12-09T23:00:00-06:00")
    daily = {row["target_date"]: row["gfs_seamless_high_native"] for row in out["daily_rows"]}
    assert daily == {"2024-12-09": 99.0, "2024-12-10": 40.0}


def test_air_quality_archive_puts_the_first_label_on_the_previous_day():
    rows = normalize_open_meteo_air_quality_archive(_payload(), CHICAGO, fetched_at="x", fields=("pm2_5",))
    assert rows["hourly_rows"][0]["valid_time"] == "2024-12-09T23:00:00-06:00"


def test_reanalysis_normalize_payload_reads_the_response_offset():
    records = normalize_payload(_payload(), CHICAGO)
    assert records[0]["valid_time_utc"].startswith("2024-12-10T05:00")  # 23:00 CST on 12-09


def _store(tmp_path, payload):
    store = ReanalysisStore(CHICAGO, root=tmp_path / "kord")
    raw = store.raw_root / "year=2024"
    raw.mkdir(parents=True)
    (raw / "2024-12-10_2024-12-10.json").write_text(json.dumps(payload), encoding="utf-8")
    return store


def test_reanalysis_store_and_synoptic_daily_metrics_use_the_response_offset(tmp_path):
    store = _store(tmp_path, _payload())
    assert sorted(d.isoformat() for d in store.raw_normalizable_dates()) == ["2024-12-09", "2024-12-10"]
    daily = load_raw_daily_metrics(store)
    assert {d.isoformat(): v["precipitation"] for d, v in daily.items()} == {"2024-12-09": 5.0, "2024-12-10": 0.0}


@pytest.mark.parametrize("offset", [None, "-18000", True, float("nan"), 86400, -18000.5])
def test_a_naive_label_without_a_usable_offset_is_refused_never_guessed(tmp_path, offset):
    payload = _payload(offset=offset)
    assert response_offset_seconds(payload) is None
    times, refusal = payload_local_times(payload, CHICAGO.tz)
    assert refusal == REFUSED_NO_OFFSET and times == [None] * len(LABELS)
    assert normalize_open_meteo_global_model_archive(payload, CHICAGO, fetched_at="x",
                                                     model_members=("gfs_seamless",))["hourly_rows"] == []
    assert normalize_open_meteo_air_quality_archive(payload, CHICAGO, fetched_at="x",
                                                    fields=("pm2_5",))["hourly_rows"] == []
    assert normalize_payload(payload, CHICAGO) == []
    store = _store(tmp_path, payload)
    assert store.raw_normalizable_dates() == set() and load_raw_daily_metrics(store) == {}


def test_labels_with_their_own_offset_need_no_response_offset():
    payload = _payload(offset=None, labels=[f"2024-12-10T{h:02d}:00-06:00" for h in range(3)])
    times, refusal = payload_local_times(payload, CHICAGO.tz)
    assert refusal is None and times[0].isoformat() == "2024-12-10T00:00:00-06:00"


def test_an_offset_that_matches_the_zone_reads_as_zone_local():
    labels = [f"2024-07-10T{h:02d}:00" for h in range(24)]
    times, refusal = payload_local_times(_payload(labels=labels), CHICAGO.tz)
    assert refusal is None
    assert [t.isoformat() for t in times[:2]] == ["2024-07-10T00:00:00-05:00", "2024-07-10T01:00:00-05:00"]


def test_daily_refresh_reanalysis_step_reports_rows_refused_for_a_missing_offset(tmp_path):
    """Item 340 clearance condition: a refusal in daily refresh is counted in the step output and the report."""
    from datetime import date
    from types import SimpleNamespace
    from unittest.mock import patch

    from weather.operations import daily_refresh_source_steps as steps
    from weather.operations.daily_refresh_report import render_report

    no_offset = _payload(offset=None)

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def fetch_range(self, spec, start, end):
            return no_offset

    def store_for(spec):
        return ReanalysisStore(spec, root=tmp_path / spec.icao.lower())

    args = SimpleNamespace(skip_reanalysis_refresh=False, reanalysis_end_date="2024-12-10", reanalysis_lag_days=1,
                           reanalysis_timeout=1, reanalysis_sleep=0, reanalysis_chunk_days=31)
    with patch.object(steps, "all_specs", return_value=[CHICAGO]), \
            patch.object(steps, "ReanalysisClient", FakeClient), \
            patch.object(steps, "ReanalysisStore", store_for):
        result = steps.run_reanalysis_recent_refresh_step(args)

    assert result["error_count"] == 0 and result["fetched_ranges"] == 1
    assert result["offset_refused_row_count"] == len(LABELS)
    assert result["markets"][0]["offset_refused_rows"] == len(LABELS)
    assert store_for(CHICAGO).coverage(date(2024, 12, 10), date(2024, 12, 10))["offset_refused_row_count"] == 24
    report = render_report({"steps": [{"name": "reanalysis_recent_refresh", "result": result}]})
    assert f"offset-refused rows {len(LABELS)}" in report


def test_a_store_whose_payloads_carry_the_offset_reports_zero_refused_rows(tmp_path):
    assert _store(tmp_path, _payload()).offset_refused_row_count() == 0
