import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from weather.calibration.pooled_candidate_replay import (
    attach_band_candidate_probabilities,
    attach_density_candidate_probabilities,
    annotate_casebook_rows,
    apply_current_blend_guardrail,
    band_probability_from_distribution,
    build_microstructure_gate,
    candidate_shadow_variant_rows,
    candidate_comparison,
    candidate_variant_defaults,
    cutoff_regime,
    conservative_bridge_report,
    conservative_bridge_shadow_variant_rows,
    exact_winner_candidate_diagnostics,
    forecast_profile_guardrails,
    apply_microstructure_gate,
    apply_conservative_bridge,
    bridge_alpha_for_market,
    load_casebook_index,
    market_verdict,
    microstructure_comparison,
    microstructure_feature_frame,
    microstructure_shadow_variant_rows,
    out_of_fold_microstructure_predictions,
    normalize_partition_probabilities,
    replay_gate_status,
    sidecar_eligibility_summary_from_audit,
    source_freshness_group,
    write_candidate_shadow_variants,
    write_report,
    _record_feature_row,
)
from weather.calibration.pooled_candidate_scoring import (
    blocked_candidate_validation_gate,
    source_state_ablation_report,
    source_state_ablation_shadow_variant_rows,
)
from weather.model.continuous_density import continuous_density_payload
from weather.market.market_registry import NYC


