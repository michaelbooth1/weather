import csv
import gzip
import tempfile
import unittest
from pathlib import Path

from weather.io import read_csv_rows_with_diagnostics
from weather.market.market_making_run_support import latest_book_rows, preflight_csv_encoding_diagnostics


def write_legacy_book(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"captured_at_utc,event_slug,market_id,range_label,outcome,best_bid,best_ask\n"
        b"2026-06-17T12:00:00+00:00,event,nyc,80\xb0 F,yes,0.49,0.51\n"
    )


class TestMarketMakingCsvEncoding(unittest.TestCase):
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

if __name__ == "__main__":
    unittest.main()
