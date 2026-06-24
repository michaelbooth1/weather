import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.data_quality.feature_quality_quarantine import (
    audit_folder_feature_quality,
    build_payload,
    write_outputs,
)


JUNE20_SLUGS = [
    "highest-temperature-in-austin-on-june-20-2026",
    "highest-temperature-in-denver-on-june-20-2026",
    "highest-temperature-in-miami-on-june-20-2026",
    "highest-temperature-in-nyc-on-june-20-2026",
    "highest-temperature-in-houston-on-june-20-2026",
    "highest-temperature-in-seattle-on-june-20-2026",
]


def _write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _build_bad_folder(root, slug, *, with_raw_observation_payload=False):
    folder = Path(root) / slug
    snapshot_id = "20260620T010541-0400"
    (folder / "settlement.json").parent.mkdir(parents=True, exist_ok=True)
    (folder / "settlement.json").write_text(
        json.dumps({
            "event_slug": slug,
            "market_id": slug.split("-in-")[1].split("-on-")[0],
            "target_date": "2026-06-20",
            "settlement_unit": "F",
            "quality_grade": "complete",
        }),
        encoding="utf-8",
    )
    _write_csv(
        folder / "features_long.csv",
        [
            "snapshot_id",
            "captured_at_utc",
            "captured_at_local",
            "event_slug",
            "target_date",
            "cutoff_hour",
            "high_so_far",
            "current_temp",
            "live_reading_temp",
        ],
        [
            {
                "snapshot_id": snapshot_id,
                "captured_at_utc": "2026-06-20T05:05:41+00:00",
                "captured_at_local": "2026-06-20T00:05:41-05:00",
                "event_slug": slug,
                "target_date": "2026-06-20",
                "cutoff_hour": "7",
                "high_so_far": "17.0",
                "current_temp": "17.0",
                "live_reading_temp": "",
            }
        ],
    )
    _write_csv(
        folder / "snapshots_long.csv",
        [
            "snapshot_id",
            "captured_at_utc",
            "captured_at_local",
            "event_slug",
            "wu_history_high_c",
            "wu_current_c",
            "wu_max_since_7am_c",
        ],
        [
            {
                "snapshot_id": snapshot_id,
                "captured_at_utc": "2026-06-20T05:05:41+00:00",
                "captured_at_local": "2026-06-20T01:05:41-04:00",
                "event_slug": slug,
                "wu_history_high_c": "80.0",
                "wu_current_c": "79.0",
                "wu_max_since_7am_c": "93.0",
            }
        ],
    )
    (folder / "replay_inputs.jsonl").write_text(
        json.dumps({
            "snapshot_id": snapshot_id,
            "feature_vector": {"high_so_far": 17.0, "current_temp": 17.0},
        })
        + "\n",
        encoding="utf-8",
    )
    if with_raw_observation_payload:
        _write_csv(
            folder / "observation_payloads_long.csv",
            ["snapshot_id", "source", "status"],
            [{"snapshot_id": snapshot_id, "source": "wu_current", "status": "fresh"}],
        )
    return folder


class TestFeatureQualityQuarantine(unittest.TestCase):
    def test_build_payload_quarantines_june20_startup_and_current_max_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index, slug in enumerate(JUNE20_SLUGS):
                _build_bad_folder(tmp, slug, with_raw_observation_payload=index == 0)

            payload = build_payload(tmp)

        summary = payload["summary"]
        self.assertEqual(summary["affected_market_count"], 6)
        self.assertEqual(summary["affected_snapshot_count"], 6)
        self.assertEqual(summary["reason_counts"]["startup_live_observation_implausible"], 12)
        self.assertEqual(summary["reason_counts"]["current_max_exceeds_observed_support"], 6)
        self.assertEqual(summary["training_excluded_row_count"], 18)
        self.assertEqual(summary["promotion_excluded_row_count"], 18)
        self.assertEqual(summary["replay_input_impacted_count"], 18)
        self.assertGreaterEqual(summary["backfill_candidate_row_count"], 3)
        self.assertEqual(
            sorted(row["market_id"] for row in payload["by_market"]),
            ["austin", "denver", "houston", "miami", "nyc", "seattle"],
        )

    def test_folder_summary_marks_raw_evidence_as_pending_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _build_bad_folder(
                tmp,
                "highest-temperature-in-austin-on-june-20-2026",
                with_raw_observation_payload=True,
            )

            audit = audit_folder_feature_quality(folder)

        dispositions = {row["disposition"] for row in audit["rows"]}
        self.assertEqual(dispositions, {"training_excluded_pending_backfill"})
        self.assertEqual(audit["summary"]["backfill_candidate_row_count"], 3)

    def test_write_outputs_creates_json_csv_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            _build_bad_folder(tmp, "highest-temperature-in-austin-on-june-20-2026")
            payload = build_payload(tmp)
            out_dir = Path(tmp) / "out"

            paths = write_outputs(
                payload,
                json_out=out_dir / "feature_quality.json",
                csv_out=out_dir / "feature_quality.csv",
                report_out=out_dir / "feature_quality.md",
            )

            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["csv"]).exists())
            text = Path(paths["report"]).read_text(encoding="utf-8")
            self.assertIn("Feature Quality Quarantine", text)
            self.assertIn("startup_live_observation_implausible", text)


if __name__ == "__main__":
    unittest.main()
