import gzip
import os
import tempfile
import time
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from weather.operations.clob_order_book_tiering import MIN_QUIET_SECONDS, build_payload, run


DiskUsage = namedtuple("DiskUsage", "total used free")


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_long_book(folder, text="capture_id,side,level_index,price,size\nb1,bid,1,0.40,10\n", *, quiet=True):
    write(folder / "order_books_summary.csv", "capture_id,best_bid,best_ask\nb1,0.40,0.45\n")
    write(folder / "order_books.jsonl", "{}\n")
    write(folder / "clob_tokens.csv", "token\n")
    source = write(folder / "order_books_long.csv", text)
    if quiet:
        # These fixtures stand in for closed days, so age them past MIN_QUIET_SECONDS.
        # A freshly written file is deliberately ineligible: the writer may still hold it.
        old = time.time() - (MIN_QUIET_SECONDS + 60)
        os.utime(source, (old, old))
    return source


class ClobOrderBookTieringTests(unittest.TestCase):
    def test_plan_identifies_settled_candidates_and_blocks_active_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settled = root / "highest-temperature-in-nyc-on-june-16-2026"
            active = root / "highest-temperature-in-nyc-on-june-20-2026"
            unknown = root / "manual-event"
            write_long_book(settled)
            write_long_book(active)
            write_long_book(unknown)

            payload = build_payload(root, settled_before="2026-06-19", min_free_bytes=0)

        counts = payload["summary"]["status_counts"]
        self.assertEqual(payload["status"], "WARN")
        self.assertEqual(counts["candidate"], 1)
        self.assertEqual(counts["blocked_active_or_unsettled"], 1)
        self.assertEqual(counts["blocked_unknown_event_date"], 1)
        self.assertGreater(payload["summary"]["candidate_bytes"], 0)

    def test_settled_day_still_being_written_is_not_a_candidate(self):
        # The UTC-vs-local cutoff once marked the current day settled from 20:00 local while
        # the CLOB loop was still appending (2026-07-27). The date arithmetic is only a cheap
        # pre-filter; recent writer activity is the invariant that actually protects the file.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder, quiet=False)

            payload = build_payload(root, settled_before="2026-06-19", min_free_bytes=0)

        counts = payload["summary"]["status_counts"]
        self.assertEqual(counts.get("candidate", 0), 0)
        self.assertEqual(counts["blocked_recently_written"], 1)

    def test_apply_refuses_a_source_written_since_the_plan(self):
        # Apply re-checks rather than trusting the plan: a plan can be hours old.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            source = write_long_book(folder)

            payload = build_payload(root, settled_before="2026-06-19", min_free_bytes=0)
            self.assertEqual(payload["summary"]["status_counts"]["candidate"], 1)

            # A writer touches the file between plan and apply.
            source.write_text("capture_id,side,level_index,price,size\nb2,ask,1,0.55,4\n", encoding="utf-8")

            from weather.operations.clob_order_book_tiering import apply_tiering

            result = apply_tiering(payload, delete_source=True)

            self.assertTrue(source.exists(), "source must survive a refused apply")
            self.assertFalse(folder.joinpath("order_books_long.csv.gz").exists())

        self.assertEqual(result["actions"][0]["status"], "skipped_recently_written")
        self.assertEqual(result["summary"]["deleted_sources"], 0)

    def test_apply_compresses_and_deletes_source_after_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            source_text = "capture_id,side,level_index,price,size\nb1,bid,1,0.40,10\n"
            write_long_book(folder, source_text)

            payload = run(
                snapshots_root=root,
                settled_before="2026-06-19",
                min_free_bytes=0,
                apply=True,
                delete_source=True,
            )
            gzip_path = folder / "order_books_long.csv.gz"

            with gzip.open(gzip_path, "rt", encoding="utf-8") as handle:
                restored = handle.read()
            source_exists = (folder / "order_books_long.csv").exists()
            gzip_exists = gzip_path.exists()

        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(source_exists)
        self.assertTrue(gzip_exists)
        self.assertEqual(restored, source_text)
        self.assertEqual(payload["apply"]["summary"]["compressed_files"], 1)
        self.assertEqual(payload["apply"]["summary"]["deleted_sources"], 1)

    def test_apply_skips_without_headroom_and_leaves_source_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder)

            with patch(
                "weather.operations.clob_order_book_tiering.shutil.disk_usage",
                return_value=DiskUsage(total=100, used=99, free=1),
            ):
                payload = run(
                    snapshots_root=root,
                    settled_before="2026-06-19",
                    min_free_bytes=100,
                    apply=True,
                    delete_source=True,
                )
            source_exists = (folder / "order_books_long.csv").exists()
            gzip_exists = (folder / "order_books_long.csv.gz").exists()

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertTrue(source_exists)
        self.assertFalse(gzip_exists)
        self.assertEqual(payload["apply"]["summary"]["insufficient_headroom"], 1)

    def test_headroom_is_sized_to_the_gzip_written_not_the_source_replaced(self):
        # 2026-09-18: the only recurring reclaim refused at ~2.5 GiB free because it reserved the
        # whole source on top of the floor, to write ~1/25 of it and then free the source.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            source = write_long_book(folder, "capture_id,side\n" + "b1,bid\n" * 4000)
            source_bytes = source.stat().st_size
            floor = 1000
            free = floor + source_bytes // 2

            with patch(
                "weather.operations.clob_order_book_tiering.shutil.disk_usage",
                return_value=DiskUsage(total=10 * free, used=9 * free, free=free),
            ):
                payload = run(
                    snapshots_root=root,
                    settled_before="2026-06-19",
                    min_free_bytes=floor,
                    apply=True,
                    delete_source=True,
                )
            action = payload["apply"]["actions"][0]
            source_exists = source.exists()

        self.assertLess(free, source_bytes + floor)
        self.assertEqual(action["required_free_bytes"], -(-source_bytes // 4) + floor)
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(source_exists)

    def test_writer_aborts_when_the_floor_is_breached_mid_write_and_keeps_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            source = write_long_book(folder, "capture_id,side\n" + "b1,bid\n" * 4000)
            readings = iter([DiskUsage(total=10**9, used=0, free=10**9)])

            def shrinking_disk(_path):
                return next(readings, DiskUsage(total=10**9, used=10**9 - 1, free=1))

            with patch(
                "weather.operations.clob_order_book_tiering.shutil.disk_usage",
                side_effect=shrinking_disk,
            ), patch("weather.operations.clob_order_book_tiering.HEADROOM_RECHECK_BYTES", 1):
                payload = run(
                    snapshots_root=root,
                    settled_before="2026-06-19",
                    min_free_bytes=1000,
                    apply=True,
                    delete_source=True,
                )
            action = payload["apply"]["actions"][0]
            leftovers = sorted(path.name for path in folder.iterdir() if ".gz" in path.name)
            source_exists = source.exists()

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(action["status"], "skipped_insufficient_headroom")
        self.assertTrue(action["floor_breached_during_write"])
        self.assertTrue(source_exists)
        self.assertEqual(leftovers, [])

    def test_a_candidate_blocked_at_its_turn_is_retried_after_later_deletes_free_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            big_folder = root / "highest-temperature-in-atlanta-on-june-16-2026"
            small_folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            big = write_long_book(big_folder, "capture_id,side\n" + "b1,bid\n" * 8000)
            small = write_long_book(small_folder, "capture_id,side\n" + "b1,bid\n" * 40)
            floor = 1000
            tight = floor + small.stat().st_size
            big_required = -(-big.stat().st_size // 4) + floor

            def disk(_path):
                # Roomy only once the small source has been verified and deleted.
                free = tight if small.exists() else 10**9
                return DiskUsage(total=10**10, used=0, free=free)

            with patch(
                "weather.operations.clob_order_book_tiering.shutil.disk_usage",
                side_effect=disk,
            ):
                payload = run(
                    snapshots_root=root,
                    settled_before="2026-06-19",
                    min_free_bytes=floor,
                    apply=True,
                    delete_source=True,
                )
            by_source = {
                Path(action["source_path"]).parent.name: action
                for action in payload["apply"]["actions"]
            }
            big_exists = big.exists()

        self.assertLess(tight, big_required)
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(big_exists)
        self.assertTrue(by_source[big_folder.name]["retried_after_reclaim"])
        self.assertEqual(by_source[big_folder.name]["status"], "compressed")
        self.assertNotIn("retried_after_reclaim", by_source[small_folder.name])

    def test_apply_records_compression_failures_without_deleting_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "highest-temperature-in-nyc-on-june-16-2026"
            write_long_book(folder)
            (folder / "order_books_long.csv.gz.tmp").write_text("leftover\n", encoding="utf-8")

            payload = run(
                snapshots_root=root,
                settled_before="2026-06-19",
                min_free_bytes=0,
                apply=True,
                delete_source=True,
            )
            source_exists = (folder / "order_books_long.csv").exists()

        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(payload["apply"]["actions"][0]["status"], "failed")
        self.assertIn("temporary gzip path already exists", payload["apply"]["actions"][0]["error"])
        self.assertTrue(source_exists)


if __name__ == "__main__":
    unittest.main()
