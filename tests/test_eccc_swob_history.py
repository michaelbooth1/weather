import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, os.path.abspath("src"))

from eccc_swob_history import (  # noqa: E402
    SWOBHistoryStore,
    compare_with_wu,
    parse_swob_xml,
)


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
            self.assertEqual(result["rows"][0]["swob_first_reach_time"], "15:00")
            self.assertEqual(result["rows"][0]["lead_minutes"], 60)
            self.assertTrue((store.analysis_root / "comparison_report.md").exists())


if __name__ == "__main__":
    unittest.main()