class TestPooledCandidateReplay(unittest.TestCase):
    def test_record_feature_row_applies_reanalysis_sidecar_and_lane_mask(self):
        class FakeModel:
            def set_target_date(self, _target_date):
                return None

            def source_data(self, _sources, source):
                if source == "wu_history":
                    return {"rows": [{"temperature": 80.0}]}
                return {}

            def effective_intraday_cutoff_hour(self, _now, _rows):
                return 7

            def extract_live_features(self, _sources, _cutoff_hour, now=None):
                return {
                    "high_so_far": 80.0,
                    "current_temp": 80.0,
                    "forecast_high": 84.0,
                    "forecast_gap": 4.0,
                    "wind_group": "Other/variable",
                    "cloud_group": "Fair/clear",
                }

            def max_value(self, *values):
                values = [value for value in values if value is not None]
                return max(values) if values else None

            def round_half_up(self, value):
                return int(value) if value is not None else None

        record = {
            "built_at": "2026-06-18T07:00:00-04:00",
            "target_date": "2026-06-18",
            "sources": {},
        }
        lane = {
            "allowed_markets": ["austin"],
            "quarantined_markets": ["nyc"],
        }

        masked = _record_feature_row(
            FakeModel(),
            NYC,
            {"climate_normal": 82.0, "climate_std": 4.0},
            record,
            reanalysis_synoptic_features={
                "reanalysis_synoptic_available": 1.0,
                "reanalysis_prev_day_max_temp": 81.0,
            },
            reanalysis_promotion_lane=lane,
        )
        allowed = _record_feature_row(
            FakeModel(),
            NYC,
            {"climate_normal": 82.0, "climate_std": 4.0},
            record,
            reanalysis_synoptic_features={
                "reanalysis_synoptic_available": 1.0,
                "reanalysis_prev_day_max_temp": 81.0,
            },
            reanalysis_promotion_lane={"allowed_markets": ["nyc"]},
        )

        self.assertEqual(masked["reanalysis_synoptic_available"], 0.0)
        self.assertIsNone(masked["reanalysis_prev_day_max_temp"])
        self.assertEqual(allowed["reanalysis_synoptic_available"], 1.0)
        self.assertEqual(allowed["reanalysis_prev_day_max_temp"], 81.0)

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

    def test_blocked_candidate_validation_gate_requires_daily_first_pass(self):
        rows = [
            {
                "market_id": "nyc",
                "target_date": "2026-06-01",
                "candidate_p": 0.80,
                "replayed_p": 0.60,
                "recorded_p": 0.60,
                "market_yes": 0.70,
                "outcome": 1,
            },
            {
                "market_id": "nyc",
                "target_date": "2026-06-02",
                "candidate_p": 0.20,
                "replayed_p": 0.40,
                "recorded_p": 0.40,
                "market_yes": 0.30,
                "outcome": 0,
            },
        ]

        gate = blocked_candidate_validation_gate(rows, current_tol=0.0, market_tol=0.0, min_days=2)

        self.assertTrue(gate["passed"])
        self.assertEqual(gate["verdict"], "PASS")
        self.assertEqual(gate["split_mode"], "daily_first_market_day")
        self.assertEqual(gate["split_audit"]["leak_count"], 0)

    def test_blocked_candidate_validation_gate_blocks_daily_first_regression(self):
        rows = [
            {
                "market_id": "nyc",
                "target_date": "2026-06-01",
                "candidate_p": 0.40,
                "replayed_p": 0.80,
                "recorded_p": 0.80,
                "market_yes": 0.75,
                "outcome": 1,
            },
            {
                "market_id": "nyc",
                "target_date": "2026-06-02",
                "candidate_p": 0.60,
                "replayed_p": 0.20,
                "recorded_p": 0.20,
                "market_yes": 0.25,
                "outcome": 0,
            },
        ]

        gate = blocked_candidate_validation_gate(rows, current_tol=0.0, market_tol=0.0, min_days=2)

        self.assertFalse(gate["passed"])
        self.assertEqual(gate["verdict"], "BLOCK")
        self.assertIn("daily-first candidate regresses current", "; ".join(gate["reasons"]))

    def test_exact_winner_candidate_diagnostics_scores_item70_slices(self):
        rows = [
            {
                "market_id": "seattle",
                "target_date": "2026-06-14",
                "candidate_cutoff_hour": 12,
                "bin_type": "eq",
                "settlement_distance_bucket": "0",
                "candidate_p": 0.70,
                "replayed_p": 0.50,
                "recorded_p": 0.48,
                "market_yes": 0.80,
                "outcome": 1,
            },
            {
                "market_id": "seattle",
                "target_date": "2026-06-14",
                "candidate_cutoff_hour": 12,
                "bin_type": "eq",
                "settlement_distance_bucket": "1",
                "candidate_p": 0.20,
                "replayed_p": 0.10,
                "recorded_p": 0.12,
                "market_yes": 0.25,
                "outcome": 0,
            },
            {
                "market_id": "chicago",
                "target_date": "2026-06-15",
                "candidate_cutoff_hour": 16,
                "bin_type": "gte",
                "settlement_distance_bucket": "2",
                "candidate_p": 0.30,
                "replayed_p": 0.35,
                "recorded_p": 0.34,
                "market_yes": 0.40,
                "outcome": 0,
            },
        ]

        diagnostics = exact_winner_candidate_diagnostics(rows)
        scopes = {row["slice"]: row for row in diagnostics["scopes"]}

        self.assertIn("settlement_distance_0", scopes)
        self.assertIn("one_above_guardrail", scopes)
        self.assertIn("combined_target_failure_slice", scopes)
        self.assertAlmostEqual(
            scopes["settlement_distance_0"]["exact_winner"]["candidate_mean_probability"],
            0.70,
        )
        self.assertEqual(diagnostics["daily_first"]["n_days"], 2)
        self.assertEqual(diagnostics["worst_daily_current_regressions"][0]["market_id"], "chicago")

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

    def test_current_blend_guardrail_can_cap_by_source_freshness_state(self):
        rows = [
            {
                "market_id": "denver",
                "source_freshness_state": "failed:wu_history",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
            {
                "market_id": "denver",
                "source_freshness_state": "stale:metar",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
        ]

        apply_current_blend_guardrail(rows, {
            "current_blend_default_alpha": 1.0,
            "current_blend_market_alpha": {"denver": 0.80},
            "current_blend_source_freshness_default_alpha": 0.0,
            "current_blend_source_freshness_alpha": {
                "failed:wu_history": 0.0,
                "stale:metar": 0.50,
            },
        })

        self.assertAlmostEqual(rows[0]["candidate_p"], 0.20)
        self.assertAlmostEqual(rows[1]["candidate_p"], 0.50)

    def test_current_blend_guardrail_supports_context_alpha_rules(self):
        rows = [
            {
                "market_id": "austin",
                "source_freshness_state": "all_fresh",
                "candidate_cutoff_hour": 12,
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
            {
                "market_id": "austin",
                "source_freshness_state": "all_fresh",
                "cutoff_regime": "early",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
            {
                "market_id": "nyc",
                "source_freshness_state": "all_fresh",
                "cutoff_regime": "midday",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
            },
        ]

        apply_current_blend_guardrail(rows, {
            "current_blend_default_alpha": 1.0,
            "current_blend_market_alpha": {"austin": 0.0},
            "current_blend_context_alpha": [
                {
                    "policy_id": "austin_all_fresh_midday_late",
                    "market_id": "austin",
                    "source_freshness_state": "all_fresh",
                    "cutoff_regime": ["midday", "late"],
                    "alpha": 1.0,
                }
            ],
        })

        self.assertAlmostEqual(rows[0]["candidate_p"], 0.80)
        self.assertAlmostEqual(rows[1]["candidate_p"], 0.20)
        self.assertAlmostEqual(rows[2]["candidate_p"], 0.80)

    def test_conservative_bridge_alpha_schedule_is_predeclared(self):
        self.assertAlmostEqual(bridge_alpha_for_market("atlanta"), 0.90)
        self.assertAlmostEqual(bridge_alpha_for_market("houston"), 0.90)
        self.assertAlmostEqual(bridge_alpha_for_market("miami"), 0.00)
        self.assertAlmostEqual(bridge_alpha_for_market("dallas"), 0.00)
        self.assertAlmostEqual(bridge_alpha_for_market("nyc"), 0.35)
        self.assertAlmostEqual(bridge_alpha_for_market("seattle"), 0.35)
        self.assertAlmostEqual(bridge_alpha_for_market("unknown-market"), 0.00)

    def test_apply_conservative_bridge_blends_candidate_and_current_by_market(self):
        rows = [
            {"market_id": "atlanta", "candidate_p": 0.80, "replayed_p": 0.20},
            {"market_id": "miami", "candidate_p": 0.80, "replayed_p": 0.20},
            {"market_id": "nyc", "candidate_p": 0.80, "replayed_p": 0.20},
        ]

        policy = apply_conservative_bridge(rows)

        self.assertEqual(policy["schema_version"], "conservative_bridge_policy_v0.1")
        self.assertAlmostEqual(rows[0]["bridge_candidate_p"], 0.74)
        self.assertAlmostEqual(rows[1]["bridge_candidate_p"], 0.20)
        self.assertAlmostEqual(rows[2]["bridge_candidate_p"], 0.41)
        self.assertEqual(rows[0]["bridge_policy_id"], "item73_conservative_bridge_2026_06_15")

    def test_candidate_shadow_variant_rows_are_item69_compatible(self):
        rows = [
            {
                "market_id": "atlanta",
                "target_date": "2026-06-14",
                "snapshot_id": "s1",
                "range_label": "82-83 F",
                "bin_type": "eq",
                "bin_value_c": "82",
                "candidate_cutoff_hour": 14,
                "candidate_p": 0.80,
                "replayed_p": 0.20,
                "recorded_p": 0.25,
                "market_yes": 0.75,
                "outcome": 1,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "candidate_variants.csv"
            path, count = write_candidate_shadow_variants(
                out,
                rows,
                variant_id="pooled_f_exact_winner_catchup_v0_1",
                variant_family="exact_winner_catchup",
                postprocess_config_hash="pooled_feature_band_hgb_v0.4",
            )
            disabled_path, disabled_count = write_candidate_shadow_variants(
                None,
                rows,
                variant_id="unused",
                variant_family="unused",
            )
            blocked_out = Path(tmp) / "blocked_candidate_variants.csv"
            with self.assertRaisesRegex(OSError, "insufficient disk headroom"):
                write_candidate_shadow_variants(
                    blocked_out,
                    rows,
                    variant_id="pooled_f_exact_winner_catchup_v0_1",
                    variant_family="exact_winner_catchup",
                    min_free_bytes=10**18,
                )
            variant_rows = candidate_shadow_variant_rows(
                rows,
                variant_id="pooled_f_exact_winner_catchup_v0_1",
                variant_family="exact_winner_catchup",
                postprocess_config_hash="pooled_feature_band_hgb_v0.4",
                experiment_start_date="2026-06-15",
            )

            self.assertEqual(path, str(out))
            self.assertEqual(count, 1)
            self.assertTrue(out.exists())
            self.assertIsNone(disabled_path)
            self.assertEqual(disabled_count, 0)
            self.assertFalse(blocked_out.exists())

        self.assertEqual(len(variant_rows), 1)
        row = variant_rows[0]
        self.assertEqual(row["variant_id"], "pooled_f_exact_winner_catchup_v0_1")
        self.assertEqual(row["variant_family"], "exact_winner_catchup")
        self.assertFalse(row["uses_market_features"])
        self.assertFalse(row["is_control"])
        self.assertEqual(row["band_key"], "82-83 F")
        self.assertEqual(row["postprocess_config_hash"], "pooled_feature_band_hgb_v0.4")
        self.assertAlmostEqual(row["probability"], 0.80)
        self.assertAlmostEqual(row["current_probability"], 0.20)

    def test_source_state_ablation_report_scores_control_and_dynamic_candidate(self):
        rows = [
            {
                "market_id": "atlanta",
                "target_date": "2026-06-14",
                "snapshot_id": "s1",
                "range_label": "82-83 F",
                "bin_type": "eq",
                "bin_value_c": "82",
                "candidate_cutoff_hour": 14,
                "candidate_p": 0.80,
                "replayed_p": 0.70,
                "recorded_p": 0.70,
                "market_yes": 0.75,
                "outcome": 1,
                "source_freshness_state": "all_fresh",
            },
            {
                "market_id": "nyc",
                "target_date": "2026-06-14",
                "snapshot_id": "s2",
                "range_label": "86-87 F",
                "bin_type": "eq",
                "bin_value_c": "86",
                "candidate_cutoff_hour": 15,
                "candidate_p": 0.20,
                "replayed_p": 0.80,
                "recorded_p": 0.80,
                "market_yes": 0.60,
                "outcome": 0,
                "source_freshness_state": "failed:open_meteo;stale:metar",
            },
        ]
        artifact = {
            "dynamic_source_state_enabled": True,
            "dynamic_source_state_columns": [
                "source_forecast_payload_age_minutes",
                "source_forecast_max_age_minutes",
                "source_forecast_failed_count",
                "source_status_group",
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "source_state_variants.csv"
            report = source_state_ablation_report(
                rows,
                artifact,
                candidate_artifact_hash="abc123",
                variant_out_path=out,
            )
            variant_rows = source_state_ablation_shadow_variant_rows(
                rows,
                experiment_start_date="2026-06-17",
                candidate_artifact_hash="abc123",
            )

            self.assertTrue(out.exists())

        self.assertTrue(report["enabled"])
        self.assertEqual(report["gate"]["verdict"], "READY")
        self.assertIn("freshest_forecast_age", report["feature_groups"])
        self.assertIn("max_forecast_age", report["feature_groups"])
        self.assertIn("forecast_family_degradation", report["feature_groups"])
        self.assertEqual(report["shadow_variants"]["rows"], 4)
        self.assertEqual({row["variant_id"] for row in variant_rows}, {
            "source_state_no_source_state_current",
            "source_state_dynamic_candidate",
        })
        control = [row for row in variant_rows if row["is_control"]][0]
        dynamic = [row for row in variant_rows if not row["is_control"]][0]
        self.assertAlmostEqual(control["probability"], 0.70)
        self.assertAlmostEqual(dynamic["probability"], 0.80)

    def test_conservative_bridge_report_writes_item69_variant_rows(self):
        rows = [
            {
                "market_id": "atlanta",
                "target_date": "2026-06-14",
                "snapshot_id": "s1",
                "range_label": "82-83 F",
                "bin_type": "eq",
                "bin_value_c": "82",
                "candidate_cutoff_hour": 14,
                "candidate_p": 0.80,
                "replayed_p": 0.20,
                "recorded_p": 0.25,
                "market_yes": 0.75,
                "outcome": 1,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bridge_variants.csv"
            report = conservative_bridge_report(rows, variant_out_path=out)
            variant_rows = conservative_bridge_shadow_variant_rows(rows, experiment_start_date="2026-06-15")

            self.assertTrue(out.exists())

        self.assertEqual(report["schema_version"], "conservative_bridge_policy_v0.1")
        self.assertEqual(report["diagnostics"]["shadow_variant_rows"], 2)
        self.assertEqual(report["aggregate"]["n"], 1)
        self.assertEqual({row["variant_id"] for row in variant_rows}, {
            "pooled_f_candidate_control",
            "conservative_bridge_policy_v0_1",
        })
        bridge_row = [row for row in variant_rows if row["variant_id"] == "conservative_bridge_policy_v0_1"][0]
        self.assertFalse(bridge_row["uses_market_features"])
        self.assertAlmostEqual(bridge_row["probability"], 0.74)

    def test_source_freshness_group_surfaces_failed_and_stale_sources(self):
        group = source_freshness_group({
            "sources": {
                "wu_history": {"ok": False, "status": "failed"},
                "wu_current": {"ok": True, "stale": True, "status": "stale_cache"},
                "open_meteo": {"ok": True, "stale": False},
            }
        })

        self.assertEqual(group, "failed:wu_history;stale:wu_current")
        self.assertEqual(
            source_freshness_group({"sources": {"open_meteo": {"ok": True, "stale": False}}}),
            "all_fresh",
        )

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
                "forecast_gap": 4.0,
                "forecast_source_count": 1,
                "forecast_disagreement": 3.2,
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

        with patch("weather.calibration.pooled_candidate_replay.predict_band_rows_for_bundle", return_value=[0.72]) as predict:
            rows, coverage = attach_band_candidate_probabilities(
                replay_results,
                feature_rows,
                artifact,
                "F",
                clob_features=clob_features,
                source_freshness={("nyc", "s1"): "stale:wu_current"},
            )

        self.assertEqual(coverage["candidate_rows"], 1)
        self.assertAlmostEqual(rows[0]["candidate_p"], 0.72)
        self.assertEqual(rows[0]["source_freshness_state"], "stale:wu_current")
        self.assertEqual(rows[0]["forecast_source_count_bucket"], "low_count")
        self.assertEqual(rows[0]["forecast_disagreement_bucket"], "high_disagreement")
        self.assertEqual(rows[0]["forecast_bucket_pressure"], "cool_side")
        self.assertEqual(rows[0]["clob_feature_available"], 1.0)
        self.assertAlmostEqual(rows[0]["clob_midpoint"], 0.39)
        band_rows = predict.call_args.args[1]
        self.assertEqual(band_rows[0]["band_value_hi"], 83.0)
        self.assertEqual(band_rows[0]["clob_feature_available"], 1.0)
        self.assertAlmostEqual(band_rows[0]["clob_liquidity_score"], 2.5)

    def test_band_candidate_replay_applies_forecast_centering_postprocess(self):
        replay_results = {
            "all_rows": [
                {
                    "market_id": "nyc",
                    "snapshot_id": "s1",
                    "range_label": "84 F",
                    "bin_type": "eq",
                    "bin_value_c": "84",
                    "market_yes": 0.40,
                    "outcome": 1,
                }
            ]
        }
        feature_rows = {
            ("nyc", "s1"): {
                "cutoff_hour": 3,
                "high_so_far": 78.0,
                "current_temp": 77.0,
                "forecast_high": 84.0,
                "forecast_gap": 6.0,
                "live_reading_temp": 78.0,
                "climate_normal": 82.0,
                "wind_group": "S-SW",
                "cloud_group": "Fair/clear",
                "market_id": "nyc",
            }
        }
        artifact = {
            "models": {"3": {"feature_names": ["placeholder"]}},
            "postprocess": {
                "partition_normalization_enabled": False,
                "support_floor_enabled": False,
                "late_lockin_enabled": False,
                "adjacent_calibration_enabled": False,
                "forecast_centering_enabled": True,
                "forecast_centering_early_alpha": 0.5,
                "forecast_centering_sigma": 1.25,
            },
        }

        with patch("weather.calibration.pooled_candidate_replay.predict_band_rows_for_bundle", return_value=[0.10]) as predict:
            rows, coverage = attach_band_candidate_probabilities(
                replay_results,
                feature_rows,
                artifact,
                "F",
            )

        self.assertEqual(coverage["candidate_rows"], 1)
        self.assertGreater(rows[0]["candidate_p"], 0.10)
        self.assertEqual(predict.call_args.kwargs["postprocess"], False)

    def test_density_candidate_replay_projects_payloads_to_mixed_unit_bands(self):
        replay_results = {
            "all_rows": [
                {
                    "market_id": "toronto",
                    "snapshot_id": "s1",
                    "range_label": "26 C",
                    "bin_type": "eq",
                    "bin_value_c": "26",
                    "market_yes": 0.40,
                    "outcome": 1,
                },
                {
                    "market_id": "nyc",
                    "snapshot_id": "s2",
                    "range_label": "82+ F",
                    "bin_type": "gte",
                    "bin_value_c": "82",
                    "market_yes": 0.35,
                    "outcome": 1,
                },
            ]
        }
        feature_rows = {
            ("toronto", "s1"): {
                "market_id": "toronto",
                "cutoff_hour": 12,
                "high_so_far": 26.0,
            },
            ("nyc", "s2"): {
                "market_id": "nyc",
                "cutoff_hour": 12,
                "high_so_far": 82.0,
            },
        }
        payloads = [
            continuous_density_payload({76.8: 0.5, 78.8: 0.5}, mean_f=77.8, sigma_f=1.0),
            continuous_density_payload({81.0: 0.5, 83.0: 0.5}, mean_f=82.0, sigma_f=1.5),
        ]
        artifact = {
            "prediction_mode": "continuous_density_f",
            "family_unit": "all",
            "exact_distribution": {
                "enabled": True,
                "temperature": 1.0,
                "prior_weight": 0.0,
            },
        }

        with patch("weather.calibration.pooled_candidate_replay.predict_density_rows_for_bundle", return_value=payloads) as predict:
            rows, coverage = attach_density_candidate_probabilities(
                replay_results,
                feature_rows,
                artifact,
                "all",
                source_freshness={("toronto", "s1"): "all_fresh"},
            )

        self.assertEqual(coverage["family_rows"], 2)
        self.assertEqual(coverage["candidate_rows"], 2)
        self.assertAlmostEqual(rows[0]["candidate_p"], 1.0)
        self.assertAlmostEqual(rows[1]["candidate_p"], 1.0)
        self.assertEqual(rows[0]["source_freshness_state"], "all_fresh")
        self.assertEqual(rows[1]["source_freshness_state"], "missing_source_status")
        self.assertAlmostEqual(rows[0]["candidate_density_mean_f"], 78.8)
        self.assertEqual(rows[0]["candidate_density_floor_bucket"], 26)
        self.assertEqual(rows[1]["candidate_density_floor_bucket"], 82)
        self.assertEqual(predict.call_args.args[0], artifact)
        self.assertEqual(len(predict.call_args.args[1]), 2)

    def test_density_candidate_replay_applies_market_band_postprocess(self):
        replay_results = {
            "all_rows": [
                {
                    "market_id": "nyc",
                    "snapshot_id": "s1",
                    "range_label": "82 F",
                    "bin_type": "eq",
                    "bin_value_c": "82",
                    "market_yes": 0.35,
                    "outcome": 0,
                },
            ]
        }
        feature_rows = {
            ("nyc", "s1"): {
                "market_id": "nyc",
                "cutoff_hour": 12,
                "high_so_far": 80.0,
                "forecast_high": 82.0,
                "current_temp": 80.0,
                "climate_normal": 82.0,
            },
        }
        payloads = [
            continuous_density_payload({80.0: 0.2, 82.0: 0.8}, mean_f=81.6, sigma_f=1.0),
        ]
        artifact = {
            "prediction_mode": "continuous_density_f",
            "family_unit": "all",
            "density_postprocess": {
                "enabled": True,
                "adjacent_calibration_enabled": True,
                "partition_normalization_enabled": False,
                "adjacent_calibration": {
                    "contexts": {
                        "floor_gap=+2": {"factor": 0.5},
                    },
                },
            },
        }

        with patch("weather.calibration.pooled_candidate_replay.predict_density_rows_for_bundle", return_value=payloads):
            rows, coverage = attach_density_candidate_probabilities(
                replay_results,
                feature_rows,
                artifact,
                "all",
                source_freshness={("nyc", "s1"): "all_fresh"},
            )

        self.assertEqual(coverage["candidate_rows"], 1)
        self.assertAlmostEqual(rows[0]["candidate_p"], 0.4)
        self.assertEqual(rows[0]["forecast_bucket_pressure"], "near_forecast")

    def test_density_candidate_replay_applies_forecast_relative_postprocess(self):
        replay_results = {
            "all_rows": [
                {
                    "market_id": "nyc",
                    "snapshot_id": "s1",
                    "range_label": "82 F",
                    "bin_type": "eq",
                    "bin_value_c": "82",
                    "market_yes": 0.35,
                    "outcome": 0,
                },
            ]
        }
        feature_rows = {
            ("nyc", "s1"): {
                "market_id": "nyc",
                "cutoff_hour": 12,
                "high_so_far": 80.0,
                "forecast_high": 82.0,
                "forecast_source_count": 2,
                "forecast_disagreement": 0.4,
                "current_temp": 80.0,
                "climate_normal": 82.0,
            },
        }
        payloads = [
            continuous_density_payload({80.0: 0.2, 82.0: 0.8}, mean_f=81.6, sigma_f=1.0),
        ]
        artifact = {
            "prediction_mode": "continuous_density_f",
            "family_unit": "all",
            "density_postprocess": {
                "enabled": True,
                "forecast_relative_calibration_enabled": True,
                "partition_normalization_enabled": False,
                "forecast_relative_calibration": {
                    "strength": 1.0,
                    "contexts": {
                        "pressure=near_forecast": {"factor": 0.5},
                    },
                },
            },
        }

        with patch("weather.calibration.pooled_candidate_replay.predict_density_rows_for_bundle", return_value=payloads):
            rows, coverage = attach_density_candidate_probabilities(
                replay_results,
                feature_rows,
                artifact,
                "all",
                source_freshness={("nyc", "s1"): "all_fresh"},
            )

        self.assertEqual(coverage["candidate_rows"], 1)
        self.assertAlmostEqual(rows[0]["candidate_p"], 0.4)
        self.assertEqual(rows[0]["forecast_disagreement_bucket"], "low_disagreement")

    def test_density_candidate_variant_defaults_use_named_lane(self):
        variant_id, variant_family = candidate_variant_defaults({
            "prediction_mode": "continuous_density_f",
        })

        self.assertEqual(variant_id, "pooled_continuous_density_hgb_v0_1")
        self.assertEqual(variant_family, "pooled_continuous_density")

    def test_density_candidate_variant_defaults_follow_schema_when_present(self):
        variant_id, variant_family = candidate_variant_defaults({
            "prediction_mode": "continuous_density_f",
            "schema_version": "pooled_continuous_density_hgb_v0.3",
        })

        self.assertEqual(variant_id, "pooled_continuous_density_hgb_v0_3")
        self.assertEqual(variant_family, "pooled_continuous_density")

    def test_candidate_variant_defaults_prefer_active_registry_contract_for_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "registered.pkl"
            artifact.write_bytes(b"demo")
            registry = {
                "schema_version": "model_variant_registry_v0.1",
                "exists": True,
                "path": "inline",
                "variants": [
                    {
                        "variant_id": "registered_active_v",
                        "variant_family": "registered_family",
                        "lifecycle": "active",
                        "track": "no_market",
                        "active_for_headline": True,
                        "artifact_path": str(artifact),
                        "prediction_function": "weather.calibration.pooled_candidate_replay:run_pooled_candidate_replay",
                        "prediction_mode": "band_binary",
                        "export_family": "registered_family",
                        "default_export_path": str(Path(tmp) / "registered.csv"),
                        "live_runtime": "pooled_candidate_replay",
                    }
                ],
            }

            variant_id, variant_family = candidate_variant_defaults(
                {"prediction_mode": "bucket_distribution"},
                variant_registry=registry,
                artifact_path=str(artifact),
            )

        self.assertEqual(variant_id, "registered_active_v")
        self.assertEqual(variant_family, "registered_family")

    def test_forecast_profile_variant_defaults_and_guardrails(self):
        variant_id, variant_family = candidate_variant_defaults({
            "prediction_mode": "band_binary",
            "feature_subset": "forecast_profile",
        })
        rows = [
            {
                "market_id": "nyc",
                "forecast_disagreement_bucket": "high_disagreement",
                "candidate_p": 0.90,
                "replayed_p": 0.10,
                "recorded_p": 0.10,
                "market_yes": 0.10,
                "outcome": 0,
            },
            {
                "market_id": "nyc",
                "forecast_disagreement_bucket": "high_disagreement",
                "candidate_p": 0.80,
                "replayed_p": 0.20,
                "recorded_p": 0.20,
                "market_yes": 0.20,
                "outcome": 0,
            },
        ]

        guardrails = forecast_profile_guardrails(rows, min_rows=1, tolerance=0.003)

        self.assertEqual(variant_id, "item134_forecast_profile_v0_1")
        self.assertEqual(variant_family, "forecast_profile_calibration")
        self.assertEqual(cutoff_regime(8), "early")
        self.assertEqual(cutoff_regime(14), "midday")
        self.assertEqual(cutoff_regime(15), "late")
        self.assertEqual(guardrails["blocked_markets"], ["nyc"])

    def test_candidate_shadow_variant_rows_preserve_source_state_context(self):
        rows = [
            {
                "market_id": "nyc",
                "target_date": "2026-06-18",
                "snapshot_id": "s1",
                "bin_type": "eq",
                "bin_value": 90,
                "candidate_p": 0.42,
                "replayed_p": 0.40,
                "recorded_p": 0.39,
                "market_yes": 0.41,
                "outcome": 1,
                "candidate_cutoff_hour": 8,
                "candidate_cutoff_regime": "early",
                "source_freshness_state": "stale:open_meteo",
                "settlement_distance_bucket": "0",
                "forecast_source_count_bucket": "low_count",
                "forecast_disagreement_bucket": "high_disagreement",
                "forecast_bucket_pressure": "warm_side",
                "casebook_taxonomy": "market_lead",
                "casebook_case_id": "case-1",
                "casebook_result": "candidate_win",
                "casebook_slice_type": "clob_taxonomy",
                "feature_schema_version": "toronto_feature_store_v1.6",
                "clob_feature_available": 1.0,
                "clob_midpoint": 0.72,
            }
        ]

        variant_rows = candidate_shadow_variant_rows(
            rows,
            "candidate",
            "family",
            artifact_hash="hash",
            postprocess_config_hash="schema",
            experiment_start_date="2026-06-18",
        )

        self.assertEqual(variant_rows[0]["cutoff_regime"], "early")
        self.assertEqual(variant_rows[0]["source_freshness_state"], "stale:open_meteo")
        self.assertEqual(variant_rows[0]["settlement_distance_bucket"], "0")
        self.assertEqual(variant_rows[0]["forecast_source_count_bucket"], "low_count")
        self.assertEqual(variant_rows[0]["forecast_disagreement_bucket"], "high_disagreement")
        self.assertEqual(variant_rows[0]["forecast_bucket_pressure"], "warm_side")
        self.assertEqual(variant_rows[0]["casebook_taxonomy"], "market_lead")
        self.assertEqual(variant_rows[0]["feature_schema_version"], "toronto_feature_store_v1.6")
        self.assertTrue(variant_rows[0]["feature_family_hash"])
        self.assertTrue(variant_rows[0]["feature_missingness_hash"])
        self.assertEqual(variant_rows[0]["clob_feature_available"], 1.0)

    def test_candidate_report_writes_source_freshness_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            write_report(
                {
                    "generated_at": "2026-06-15T00:00:00",
                    "verdict": "PASS_WITH_SHADOWS",
                    "candidate_market_verdict": "PASS_WITH_SHADOWS",
                    "cutover_decision": "PER_MARKET_ONLY",
                    "artifact": {},
                    "corpus": {},
                    "coverage": {},
                    "sidecar_eligibility": {
                        "status": "loaded",
                        "source_path": "data/backtest/data_layer_audit.json",
                        "candidate_variant_id": "candidate_v1",
                        "candidate_variant_family": "pooled_f",
                        "snapshot_folder_count": 2,
                        "primary_label_counts": {"score_only": 1, "training_ready": 1},
                        "readiness_label_counts": {"score_only": 2, "training_ready": 1},
                        "missing_artifact_counts": {"features": 1},
                        "non_reconstructable_gap_counts": {"market_ws_events": 1},
                        "backfill_command_counts": {"features_components": 1},
                        "backfill_candidate_folder_count": 1,
                        "active_day_sidecar_regression_count": 0,
                        "feature_quality_quarantine": {
                            "quarantine_row_count": 3,
                            "training_excluded_row_count": 3,
                            "backfill_candidate_row_count": 1,
                            "reason_counts": {"startup_live_observation_implausible": 2},
                        },
                        "by_market": [
                            {
                                "market_id": "nyc",
                                "days": 2,
                                "training_ready_days": 1,
                                "explanation_ready_days": 1,
                                "market_aware_ready_days": 0,
                                "variant_ready_days": 0,
                                "latest_target_date": "2026-06-15",
                            }
                        ],
                        "promotion_exclusion_sample": [
                            {
                                "market_id": "nyc",
                                "target_date": "2026-06-15",
                                "primary_label": "score_only",
                                "promotion_exclusion_reasons": ["missing_features"],
                                "market_aware_exclusion_reasons": ["missing_market_ws_events"],
                                "backfill_commands": [{"artifact": "features_components"}],
                            }
                        ],
                    },
                    "diagnostics": {"source_freshness_snapshots": 1},
                    "replay_gate": {"corpus_ok": True, "fidelity_ok": True},
                    "aggregate": None,
                    "daily_first": None,
                    "microstructure": None,
                    "market_rows": [],
                    "by_market": [],
                    "by_hour": [],
                    "by_cutoff_regime": [
                        {
                            "group": "early",
                            "n": 3,
                            "candidate_brier": 0.11,
                            "current_brier": 0.12,
                            "market_brier": 0.10,
                            "delta_vs_current": -0.01,
                            "delta_vs_market": 0.01,
                            "candidate_skill": 0.1,
                            "base_rate": 0.5,
                        }
                    ],
                    "by_bin_type": [],
                    "by_settlement_distance": [],
                    "by_source_freshness": [
                        {
                            "group": "failed:wu_history",
                            "n": 2,
                            "candidate_brier": 0.20,
                            "current_brier": 0.15,
                            "market_brier": 0.10,
                            "delta_vs_current": 0.05,
                            "delta_vs_market": 0.10,
                            "candidate_skill": -1.0,
                            "base_rate": 0.5,
                        }
                    ],
                    "by_forecast_disagreement": [
                        {
                            "group": "high_disagreement",
                            "n": 2,
                            "candidate_brier": 0.20,
                            "current_brier": 0.15,
                            "market_brier": 0.10,
                            "delta_vs_current": 0.05,
                            "delta_vs_market": 0.10,
                            "candidate_skill": -1.0,
                            "base_rate": 0.5,
                        }
                    ],
                    "forecast_profile_guardrails": {
                        "rows": [
                            {
                                "market_id": "nyc",
                                "status": "blocked",
                                "comparison": {
                                    "n": 2,
                                    "candidate_brier": 0.20,
                                    "current_brier": 0.15,
                                    "market_brier": 0.10,
                                    "delta_vs_current": 0.05,
                                    "delta_vs_market": 0.10,
                                },
                                "reasons": ["candidate not proven safe"],
                            }
                        ]
                    },
                    "replay_summary": {},
                },
                out,
            )

            text = out.read_text(encoding="utf-8")

        self.assertIn("### By Source Freshness", text)
        self.assertIn("failed:wu_history", text)
        self.assertIn("## Snapshot Sidecar Eligibility", text)
        self.assertIn("score_only: 1", text)
        self.assertIn("Feature-quality quarantined rows", text)
        self.assertIn("startup_live_observation_implausible: 2", text)
        self.assertIn("### Sidecar Mix By Market", text)
        self.assertIn("### Promotion And Market-Aware Exclusions", text)
        self.assertIn("### By Cutoff Regime", text)
        self.assertIn("### By Forecast Disagreement", text)
        self.assertIn("Forecast-Profile High-Disagreement Guardrails", text)

    def test_sidecar_eligibility_summary_from_audit_compacts_market_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data_layer_audit.json"
            path.write_text(
                json.dumps({
                    "snapshots": {
                        "folder_count": 2,
                        "sidecar_eligibility": {
                            "primary_label_counts": {"replay_only": 1, "market_aware_ready": 1},
                            "label_counts": {"score_only": 2, "training_ready": 1},
                            "missing_artifact_counts": {"components": 1},
                            "non_reconstructable_gap_counts": {"variant_predictions": 1},
                            "backfill_command_counts": {"features_components": 1},
                            "backfill_candidate_folder_count": 1,
                            "active_day_sidecar_regression_count": 0,
                            "feature_quality_quarantine": {
                                "quarantine_row_count": 2,
                                "training_excluded_row_count": 2,
                                "reason_counts": {"current_max_exceeds_observed_support": 2},
                            },
                            "promotion_exclusion_sample": [
                                {
                                    "market_id": "nyc",
                                    "target_date": "2026-06-15",
                                    "primary_label": "replay_only",
                                    "promotion_exclusion_reasons": ["missing_components"],
                                    "market_aware_exclusion_reasons": [],
                                    "backfill_commands": [{"artifact": "features_components"}],
                                }
                            ],
                        },
                        "by_market": [
                            {
                                "market_id": "nyc",
                                "folders": 2,
                                "training_ready_label_days": 1,
                                "explanation_ready_days": 1,
                                "market_aware_ready_days": 1,
                                "variant_ready_days": 0,
                                "latest_target_date": "2026-06-15",
                            }
                        ],
                    }
                }),
                encoding="utf-8",
            )

            summary = sidecar_eligibility_summary_from_audit(
                path,
                candidate_variant_id="candidate_v1",
                candidate_variant_family="pooled_f",
            )

        self.assertTrue(summary["loaded"])
        self.assertEqual(summary["status"], "loaded")
        self.assertEqual(summary["candidate_variant_id"], "candidate_v1")
        self.assertEqual(summary["primary_label_counts"]["replay_only"], 1)
        self.assertEqual(summary["backfill_candidate_folder_count"], 1)
        self.assertEqual(summary["feature_quality_quarantine"]["quarantine_row_count"], 2)
        self.assertEqual(summary["by_market"][0]["market_id"], "nyc")
        self.assertEqual(summary["by_market"][0]["market_aware_ready_days"], 1)
        self.assertEqual(summary["promotion_exclusion_sample"][0]["primary_label"], "replay_only")

    def test_candidate_report_blocks_before_create_when_headroom_is_low(self):
        payload = {
            "generated_at": "2026-06-15T00:00:00",
            "verdict": "PASS_WITH_SHADOWS",
            "candidate_market_verdict": "PASS_WITH_SHADOWS",
            "cutover_decision": "PER_MARKET_ONLY",
            "artifact": {},
            "corpus": {},
            "coverage": {},
            "diagnostics": {},
            "replay_gate": {"corpus_ok": True, "fidelity_ok": True},
            "aggregate": None,
            "daily_first": None,
            "microstructure": None,
            "source_state_ablation": None,
            "conservative_bridge": None,
            "market_rows": [],
            "by_market": [],
            "by_hour": [],
            "by_cutoff_regime": [],
            "by_bin_type": [],
            "by_settlement_distance": [],
            "by_source_freshness": [],
            "forecast_profile_guardrails": {},
            "replay_summary": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"

            with self.assertRaises(OSError):
                write_report(payload, out, min_free_bytes=10**18)

            self.assertFalse(out.exists())

    def test_candidate_report_writes_source_state_ablation_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            write_report(
                {
                    "generated_at": "2026-06-15T00:00:00",
                    "verdict": "BLOCK",
                    "candidate_market_verdict": "BLOCK",
                    "cutover_decision": "DO_NOT_CUT_OVER",
                    "artifact": {},
                    "corpus": {},
                    "coverage": {},
                    "diagnostics": {},
                    "replay_gate": {"corpus_ok": True, "fidelity_ok": True},
                    "aggregate": None,
                    "daily_first": None,
                    "microstructure": None,
                    "source_state_ablation": {
                        "schema_version": "source_state_ablation_v0.1",
                        "enabled": True,
                        "feature_groups": {
                            "freshest_forecast_age": ["source_forecast_payload_age_minutes"],
                            "max_forecast_age": ["source_forecast_max_age_minutes"],
                        },
                        "shadow_variants": {
                            "rows": 2,
                            "path": "data/backtest/source_state_ablation_shadow_variants.csv",
                            "variant_ids": [
                                "source_state_dynamic_candidate",
                                "source_state_no_source_state_current",
                            ],
                        },
                        "gate": {
                            "verdict": "SHADOW",
                            "reasons": ["degraded-source rows regress current serving"],
                            "aggregate": {
                                "n": 2,
                                "candidate_brier": 0.20,
                                "current_brier": 0.15,
                                "market_brier": 0.10,
                                "delta_vs_current": 0.05,
                                "delta_vs_market": 0.10,
                                "candidate_skill": -1.0,
                                "base_rate": 0.5,
                            },
                        },
                        "by_degradation": [],
                        "by_source_freshness": [],
                    },
                    "market_rows": [],
                    "by_market": [],
                    "by_hour": [],
                    "by_bin_type": [],
                    "by_settlement_distance": [],
                    "by_source_freshness": [],
                    "replay_summary": {},
                },
                out,
            )

            text = out.read_text(encoding="utf-8")

        self.assertIn("## Source-State Feature Ablation", text)
        self.assertIn("degraded-source rows regress current serving", text)
        self.assertIn("source_state_dynamic_candidate", text)

    def test_candidate_report_labels_all_market_density_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            write_report(
                {
                    "generated_at": "2026-06-15T00:00:00",
                    "verdict": "BLOCK",
                    "candidate_market_verdict": "BLOCK",
                    "cutover_decision": "DO_NOT_CUT_OVER",
                    "artifact": {
                        "family_unit": "all",
                        "prediction_mode": "continuous_density_f",
                        "market_bias_calibration_enabled": True,
                        "market_bias_calibration_contexts": 12,
                        "market_bias_baseline_brier": 0.05,
                        "market_bias_candidate_brier": 0.04,
                        "market_bias_delta_brier": -0.01,
                        "current_blend_source_freshness_default_alpha": 0.0,
                        "current_blend_source_freshness_alpha": {"all_fresh": 1.0},
                        "market_bias_excluded_markets": ["toronto"],
                        "market_bias_allowed_source_freshness_states": ["all_fresh"],
                    },
                    "corpus": {},
                    "coverage": {
                        "family_unit": "all",
                        "total_replay_rows": 2,
                        "family_rows": 2,
                        "candidate_rows": 1,
                        "excluded_non_family_rows": 0,
                    },
                    "diagnostics": {},
                    "replay_gate": {"corpus_ok": True, "fidelity_ok": True},
                    "aggregate": {
                        "n": 1,
                        "candidate_brier": 0.10,
                        "current_brier": 0.20,
                        "recorded_brier": 0.30,
                        "market_brier": 0.40,
                        "delta_vs_current": -0.10,
                        "delta_vs_market": -0.30,
                        "candidate_skill": 0.5,
                        "base_rate": 1.0,
                    },
                    "daily_first": None,
                    "microstructure": None,
                    "market_rows": [],
                    "by_market": [],
                    "by_hour": [],
                    "by_bin_type": [],
                    "by_settlement_distance": [],
                    "by_source_freshness": [],
                    "replay_summary": {},
                },
                out,
            )

            text = out.read_text(encoding="utf-8")

        self.assertIn("# Pooled All-Market Candidate Replay", text)
        self.assertIn("All market rows", text)
        self.assertIn("Excluded non-market rows", text)
        self.assertIn("Market bias calibration enabled", text)
        self.assertIn("0.0500 -> 0.0400", text)
        self.assertIn("Current blend source-freshness alpha", text)
        self.assertIn("Market bias excluded markets", text)
        self.assertNotIn("F-family rows", text)

    def test_candidate_report_writes_exact_winner_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.md"
            write_report(
                {
                    "generated_at": "2026-06-15T00:00:00",
                    "verdict": "PASS_WITH_SHADOWS",
                    "candidate_market_verdict": "PASS_WITH_SHADOWS",
                    "cutover_decision": "PER_MARKET_ONLY",
                    "artifact": {},
                    "corpus": {},
                    "coverage": {},
                    "diagnostics": {},
                    "replay_gate": {"corpus_ok": True, "fidelity_ok": True},
                    "aggregate": None,
                    "daily_first": None,
                    "candidate_shadow_variants": None,
                    "exact_winner_diagnostics": {
                        "scopes": [
                            {
                                "slice": "settlement_distance_0",
                                "n": 2,
                                "candidate_brier": 0.20,
                                "current_brier": 0.25,
                                "market_brier": 0.15,
                                "delta_vs_current": -0.05,
                                "delta_vs_market": 0.05,
                                "candidate_ece": 0.10,
                                "current_ece": 0.15,
                                "market_ece": 0.08,
                                "exact_winner": {
                                    "winner_rows": 1,
                                    "candidate_mean_probability": 0.70,
                                    "current_mean_probability": 0.50,
                                    "market_mean_probability": 0.80,
                                },
                            }
                        ],
                        "daily_first": {
                            "n_days": 1,
                            "n": 2,
                            "candidate_brier": 0.20,
                            "current_brier": 0.25,
                            "market_brier": 0.15,
                            "delta_vs_current": -0.05,
                            "delta_vs_market": 0.05,
                        },
                        "worst_daily_current_regressions": [
                            {
                                "group": "seattle:2026-06-14",
                                "n": 2,
                                "candidate_brier": 0.20,
                                "current_brier": 0.25,
                                "market_brier": 0.15,
                                "delta_vs_current": -0.05,
                                "delta_vs_market": 0.05,
                                "candidate_ece": 0.10,
                                "base_rate": 0.5,
                            }
                        ],
                    },
                    "microstructure": None,
                    "market_rows": [],
                    "by_market": [],
                    "by_hour": [],
                    "by_bin_type": [],
                    "by_settlement_distance": [],
                    "by_source_freshness": [],
                    "replay_summary": {},
                },
                out,
            )

            text = out.read_text(encoding="utf-8")

        self.assertIn("## Exact-Winner Catch-Up Diagnostics", text)
        self.assertIn("settlement_distance_0", text)
        self.assertIn("Worst Daily Current Regressions", text)

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
        self.assertIn("micro_ece", comp)
        self.assertIn("micro_overconfident_error_rate", comp)

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
                "micro_logloss": 0.20,
                "candidate_logloss": 0.30,
                "micro_ece": 0.03,
                "micro_overconfident_error_rate": 0.0,
                "delta_vs_candidate": -0.06,
                "delta_vs_market": -0.01,
            },
            {
                "group": "market_lead",
                "n": 30,
                "micro_brier": 0.01,
                "candidate_brier": 0.03,
                "market_brier": 0.02,
                "micro_logloss": 0.12,
                "candidate_logloss": 0.20,
                "micro_ece": 0.02,
                "micro_overconfident_error_rate": 0.0,
                "delta_vs_candidate": -0.02,
                "delta_vs_market": -0.01,
            },
            {
                "group": "market_overreaction",
                "n": 80,
                "micro_brier": 0.17,
                "candidate_brier": 0.10,
                "market_brier": 0.19,
                "micro_logloss": 0.50,
                "candidate_logloss": 0.30,
                "micro_ece": 0.20,
                "micro_overconfident_error_rate": 0.5,
                "delta_vs_candidate": 0.07,
                "delta_vs_market": -0.02,
            },
        ]

        gate = build_microstructure_gate(taxonomy_scores)

        self.assertEqual(
            gate["allowed_taxonomies"],
            ["market_lead", "book_liquidity_artifact"],
        )
        self.assertEqual(
            [row["taxonomy"] for row in gate["decisions"]],
            ["market_lead", "book_liquidity_artifact"],
        )
        self.assertEqual(gate["max_logloss_delta_vs_candidate"], 0.0)
        self.assertEqual(gate["max_ece"], 0.12)

    def test_microstructure_gate_blocks_bad_logloss_or_calibration(self):
        gate = build_microstructure_gate([
            {
                "group": "market_lead",
                "n": 40,
                "micro_brier": 0.08,
                "candidate_brier": 0.14,
                "market_brier": 0.09,
                "micro_logloss": 0.45,
                "candidate_logloss": 0.30,
                "micro_ece": 0.03,
                "micro_overconfident_error_rate": 0.0,
                "delta_vs_candidate": -0.06,
                "delta_vs_market": -0.01,
            },
            {
                "group": "book_liquidity_artifact",
                "n": 40,
                "micro_brier": 0.08,
                "candidate_brier": 0.14,
                "market_brier": 0.09,
                "micro_logloss": 0.20,
                "candidate_logloss": 0.30,
                "micro_ece": 0.18,
                "micro_overconfident_error_rate": 0.0,
                "delta_vs_candidate": -0.06,
                "delta_vs_market": -0.01,
            },
        ])

        by_taxonomy = {row["taxonomy"]: row for row in gate["decisions"]}
        self.assertFalse(by_taxonomy["market_lead"]["allowed"])
        self.assertIn("logloss_delta_vs_candidate", by_taxonomy["market_lead"]["reason"])
        self.assertFalse(by_taxonomy["book_liquidity_artifact"]["allowed"])
        self.assertIn("micro_ece", by_taxonomy["book_liquidity_artifact"]["reason"])

    def test_microstructure_shadow_variant_rows_are_item69_compatible(self):
        rows = [
            {
                "market_id": "nyc",
                "target_date": "2026-06-14",
                "snapshot_id": "s1",
                "range_label": "82-83 F",
                "bin_type": "eq",
                "bin_value_c": "82",
                "candidate_cutoff_hour": 14,
                "candidate_p": 0.30,
                "micro_candidate_p": 0.34,
                "micro_gated_candidate_p": 0.32,
                "replayed_p": 0.28,
                "recorded_p": 0.29,
                "market_yes": 0.35,
                "outcome": 1,
            }
        ]

        variant_rows = microstructure_shadow_variant_rows(rows, experiment_start_date="2026-06-15")
        by_id = {row["variant_id"]: row for row in variant_rows}

        self.assertEqual(len(variant_rows), 3)
        self.assertFalse(by_id["pooled_f_candidate_control"]["uses_market_features"])
        self.assertTrue(by_id["pooled_f_candidate_control"]["is_control"])
        self.assertTrue(by_id["clob_overlay_raw_oof"]["uses_market_features"])
        self.assertTrue(by_id["clob_overlay_gated_taxonomy"]["uses_market_features"])
        self.assertEqual(by_id["clob_overlay_gated_taxonomy"]["variant_family"], "clob_overlay")
        self.assertEqual(by_id["clob_overlay_gated_taxonomy"]["band_key"], "82-83 F")
        self.assertEqual(by_id["clob_overlay_gated_taxonomy"]["experiment_start_date"], "2026-06-15")

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
