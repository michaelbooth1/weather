import csv
import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.source_gates.nbm_probabilistic_tmax_settlement_scoring import (
    build_payload,
    cdf_from_percentile_curve,
    nbm_band_probability_from_percentiles,
    score_folder,
)


def _write_csv(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_nbm_folder(root, day, *, city="nyc", settlement_bucket=84):
    folder = Path(root) / f"highest-temperature-in-{city}-on-june-{int(day[-2:])}-2026"
    folder.mkdir(parents=True)
    snapshot_id = f"{city}-{day}-s1"
    (folder / "settlement.json").write_text(
        json.dumps({
            "target_date": day,
            "quality_grade": "complete",
            "settlement_bucket": settlement_bucket,
        }),
        encoding="utf-8",
    )
    _write_csv(
        folder / "features_long.csv",
        [
            {
                "snapshot_id": snapshot_id,
                "feature_schema_version": "feature_store_vtest",
                "cutoff_hour": "13",
                "nbm_prob_tmax_p10": "82.0",
                "nbm_prob_tmax_p25": "83.5",
                "nbm_prob_tmax_p50": "84.5",
                "nbm_prob_tmax_p75": "85.5",
                "nbm_prob_tmax_p90": "87.0",
                "nbm_prob_tmax_stddev": "2.0",
                "nbm_prob_tmax_iqr": "2.0",
                "nbm_prob_tmax_physical_valid_flag": "1",
                "nbm_prob_tmax_impossible_flag": "0",
            }
        ],
    )
    _write_csv(
        folder / "forecast_payloads_long.csv",
        [
            {
                "snapshot_id": snapshot_id,
                "source": "nbm_probabilistic_tmax",
                "payload_hash": f"hash-{day}",
                "source_url": "https://example.test/nbp",
            }
        ],
    )
    _write_csv(
        folder / "snapshots_long.csv",
        [
            {
                "snapshot_id": snapshot_id,
                "captured_at_utc": f"{day}T17:00:00+00:00",
                "captured_at_local": f"{day}T13:00:00-04:00",
                "target_date": day,
                "range_label": "83 F or below",
                "bin_kind": "lte",
                "bin_value_c": "83",
                "bin_value_hi": "",
                "model_probability": "0.35",
                "market_yes": "0.40",
            },
            {
                "snapshot_id": snapshot_id,
                "captured_at_utc": f"{day}T17:00:00+00:00",
                "captured_at_local": f"{day}T13:00:00-04:00",
                "target_date": day,
                "range_label": "84-85 F",
                "bin_kind": "eq",
                "bin_value_c": "84",
                "bin_value_hi": "",
                "model_probability": "0.30",
                "market_yes": "0.20",
            },
            {
                "snapshot_id": snapshot_id,
                "captured_at_utc": f"{day}T17:00:00+00:00",
                "captured_at_local": f"{day}T13:00:00-04:00",
                "target_date": day,
                "range_label": "86 F or higher",
                "bin_kind": "gte",
                "bin_value_c": "86",
                "bin_value_hi": "",
                "model_probability": "0.35",
                "market_yes": "0.40",
            },
        ],
    )
    return folder


class NbmProbabilisticTmaxSettlementScoringTests(unittest.TestCase):
    def test_percentile_curve_scores_half_degree_settlement_intervals(self):
        percentiles = {"10": 82.0, "25": 83.5, "50": 84.5, "75": 85.5, "90": 87.0}

        self.assertAlmostEqual(cdf_from_percentile_curve(percentiles, 84.5), 0.50)
        self.assertAlmostEqual(nbm_band_probability_from_percentiles(percentiles, "lte", 83), 0.25)
        self.assertAlmostEqual(nbm_band_probability_from_percentiles(percentiles, "eq", 84, 85), 0.50)
        self.assertAlmostEqual(nbm_band_probability_from_percentiles(percentiles, "gte", 86), 0.25)

    def test_score_folder_builds_gate_compatible_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _write_nbm_folder(tmp, "2026-06-23")

            result = score_folder(folder)

        self.assertEqual(result["status"], "SCORED")
        self.assertEqual(result["market_id"], "nyc")
        self.assertEqual(result["scored_rows"], 3)
        self.assertEqual(result["payload_summary"]["nbm_forecast_payload_rows"], 1)
        rows = result["rows"]
        self.assertAlmostEqual(sum(row["candidate_p"] for row in rows), 1.0)
        winner = [row for row in rows if row["outcome"] == 1]
        self.assertEqual(len(winner), 1)
        self.assertGreater(winner[0]["candidate_p"], winner[0]["replayed_p"])
        self.assertIn("nbm_prob_tmax_p50", winner[0])

    def test_build_payload_passes_when_nbm_anchor_beats_current_and_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders = [
                _write_nbm_folder(tmp, "2026-06-23"),
                _write_nbm_folder(tmp, "2026-06-24"),
            ]

            payload = build_payload(tmp, folders=folders)

        self.assertEqual(payload["schema_version"], "nbm_probabilistic_tmax_settlement_scoring_v0.1")
        self.assertEqual(payload["verdict"], "PASS")
        self.assertEqual(payload["cutover_decision"], "SHADOW_READY")
        self.assertTrue(payload["blocked_validation"]["passed"])
        self.assertEqual(payload["coverage"]["nbm_payload_folder_count"], 2)
        self.assertEqual(payload["coverage"]["target_date_count"], 2)
        self.assertEqual(payload["artifact"]["prediction_mode"], "nbm_percentile_curve_anchor")
        self.assertLessEqual(payload["aggregate"]["delta_vs_current"], 0)
        self.assertEqual(payload["nbm_probabilistic_tmax_gate"]["by_us_market"], payload["by_nbm_us_market"])

    def test_non_us_market_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = _write_nbm_folder(tmp, "2026-06-23", city="toronto")

            result = score_folder(folder)

        self.assertEqual(result["status"], "SKIP")
        self.assertEqual(result["reason"], "not_us_nbm_market")


if __name__ == "__main__":
    unittest.main()
