import os
import sys
import unittest
from datetime import date


sys.path.insert(0, os.path.abspath("src"))

from market_config import config_for_date, date_from_event_slug, event_slug_for_date  # noqa: E402
from snapshot_tracker import SnapshotStore  # noqa: E402


class TestMarketConfig(unittest.TestCase):
    def test_event_slug_round_trips_target_date(self):
        target = date(2026, 5, 28)
        slug = event_slug_for_date(target)

        self.assertEqual(slug, "highest-temperature-in-toronto-on-may-28-2026")
        self.assertEqual(date_from_event_slug(slug), target)

    def test_snapshot_store_defaults_to_event_slug_folder(self):
        config = config_for_date(date(2026, 5, 28))
        store = SnapshotStore(event_slug=config.event_slug)

        self.assertEqual(
            store.root.as_posix(),
            "data/snapshots/highest-temperature-in-toronto-on-may-28-2026",
        )


if __name__ == "__main__":
    unittest.main()
