import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.validation.current_blend_validation import (
    base_alpha_for_row,
    build_payload,
    candidate_probability,
    reconstruct_raw_probability,
    write_markdown_report,
)


def write_base_replay(path):
    payload = {
        "artifact": {
            "current_blend_default_alpha": 1.0,
            "current_blend_market_alpha": {
                "fallback": 0.0,
                "recoverable": 0.5,
            },
            "artifact_hash": "abc",
            "postprocess_config_hash": "schema",
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_rows(path):
    rows = []
    fieldnames = [
        "market_id",
        "target_date",
        "snapshot_id",
        "band_key",
        "probability",
        "current_probability",
        "market_yes",
        "outcome",
    ]

    def add(market, target_date, probability, current, market_yes, outcome):
        rows.append({
            "market_id": market,
            "target_date": target_date,
            "snapshot_id": f"{market}-{target_date}-{len(rows)}",
            "band_key": "eq:80",
            "probability": str(probability),
            "current_probability": str(current),
            "market_yes": str(market_yes),
            "outcome": str(outcome),
        })

    # Earlier day selects mostly-current alpha for recoverable.
    add("recoverable", "2026-06-01", 0.40, 0.40, 0.80, 1)
    add("recoverable", "2026-06-01", 0.60, 0.60, 0.20, 0)
    # Later day evaluates without overlapping the selection date.
    add("recoverable", "2026-06-02", 0.45, 0.50, 0.70, 1)
    add("recoverable", "2026-06-02", 0.55, 0.50, 0.30, 0)
    # Full-current fallback cannot reconstruct raw probabilities.
    add("fallback", "2026-06-01", 0.25, 0.25, 0.20, 0)
    add("fallback", "2026-06-02", 0.75, 0.75, 0.80, 1)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class CurrentBlendValidationTests(unittest.TestCase):
    def test_reconstruct_raw_probability_inverts_existing_blend(self):
        raw = reconstruct_raw_probability(probability=0.40, current_probability=0.20, alpha=0.5)

        self.assertAlmostEqual(raw, 0.60)
        self.assertIsNone(reconstruct_raw_probability(0.20, 0.20, 0.0))

    def test_candidate_probability_falls_back_to_current_when_raw_missing(self):
        probability = candidate_probability({"raw_probability": None, "current_probability": 0.33}, 1.0)

        self.assertAlmostEqual(probability, 0.33)

    def test_context_alpha_reconstructs_raw_rows_when_market_default_is_current(self):
        schedule = {
            "default_alpha": 1.0,
            "market_alpha": {"austin": 0.0},
            "source_freshness_alpha": {},
            "source_freshness_default_alpha": 0.0,
            "context_alpha": [
                {
                    "market_id": "austin",
                    "source_freshness_state": "all_fresh",
                    "cutoff_regime": ["midday", "late"],
                    "alpha": 1.0,
                }
            ],
        }

        self.assertEqual(
            base_alpha_for_row(
                {
                    "market_id": "austin",
                    "source_freshness_state": "all_fresh",
                    "cutoff_hour": "14",
                },
                schedule,
            ),
            1.0,
        )
        self.assertEqual(
            base_alpha_for_row(
                {
                    "market_id": "austin",
                    "source_freshness_state": "failed:wu_history",
                    "cutoff_hour": "14",
                },
                schedule,
            ),
            0.0,
        )

    def test_build_payload_uses_earlier_dates_for_selection_and_later_dates_for_eval(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            replay_path = Path(tmp) / "replay.json"
            write_rows(rows_path)
            write_base_replay(replay_path)

            payload = build_payload(rows_path, replay_path, alpha_grid="0,0.5,1")

        self.assertEqual(payload["schema_version"], "current_blend_time_split_validation_v0.1")
        self.assertEqual(payload["no_leakage_audit"]["primary_evidence_unit"], "market_day")
        self.assertEqual(payload["row_counts"]["train"], 3)
        self.assertEqual(payload["row_counts"]["eval"], 3)
        recoverable = next(row for row in payload["market_results"] if row["market_id"] == "recoverable")
        fallback = next(row for row in payload["market_results"] if row["market_id"] == "fallback")
        self.assertEqual(recoverable["train_dates"], ["2026-06-01"])
        self.assertEqual(recoverable["eval_dates"], ["2026-06-02"])
        self.assertEqual(fallback["selected_alpha"], 0.0)
        self.assertEqual(
            fallback["selection_reason"],
            "baseline_artifact_full_current_fallback_no_raw_candidate",
        )
        self.assertEqual(fallback["raw_candidate_eval_rows"], 0)
        self.assertGreater(recoverable["raw_candidate_eval_rows"], 0)

    def test_build_payload_counts_context_raw_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            replay_path = Path(tmp) / "replay.json"
            replay_path.write_text(
                json.dumps({
                    "artifact": {
                        "current_blend_default_alpha": 1.0,
                        "current_blend_market_alpha": {"austin": 0.0},
                        "current_blend_context_alpha": [
                            {
                                "market_id": "austin",
                                "source_freshness_state": "all_fresh",
                                "cutoff_regime": ["midday", "late"],
                                "alpha": 1.0,
                            }
                        ],
                    }
                }),
                encoding="utf-8",
            )
            rows = [
                {
                    "market_id": "austin",
                    "target_date": "2026-06-01",
                    "snapshot_id": "train-1",
                    "band_key": "eq:80",
                    "probability": "0.6",
                    "current_probability": "0.4",
                    "market_yes": "0.8",
                    "outcome": "1",
                    "source_freshness_state": "all_fresh",
                    "cutoff_regime": "midday",
                },
                {
                    "market_id": "austin",
                    "target_date": "2026-06-02",
                    "snapshot_id": "eval-1",
                    "band_key": "eq:80",
                    "probability": "0.7",
                    "current_probability": "0.3",
                    "market_yes": "0.8",
                    "outcome": "1",
                    "source_freshness_state": "all_fresh",
                    "cutoff_regime": "late",
                },
                {
                    "market_id": "austin",
                    "target_date": "2026-06-02",
                    "snapshot_id": "eval-2",
                    "band_key": "eq:82",
                    "probability": "0.2",
                    "current_probability": "0.2",
                    "market_yes": "0.1",
                    "outcome": "0",
                    "source_freshness_state": "failed:wu_history",
                    "cutoff_regime": "late",
                },
            ]
            with rows_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            payload = build_payload(rows_path, replay_path, alpha_grid="0,1")

        austin = next(row for row in payload["market_results"] if row["market_id"] == "austin")
        self.assertEqual(austin["selection_reason"], "min_train_brier_on_earlier_market_days")
        self.assertEqual(austin["raw_candidate_train_rows"], 1)
        self.assertEqual(austin["raw_candidate_eval_rows"], 1)

    def test_markdown_report_includes_development_evidence_caveat(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows_path = Path(tmp) / "rows.csv"
            replay_path = Path(tmp) / "replay.json"
            report_path = Path(tmp) / "report.md"
            write_rows(rows_path)
            write_base_replay(replay_path)
            payload = build_payload(rows_path, replay_path, alpha_grid="0,0.5,1")

            write_markdown_report(report_path, payload)

            text = report_path.read_text(encoding="utf-8")
        self.assertIn("not promotion evidence", text)
        self.assertIn("# Current-Blend Time-Split Validation", text)
        self.assertNotIn("Item 35 Current-Blend", text)
        self.assertIn("Market Holdout", text)
        self.assertIn("Raw Eval Rows", text)
        self.assertIn("Selection reason", text)


if __name__ == "__main__":
    unittest.main()
