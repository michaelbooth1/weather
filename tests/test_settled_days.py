import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.abspath("src"))

from settled_days import discover_settled_folders, discover_settled_slugs


def _make_day(root, slug, files=("snapshots_long.csv",)):
    folder = Path(root) / slug
    folder.mkdir(parents=True, exist_ok=True)
    for name in files:
        (folder / name).write_text("x", encoding="utf-8")
    return folder


SETTLED_A = "highest-temperature-in-toronto-on-may-27-2026"   # settled
SETTLED_B = "highest-temperature-in-toronto-on-may-28-2026"   # settled (later)
TODAY = "highest-temperature-in-toronto-on-june-3-2026"       # not settled (== as_of)
FUTURE = "highest-temperature-in-toronto-on-june-9-2026"      # not settled (> as_of)
AS_OF = date(2026, 6, 3)


class TestSettledDayDiscovery(unittest.TestCase):
    def test_includes_only_settled_days_with_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_day(tmp, SETTLED_A)
            _make_day(tmp, SETTLED_B)
            _make_day(tmp, TODAY)
            _make_day(tmp, FUTURE)
            slugs = discover_settled_slugs(tmp, as_of=AS_OF)
            self.assertEqual(slugs, [SETTLED_A, SETTLED_B])  # settled, chronological

    def test_today_and_future_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_day(tmp, TODAY)
            _make_day(tmp, FUTURE)
            self.assertEqual(discover_settled_slugs(tmp, as_of=AS_OF), [])

    def test_missing_tape_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_day(tmp, SETTLED_A, files=())            # folder, no tape
            _make_day(tmp, SETTLED_B)                       # has tape
            self.assertEqual(discover_settled_slugs(tmp, as_of=AS_OF), [SETTLED_B])

    def test_required_file_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_day(tmp, SETTLED_A, files=("snapshots_long.csv",))   # no forecasts tape
            _make_day(tmp, SETTLED_B, files=("snapshots_long.csv", "forecasts_long.csv"))
            self.assertEqual(
                discover_settled_slugs(tmp, as_of=AS_OF, required_file="forecasts_long.csv"),
                [SETTLED_B],
            )

    def test_non_market_folders_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_day(tmp, SETTLED_A)
            (Path(tmp) / "loop_status.json").write_text("{}", encoding="utf-8")  # stray file
            _make_day(tmp, "some-other-event-2026")        # unparseable slug
            self.assertEqual(discover_settled_slugs(tmp, as_of=AS_OF), [SETTLED_A])

    def test_as_of_accepts_datetime_and_iso_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_day(tmp, SETTLED_A)
            _make_day(tmp, SETTLED_B)
            from datetime import datetime
            self.assertEqual(
                discover_settled_slugs(tmp, as_of=datetime(2026, 5, 28, 9, 0)),
                [SETTLED_A],   # may-28 not yet settled at as_of == may-28
            )
            self.assertEqual(discover_settled_slugs(tmp, as_of="2026-05-28"), [SETTLED_A])

    def test_missing_root_returns_empty(self):
        self.assertEqual(discover_settled_folders(Path("does/not/exist")), [])

    def test_reproduces_real_six_day_list(self):
        # Against the live data root, as of today it must match the former
        # hand-maintained list (and exclude today's still-resolving market).
        slugs = discover_settled_slugs(as_of=date(2026, 6, 3))
        self.assertEqual(slugs, [
            "highest-temperature-in-toronto-on-may-27-2026",
            "highest-temperature-in-toronto-on-may-28-2026",
            "highest-temperature-in-toronto-on-may-30-2026",
            "highest-temperature-in-toronto-on-may-31-2026",
            "highest-temperature-in-toronto-on-june-1-2026",
            "highest-temperature-in-toronto-on-june-2-2026",
        ])


if __name__ == "__main__":
    unittest.main()
