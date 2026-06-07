import os
import sys
import unittest
from datetime import date
from pathlib import Path
import tempfile
import requests

sys.path.insert(0, os.path.abspath("src"))

import forecast_history as fh
import wu_history as wh
import backfill_all
from market_registry import NYC, TORONTO


class TestBackfillParameterization(unittest.TestCase):
    """The backfill tools must be registry-driven, with Toronto defaults intact."""

    def test_forecast_paths_per_market(self):
        self.assertEqual(fh.daily_path_for(TORONTO).as_posix(),
                         "data/forecast_history/cyyz/forecast_daily.csv")
        self.assertEqual(fh.daily_path_for(NYC).as_posix(),
                         "data/forecast_history/klga/forecast_daily.csv")
        self.assertEqual(fh.DAILY_PATH, fh.daily_path_for(TORONTO))  # back-compat default

    def test_wu_client_uses_market_history_id(self):
        self.assertIn("KLGA:9:US", wh.WundergroundHistoryClient(history_id=NYC.wu_history_id).url)
        self.assertIn("CYYZ:9:CA", wh.WundergroundHistoryClient().url)  # default toronto

    def test_wu_store_data_root_per_market(self):
        store = wh.WundergroundHistoryStore(
            str(NYC.data_root), station_icao=NYC.icao, history_id=NYC.wu_history_id
        )
        self.assertEqual(store.station_icao, "KLGA")
        self.assertEqual(store.history_id, "KLGA:9:US")
        self.assertEqual(store.root.as_posix(), "data/wunderground/klga")

    def test_wu_store_missing_ranges_are_resumable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = wh.WundergroundHistoryStore(root)
            for day in ("2026-05-01", "2026-05-03"):
                path = root / "raw" / "year=2026" / "month=05" / f"{day}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"observations": []}', encoding="utf-8")

            ranges = store.missing_ranges(date(2026, 5, 1), date(2026, 5, 5), chunk_days=2)

            self.assertEqual(ranges, [
                (date(2026, 5, 2), date(2026, 5, 2)),
                (date(2026, 5, 4), date(2026, 5, 5)),
            ])

    def test_wu_store_source_unavailable_dates_are_not_requeued(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = wh.WundergroundHistoryStore(tmp)
            store.write_fetch_error(date(2026, 5, 2), date(2026, 5, 2), requests.HTTPError("400"))

            ranges = store.missing_ranges(date(2026, 5, 1), date(2026, 5, 3), chunk_days=7)
            coverage = wh.history_coverage(store, date(2026, 5, 1), date(2026, 5, 3))

            self.assertEqual(ranges, [
                (date(2026, 5, 1), date(2026, 5, 1)),
                (date(2026, 5, 3), date(2026, 5, 3)),
            ])
            self.assertEqual(coverage["source_unavailable_days"], 1)

    def test_fleet_backfill_builds_source_specific_commands(self):
        python = "python"

        wu = backfill_all.build_command("wu", python, "nyc", "2020-05-01", "2020-05-03", 14, 0.1, True)
        ghcnh = backfill_all.build_command("ghcnh", python, "nyc", "2020-05-01", "2022-05-03", 14, 0.1, True)
        reanalysis = backfill_all.build_command("reanalysis", python, "nyc", "2020-05-01", "2020-05-03", 14, 0.1, True)

        self.assertIn("src.wu_history", wu)
        self.assertIn("src.noaa_ghcnh_history", ghcnh)
        self.assertIn("2020", ghcnh)
        self.assertIn("2022", ghcnh)
        self.assertIn("src.reanalysis_history", reanalysis)
        self.assertIn("--skip-existing", wu)
        self.assertIn("--continue-on-error", wu)
        self.assertTrue(ghcnh[-1] == reanalysis[-1] == "--skip-existing")


if __name__ == "__main__":
    unittest.main()
