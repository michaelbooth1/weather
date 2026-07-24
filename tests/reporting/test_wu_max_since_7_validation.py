import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.reporting.promotion.promotion_corpus import build_promotion_corpus, write_manifest  # noqa: E402
from weather.reporting.validation.wu_max_since_7_validation import (  # noqa: E402
    build_validation_payload,
    classify_current_max,
    summarize_validation_rows,
    write_json,
    write_report,
)


SLUG = "highest-temperature-in-toronto-on-june-3-2026"


def write_csv(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_test_folder(root):
    folder = Path(root) / SLUG
    folder.mkdir(parents=True)
    rows = []
    snapshots = [
        ("s1", "2026-06-03T09:05:00-04:00", 24, "fresh"),
        ("s2", "2026-06-03T13:05:00-04:00", 25, "stale"),
        ("s3", "2026-06-03T15:05:00-04:00", 26, "failed"),
    ]
    for snapshot_id, captured_at, wu_max, _freshness in snapshots:
        for label, kind, value in [
            ("24 C or below", "lte", 24),
            ("25 C", "eq", 25),
        ]:
            rows.append({
                "snapshot_id": snapshot_id,
                "captured_at_local": captured_at,
                "captured_at_utc": captured_at.replace("-04:00", "+00:00"),
                "event_slug": SLUG,
                "range_label": label,
                "bin_kind": kind,
                "bin_value_c": value,
                "model_probability": 0.5,
                "market_yes": 0.5,
                "market_no": 0.5,
                "wu_max_since_7am_native": wu_max,
                "wu_max_since_7am_c": wu_max,
            })
    write_csv(folder / "snapshots_long.csv", rows)
    records = []
    for snapshot_id, _captured_at, _wu_max, freshness in snapshots:
        source = {"ok": True, "status": "fresh", "stale": False}
        if freshness == "stale":
            source = {"ok": True, "status": "stale_cache", "stale": True}
        elif freshness == "failed":
            source = {"ok": False, "status": "failed", "stale": False}
        records.append({
            "snapshot_id": snapshot_id,
            "sources": {"wu_current": source},
            "recorded_distribution": {"25": 0.5},
        })
    with (folder / "replay_inputs.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    (folder / "settlement.json").write_text(
        json.dumps({
            "schema_version": "settlement_ledger_v1",
            "event_slug": SLUG,
            "market_id": "toronto",
            "city": "Toronto",
            "target_date": "2026-06-03",
            "settlement_high": 25.0,
            "settlement_bucket": 25,
            "settlement_unit": "C",
            "winning_band": "25 C",
            "winning_band_kind": "eq",
            "winning_band_value": 25,
            "settlement_source": "test",
            "quality_grade": "complete",
            "quality_reason": "test label",
            "coverage_clean": True,
            "capture_ratio": 1.0,
            "max_gap_minutes": 10.0,
            "snapshot_tape_path": str(folder / "snapshots_long.csv"),
        }, sort_keys=True),
        encoding="utf-8",
    )
    return folder


class TestWuMaxSince7Validation(unittest.TestCase):
    def test_classifies_current_max_against_final_high(self):
        self.assertEqual(classify_current_max(None, 25), "missing_current_max")
        self.assertEqual(classify_current_max(24, None), "missing_final_wu_high")
        self.assertEqual(classify_current_max(24, 25), "below_final_wu_high")
        self.assertEqual(classify_current_max(25, 25), "matches_final_wu_high")
        self.assertEqual(classify_current_max(26, 25), "above_final_wu_high")

    def test_summary_counts_safe_and_above_final_rows(self):
        rows = [
            {"validation_state": "below_final_wu_high", "wu_max_since_7am_c": 24, "final_wu_high": 25, "gap_to_final_wu_high": -1},
            {"validation_state": "matches_final_wu_high", "wu_max_since_7am_c": 25, "final_wu_high": 25, "gap_to_final_wu_high": 0},
            {"validation_state": "above_final_wu_high", "wu_max_since_7am_c": 26, "final_wu_high": 25, "gap_to_final_wu_high": 1},
        ]

        summary = summarize_validation_rows(rows)

        self.assertEqual(summary["snapshots"], 3)
        self.assertEqual(summary["safe_as_support_bound"], 2)
        self.assertEqual(summary["above_final_wu_high"], 1)
        self.assertAlmostEqual(summary["safe_rate"], 2 / 3)

    def test_builds_payload_from_pinned_corpus_and_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshots_root = Path(tmp) / "snapshots"
            folder = write_test_folder(snapshots_root)
            manifest = build_promotion_corpus(
                [folder], snapshots_root=snapshots_root, as_of="2026-06-04"
            )
            corpus_path = write_manifest(
                manifest, Path(tmp) / "output" / "promotion_corpus.json"
            )

            payload = build_validation_payload(
                corpus_path,
                snapshots_root=snapshots_root,
                focus_market="toronto",
            )

            self.assertEqual(payload["summary"]["snapshots"], 3)
            self.assertEqual(payload["summary"]["state_counts"]["above_final_wu_high"], 1)
            self.assertEqual(payload["summary"]["source_freshness_counts"]["all_fresh"], 1)
            self.assertEqual(payload["summary"]["source_freshness_counts"]["stale:wu_current"], 1)
            self.assertEqual(payload["summary"]["source_freshness_counts"]["failed:wu_current"], 1)
            self.assertEqual(payload["focus_market"]["summary"]["snapshots"], 3)
            self.assertEqual(payload["rows"][0]["cutoff_hour"], 9)

            report_path = write_report(payload, Path(tmp) / "wu_report.md")
            json_path = write_json(payload, Path(tmp) / "wu_report.json")

            self.assertTrue(report_path.exists())
            self.assertTrue(json_path.exists())
            text = report_path.read_text(encoding="utf-8")
            self.assertIn("# WU Max Since 7 AM Validation", text)
            self.assertIn("above_final_wu_high", text)
            self.assertIn("promotion_gauntlet_latest_report.md", text)


if __name__ == "__main__":
    unittest.main()
