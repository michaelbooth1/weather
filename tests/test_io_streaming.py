"""Streaming CSV reader contract: identical rows to the materializing reader,
legacy-encoding fallback parity, and flat peak memory as tape size grows."""

from __future__ import annotations

import csv
import gzip
import tracemalloc
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from weather.io import (
    TIERED_TEXT_COMPARE_CHUNK_BYTES,
    TieredTextConflictError,
    TieredTextGzipError,
    iter_csv_rows,
    open_tiered_text,
    pretty_json_root_is_closed,
    read_csv_rows,
    read_pretty_json_object_values,
    read_pretty_json_top_level_values,
    resolve_tiered_text,
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


def _write_gzip(path: Path, payload: bytes) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as handle:
            handle.write(payload)


class TestTieredText(unittest.TestCase):
    def test_plain_only_streams_transparently(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            path.write_bytes(b'{"row":1}\n{"row":2}\n')

            resolution = resolve_tiered_text(path)
            with open_tiered_text(path) as handle:
                rows = list(handle)

            self.assertEqual(resolution.selected_path, path)
            self.assertEqual(resolution.representation, "plain")
            self.assertFalse(resolution.compressed)
            self.assertFalse(resolution.transitional_pair)
            self.assertEqual(rows, ['{"row":1}\n', '{"row":2}\n'])

    def test_gzip_only_streams_when_plain_path_is_requested(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            gzip_path = Path(f"{path}.gz")
            _write_gzip(gzip_path, b'{"row":1}\n{"row":2}\n')

            resolution = resolve_tiered_text(path)
            with open_tiered_text(path) as handle:
                first = handle.readline()
                remaining = list(handle)

            self.assertEqual(resolution.selected_path, gzip_path)
            self.assertEqual(resolution.representation, "gzip")
            self.assertTrue(resolution.compressed)
            self.assertFalse(resolution.transitional_pair)
            self.assertEqual(first, '{"row":1}\n')
            self.assertEqual(remaining, ['{"row":2}\n'])

    def test_identical_transitional_pair_is_accepted_and_selects_plain(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            gzip_path = Path(f"{path}.gz")
            payload = b'{"row":1}\n{"row":2}\n'
            path.write_bytes(payload)
            _write_gzip(gzip_path, payload)

            resolution = resolve_tiered_text(gzip_path)
            with open_tiered_text(path) as handle:
                restored = handle.read()

            self.assertEqual(resolution.selected_path, path)
            self.assertEqual(resolution.representation, "plain")
            self.assertTrue(resolution.transitional_pair)
            self.assertEqual(restored.encode("utf-8"), payload)

    def test_pair_mismatch_after_first_chunk_fails_before_handle_is_returned(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            gzip_path = Path(f"{path}.gz")
            prefix = b"x" * (TIERED_TEXT_COMPARE_CHUNK_BYTES + 17)
            path.write_bytes(prefix + b"plain-tail\n")
            _write_gzip(gzip_path, prefix + b"gzip-tail\n")
            entered = False

            with self.assertRaises(TieredTextConflictError):
                with open_tiered_text(path):
                    entered = True

            self.assertFalse(entered)

    def test_truncated_transitional_gzip_fails_before_handle_is_returned(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            gzip_path = Path(f"{path}.gz")
            payload = b'{"row":1}\n{"row":2}\n'
            path.write_bytes(payload)
            _write_gzip(gzip_path, payload)
            gzip_path.write_bytes(gzip_path.read_bytes()[:-8])
            entered = False

            with self.assertRaises(TieredTextGzipError):
                with open_tiered_text(path):
                    entered = True

            self.assertFalse(entered)

    def test_truncated_gzip_only_fails_loudly_while_streaming(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            gzip_path = Path(f"{path}.gz")
            _write_gzip(gzip_path, b'{"row":1}\n{"row":2}\n')
            gzip_path.write_bytes(gzip_path.read_bytes()[:-8])

            with self.assertRaises(TieredTextGzipError):
                with open_tiered_text(path) as handle:
                    handle.read()


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

    def test_pretty_json_object_values_skip_growing_sibling_array(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "price-free.json"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write('{\n  "current_max_carryover": {\n')
                handle.write('    "by_market_hour": [{"market_id": "toronto"}],\n')
                handle.write('    "examples": [{"snapshot_id": "example"}],\n')
                handle.write('    "rows": [\n')
                for index in range(50_000):
                    comma = "," if index < 49_999 else ""
                    handle.write(f'      {{"snapshot_id": "s-{index}"}}{comma}\n')
                handle.write('    ],\n')
                handle.write('    "summary": {"snapshot_rows": 50000}\n')
                handle.write('  },\n  "status": "OK"\n}\n')

            tracemalloc.start()
            values = read_pretty_json_object_values(
                path,
                "current_max_carryover",
                ("by_market_hour", "examples", "summary"),
            )
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            self.assertEqual(
                values,
                {
                    "by_market_hour": [{"market_id": "toronto"}],
                    "examples": [{"snapshot_id": "example"}],
                    "summary": {"snapshot_rows": 50000},
                },
            )
            self.assertLess(peak, 512 * 1024)

    def test_pretty_json_object_values_reject_truncated_object(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "truncated.json"
            path.write_text(
                '{\n  "current_max_carryover": {\n'
                '    "summary": {"snapshot_rows": 1}\n',
                encoding="utf-8",
            )
            self.assertEqual(
                read_pretty_json_object_values(
                    path,
                    "current_max_carryover",
                    ("summary",),
                ),
                {},
            )

    def test_pretty_json_root_close_must_be_at_column_zero(self):
        with TemporaryDirectory() as tmp:
            valid = Path(tmp) / "valid.json"
            nested_only = Path(tmp) / "nested-only.json"
            valid.write_bytes(b'{\n  "value": {}\n}\n')
            nested_only.write_bytes(b'{\n  "value": {\n  }\n')

            self.assertTrue(pretty_json_root_is_closed(valid))
            self.assertFalse(pretty_json_root_is_closed(nested_only))


if __name__ == "__main__":
    unittest.main()
