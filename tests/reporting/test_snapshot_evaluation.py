import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.reporting.scorecards.snapshot_evaluation import build_evaluation, write_outputs  # noqa: E402


SLUG = "highest-temperature-in-toronto-on-june-3-2026"


def write_snapshot_folder(root):
    folder = Path(root) / SLUG
    folder.mkdir(parents=True)
    columns = [
        "snapshot_id",
        "captured_at_utc",
        "captured_at_local",
        "event_slug",
        "model_version",
        "range_label",
        "model_probability",
        "market_yes",
    ]
    rows = [
        {
            "snapshot_id": "s1",
            "captured_at_utc": "2026-06-03T14:00:00+00:00",
            "captured_at_local": "2026-06-03T10:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "24 C",
            "model_probability": "0.55",
            "market_yes": "0.45",
        },
        {
            "snapshot_id": "s1",
            "captured_at_utc": "2026-06-03T14:00:00+00:00",
            "captured_at_local": "2026-06-03T10:00:00-04:00",
            "event_slug": SLUG,
            "model_version": "test-v1",
            "range_label": "25 C",
            "model_probability": "0.45",
            "market_yes": "0.55",
        },
    ]
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    for filename in [
        "replay_inputs.jsonl",
        "replay_input_status_long.csv",
        "features_long.csv",
        "components_long.csv",
        "forecasts_long.csv",
        "source_status_long.csv",
        "clob_features_long.csv",
        "order_books_summary.csv",
    ]:
        (folder / filename).write_text("{}\n", encoding="utf-8")
    return folder


def write_backtest_artifacts(root):
    root = Path(root)
    root.mkdir(parents=True)
    (root / "f_family_promotion_refresh.json").write_text(
        json.dumps(
            {
                "generated_at_utc": "2026-06-04T12:00:00+00:00",
                "family_unit": "F",
                "corpus": {
                    "market_day_count": 2,
                    "snapshot_count": 3,
                    "band_row_count": 12,
                },
                "candidate": {
                    "aggregate": {
                        "rows": 100,
                        "candidate_brier": 0.08,
                        "current_brier": 0.10,
                        "market_brier": 0.07,
                        "delta_vs_current": -0.02,
                        "delta_vs_market": 0.01,
                    },
                    "coverage": {"missing_candidate_rows": 0},
                    "slices": {
                        "by_market": [
                            {
                                "market_id": "miami",
                                "rows": 50,
                                "comparison": {
                                    "candidate_brier": 0.12,
                                    "market_brier": 0.07,
                                    "delta_vs_current": -0.01,
                                    "delta_vs_market": 0.05,
                                },
                            }
                        ],
                        "by_cutoff_hour": [
                            {
                                "group": 8,
                                "n": 100,
                                "candidate_brier": 0.09,
                                "market_brier": 0.08,
                                "delta_vs_market": 0.01,
                            }
                        ],
                    },
                },
                "serving_gauntlet": {"verdict": "PASS_WITH_SHADOWS", "market_rows": []},
                "decisions": {
                    "promote_markets": ["nyc"],
                    "shadow_markets": ["miami"],
                    "blocked_markets": [],
                },
                "readiness": {"status": "OPEN", "blockers": []},
            }
        ),
        encoding="utf-8",
    )
    (root / "data_layer_audit.json").write_text(
        json.dumps(
            {
                "gate_summary": {"status": "WARN", "pass_count": 2, "warn_count": 1, "fail_count": 0},
                "recommendations": [
                    {
                        "priority": "P1",
                        "area": "replay inputs",
                        "recommendation": "Backfill replay input status for old folders.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "fleet_observability.json").write_text(
        json.dumps(
            {
                "status": "OK",
                "summary": {},
                "live_forward_slo": {
                    "counts_toward_live_forward_gate": True,
                    "reason": "all loops fresh",
                },
            }
        ),
        encoding="utf-8",
    )


class TestSnapshotEvaluation(unittest.TestCase):
    def test_build_evaluation_rolls_snapshot_replay_and_audit_evidence_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshots_root = Path(tmp) / "snapshots"
            backtest_root = Path(tmp) / "backtest"
            write_snapshot_folder(snapshots_root)
            write_backtest_artifacts(backtest_root)

            # archive_root must be pinned into the fixture: prefer_archive
            # otherwise reads the PRODUCTION parquet archive, and once the
            # real archive gains a parquet for this slug the inventory counts
            # live rows instead of the fixture's (failed 2026-07-05 when the
            # archive backlog reached the fixture's market-day).
            payload = build_evaluation(
                backtest_root=backtest_root,
                snapshots_root=snapshots_root,
                archive_root=Path(tmp) / "archive",
            )
            json_out, report_out = write_outputs(
                payload,
                json_out=backtest_root / "snapshot_evaluation.json",
                report_out=backtest_root / "snapshot_evaluation_report.md",
            )

            gates = {gate["name"]: gate for gate in payload["gates"]}
            json_exists = Path(json_out).exists()
            report = Path(report_out).read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "snapshot_evaluation_v0.1")
        self.assertEqual(payload["status"]["status"], "WARN")
        self.assertEqual(payload["snapshot_inventory"]["folder_count"], 1)
        self.assertEqual(payload["snapshot_inventory"]["snapshot_count"], 1)
        self.assertIn(
            "text_tape",
            payload["snapshot_inventory"]["historical_reader_summary"]["source_modes"],
        )
        self.assertEqual(gates["candidate_vs_current"]["status"], "PASS")
        self.assertEqual(gates["candidate_vs_market"]["status"], "WARN")
        self.assertEqual(gates["data_layer_audit"]["status"], "WARN")
        self.assertTrue(json_exists)
        self.assertIn("Continuous Snapshot Evaluation", report)
        self.assertIn("Historical Reader Sources", report)
        self.assertIn("miami", report)
        self.assertIn("Backfill replay input status", report)


if __name__ == "__main__":
    unittest.main()
