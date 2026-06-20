import csv
import tempfile
import unittest
from pathlib import Path

from weather.reporting.clob_coverage_audit import (
    audit_folder,
    build_payload,
    classify_folder,
    parse_event_slug,
    write_markdown_report,
)


FIELDS = [
    "snapshot_id",
    "captured_at_utc",
    "event_slug",
    "market_id",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "clob_token_id",
    "clob_book_captured_at_utc",
    "clob_feature_available",
    "clob_book_age_seconds",
    "clob_midpoint",
    "clob_spread",
    "clob_best_bid",
    "clob_best_ask",
    "clob_liquidity_score",
]


def write_snapshots(folder):
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["snapshot_id"])
        writer.writeheader()
        writer.writerow({"snapshot_id": "s1"})


def write_features(folder, rows):
    with (folder / "clob_features_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def feature(**overrides):
    row = {
        "snapshot_id": "s1",
        "captured_at_utc": "2026-06-13T00:00:00+00:00",
        "event_slug": "event",
        "market_id": "nyc",
        "range_label": "80-81F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": "",
        "clob_book_captured_at_utc": "",
        "clob_feature_available": "0.0",
        "clob_book_age_seconds": "",
        "clob_midpoint": "",
        "clob_spread": "",
        "clob_best_bid": "",
        "clob_best_ask": "",
        "clob_liquidity_score": "",
    }
    row.update({key: str(value) for key, value in overrides.items()})
    return row


class ClobCoverageAuditTests(unittest.TestCase):
    def test_parse_event_slug_extracts_market_and_target_date(self):
        parsed = parse_event_slug("highest-temperature-in-san-francisco-on-june-13-2026")

        self.assertEqual(parsed["market_id"], "san-francisco")
        self.assertEqual(parsed["target_date"], "2026-06-13")

    def test_classifies_missing_raw_tape_and_token_map(self):
        summary = {
            "raw_book_present": False,
            "token_file_present": False,
            "features": {"feature_rows": 2, "token_rows": 0, "midpoint_rows": 0, "feature_available_rows": 0},
        }

        self.assertEqual(classify_folder(summary), "missing_raw_clob_tape_and_token_map")

    def test_audit_folder_classifies_midpoint_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_snapshots(folder)
            (folder / "order_books_summary.csv").write_text("x\n", encoding="utf-8")
            (folder / "clob_tokens.csv").write_text("x\n", encoding="utf-8")
            write_features(folder, [
                feature(
                    clob_token_id="token",
                    clob_feature_available="1.0",
                    clob_midpoint="0.40",
                    clob_spread="0.02",
                    clob_best_bid="0.39",
                    clob_best_ask="0.41",
                    clob_liquidity_score="1.5",
                )
            ])

            payload = audit_folder(folder)

        self.assertEqual(payload["classification"], "midpoint_available")
        self.assertAlmostEqual(payload["features"]["midpoint_coverage"], 1.0)

    def test_audit_folder_classifies_one_sided_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_snapshots(folder)
            (folder / "order_books_long.csv.gz").write_bytes(b"gzip bytes\n")
            (folder / "clob_tokens.csv").write_text("x\n", encoding="utf-8")
            write_features(folder, [
                feature(
                    clob_token_id="token",
                    clob_feature_available="1.0",
                    clob_best_ask="0.01",
                )
            ])

            payload = audit_folder(folder)

        self.assertEqual(payload["classification"], "one_sided_books_no_midpoint")
        self.assertTrue(payload["raw_book_present"])

    def test_build_payload_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "highest-temperature-in-nyc-on-june-7-2026"
            second = Path(tmp) / "highest-temperature-in-nyc-on-june-13-2026"
            first.mkdir()
            second.mkdir()
            write_snapshots(first)
            write_features(first, [feature()])
            write_snapshots(second)
            (second / "order_books_summary.csv").write_text("x\n", encoding="utf-8")
            (second / "clob_tokens.csv").write_text("x\n", encoding="utf-8")
            write_features(second, [
                feature(
                    clob_token_id="token",
                    clob_feature_available="1.0",
                    clob_midpoint="0.40",
                    clob_spread="0.02",
                )
            ])
            report = Path(tmp) / "report.md"

            payload = build_payload([first, second], min_train_midpoint_coverage=0.05)
            write_markdown_report(report, payload)
            text = report.read_text(encoding="utf-8")

        self.assertEqual(payload["summary"]["folders"], 2)
        self.assertIn("missing_raw_clob_tape_and_token_map", payload["summary"]["classifications"])
        self.assertEqual(payload["split_coverage_gate"]["status"], "BLOCK")
        self.assertEqual(payload["split_coverage_gate"]["train"]["folders"], 1)
        self.assertEqual(payload["split_coverage_gate"]["eval"]["midpoint_available_folders"], 1)
        self.assertIn("midpoint_available", text)
        self.assertIn("Chronological Split Coverage", text)
        self.assertIn("Split coverage gate", text)

    def test_split_coverage_gate_passes_when_train_midpoint_coverage_clears_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "highest-temperature-in-seattle-on-june-12-2026"
            second = Path(tmp) / "highest-temperature-in-seattle-on-june-13-2026"
            first.mkdir()
            second.mkdir()
            for folder in (first, second):
                write_snapshots(folder)
                (folder / "order_books_summary.csv").write_text("x\n", encoding="utf-8")
                (folder / "clob_tokens.csv").write_text("x\n", encoding="utf-8")
                write_features(folder, [
                    feature(
                        clob_token_id="token",
                        clob_feature_available="1.0",
                        clob_midpoint="0.40",
                    )
                ])

            payload = build_payload([first, second], min_train_midpoint_coverage=0.50)

        self.assertEqual(payload["split_coverage_gate"]["status"], "PASS")
        self.assertAlmostEqual(payload["split_coverage_gate"]["train"]["midpoint_coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
