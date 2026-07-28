import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from weather.io import read_csv_rows_with_diagnostics
from weather.market.market_making_run_support import latest_book_rows, preflight_csv_encoding_diagnostics
from weather.operations.market_making_tape_encoding import build_payload, discover_files


def write_legacy_book(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"captured_at_utc,event_slug,market_id,range_label,outcome,best_bid,best_ask\n"
        b"2026-06-17T12:00:00+00:00,event,nyc,80\xb0 F,yes,0.49,0.51\n"
    )


class TestMarketMakingCsvEncoding(unittest.TestCase):
    def test_encoding_audit_discovers_and_reads_gzip_long_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "event" / "order_books_long.csv.gz"
            path.parent.mkdir(parents=True)
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                handle.write("capture_id,price,size\nbook-1,0.49,12\n")

            discovered = discover_files(roots=[root])
            payload = build_payload(discovered, repair=False)

        self.assertEqual(discovered, [path])
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["summary"]["file_count"], 1)
        self.assertEqual(payload["files"][0]["status"], "ok")
        self.assertEqual(payload["files"][0]["compression"], "gzip")
        self.assertEqual(payload["files"][0]["row_count"], 1)
        self.assertEqual(payload["files"][0]["fieldnames"], ["capture_id", "price", "size"])

    def test_encoding_repair_refuses_compressed_input_without_changing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order_books_long.csv.gz"
            with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
                handle.write("capture_id,price,size\nbook-1,0.49,12\n")
            before = path.read_bytes()

            payload = build_payload([path], repair=True, backup=True)
            after = path.read_bytes()

        self.assertEqual(before, after)
        self.assertEqual(payload["repair"]["repaired"], [])
        self.assertEqual(len(payload["repair"]["skipped"]), 1)
        self.assertEqual(
            payload["repair"]["skipped"][0]["status"],
            "refused_compressed_input",
        )
        self.assertIn("read-only audit", payload["repair"]["skipped"][0]["reason"])

    def test_shared_reader_reports_legacy_degree_byte_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order_books_summary.csv"
            write_legacy_book(path)

            rows, diagnostics = read_csv_rows_with_diagnostics(path, attach_diagnostics=True)

        self.assertEqual(diagnostics["status"], "legacy_encoding")
        self.assertEqual(diagnostics["encoding"], "cp1252")
        self.assertEqual(diagnostics["quarantined_row_count"], 1)
        self.assertEqual(rows[0]["_csv_encoding_status"], "legacy_encoding")
        self.assertIn("\u00b0", rows[0]["range_label"])

    def test_market_making_book_reader_and_preflight_diagnostics_tolerate_legacy_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "snapshots" / "event"
            write_legacy_book(folder / "order_books_summary.csv")

            rows = latest_book_rows(folder)
            diagnostics = preflight_csv_encoding_diagnostics(folder)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_csv_source_encoding"], "cp1252")
        self.assertEqual(diagnostics["status"], "WARN")
        self.assertEqual(diagnostics["quarantined_row_count"], 1)

    def test_encoding_repair_rewrites_legacy_book_tape_as_utf8_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "order_books_summary.csv"
            write_legacy_book(path)

            before = build_payload([path], repair=False)
            after = build_payload([path], repair=True, backup=True)
            repaired_text = path.read_text(encoding="utf-8")
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            backup_exists = Path(after["repair"]["repaired"][0]["backup_path"]).exists()

        self.assertEqual(before["status"], "WARN")
        self.assertEqual(after["status"], "PASS")
        self.assertEqual(after["repair"]["repaired"][0]["source_encoding"], "cp1252")
        self.assertTrue(backup_exists)
        self.assertIn("deg", repaired_text)
        self.assertEqual(rows[0]["range_label"], "80 deg F")


if __name__ == "__main__":
    unittest.main()
