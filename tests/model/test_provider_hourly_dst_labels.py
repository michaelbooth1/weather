"""Open-Meteo hourly labels keep their true market-local hour across a DST change.

Guards: provider hourly time-label contract (weather.time.provider_hourly_local_times).
Open-Meteo applies one scalar ``utc_offset_seconds`` per response to every label
(fixed-offset, contiguous in UTC). Reading a label with ``replace(tzinfo=zone)``
moved every far-side-of-DST hour by one hour (captured Archive/Previous Runs
responses for 2025-11-02 and 2026-03-08 are fixed-offset, -14400 throughout).
"""

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from weather.market.market_registry import spec_for_id
from weather.model.toronto_model import TorontoHighTempModel
from weather.sources.eccc_gridded import normalize_open_meteo_gem_payload
from weather.time import provider_hourly_local_times

NEW_YORK = ZoneInfo("America/New_York")
TORONTO = ZoneInfo("America/Toronto")


def contiguous_labels(start, hours):
    first = datetime.fromisoformat(start)
    return [(first + timedelta(hours=step)).strftime("%Y-%m-%dT%H:%M") for step in range(hours)]


def by_label(times, values):
    return dict(zip(times, values))


class ProviderHourlyLocalTimesTest(unittest.TestCase):
    def test_fixed_offset_fall_back_labels_are_read_as_utc_instants(self):
        # Requested before the 2026-11-01 fall-back: every label carries EDT (-4 h).
        times = contiguous_labels("2026-11-01T00:00", 48)
        local = by_label(times, provider_hourly_local_times(times, NEW_YORK, -14400))

        self.assertEqual(local["2026-11-01T00:00"].isoformat(), "2026-11-01T00:00:00-04:00")
        self.assertEqual(local["2026-11-01T01:00"].isoformat(), "2026-11-01T01:00:00-04:00")
        # The next label is the repeated 01:00 hour, now in EST.
        self.assertEqual(local["2026-11-01T02:00"].isoformat(), "2026-11-01T01:00:00-05:00")
        self.assertEqual(local["2026-11-01T02:00"].fold, 1)
        self.assertEqual(local["2026-11-01T14:00"].isoformat(), "2026-11-01T13:00:00-05:00")
        self.assertEqual(local["2026-11-02T14:00"].isoformat(), "2026-11-02T13:00:00-05:00")
        # The old reading put the same label at 14:00 local, one hour late.
        old = datetime.fromisoformat("2026-11-01T14:00").replace(tzinfo=NEW_YORK)
        self.assertEqual(old - local["2026-11-01T14:00"], timedelta(hours=1))
        # The 25-hour local day is complete and every instant is distinct.
        nov1 = [value for value in local.values() if value.date().isoformat() == "2026-11-01"]
        self.assertEqual(len(nov1), 25)
        self.assertEqual(len({value.astimezone(timezone.utc) for value in local.values()}), 48)

    def test_fixed_offset_spring_forward_labels_skip_the_missing_hour(self):
        # Requested before the 2026-03-08 spring-forward: every label carries EST (-5 h).
        times = contiguous_labels("2026-03-08T00:00", 48)
        local = by_label(times, provider_hourly_local_times(times, NEW_YORK, -18000))

        self.assertEqual(local["2026-03-08T01:00"].isoformat(), "2026-03-08T01:00:00-05:00")
        self.assertEqual(local["2026-03-08T02:00"].isoformat(), "2026-03-08T03:00:00-04:00")
        self.assertEqual(local["2026-03-08T14:00"].isoformat(), "2026-03-08T15:00:00-04:00")
        mar8 = [value for value in local.values() if value.date().isoformat() == "2026-03-08"]
        self.assertEqual(len(mar8), 23)
        self.assertNotIn(2, {value.hour for value in mar8})

    def test_true_local_labels_keep_wall_clock_and_disambiguate_the_repeat(self):
        # A wall-clock response repeats 01:00; it must not be shifted by the scalar offset.
        times = contiguous_labels("2026-11-01T00:00", 2)
        times += ["2026-11-01T01:00"] + contiguous_labels("2026-11-01T02:00", 22)
        local = provider_hourly_local_times(times, NEW_YORK, -14400)

        self.assertEqual(local[1].isoformat(), "2026-11-01T01:00:00-04:00")
        self.assertEqual(local[2].isoformat(), "2026-11-01T01:00:00-05:00")
        self.assertEqual(local[3].isoformat(), "2026-11-01T02:00:00-05:00")
        self.assertEqual(local[15].isoformat(), "2026-11-01T14:00:00-05:00")

    def test_true_local_spring_forward_gap_keeps_wall_clock(self):
        times = contiguous_labels("2026-03-08T00:00", 2) + contiguous_labels("2026-03-08T03:00", 21)
        local = provider_hourly_local_times(times, NEW_YORK, -18000)

        self.assertEqual(local[2].isoformat(), "2026-03-08T03:00:00-04:00")
        self.assertEqual(local[13].isoformat(), "2026-03-08T14:00:00-04:00")

    def test_matching_offset_equals_the_zone_local_reading(self):
        times = contiguous_labels("2026-07-15T00:00", 48)
        local = provider_hourly_local_times(times, NEW_YORK, -14400)
        expected = [datetime.fromisoformat(value).replace(tzinfo=NEW_YORK) for value in times]
        self.assertEqual([value.isoformat() for value in local], [value.isoformat() for value in expected])

    def test_missing_offset_keeps_the_zone_local_reading(self):
        times = contiguous_labels("2026-11-01T12:00", 3)
        local = provider_hourly_local_times(times, NEW_YORK, None)
        self.assertEqual(local[2].isoformat(), "2026-11-01T14:00:00-05:00")

    def test_gmt_response_and_explicit_offsets_convert_to_market_local(self):
        local = provider_hourly_local_times(
            ["2026-11-01T18:00", "2026-11-01T19:00"], NEW_YORK, 0
        )
        self.assertEqual(local[0].isoformat(), "2026-11-01T13:00:00-05:00")
        explicit = provider_hourly_local_times(["2026-11-01T18:00Z", "bad"], NEW_YORK, -14400)
        self.assertEqual(explicit[0].isoformat(), "2026-11-01T13:00:00-05:00")
        self.assertIsNone(explicit[1])


