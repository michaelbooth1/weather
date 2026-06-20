import gzip
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from weather.operations.clob_order_book_tiering import build_payload, run


DiskUsage = namedtuple("DiskUsage", "total used free")


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_long_book(folder, text="capture_id,side,level_index,price,size\nb1,bid,1,0.40,10\n"):
    write(folder / "order_books_summary.csv", "capture_id,best_bid,best_ask\nb1,0.40,0.45\n")
    write(folder / "order_books.jsonl", "{}\n")
    write(folder / "clob_tokens.csv", "token\n")
    return write(folder / "order_books_long.csv", text)


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
