import os
import sys
import unittest

sys.path.insert(0, os.path.abspath("src"))

import forecast_history as fh
import wu_history as wh
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


if __name__ == "__main__":
    unittest.main()
