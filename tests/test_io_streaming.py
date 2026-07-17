"""Streaming CSV reader contract: identical rows to the materializing reader,
legacy-encoding fallback parity, and flat peak memory as tape size grows."""

from __future__ import annotations

import csv
import tracemalloc
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from weather.io import (
    iter_csv_rows,
    read_csv_rows,
    read_pretty_json_top_level_values,
)


def _write_csv(path: Path, row_count: int, *, encoding: str = "utf-8") -> None:
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["market_id", "target_date", "note"])
        writer.writeheader()
        for index in range(row_count):
            writer.writerow(
                {
                    "market_id": f"market-{index % 12}",
                    "target_date": f"2026-07-{(index % 28) + 1:02d}",
                    "note": "x" * 64,
                }
            )


class TestIterCsvRows(unittest.TestCase):
    def test_streaming_rows_match_materializing_reader(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tape.csv"
            _write_csv(path, 250)
            self.assertEqual(list(iter_csv_rows(path)), read_csv_rows(path))

    def test_missing_file_yields_nothing(self):
        self.assertEqual(list(iter_csv_rows(Path("does-not-exist.csv"))), [])

    def test_legacy_encoding_falls_back_with_identical_provenance(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.csv"
            payload = "market_id,target_date,note\r\natlanta,2026-07-01,café\r\n"
            path.write_bytes(payload.encode("cp1252"))
            streamed = list(iter_csv_rows(path, attach_diagnostics=True))
            materialized = read_csv_rows(path, attach_diagnostics=True)
            self.assertEqual(streamed, materialized)
            self.assertEqual(streamed[0]["_csv_encoding_status"], "legacy_encoding")

    def test_peak_memory_stays_flat_as_tape_grows(self):
        with TemporaryDirectory() as tmp:
            small = Path(tmp) / "small.csv"
            large = Path(tmp) / "large.csv"
            _write_csv(small, 1_000)
            _write_csv(large, 50_000)

            def peak_during_full_iteration(path: Path) -> int:
                tracemalloc.start()
                count = 0
                for _row in iter_csv_rows(path):
                    count += 1
                _current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                self.assertGreater(count, 0)
                return peak

            small_peak = peak_during_full_iteration(small)
            large_peak = peak_during_full_iteration(large)
            # A materializing reader scales peak ~50x here; streaming must not.
            self.assertLess(large_peak, small_peak * 5)

    def test_pretty_json_top_level_values_skip_large_nested_payload(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.json"
            with path.open("wb") as handle:
                handle.write(b"{\n")
                handle.write(b'  "pnl": {\n')
                handle.write(b'    "huge": "' + (b"x" * (2 * 1024 * 1024)) + b'"\n')
                handle.write(b"  },\n")
                handle.write(b'  "run_id": "run-1",\n')
                handle.write(b'  "summary": {\n')
                handle.write(b'    "budget_usdc": 100.0,\n')
                handle.write(b'    "cumulative_filled_orders": 2\n')
                handle.write(b"  },\n")
                handle.write(b'  "target_date": "2026-07-14"\n')
                handle.write(b"}\n")

            tracemalloc.start()
            values = read_pretty_json_top_level_values(
                path,
                ("run_id", "summary", "target_date"),
                max_line_bytes=64 * 1024,
            )
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            self.assertEqual(values, {
                "run_id": "run-1",
                "summary": {
                    "budget_usdc": 100.0,
                    "cumulative_filled_orders": 2,
                },
                "target_date": "2026-07-14",
            })
            self.assertLess(peak, 512 * 1024)

    def test_pretty_json_top_level_values_omit_oversized_selected_scalar(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "selected-too-large.json"
            path.write_text(
                '{\n  "run_id": "' + ("x" * 128) + '"\n}\n',
                encoding="utf-8",
            )

            self.assertEqual(
                read_pretty_json_top_level_values(
                    path,
                    ("run_id",),
                    max_line_bytes=1_024,
                    max_value_bytes=32,
                ),
                {},
            )


if __name__ == "__main__":
    unittest.main()
