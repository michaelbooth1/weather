import csv
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from market_registry import spec_for_id  # noqa: E402
from metar_history import MetarStore, chunk_date_ranges, normalize_csv  # noqa: E402


CSV_TEXT = """station,valid,tmpc,dwpc,relh,drct,sknt,gust,alti,mslp,vsby,skyc1,skyc2,skyc3,wxcodes
KLGA,2026-06-01 18:00,30,20,50,180,10,15,29.92,1013,10,CLR,,,RA
KLGA,2026-06-01 21:00,31,21,45,200,12,18,29.90,1012,10,FEW,SCT,, 
"""


class TestMetarHistory(unittest.TestCase):
    def test_chunk_date_ranges_splits_inclusive_windows(self):
        ranges = chunk_date_ranges(date(2026, 6, 1), date(2026, 6, 5), chunk_days=2)

        self.assertEqual(ranges, [
            (date(2026, 6, 1), date(2026, 6, 2)),
            (date(2026, 6, 3), date(2026, 6, 4)),
            (date(2026, 6, 5), date(2026, 6, 5)),
        ])

    def test_normalize_csv_uses_market_native_units(self):
        spec = spec_for_id("nyc")
        records = normalize_csv(CSV_TEXT, spec)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["source"], "metar_asos")
        self.assertEqual(records[0]["temperature_unit"], "F")
        self.assertAlmostEqual(records[0]["temp_native"], 86.0)
        self.assertAlmostEqual(records[0]["dewpoint_native"], 68.0)
        self.assertAlmostEqual(records[0]["wind_speed_kmh"], 18.52)
        self.assertAlmostEqual(records[0]["pressure_hpa"], 1013.21)
        self.assertEqual(records[0]["local_date"], "2026-06-01")

    def test_rebuild_writes_daily_summary_and_manifest(self):
        spec = spec_for_id("nyc")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MetarStore(spec, root=root)
            store.raw_root.mkdir(parents=True)
            (store.raw_root / "asos_2026-06-01_2026-06-01.csv").write_text(CSV_TEXT, encoding="utf-8")

            result = store.rebuild()

            self.assertEqual(result["records"], 2)
            self.assertEqual(result["daily_rows"], 1)
            with (store.daily_root / "daily_summary.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["source"], "metar_asos")
        self.assertEqual(rows[0]["temperature_unit"], "F")
        self.assertAlmostEqual(float(rows[0]["max_temp"]), 87.8)
        self.assertEqual(int(rows[0]["max_temp_bucket"]), 88)
        self.assertEqual(rows[0]["max_temp_times"], "17:00")

    def test_backfill_fetches_chunks_and_rebuilds_once(self):
        class FakeClient:
            def __init__(self):
                self.fetches = []

            def fetch(self, station, start_date, end_date):
                self.fetches.append((station, start_date, end_date))
                return CSV_TEXT

        spec = spec_for_id("nyc")
        with tempfile.TemporaryDirectory() as tmp:
            store = MetarStore(spec, root=Path(tmp))
            client = FakeClient()

            result = store.backfill(
                date(2026, 6, 1),
                date(2026, 6, 3),
                client=client,
                chunk_days=2,
            )

            self.assertEqual(client.fetches, [
                ("KLGA", date(2026, 6, 1), date(2026, 6, 2)),
                ("KLGA", date(2026, 6, 3), date(2026, 6, 3)),
            ])
            self.assertTrue((store.raw_root / "asos_2026-06-01_2026-06-02.csv").exists())
            self.assertTrue((store.raw_root / "asos_2026-06-03_2026-06-03.csv").exists())
            self.assertEqual(result["daily_rows"], 1)


if __name__ == "__main__":
    unittest.main()
