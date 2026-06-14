import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath("src"))

from pooled_candidate_replay import (
    attach_band_candidate_probabilities,
    annotate_casebook_rows,
    apply_current_blend_guardrail,
    band_probability_from_distribution,
    build_microstructure_gate,
    candidate_comparison,
    apply_microstructure_gate,
    load_casebook_index,
    market_verdict,
    microstructure_comparison,
    microstructure_feature_frame,
    out_of_fold_microstructure_predictions,
    normalize_partition_probabilities,
    replay_gate_status,
)


class TestPooledCandidateReplay(unittest.TestCase):
    def test_band_probability_handles_thresholds_and_ranges(self):
        distribution = {70: 0.10, 71: 0.20, 72: 0.30, 73: 0.40}

        self.assertAlmostEqual(
            band_probability_from_distribution(distribution, "lte", 71),
            0.30,
        )
        self.assertAlmostEqual(
            band_probability_from_distribution(distribution, "gte", 72),
            0.70,
        )
        self.assertAlmostEqual(
            band_probability_from_distribution(distribution, "eq", 71, 72),
            0.50,
        )

    def test_candidate_comparison_scores_all_probability_columns_on_same_rows(self):
        rows = [
            {
                "candidate_p": 0.90,
                "replayed_p": 0.70,
                "recorded_p": 0.60,
                "market_yes": 0.50,
                "outcome": 1,
            },
            {
                "candidate_p": 0.20,
                "replayed_p": 0.30,
                "recorded_p": 0.40,
                "market_yes": 0.60,
                "outcome": 0,
            },
        ]

        comp = candidate_comparison(rows)

        self.assertEqual(comp["n"], 2)
        self.assertLess(comp["candidate_brier"], comp["current_brier"])
        self.assertLess(comp["candidate_brier"], comp["market_brier"])
        self.assertLess(comp["delta_vs_current"], 0)

    def test_market_verdict_blocks_large_current_regression(self):
        verdict, reasons = market_verdict(
            {
                "candidate_brier": 0.20,
                "current_brier": 0.10,
                "market_brier": 0.15,
                "delta_vs_current": 0.10,
            },
            day_count=3,
            trust={"trust_score": 80},
            current_tol=0.003,
            market_tol=0.003,
            min_days=2,
            min_trust=25,
        )

        self.assertEqual(verdict, "BLOCK")
        self.assertIn("regresses current", reasons[0])

    def test_market_verdict_shadows_when_not_better_than_current(self):
        verdict, reasons = market_verdict(
            {
                "candidate_brier": 0.101,
                "current_brier": 0.100,
                "market_brier": 0.130,
                "delta_vs_current": 0.001,
            },
            day_count=3,
            trust={"trust_score": 80},
            current_tol=0.003,
            market_tol=0.003,
            min_days=2,
            min_trust=25,
        )

        self.assertEqual(verdict, "SHADOW")
        self.assertIn("not proven better than current replay", reasons)

    def test_partition_normalization_makes_snapshot_bands_sum_to_one(self):
        rows = [
            {"market_id": "nyc", "snapshot_id": "s1", "candidate_p": 0.8},
            {"market_id": "nyc", "snapshot_id": "s1", "candidate_p": 0.6},
            {"market_id": "nyc", "snapshot_id": "s1", "candidate_p": 0.1},
            {"market_id": "nyc", "snapshot_id": "s2", "candidate_p": 0.4},
        ]

        normalize_partition_probabilities(rows, gamma=1.0)

        self.assertAlmostEqual(sum(row["candidate_p"] for row in rows[:3]), 1.0)
        self.assertAlmostEqual(rows[3]["candidate_p"], 1.0)

    def test_current_blend_guardrail_uses_market_specific_alpha(self):
        rows = [
            {
                "market_id": "denver",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
            {
                "market_id": "chicago",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
        ]

        apply_current_blend_guardrail(rows, {
            "current_blend_default_alpha": 1.0,
            "current_blend_market_alpha": {"denver": 0.25},
        })

        self.assertAlmostEqual(rows[0]["candidate_p"], 0.35)
        self.assertAlmostEqual(rows[1]["candidate_p"], 0.80)

    def test_replay_gate_blocks_corpus_pin_warnings(self):
        status = replay_gate_status(
            {
                "corpus_warnings": ["changed row"],
                "fidelity": {"same_identity_n": 1, "same_identity_max_l1": 0.0},
            }
        )

        self.assertFalse(status["global_ok"])
        self.assertFalse(status["corpus_ok"])

    def test_replay_gate_can_require_exact_identity_rows(self):
        status = replay_gate_status(
            {
                "corpus_warnings": [],
                "fidelity": {"same_identity_n": 0},
            },
            require_exact_identity=True,
        )

        self.assertFalse(status["global_ok"])
        self.assertFalse(status["fidelity_ok"])
        self.assertIn("no exact-identity", status["fidelity_message"])

    def test_band_candidate_replay_attaches_clob_features_with_label_hi_fallback(self):
        replay_results = {
            "all_rows": [
                {
                    "market_id": "nyc",
                    "snapshot_id": "s1",
                    "range_label": "82-83 F",
                    "bin_type": "eq",
                    "bin_value_c": "82",
                    "bin_value_hi": "",
                    "market_yes": 0.40,
                    "outcome": 1,
                }
            ]
        }
        feature_rows = {
            ("nyc", "s1"): {
                "cutoff_hour": 14,
                "high_so_far": 80.0,
                "current_temp": 79.0,
                "forecast_high": 84.0,
                "live_reading_temp": 80.0,
                "climate_normal": 82.0,
                "wind_group": "S-SW",
                "cloud_group": "Fair/clear",
                "market_id": "nyc",
            }
        }
        clob_features = {
            ("nyc", "s1", "eq", 82, 83): {
                "clob_feature_available": 1.0,
                "clob_midpoint": 0.39,
                "clob_spread": 0.02,
                "clob_liquidity_score": 2.5,
            }
        }
        artifact = {
            "models": {"14": {"feature_names": ["placeholder"]}},
            "postprocess": {"partition_normalization_enabled": False},
        }

        with patch("pooled_candidate_replay.predict_band_rows_for_bundle", return_value=[0.72]) as predict:
            rows, coverage = attach_band_candidate_probabilities(
                replay_results,
                feature_rows,
                artifact,
                "F",
                clob_features=clob_features,
            )

        self.assertEqual(coverage["candidate_rows"], 1)
        self.assertAlmostEqual(rows[0]["candidate_p"], 0.72)
        self.assertEqual(rows[0]["clob_feature_available"], 1.0)
        self.assertAlmostEqual(rows[0]["clob_midpoint"], 0.39)
        band_rows = predict.call_args.args[1]
        self.assertEqual(band_rows[0]["band_value_hi"], 83.0)
        self.assertEqual(band_rows[0]["clob_feature_available"], 1.0)
        self.assertAlmostEqual(band_rows[0]["clob_liquidity_score"], 2.5)

    def test_microstructure_feature_frame_includes_clob_and_context_columns(self):
        frame = microstructure_feature_frame([
            {
                "candidate_p": 0.60,
                "replayed_p": 0.55,
                "market_yes": 0.40,
                "candidate_cutoff_hour": 14,
                "candidate_cutoff_hour_bucket": "14-16",
                "clob_feature_available": 1.0,
                "clob_midpoint": 0.39,
                "clob_liquidity_score": 2.5,
                "market_id": "nyc",
                "bin_type": "eq",
            }
        ])

        self.assertIn("candidate_minus_market", frame.columns)
        self.assertIn("clob_midpoint", frame.columns)
        self.assertIn("market_id_nyc", frame.columns)
        self.assertIn("bin_type_eq", frame.columns)
        self.assertAlmostEqual(frame.loc[0, "clob_liquidity_score"], 2.5)

    def test_microstructure_oof_scores_only_clob_available_rows(self):
        rows = []
        for target_date in ["2026-06-11", "2026-06-12"]:
            for idx, outcome in enumerate([0, 1, 0, 1]):
                rows.append({
                    "market_id": "nyc",
                    "target_date": target_date,
                    "snapshot_id": f"{target_date}-{idx}",
                    "range_label": "82-83 F",
                    "bin_type": "eq",
                    "bin_value_c": "82",
                    "bin_value_hi": "83",
                    "candidate_cutoff_hour": 14,
                    "candidate_p": 0.20 if outcome == 0 else 0.80,
                    "replayed_p": 0.25 if outcome == 0 else 0.75,
                    "recorded_p": 0.30 if outcome == 0 else 0.70,
                    "market_yes": 0.35 if outcome == 0 else 0.65,
                    "outcome": outcome,
                    "clob_feature_available": 1.0,
                    "clob_midpoint": 0.30 if outcome == 0 else 0.70,
                    "clob_spread": 0.02,
                    "clob_liquidity_score": 2.0,
                })
        rows.append({
            "market_id": "nyc",
            "target_date": "2026-06-12",
            "snapshot_id": "missing-book",
            "candidate_p": 0.5,
            "replayed_p": 0.5,
            "recorded_p": 0.5,
            "market_yes": 0.5,
            "outcome": 0,
            "clob_feature_available": 0.0,
        })

        diagnostics = out_of_fold_microstructure_predictions(rows, min_train_rows=2)
        comp = microstructure_comparison(rows)

        self.assertEqual(diagnostics["eligible_rows"], 8)
        self.assertEqual(diagnostics["predicted_rows"], 8)
        self.assertEqual(diagnostics["fold_count"], 2)
        self.assertIsNone(rows[-1]["micro_candidate_p"])
        self.assertEqual(comp["n"], 8)
        self.assertIn("delta_vs_candidate", comp)

    def test_casebook_annotation_matches_snapshot_and_band_key(self):
        payload = {
            "cases": [
                {
                    "case_id": "case-1",
                    "market_id": "nyc",
                    "band_key": "eq:82-83",
                    "taxonomy": "market_overreaction",
                    "model_result": "model_win",
                    "peak_abs_edge": 0.4,
                    "snapshot_ids": ["s1"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "casebook.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            index, diagnostics = load_casebook_index(path)

        rows = [
            {
                "market_id": "nyc",
                "snapshot_id": "s1",
                "range_label": "82-83 F",
                "bin_type": "eq",
                "bin_value_c": "82",
                "bin_value_hi": "83",
            }
        ]
        matched = annotate_casebook_rows(rows, index)

        self.assertTrue(diagnostics["exists"])
        self.assertEqual(matched, 1)
        self.assertEqual(rows[0]["casebook_taxonomy"], "market_overreaction")
        self.assertEqual(rows[0]["casebook_case_id"], "case-1")

    def test_microstructure_gate_allows_only_replay_proven_target_taxonomies(self):
        taxonomy_scores = [
            {
                "group": "book_liquidity_artifact",
                "n": 40,
                "micro_brier": 0.08,
                "candidate_brier": 0.14,
                "market_brier": 0.09,
                "delta_vs_candidate": -0.06,
                "delta_vs_market": -0.01,
            },
            {
                "group": "market_lead",
                "n": 30,
                "micro_brier": 0.01,
                "candidate_brier": 0.03,
                "market_brier": 0.02,
                "delta_vs_candidate": -0.02,
                "delta_vs_market": -0.01,
            },
            {
                "group": "market_overreaction",
                "n": 80,
                "micro_brier": 0.17,
                "candidate_brier": 0.10,
                "market_brier": 0.19,
                "delta_vs_candidate": 0.07,
                "delta_vs_market": -0.02,
            },
        ]

        gate = build_microstructure_gate(taxonomy_scores)

        self.assertEqual(
            gate["allowed_taxonomies"],
            ["market_lead", "book_liquidity_artifact"],
        )
        overreaction = [row for row in gate["decisions"] if row["taxonomy"] == "market_overreaction"][0]
        self.assertFalse(overreaction["allowed"])
        self.assertIn("delta_vs_candidate", overreaction["reason"])

    def test_apply_microstructure_gate_falls_back_to_base_for_blocked_taxonomy(self):
        gate = {
            "allowed_taxonomies": ["book_liquidity_artifact"],
        }
        rows = [
            {
                "candidate_p": 0.60,
                "micro_candidate_p": 0.80,
                "casebook_taxonomy": "book_liquidity_artifact",
            },
            {
                "candidate_p": 0.30,
                "micro_candidate_p": 0.10,
                "casebook_taxonomy": "market_overreaction",
            },
            {
                "candidate_p": 0.45,
                "micro_candidate_p": 0.90,
                "casebook_taxonomy": None,
            },
        ]

        counts = apply_microstructure_gate(rows, gate)

        self.assertEqual(counts["overlay_rows"], 1)
        self.assertEqual(counts["base_rows"], 2)
        self.assertAlmostEqual(rows[0]["micro_gated_candidate_p"], 0.80)
        self.assertAlmostEqual(rows[1]["micro_gated_candidate_p"], 0.30)
        self.assertAlmostEqual(rows[2]["micro_gated_candidate_p"], 0.45)
        self.assertEqual(rows[0]["micro_gate_action"], "overlay")
        self.assertEqual(rows[1]["micro_gate_action"], "base")


if __name__ == "__main__":
    unittest.main()
