"""ECCC SWOB backfill history: parse, daily summary, comparison and the CSV time format.

Guards: owner decision SWOB-a (2026-10-07) - the backfill CSVs carry observation times as ISO 8601 with a
UTC offset, readers get the same local minutes from old ``HH:MM`` and new ISO rows, and the maker plugin
clock accepts the new rows (docs/operations/maker-core-contracts.md, plugin clock observed_at contract).
"""
import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from weather.market.maker_plugin.clock import observed_time
from weather.reporting.source_gates.source_redundancy import earliest_minute
from weather.sources.eccc_swob_history import (  # noqa: E402
    DAILY_FIELDS,
    SWOBHistoryStore,
    compare_with_wu,
    parse_swob_xml,
    summarize_daily,
    time_to_minutes,
)

TIME_FIELDS = ("first_time", "last_time", "max_temp_times", "swob_air_temp_max_times", "swob_max_1h_times")


def sample_swob_xml(
    utc_time,
    temp_c,
    max_1h_c,
    dewpoint_c=12.0,
    humidity=55,
    pressure=992.7,
    wind_dir=270,
    wind_speed=18.5,
    gust=32.0,
):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ObservationCollection>
  <element name="stn_nam" value="Toronto/Pearson International" />
  <element name="icao_stn_id" value="CYYZ" />
  <element name="date_tm" value="{utc_time}" />
  <element name="stn_pres" value="{pressure}" />
  <element name="mslp" value="1013.3" />
  <element name="altmetr_setng" value="29.93" />
  <element name="air_temp" value="{temp_c}" />
  <element name="dwpt_temp" value="{dewpoint_c}" />
  <element name="rel_hum" value="{humidity}" />
  <element name="max_air_temp_pst1hr" value="{max_1h_c}" />
  <element name="max_air_temp_pst6hrs" value="25.6" />
  <element name="max_air_temp_pst24hrs" value="26.4" />
  <element name="vis" value="24.140" />
  <element name="avg_wnd_dir_10m_pst2mts" value="{wind_dir}" />
  <element name="avg_wnd_spd_10m_pst2mts" value="{wind_speed}" />
  <element name="max_wnd_gst_spd_10m_pst10mts" value="{gust}" />
  <element name="cld_amt_code_1" value="32" />
  <element name="cld_typ_1" value="7" />
  <element name="cld_bas_hgt_1" value="1220" />
  <element name="prsnt_wx_1" value="125" />
  <element name="rmk" value="CU1CI2" />
