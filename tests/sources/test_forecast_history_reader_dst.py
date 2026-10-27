"""The forecast-history backfill reader places hourly labels with the response's own offset (EF §10w).

Guards: EF §10w (Open-Meteo hourly labels are fixed-offset per response) and item 340 head B. A Chicago historical-
forecast / previous-runs payload downloaded in summer (utc_offset_seconds -18000, CDT) for the standard-time date
2024-12-10 labels every hour one hour late when read as zone wall time: label 2024-12-10T00:00 is truly 2024-12-09
23:00 CST. ``historical_forecast_rows`` and ``previous_run_rows`` (the manual ``backfill()`` path) must put it on
12-09; a naive label without a usable response offset is refused, never read as zone wall time. Synthetic payloads.
"""
from __future__ import annotations

import pytest

from weather.market.market_registry import spec_for_id
from weather.sources.forecast_history import historical_forecast_rows, previous_run_rows

CHICAGO = spec_for_id("chicago")
LABELS = [f"2024-12-10T{h:02d}:00" for h in range(24)]


def _payload(offset=-18000, labels=LABELS):
    values = [99.0] + [40.0] * (len(labels) - 1)  # the first label carries a distinct value
    payload = {"hourly": {"time": list(labels), "temperature_2m": values,
                          "temperature_2m_previous_day1": values}}
    if offset is not None:
        payload["utc_offset_seconds"] = offset
    return payload


def test_historical_forecast_rows_put_a_summer_downloaded_first_label_on_the_previous_day():
    rows = historical_forecast_rows(_payload(), CHICAGO)
    assert (rows[0]["target_date"], rows[0]["valid_time"]) == ("2024-12-09", "2024-12-09T23:00:00-06:00")
    assert rows[0]["target_temp_native"] == 99.0
    assert {row["target_date"] for row in rows[1:]} == {"2024-12-10"}


def test_previous_run_rows_put_the_first_label_and_its_issue_on_the_previous_day():
    rows = previous_run_rows(_payload(), CHICAGO, leads=(1,))
    assert (rows[0]["target_date"], rows[0]["valid_time"]) == ("2024-12-09", "2024-12-09T23:00:00-06:00")
    assert rows[0]["issue_time"].startswith("2024-12-08")


@pytest.mark.parametrize("offset", [None, "-18000", True, float("nan"), 86400, -18000.5])
def test_a_naive_label_without_a_usable_offset_is_refused_never_guessed(offset):
    payload = _payload(offset=offset)
    assert historical_forecast_rows(payload, CHICAGO) == []
    assert previous_run_rows(payload, CHICAGO, leads=(1,)) == []


def test_an_offset_that_matches_the_zone_reads_as_zone_local():
    labels = [f"2024-07-10T{h:02d}:00" for h in range(24)]
    rows = historical_forecast_rows(_payload(labels=labels), CHICAGO)
    assert rows[0]["valid_time"] == "2024-07-10T00:00:00-05:00"