def open_meteo_payload(times, offset):
    temps = [50.0 + index for index in range(len(times))]
    return {
        "timezone": "America/New_York",
        "utc_offset_seconds": offset,
        "hourly": {"time": times, "temperature_2m": temps},
    }


class OpenMeteoFetchDstTest(unittest.TestCase):
    def test_fetch_open_meteo_rows_carry_true_local_hour_on_fall_back_day(self):
        model = TorontoHighTempModel(target_date="2026-11-01", market_id="nyc")
        times = contiguous_labels("2026-11-01T00:00", 48)
        model.get_json = lambda url, params: open_meteo_payload(times, -14400)

        data = model.fetch_open_meteo()

        rows = {row["valid_time"]: row for row in data["day_rows"]}
        self.assertEqual(len(data["day_rows"]), 25)
        # Label 2026-11-01T14:00 (value 64.0) is 13:00 EST, not 14:00.
        self.assertEqual(rows["2026-11-01T13:00:00-05:00"]["temp_native"], 64.0)
        self.assertEqual(rows["2026-11-01T13:00:00-05:00"]["time"], "13:00")
        # The day window now ends at the true 23:00 EST hour (label 2026-11-02T00:00).
        self.assertEqual(data["day_max_native"], 74.0)

    def test_fetch_global_ensemble_uses_the_same_instants(self):
        model = TorontoHighTempModel(target_date="2026-03-08", market_id="nyc")
        times = contiguous_labels("2026-03-08T00:00", 48)
        payload = open_meteo_payload(times, -18000)
        model.get_json = lambda url, params: payload

        data = model.fetch_global_ensemble()

        clock = [row["time"] for row in data["day_rows"]]
        self.assertEqual(len(clock), 23)
        self.assertNotIn("02:00", clock)
        self.assertEqual(data["day_rows"][14]["valid_time"], "2026-03-08T15:00:00-04:00")

    def test_summer_fetch_is_unchanged(self):
        model = TorontoHighTempModel(target_date="2026-07-15", market_id="nyc")
        times = contiguous_labels("2026-07-15T00:00", 48)
        model.get_json = lambda url, params: open_meteo_payload(times, -14400)

        data = model.fetch_open_meteo()

        self.assertEqual(len(data["day_rows"]), 24)
        self.assertEqual(data["day_rows"][14]["valid_time"], "2026-07-15T14:00:00-04:00")
        self.assertEqual(data["day_rows"][14]["time"], "14:00")
        self.assertEqual(data["day_max_native"], 73.0)


class OpenMeteoGemDstTest(unittest.TestCase):
    def test_gem_rows_carry_true_local_hour_on_fall_back_day(self):
        spec = spec_for_id("toronto")
        times = contiguous_labels("2026-11-01T00:00", 48)
        payload = {
            "utc_offset_seconds": -14400,
            "hourly": {
                "time": times,
                "temperature_2m_gem_seamless": [float(index) for index in range(48)],
            },
        }
        data = normalize_open_meteo_gem_payload(
            payload,
            spec,
            "2026-11-01",
            now=datetime(2026, 11, 1, 12, 0, tzinfo=TORONTO),
        )

        rows = {row["valid_time"]: row for row in data["day_rows"]}
        self.assertEqual(len(data["day_rows"]), 25)
        self.assertEqual(rows["2026-11-01T13:00:00-05:00"]["models"]["gem_seamless"]["temp_native"], 14.0)
        self.assertEqual(data["day_model_highs"]["gem_seamless"], 24.0)


if __name__ == "__main__":
    unittest.main()