</ObservationCollection>"""


class TestECCCSWOBHistory(unittest.TestCase):
    def test_parse_swob_xml_normalizes_to_wu_shape(self):
        row = parse_swob_xml(
            sample_swob_xml("2026-05-27T18:00:00.000Z", 24.8, 24.9),
            source_file="2026-05-27-1800-CYYZ-MAN-swob.xml",
        )

        self.assertEqual(row["station"], "CYYZ")
        self.assertEqual(row["local_date"], "2026-05-27")
        self.assertEqual(row["local_time"], "14:00")
        self.assertEqual(row["minute"], 0)
        self.assertEqual(row["temp_c"], 24.8)
        self.assertEqual(row["dewpoint_c"], 12.0)
        self.assertEqual(row["pressure"], 992.7)
        self.assertEqual(row["wind_cardinal"], "W")
        self.assertEqual(row["swob_max_1h_c"], 24.9)
        self.assertIn("present_wx_code=125", row["condition"])

    def test_daily_summary_uses_swob_one_hour_max_as_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SWOBHistoryStore(Path(tmp) / "swob")
            raw_dir = store.raw_day_dir("2026-05-27")
            raw_dir.mkdir(parents=True)
            (raw_dir / "2026-05-27-1800-CYYZ-MAN-swob.xml").write_text(
                sample_swob_xml("2026-05-27T18:00:00.000Z", 24.8, 24.9),
                encoding="utf-8",
            )
            (raw_dir / "2026-05-27-1900-CYYZ-MAN-swob.xml").write_text(
                sample_swob_xml("2026-05-27T19:00:00.000Z", 24.9, 25.4),
                encoding="utf-8",
            )

            hourly, daily = store.rebuild_normalized_files()

            self.assertEqual(len(hourly), 2)
            self.assertEqual(daily[0]["local_date"], "2026-05-27")
            self.assertEqual(daily[0]["max_temp_c"], 25.4)
            self.assertEqual(daily[0]["max_temp_source"], "swob_1h")
            self.assertEqual(daily[0]["swob_air_temp_max_c"], 24.9)
            self.assertTrue(
                (store.hourly_root / "year=2026" / "month=05" / "observations.jsonl").exists()
            )

    def test_compare_with_wu_tracks_reach_and_lead_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SWOBHistoryStore(root / "swob")
            raw_dir = store.raw_day_dir("2026-05-27")
            raw_dir.mkdir(parents=True)
            (raw_dir / "2026-05-27-1800-CYYZ-MAN-swob.xml").write_text(
                sample_swob_xml("2026-05-27T18:00:00.000Z", 24.8, 24.9),
                encoding="utf-8",
            )
            (raw_dir / "2026-05-27-1900-CYYZ-MAN-swob.xml").write_text(
                sample_swob_xml("2026-05-27T19:00:00.000Z", 24.9, 25.4),
                encoding="utf-8",
            )
            store.rebuild_normalized_files()

            wu_daily = root / "wu" / "daily"
            wu_daily.mkdir(parents=True)
            with (wu_daily / "daily_summary.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "local_date",
                        "row_count",
                        "max_temp_c",
                        "max_temp_times",
                        "max_temp_bucket_c",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "local_date": "2026-05-27",
                        "row_count": "24",
                        "max_temp_c": "25.0",
                        "max_temp_times": "16:00",
                        "max_temp_bucket_c": "25",
                    }
                )

            result = compare_with_wu(
                swob_root=store.root,
                wu_root=root / "wu",
                snapshot_root=root / "missing_snapshots",
                min_swob_row_count=0,
            )

            self.assertEqual(result["summary"]["days_compared"], 1)
            self.assertEqual(result["rows"][0]["swob_first_reach_time"], "2026-05-27T15:00:00-04:00")
            self.assertEqual(result["rows"][0]["swob_times"], "2026-05-27T15:00:00-04:00")
            self.assertEqual(result["rows"][0]["lead_minutes"], 60)  # Unchanged by the ISO format.
            self.assertTrue((store.analysis_root / "comparison_report.md").exists())
            with (store.analysis_root / "comparison_rows.csv").open(encoding="utf-8", newline="") as handle:
                written, = csv.DictReader(handle)
            self.assertEqual(written["swob_first_reach_time"], "2026-05-27T15:00:00-04:00")
            self.assertEqual(written["lead_minutes"], "60")

    def test_daily_csv_times_are_iso_with_offset_and_the_clock_accepts_them(self):
        """SWOB-a: every observation time written to daily_summary.csv is an aware ISO instant."""
        with tempfile.TemporaryDirectory() as tmp:
            store = write_raw_day(Path(tmp) / "swob", [("2026-05-27T18:00:00.000Z", 24.8, 24.9),
                                                       ("2026-05-27T19:00:00.000Z", 24.9, 25.4)])
            store.rebuild_normalized_files()
            with (store.daily_root / "daily_summary.csv").open(encoding="utf-8", newline="") as handle:
                row, = csv.DictReader(handle)
        self.assertEqual(row["first_time"], "2026-05-27T14:00:00-04:00")
        self.assertEqual(row["last_time"], "2026-05-27T15:00:00-04:00")
        self.assertEqual(row["max_temp_times"], "2026-05-27T15:00:00-04:00")
        checked = 0
        for field in TIME_FIELDS:
            for part in filter(None, row[field].split("|")):
                self.assertIsNotNone(datetime.fromisoformat(part).utcoffset(), (field, part))
                instant, refused = observed_time({"observed_at": part})
                self.assertIsNone(refused, (field, part))
                self.assertEqual(instant.tzinfo, timezone.utc)
                checked += 1
        self.assertEqual(checked, len(TIME_FIELDS))
        # The bare HH:MM shape that the clock refuses is no longer written.
        self.assertEqual(observed_time({"observed_at": "14:00"}), (None, "observed_at_unparseable"))

    def test_new_iso_times_give_the_same_minutes_as_the_old_hhmm_times(self):
        """Readers see identical values: old-format (HH:MM) and new-format (ISO) daily rows of the same
        hourly records agree field by field, through both readers, including the DST fall-back hour."""
        observations = []
        start = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        for step in range(0, 40 * 60, 30):  # 40 hours every 30 minutes, across the 2026-11-01 fall-back.
            when = start + timedelta(minutes=step)
            temp = 10.0 + (step % 300) / 100.0
            observations.append((when.strftime("%Y-%m-%dT%H:%M:%S.000Z"), temp, temp + 0.1))
        records = [parse_swob_xml(sample_swob_xml(t, temp, max_1h)) for t, temp, max_1h in observations]
        new_daily = summarize_daily(records)
        old_daily = legacy_summarize_daily(records)
        self.assertEqual(len(new_daily), len(old_daily))
        self.assertIn("2026-11-01", [row["local_date"] for row in new_daily])
        compared = 0
        for new, old in zip(new_daily, old_daily):
            self.assertEqual({k: v for k, v in new.items() if k not in TIME_FIELDS},
                             {k: v for k, v in old.items() if k not in TIME_FIELDS})
            for field in TIME_FIELDS:
                new_parts, old_parts = new[field].split("|"), old[field].split("|")
                self.assertEqual(len(new_parts), len(old_parts))
                for new_part, old_part in zip(new_parts, old_parts):
                    if not old_part:
                        self.assertEqual(new_part, "")
                        continue
                    self.assertNotEqual(new_part, old_part)
                    self.assertEqual(time_to_minutes(new_part), time_to_minutes(old_part))
                    compared += 1
                self.assertEqual(earliest_minute(new[field]), earliest_minute(old[field]))
        self.assertGreater(compared, 10)
        # Both 01:30 readings of the fall-back day keep distinct offsets and the same wall-clock minute.
        fall_back = [r for r in records if r["local_date"] == "2026-11-01" and r["local_time"] == "01:30"]
        self.assertEqual(sorted(r["valid_time_local"] for r in fall_back),
                         ["2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00"])
        self.assertEqual({time_to_minutes(r["valid_time_local"]) for r in fall_back}, {90})

    def test_old_format_daily_csv_on_disk_still_parses(self):
        """A daily_summary.csv written before 2026-10-07 (HH:MM) is never rewritten and still compares."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = write_raw_day(root / "swob", [("2026-05-27T18:00:00.000Z", 24.8, 24.9),
                                                  ("2026-05-27T19:00:00.000Z", 24.9, 25.4)])
            records, _ = store.rebuild_normalized_files()
            old_row = legacy_summarize_daily(records)[0]
            with (store.daily_root / "daily_summary.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=DAILY_FIELDS, extrasaction="ignore")
                writer.writeheader()
                writer.writerow(old_row)
            # The hourly JSONL shape is unchanged by this change: local_time HH:MM plus aware valid_time_local.
            hourly, = store.hourly_root.glob("year=*/month=*/observations.jsonl")
            first = json.loads(hourly.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual((first["local_time"], first["valid_time_local"]),
                             ("14:00", "2026-05-27T14:00:00-04:00"))
            write_wu_daily(root / "wu", "16:00")
            before = (store.daily_root / "daily_summary.csv").read_bytes()
            result = compare_with_wu(swob_root=store.root, wu_root=root / "wu",
                                     snapshot_root=root / "missing_snapshots", min_swob_row_count=0)
            self.assertEqual((store.daily_root / "daily_summary.csv").read_bytes(), before)
        row = result["rows"][0]
        self.assertEqual(row["swob_times"], "15:00")  # The old daily value passes through as it is.
        self.assertEqual(row["lead_minutes"], 60)
        self.assertEqual(earliest_minute(old_row["max_temp_times"]), 15 * 60)
        self.assertEqual(time_to_minutes("15:00"), time_to_minutes("2026-05-27T15:00:00-04:00"))

    def test_time_to_minutes_refuses_a_naive_iso_value(self):
        with self.assertRaises(ValueError):
            time_to_minutes("2026-05-27T15:00:00")
        with self.assertRaises(ValueError):
            time_to_minutes("not a time")


def write_raw_day(root, observations):
    store = SWOBHistoryStore(root)
    for utc_time, temp, max_1h in observations:
        when = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
        raw_dir = store.raw_day_dir(when.date().isoformat())
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{when:%Y-%m-%d-%H%M}-CYYZ-MAN-swob.xml").write_text(
            sample_swob_xml(utc_time, temp, max_1h), encoding="utf-8")
    return store


def write_wu_daily(root, max_time):
    path = Path(root) / "daily" / "daily_summary.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["local_date", "row_count", "max_temp_c", "max_temp_times",
                                                    "max_temp_bucket_c"])
        writer.writeheader()
        writer.writerow({"local_date": "2026-05-27", "row_count": "24", "max_temp_c": "25.0",
                         "max_temp_times": max_time, "max_temp_bucket_c": "25"})


def legacy_summarize_daily(records):
    """The daily summary as written before 2026-10-07: identical except times are the bare local HH:MM."""
    import weather.sources.eccc_swob_history as module

    original = module.observation_time
    module.observation_time = lambda row: row["local_time"]
    try:
        return module.summarize_daily(records)
    finally:
        module.observation_time = original


if __name__ == "__main__":
    unittest.main()
