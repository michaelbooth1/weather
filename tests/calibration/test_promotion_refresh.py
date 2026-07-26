import csv
import os
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from weather.reporting.promotion.readers import _read_physical_feature_family_ratchet
from weather.reporting.promotion.promotion_refresh import (  # noqa: E402
    _candidate_gap_driver_rows,
    _candidate_args,
    _candidate_source_freshness_rows,
    _candidate_summary,
    _family_specs,
    _serving_blocking_source_freshness_rows,
    _write_complete_manifest,
    _write_incomplete_manifest,
    _write_json,
    _write_started_manifest,
    build_evidence_freshness_gate,
    build_early_hour_promotion_blocker,
    build_gap_owner_table,
    build_family_decisions,
    build_promotion_allowlist,
    build_source_missingness_location_gate,
    load_precomputed_candidate_report,
    market_skill_diagnostics,
    model_skill_claims,
    promotion_readiness,
    write_gap_experiment_artifacts,
    write_report,
)


def _spec(market_id, city, unit="F"):
    return SimpleNamespace(id=market_id, city_label=city, display_unit=unit)


def _early_hour_candidate():
    return {
        "aggregate": {"delta_vs_market": 0.001},
        "corpus": {"corpus_hash": "corpus-1"},
        "candidate_shadow_variants": {
            "variant_id": "candidate_v1",
            "active_registry_contract": {"variant_id": "candidate_v1"},
        },
    }


def _candidate_gate_report(gate_key, *, status="PASS", variant_id="candidate_v1", corpus_hash="corpus-1", generated_at=None):
    return {
        "generated_at_utc": generated_at or "2026-06-22T12:00:00+00:00",
        "variant_ids": [variant_id] if variant_id else [],
        "corpus": {"corpus_hash": corpus_hash} if corpus_hash else {},
        gate_key: {"status": status, "variant_ids": [variant_id] if variant_id else []},
    }


def _clean_fleet():
    return {
        "summary": {
            "live_forward_slo_status": "PASS",
            "current_code_soak_status": "PASS",
            "clean_active_day_countability_status": "PASS",
            "clean_active_day_counts_toward_early_hour_evidence": True,
            "early_hour_coverage_status": "PASS",
            "early_hour_coverage_countable_markets": 12,
            "early_hour_coverage_total_snapshots": 588,
        },
        "live_forward_slo": {"status": "PASS", "counts_toward_live_forward_gate": True},
        "current_code_soak": {"status": "PASS", "counts_toward_active_day": True},
        "clean_active_day_countability": {
            "status": "PASS",
            "counts_toward_clean_active_day": True,
            "counts_toward_early_hour_evidence": True,
            "operational_blocker_count": 0,
            "early_hour_coverage_proof": {
                "summary": {
                    "status": "PASS",
                    "countable_market_count": 12,
                    "total_snapshot_count": 588,
                },
            },
        },
    }


class TestPromotionRefresh(unittest.TestCase):
    def test_family_decisions_promote_only_passing_family_markets(self):
        specs = [
            _spec("nyc", "New York"),
            _spec("denver", "Denver"),
            _spec("toronto", "Toronto", unit="C"),
        ]
        manifest = {
            "entries": [
                {"market_id": "nyc"},
                {"market_id": "nyc"},
                {"market_id": "denver"},
                {"market_id": "toronto"},
            ],
        }
        trust_rows = [
            {"market": "nyc", "trust_score": 80, "grade": "Strong", "settled_days": 4},
            {"market": "denver", "trust_score": 15, "grade": "Unproven", "settled_days": 1},
        ]
        candidate_report = {
            "replay_gate": {"global_ok": True},
            "market_rows": [
                {
                    "market_id": "nyc",
                    "verdict": "PASS",
                    "reason": "beats current replay and clears market/trust gates",
                    "days": 4,
                    "snapshots": 20,
                    "rows": 60,
                    "comparison": {
                        "candidate_brier": 0.02,
                        "current_brier": 0.04,
                        "market_brier": 0.03,
                        "delta_vs_current": -0.02,
                        "delta_vs_market": -0.01,
                    },
                },
                {
                    "market_id": "denver",
                    "verdict": "SHADOW",
                    "reason": "trust 15 < 25",
                    "days": 1,
                    "snapshots": 5,
                    "rows": 15,
                    "comparison": {"candidate_brier": 0.05},
                },
            ],
        }

        decisions = build_family_decisions(
            manifest,
            trust_rows,
            candidate_report,
            specs=specs,
        )

        self.assertEqual(decisions["promote_markets"], ["nyc"])
        self.assertEqual(decisions["shadow_markets"], ["denver"])
        self.assertEqual(decisions["blocked_markets"], [])
        self.assertEqual(decisions["family_market_count"], 2)
        nyc = next(row for row in decisions["markets"] if row["market_id"] == "nyc")
        self.assertEqual(nyc["settled_days_in_corpus"], 2)
        self.assertEqual(nyc["action"], "PROMOTE_CANDIDATE")

    def test_promotion_allowlist_blocks_failed_market_even_when_candidate_has_promotes(self):
        specs = [
            _spec("atlanta", "Atlanta"),
            _spec("miami", "Miami"),
        ]
        manifest = {"entries": [{"market_id": "atlanta"}, {"market_id": "miami"}]}
        trust_rows = [
            {"market": "atlanta", "trust_score": 80, "grade": "Strong", "settled_days": 4},
            {"market": "miami", "trust_score": 80, "grade": "Strong", "settled_days": 4},
        ]
        candidate_report = {
            "replay_gate": {"global_ok": True},
            "market_rows": [
                {
                    "market_id": "atlanta",
                    "verdict": "PASS",
                    "reason": "beats current replay and clears market/trust gates",
                    "days": 4,
                    "snapshots": 20,
                    "rows": 60,
                    "comparison": {
                        "candidate_brier": 0.02,
                        "current_brier": 0.04,
                        "market_brier": 0.03,
                        "delta_vs_current": -0.02,
                        "delta_vs_market": -0.01,
                    },
                },
                {
                    "market_id": "miami",
                    "verdict": "BLOCK",
                    "reason": "candidate trails market by +0.0148 > 0.0030",
                    "days": 4,
                    "snapshots": 20,
                    "rows": 60,
                    "comparison": {
                        "candidate_brier": 0.0548,
                        "current_brier": 0.0600,
                        "market_brier": 0.0400,
                        "delta_vs_current": -0.0052,
                        "delta_vs_market": 0.0148,
                    },
                },
            ],
        }

        decisions = build_family_decisions(
            manifest,
            trust_rows,
            candidate_report,
            specs=specs,
        )
        allowlist = build_promotion_allowlist(
            decisions,
            {
                "json_path": "candidate.json",
                "candidate_shadow_variants": {"variant_id": "candidate_v1"},
                "verdict": "SHADOW_ONLY",
            },
            generated_at_utc="2026-06-22T12:00:00+00:00",
            path="allowlist.json",
        )
        rows = {row["market_id"]: row for row in allowlist["markets"]}

        self.assertEqual(allowlist["schema_version"], "promotion_allowlist_v0.1")
        self.assertEqual(allowlist["promote_markets"], ["atlanta"])
        self.assertEqual(allowlist["blocked_markets"], ["miami"])
        self.assertTrue(rows["atlanta"]["candidate_serving_allowed"])
        self.assertFalse(rows["miami"]["candidate_serving_allowed"])
        self.assertFalse(rows["miami"]["candidate_permission_allowed"])
        self.assertEqual(rows["miami"]["serving_behavior"], "current_or_shadow")
        self.assertIn("trails market", rows["miami"]["blocker_reason"])

    def test_promotion_allowlist_blocks_promote_when_candidate_cutover_is_denied(self):
        decisions = {
            "markets": [
                {
                    "market_id": "austin",
                    "action": "PROMOTE_CANDIDATE",
                    "verdict": "PASS",
                    "reason": "beats current replay",
                    "metrics": {
                        "candidate_brier": 0.03,
                        "current_brier": 0.04,
                        "market_brier": 0.031,
                    },
                }
            ]
        }

        allowlist = build_promotion_allowlist(
            decisions,
            {
                "candidate_shadow_variants": {"variant_id": "candidate_v1"},
                "verdict": "BLOCK",
                "cutover_decision": "DO_NOT_CUT_OVER",
            },
            generated_at_utc="2026-06-22T12:00:00+00:00",
        )

        row = allowlist["markets"][0]
        self.assertFalse(row["candidate_serving_allowed"])
        self.assertFalse(row["candidate_permission_allowed"])
        self.assertFalse(row["candidate_cutover_allowed"])
        self.assertEqual(row["effective_promotion_state"], "SHADOW")
        self.assertEqual(row["serving_behavior"], "current_or_shadow")
        self.assertIn("DO_NOT_CUT_OVER", row["blocker_reason"])

    def test_all_family_specs_include_c_and_f_markets(self):
        specs = [
            _spec("nyc", "New York"),
            _spec("toronto", "Toronto", unit="C"),
        ]

        selected = _family_specs("all", specs=specs)

        self.assertEqual({spec.id for spec in selected}, {"nyc", "toronto"})

    def test_candidate_args_pass_variant_lane_fields_to_replay(self):
        args = SimpleNamespace(
            snapshots_root="data/snapshots",
            artifact="density.pkl",
            candidate_report="candidate.md",
            candidate_json="candidate.json",
            current_replay_report=None,
            current_tol=0.003,
            market_tol=0.003,
            min_days=2,
            min_trust=25,
            max_fidelity_l1=0.0,
            clob_max_age_seconds=180.0,
            casebook="casebook.json",
            candidate_variant_out="density_variants.csv",
            candidate_variant_id="pooled_continuous_density_hgb_v0_1",
            candidate_variant_family="pooled_continuous_density",
            candidate_variant_uses_market_features=False,
            candidate_variant_control=False,
            min_artifact_free_bytes=123456789,
            microstructure_artifact="",
            microstructure_min_train_rows=500,
            skip_microstructure_overlay=True,
            require_exact_identity=False,
            require_all_markets=False,
        )

        replay_args = _candidate_args(args, "corpus.json")

        self.assertEqual(replay_args.candidate_variant_out, "density_variants.csv")
        self.assertEqual(replay_args.candidate_variant_id, "pooled_continuous_density_hgb_v0_1")
        self.assertEqual(replay_args.candidate_variant_family, "pooled_continuous_density")
        self.assertEqual(replay_args.min_artifact_free_bytes, 123456789)
        self.assertIsNone(replay_args.microstructure_artifact)

    def test_candidate_summary_exposes_independent_evidence_accounting(self):
        candidate_report = {
            "aggregate": {"n": 75},
            "market_rows": [
                {"market_id": "nyc", "days": 4, "snapshots": 20, "rows": 60, "comparison": {}},
                {"market_id": "denver", "days": 1, "snapshots": 5, "rows": 15, "comparison": {}},
            ],
        }

        summary = _candidate_summary(candidate_report, "candidate.json", "candidate.md")

        evidence = summary["evidence_accounting"]
        self.assertEqual(evidence["scored_rows"], 75)
        self.assertEqual(evidence["unique_observation_count"], 75)
        self.assertEqual(evidence["snapshot_count"], 25)
        self.assertEqual(evidence["market_day_count"], 5)

    def test_global_replay_gate_blocks_otherwise_passing_candidate(self):
        specs = [_spec("nyc", "New York")]
        candidate_report = {
            "replay_gate": {
                "global_ok": False,
                "corpus_message": "FAIL: 1 corpus pin warning(s)",
            },
            "market_rows": [
                {
                    "market_id": "nyc",
                    "verdict": "PASS",
                    "reason": "passes local gates",
                    "days": 3,
                    "snapshots": 9,
                    "rows": 27,
                    "comparison": {},
                },
            ],
        }

        decisions = build_family_decisions(
            {"entries": [{"market_id": "nyc"}]},
            [{"market": "nyc", "trust_score": 80, "grade": "Strong", "settled_days": 3}],
            candidate_report,
            specs=specs,
        )

        self.assertEqual(decisions["promote_markets"], [])
        self.assertEqual(decisions["blocked_markets"], ["nyc"])
        self.assertIn("global replay gate failed", decisions["markets"][0]["reason"])

    def test_blocked_validation_gate_blocks_otherwise_passing_candidate(self):
        specs = [_spec("nyc", "New York")]
        candidate_report = {
            "replay_gate": {"global_ok": True},
            "market_rows": [
                {
                    "market_id": "nyc",
                    "verdict": "PASS",
                    "reason": "passes local gates",
                    "days": 3,
                    "snapshots": 9,
                    "rows": 27,
                    "comparison": {
                        "candidate_brier": 0.02,
                        "current_brier": 0.04,
                        "market_brier": 0.03,
                        "delta_vs_current": -0.02,
                        "delta_vs_market": -0.01,
                    },
                    "blocked_validation": {
                        "passed": False,
                        "verdict": "BLOCK",
                        "reasons": ["daily-first candidate regresses current by +0.0100 > 0.0030"],
                    },
                },
            ],
        }

        decisions = build_family_decisions(
            {"entries": [{"market_id": "nyc"}]},
            [{"market": "nyc", "trust_score": 80, "grade": "Strong", "settled_days": 3}],
            candidate_report,
            specs=specs,
        )

        self.assertEqual(decisions["promote_markets"], [])
        self.assertEqual(decisions["blocked_markets"], ["nyc"])
        self.assertIn("blocked validation failed", decisions["markets"][0]["reason"])

    def test_missing_candidate_rows_stay_shadow_not_promoted(self):
        decisions = build_family_decisions(
            {"entries": []},
            [],
            {"replay_gate": {"global_ok": True}, "market_rows": []},
            specs=[_spec("austin", "Austin")],
        )

        self.assertEqual(decisions["shadow_markets"], ["austin"])
        self.assertEqual(decisions["markets"][0]["action"], "KEEP_SHADOW")
        self.assertIn("no pinned candidate rows", decisions["markets"][0]["reason"])

    def test_promotion_readiness_surfaces_market_and_serving_blockers(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": 0.0123}},
            {"verdict": "BLOCK"},
            {
                "shadow_markets": ["austin"],
                "blocked_markets": [],
                "markets": [
                    {
                        "market_id": "austin",
                        "action": "KEEP_SHADOW",
                        "reason": "not proven better than market on pinned rows",
                        "metrics": {
                            "candidate_brier": 0.04,
                            "current_brier": 0.05,
                            "market_brier": 0.03,
                            "delta_vs_current": -0.01,
                            "delta_vs_market": 0.01,
                        },
                    }
                ],
            },
        )

        categories = {row["category"] for row in readiness["blockers"]}
        self.assertEqual(readiness["status"], "OPEN")
        self.assertIn("candidate_market_skill", categories)
        self.assertIn("per_market_shadow", categories)
        self.assertIn("current_serving_gauntlet", categories)
        self.assertEqual(readiness["shadow_market_details"][0]["market_id"], "austin")
        self.assertEqual(
            readiness["shadow_market_details"][0]["reason"],
            "not proven better than market on pinned rows",
        )

    def test_promotion_readiness_blocks_on_hourly_performance_gate(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            hourly_performance={
                "hourly_performance_gate": {
                    "status": "BLOCK",
                    "first_blocker": {
                        "gate": "early_hour_brier_regression",
                        "detail": "early-hour model Brier trails market",
                    },
                }
            },
        )

        self.assertEqual(readiness["status"], "OPEN")
        blocker = next(row for row in readiness["blockers"] if row["category"] == "hourly_performance_gate")
        self.assertEqual(blocker["severity"], "block")
        self.assertIn("early-hour model Brier trails market", blocker["detail"])
        self.assertFalse(readiness["hourly_performance_mitigation"]["applied"])

    def test_promotion_readiness_accepts_candidate_hourly_gate_mitigation(self):
        readiness = promotion_readiness(
            {
                "aggregate": {"delta_vs_market": -0.01},
                "blocked_validation": {"passed": True},
                "candidate_shadow_variants": {"variant_id": "candidate_v1"},
            },
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            hourly_performance={
                "hourly_performance_gate": {
                    "status": "BLOCK",
                    "first_blocker": {
                        "gate": "early_hour_brier_regression",
                        "detail": "early-hour current model Brier trails market",
                    },
                }
            },
            candidate_hourly_performance={
                "variant_ids": ["candidate_v1"],
                "candidate_hourly_gate": {
                    "status": "PASS",
                    "blocker_count": 0,
                    "early_morning": {
                        "delta_vs_market": -0.0008,
                        "delta_vs_current": -0.0044,
                    },
                }
            },
        )

        self.assertEqual(readiness["status"], "READY")
        self.assertNotIn("hourly_performance_gate", {row["category"] for row in readiness["blockers"]})
        self.assertTrue(readiness["hourly_performance_mitigation"]["applied"])
        self.assertEqual(readiness["hourly_performance_mitigation"]["candidate_hourly_status"], "PASS")
        self.assertTrue(readiness["hourly_performance_mitigation"]["candidate_hourly_matches"])

    def test_promotion_readiness_does_not_mitigate_stale_hourly_scoring(self):
        readiness = promotion_readiness(
            {
                "aggregate": {"delta_vs_market": -0.01},
                "blocked_validation": {"passed": True},
                "candidate_shadow_variants": {"variant_id": "candidate_v1"},
            },
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            hourly_performance={
                "scoring_liveness": {
                    "status": "BLOCK",
                    "artifact_name": "hourly_model_performance",
                    "last_scored_target_date": "2026-06-21",
                    "latest_settled_label_date": "2026-06-23",
                    "first_blocker": {
                        "gate": "model_scoring_liveness_stale",
                        "detail": "hourly_model_performance is stale",
                        "remediation_command": "python -m weather.reporting.hourly.hourly_model_performance",
                    },
                },
                "hourly_performance_gate": {"status": "PASS"},
            },
            candidate_hourly_performance={
                "variant_ids": ["candidate_v1"],
                "candidate_hourly_gate": {"status": "PASS"},
            },
        )

        self.assertEqual(readiness["status"], "OPEN")
        blocker = next(row for row in readiness["blockers"] if row["category"] == "hourly_performance_gate")
        self.assertEqual(blocker["severity"], "block")
        self.assertIn("hourly_model_performance is stale", blocker["detail"])
        self.assertFalse(readiness["hourly_performance_mitigation"]["applied"])
        self.assertTrue(readiness["hourly_performance_mitigation"]["current_scoring_liveness_blocked"])

    def test_promotion_readiness_blocks_on_ten_minute_performance_gate(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            ten_minute_performance={
                "ten_minute_performance_gate": {
                    "status": "BLOCK",
                    "first_blocker": {
                        "gate": "weak_slot_brier_regression",
                        "detail": "03:00 weak-slot model Brier trails market",
                    },
                }
            },
        )

        self.assertEqual(readiness["status"], "OPEN")
        blocker = next(row for row in readiness["blockers"] if row["category"] == "ten_minute_performance_gate")
        self.assertEqual(blocker["severity"], "block")
        self.assertIn("03:00 weak-slot model Brier trails market", blocker["detail"])
        self.assertFalse(readiness["ten_minute_performance_mitigation"]["applied"])

    def test_promotion_readiness_accepts_candidate_ten_minute_gate_mitigation(self):
        readiness = promotion_readiness(
            {
                "aggregate": {"delta_vs_market": -0.01},
                "blocked_validation": {"passed": True},
                "candidate_shadow_variants": {"variant_id": "candidate_v1"},
            },
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            ten_minute_performance={
                "ten_minute_performance_gate": {
                    "status": "BLOCK",
                    "first_blocker": {
                        "gate": "weak_slot_brier_regression",
                        "detail": "current 10-minute weak slots trail market",
                    },
                }
            },
            candidate_ten_minute_performance={
                "variant_ids": ["candidate_v1"],
                "candidate_ten_minute_gate": {
                    "status": "PASS",
                    "blocker_count": 0,
                    "weak_slot_overlap": {
                        "delta_vs_current": -0.0044,
                        "delta_vs_market": 0.0011,
                    },
                },
            },
        )

        self.assertEqual(readiness["status"], "READY")
        self.assertNotIn("ten_minute_performance_gate", {row["category"] for row in readiness["blockers"]})
        self.assertTrue(readiness["ten_minute_performance_mitigation"]["applied"])
        self.assertEqual(readiness["ten_minute_performance_mitigation"]["candidate_ten_minute_status"], "PASS")
        self.assertTrue(readiness["ten_minute_performance_mitigation"]["candidate_ten_minute_matches"])

    def test_promotion_readiness_does_not_mitigate_stale_ten_minute_scoring(self):
        readiness = promotion_readiness(
            {
                "aggregate": {"delta_vs_market": -0.01},
                "blocked_validation": {"passed": True},
                "candidate_shadow_variants": {"variant_id": "candidate_v1"},
            },
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            ten_minute_performance={
                "scoring_liveness": {
                    "status": "BLOCK",
                    "artifact_name": "ten_minute_model_performance",
                    "last_scored_target_date": "2026-06-21",
                    "latest_settled_label_date": "2026-06-23",
                    "first_blocker": {
                        "gate": "model_scoring_liveness_stale",
                        "detail": "ten_minute_model_performance is stale",
                        "remediation_command": "python -m weather.reporting.hourly.ten_minute_model_performance",
                    },
                },
                "ten_minute_performance_gate": {"status": "PASS"},
            },
            candidate_ten_minute_performance={
                "variant_ids": ["candidate_v1"],
                "candidate_ten_minute_gate": {"status": "PASS"},
            },
        )

        self.assertEqual(readiness["status"], "OPEN")
        blocker = next(row for row in readiness["blockers"] if row["category"] == "ten_minute_performance_gate")
        self.assertEqual(blocker["severity"], "block")
        self.assertIn("ten_minute_model_performance is stale", blocker["detail"])
        self.assertFalse(readiness["ten_minute_performance_mitigation"]["applied"])
        self.assertTrue(readiness["ten_minute_performance_mitigation"]["current_scoring_liveness_blocked"])

    def test_promotion_readiness_blocks_market_informed_candidate_as_core_readiness(self):
        readiness = promotion_readiness(
            {
                "aggregate": {"delta_vs_market": -0.01},
                "blocked_validation": {"passed": True},
                "candidate_shadow_variants": {
                    "variant_id": "clob_overlay",
                    "uses_market_features": True,
                    "variant_family": "market_informed_clob_overlay",
                },
            },
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
        )

        blockers = {row["category"]: row for row in readiness["blockers"]}
        self.assertEqual(readiness["status"], "OPEN")
        self.assertIn("market_informed_candidate", blockers)
        self.assertEqual(blockers["market_informed_candidate"]["severity"], "block")
        self.assertIn("cannot satisfy weather-only core promotion readiness", blockers["market_informed_candidate"]["detail"])

    def test_promotion_readiness_blocks_on_data_layer_p0_gates(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}, "blocked_validation": {"passed": True}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            source_family_inventory={
                "promotion_preflight": {
                    "status": "BLOCK",
                    "blocked_families": ["nws_grid"],
                }
            },
            fleet_observability={
                "path": "fleet.json",
                "status": "CRITICAL",
                "summary": {
                    "live_forward_slo_status": "BLOCK",
                },
            },
        )

        blockers = {row["category"]: row for row in readiness["blockers"]}
        self.assertEqual(readiness["status"], "OPEN")
        self.assertIn("source_family_preflight", blockers)
        self.assertIn("nws_grid", blockers["source_family_preflight"]["detail"])
        self.assertIn("live_forward_slo", blockers)

    def test_promotion_readiness_blocks_on_physical_family_ratchet(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}, "blocked_validation": {"passed": True}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            physical_feature_family_ratchet={
                "path": "physical_feature_family_ratchet.json",
                "status": "BLOCK",
                "summary": {"blocking_family_count": 2, "settlement_slice_row_count": 0},
                "rollup": {"evidence_blocked": ["forecast_baseline", "reanalysis_synoptic"]},
                "blocked_family_details": [
                    {
                        "family_id": "forecast_baseline",
                        "status": "ISOLATED_REPLAY_BLOCK",
                        "detail": "harmful_slice_count=1",
                    },
                    {
                        "family_id": "reanalysis_synoptic",
                        "status": "ISOLATED_REPLAY_BLOCK",
                        "detail": "missing required slice kinds: settlement_distance; harmful_slice_count=17",
                    },
                ],
                "first_blocker": {
                    "family_id": "forecast_baseline",
                    "status": "ISOLATED_REPLAY_BLOCK",
                    "detail": "missing settlement-sliced ablation rows",
                },
            },
        )

        blockers = {row["category"]: row for row in readiness["blockers"]}
        self.assertEqual(readiness["status"], "OPEN")
        self.assertIn("physical_feature_family_ratchet", blockers)
        self.assertIn("blocked families=2", blockers["physical_feature_family_ratchet"]["detail"])
        self.assertIn("forecast_baseline: harmful_slice_count=1", blockers["physical_feature_family_ratchet"]["detail"])
        self.assertIn("reanalysis_synoptic: missing required slice kinds: settlement_distance", blockers["physical_feature_family_ratchet"]["detail"])

    def test_physical_ratchet_reader_preserves_blocked_family_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "physical_feature_family_ratchet.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "physical_feature_family_ratchet_v0.1",
                        "status": "BLOCK",
                        "summary": {"blocking_family_count": 2},
                        "rollup": {"evidence_blocked": ["forecast_baseline", "reanalysis_synoptic"]},
                        "families": [
                            {
                                "family_id": "forecast_baseline",
                                "status": "ISOLATED_REPLAY_BLOCK",
                                "rollup_bucket": "evidence_blocked",
                                "blockers": ["harmful_slice_count=1"],
                                "settlement_slice_summary": {"harmful_slice_count": 1},
                            },
                            {
                                "family_id": "reanalysis_synoptic",
                                "status": "ISOLATED_REPLAY_BLOCK",
                                "rollup_bucket": "evidence_blocked",
                                "blockers": [
                                    "missing required slice kinds: settlement_distance",
                                    "harmful_slice_count=17",
                                ],
                                "settlement_slice_summary": {
                                    "harmful_slice_count": 17,
                                    "missing_required_slice_kinds": ["settlement_distance"],
                                },
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = _read_physical_feature_family_ratchet(path)

        self.assertEqual(payload["first_blocker"]["family_id"], "forecast_baseline")
        self.assertEqual(len(payload["blocked_family_details"]), 2)
        self.assertEqual(
            payload["blocked_family_details"][1]["detail"],
            "missing required slice kinds: settlement_distance; harmful_slice_count=17",
        )

    def test_evidence_freshness_blocks_location_countability(self):
        freshness = build_evidence_freshness_gate(
            settled_day_freshness={
                "path": "settled.json",
                "status": "FAIL",
                "target_date": "2026-06-20",
                "summary": {
                    "incomplete_market_count": 12,
                    "missing_replay_status_count": 12,
                },
                "repair_command": "repair settlements",
                "replay_status_repair_command": "repair replay status",
            },
            data_layer_audit={
                "path": "data_layer.json",
                "gate_summary": {"status": "PASS", "fail_count": 0, "warn_count": 0},
            },
            ingest_quality_gate={"path": "ingest.json", "status": "PASS"},
            fleet_observability={
                "path": "fleet.json",
                "status": "OK",
                "summary": {"live_forward_slo_status": "PASS", "critical_alerts": 0},
                "clob_books": {"status": "PASS", "blocked_markets": []},
            },
            daily_learning={
                "path": "daily_learning.json",
                "status": "OK",
                "summary": {"blocker_count": 0},
            },
            disk_headroom={
                "path": "data/backtest",
                "status": "PASS",
                "free_bytes": 2_000_000_000,
                "min_free_bytes": 1_000_000_000,
            },
        )
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}, "blocked_validation": {"passed": True}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            evidence_freshness=freshness,
        )

        blockers = {row["category"]: row for row in readiness["blockers"]}
        self.assertEqual(freshness["status"], "BLOCK")
        self.assertFalse(freshness["counts_for_location_validation"])
        self.assertIn("location_evidence_freshness", blockers)
        self.assertIn("missing_replay_status=12", blockers["location_evidence_freshness"]["detail"])

    def test_evidence_freshness_passes_when_all_countability_gates_are_green(self):
        freshness = build_evidence_freshness_gate(
            settled_day_freshness={
                "status": "PASS",
                "target_date": "2026-06-20",
                "summary": {
                    "incomplete_market_count": 0,
                    "missing_replay_status_count": 0,
                },
            },
            data_layer_audit={"gate_summary": {"status": "PASS", "fail_count": 0, "warn_count": 0}},
            ingest_quality_gate={"status": "PASS"},
            fleet_observability={
                "status": "OK",
                "summary": {"live_forward_slo_status": "PASS", "critical_alerts": 0},
                "clob_books": {"status": "PASS", "blocked_markets": []},
            },
            daily_learning={"status": "OK", "summary": {"blocker_count": 0}},
            disk_headroom={"status": "PASS", "free_bytes": 2_000_000_000, "min_free_bytes": 1_000_000_000},
        )
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}, "blocked_validation": {"passed": True}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            evidence_freshness=freshness,
        )

        self.assertEqual(freshness["status"], "PASS")
        self.assertTrue(freshness["counts_for_location_validation"])
        self.assertEqual(readiness["status"], "READY")
        self.assertNotIn("location_evidence_freshness", {row["category"] for row in readiness["blockers"]})

    def test_per_location_artifact_quarantine_blocks_stale_active_candidates(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}, "blocked_validation": {"passed": True}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            per_location_artifact_quarantine={
                "path": "per_location_artifact_quarantine.json",
                "status": "FAIL",
                "summary": {"active_candidate_violation_count": 1},
                "active_candidate_violations": [
                    {
                        "market_id": "seattle",
                        "artifact_kind": "hgb_model",
                        "path": "artifacts/models/hgb/feature_model_hgb_seattle.pkl",
                        "disposition": "active_candidate_blocked",
                    }
                ],
            },
        )

        blockers = {row["category"]: row for row in readiness["blockers"]}
        self.assertEqual(readiness["status"], "OPEN")
        self.assertIn("per_location_artifact_quarantine", blockers)
        self.assertIn("active violations=1", blockers["per_location_artifact_quarantine"]["detail"])

    def test_early_hour_blocker_passes_with_matching_fresh_candidate_evidence(self):
        blocker = build_early_hour_promotion_blocker(
            candidate=_early_hour_candidate(),
            hourly_performance={"hourly_performance_gate": {"status": "BLOCK"}},
            candidate_hourly_performance=_candidate_gate_report("candidate_hourly_gate"),
            ten_minute_performance={"ten_minute_performance_gate": {"status": "BLOCK"}},
            candidate_ten_minute_performance=_candidate_gate_report("candidate_ten_minute_gate"),
            fleet_observability=_clean_fleet(),
            now=datetime(2026, 6, 22, 13, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(blocker["status"], "PASS")
        self.assertTrue(blocker["promotion_allowed"])
        self.assertEqual(blocker["production_readiness"]["clean_active_day_countability_status"], "PASS")
        self.assertTrue(blocker["production_readiness"]["counts_toward_early_hour_evidence"])

    def test_early_hour_blocker_requires_clean_active_day_countability(self):
        fleet = _clean_fleet()
        fleet["clean_active_day_countability"] = {
            "status": "BLOCK",
            "counts_toward_clean_active_day": False,
            "counts_toward_early_hour_evidence": False,
            "first_blocker": {
                "name": "early_hour_coverage",
                "detail": "12/48 minimum early-hour snapshots",
            },
        }
        fleet["summary"]["clean_active_day_countability_status"] = "BLOCK"
        fleet["summary"]["clean_active_day_counts_toward_early_hour_evidence"] = False

        blocker = build_early_hour_promotion_blocker(
            candidate=_early_hour_candidate(),
            hourly_performance={"hourly_performance_gate": {"status": "PASS"}},
            candidate_hourly_performance=None,
            ten_minute_performance={"ten_minute_performance_gate": {"status": "PASS"}},
            candidate_ten_minute_performance=None,
            fleet_observability=fleet,
            now=datetime(2026, 6, 22, 13, 0, tzinfo=timezone.utc),
        )

        categories = {row["category"] for row in blocker["blockers"]}
        self.assertEqual(blocker["status"], "BLOCK")
        self.assertIn("clean_active_day_countability", categories)
        self.assertFalse(blocker["production_readiness"]["counts_toward_early_hour_evidence"])

    def test_early_hour_blocker_fails_closed_on_mismatched_variant(self):
        blocker = build_early_hour_promotion_blocker(
            candidate=_early_hour_candidate(),
            hourly_performance={"hourly_performance_gate": {"status": "BLOCK"}},
            candidate_hourly_performance=_candidate_gate_report("candidate_hourly_gate", variant_id="other"),
            ten_minute_performance={"ten_minute_performance_gate": {"status": "PASS"}},
            candidate_ten_minute_performance=None,
            fleet_observability=_clean_fleet(),
            now=datetime(2026, 6, 22, 13, 0, tzinfo=timezone.utc),
        )

        categories = {row["category"] for row in blocker["blockers"]}
        self.assertEqual(blocker["status"], "BLOCK")
        self.assertIn("candidate_hourly_mitigation", categories)
        self.assertFalse(blocker["candidate_gates"]["hourly"]["variant_match"])

    def test_early_hour_blocker_fails_closed_on_stale_candidate_report(self):
        blocker = build_early_hour_promotion_blocker(
            candidate=_early_hour_candidate(),
            hourly_performance={"hourly_performance_gate": {"status": "BLOCK"}},
            candidate_hourly_performance=_candidate_gate_report(
                "candidate_hourly_gate",
                generated_at="2026-06-18T00:00:00+00:00",
            ),
            ten_minute_performance={"ten_minute_performance_gate": {"status": "PASS"}},
            candidate_ten_minute_performance=None,
            fleet_observability=_clean_fleet(),
            now=datetime(2026, 6, 22, 13, 0, tzinfo=timezone.utc),
            max_candidate_report_age_hours=72,
        )

        self.assertEqual(blocker["status"], "BLOCK")
        self.assertEqual(blocker["candidate_gates"]["hourly"]["freshness"]["status"], "STALE")

    def test_early_hour_blocker_fails_closed_when_ten_minute_mitigation_missing(self):
        blocker = build_early_hour_promotion_blocker(
            candidate=_early_hour_candidate(),
            hourly_performance={"hourly_performance_gate": {"status": "PASS"}},
            candidate_hourly_performance=None,
            ten_minute_performance={"ten_minute_performance_gate": {"status": "BLOCK"}},
            candidate_ten_minute_performance=None,
            fleet_observability=_clean_fleet(),
            now=datetime(2026, 6, 22, 13, 0, tzinfo=timezone.utc),
        )

        categories = {row["category"] for row in blocker["blockers"]}
        self.assertIn("candidate_ten_minute_mitigation", categories)
        self.assertEqual(blocker["candidate_gates"]["ten_minute"]["gate_status"], "MISSING")

    def test_early_hour_blocker_rejects_surrogate_only_replay(self):
        candidate = _early_hour_candidate()
        candidate["candidate_shadow_variants"] = {"variant_id": "candidate_v1"}

        blocker = build_early_hour_promotion_blocker(
            candidate=candidate,
            hourly_performance={"hourly_performance_gate": {"status": "PASS"}},
            candidate_hourly_performance=None,
            ten_minute_performance={"ten_minute_performance_gate": {"status": "PASS"}},
            candidate_ten_minute_performance=None,
            fleet_observability=_clean_fleet(),
            now=datetime(2026, 6, 22, 13, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(blocker["status"], "BLOCK")
        self.assertIn("active_replay_export_contract", {row["category"] for row in blocker["blockers"]})

    def test_promotion_readiness_surfaces_early_hour_blocker(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}, "blocked_validation": {"passed": True}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            early_hour_promotion_blocker={
                "status": "BLOCK",
                "blockers": [{"detail": "candidate hourly gate must PASS"}],
            },
        )

        blockers = {row["category"]: row for row in readiness["blockers"]}
        self.assertIn("early_hour_promotion_blocker", blockers)
        self.assertIn("candidate hourly gate must PASS", blockers["early_hour_promotion_blocker"]["detail"])

    def test_source_missingness_gate_blocks_bottom_market_slices_and_decodes_hash(self):
        fields = [
            "market_id",
            "probability",
            "current_probability",
            "market_yes",
            "outcome",
            "source_freshness_state",
            "forecast_source_count_bucket",
            "feature_missingness_hash",
            "candidate_cutoff_hour",
            "candidate_cutoff_regime",
            "settlement_distance_bucket",
            "forecast_source_count",
            "forecast_disagreement",
            "forecast_gap",
            "forecast_disagreement_bucket",
            "forecast_bucket_pressure",
            "clob_feature_available",
            "clob_midpoint",
            "clob_spread",
            "clob_liquidity_score",
            "casebook_taxonomy",
        ]
        rows = [
            {
                "market_id": "miami",
                "probability": "0.80",
                "current_probability": "0.70",
                "market_yes": "0.10",
                "outcome": "0",
                "source_freshness_state": "all_fresh",
                "forecast_source_count_bucket": "two_sources",
                "feature_missingness_hash": "shared_hash",
                "candidate_cutoff_hour": "9",
                "candidate_cutoff_regime": "midday",
                "settlement_distance_bucket": "0",
                "forecast_source_count": "2",
                "forecast_disagreement": "0.04",
                "forecast_gap": "0.02",
                "forecast_disagreement_bucket": "low",
                "forecast_bucket_pressure": "warm_side",
                "clob_feature_available": "1",
                "clob_midpoint": "",
                "clob_spread": "0.04",
                "clob_liquidity_score": "0.8",
                "casebook_taxonomy": "",
            },
            {
                "market_id": "atlanta",
                "probability": "0.10",
                "current_probability": "0.20",
                "market_yes": "0.20",
                "outcome": "0",
                "source_freshness_state": "all_fresh",
                "forecast_source_count_bucket": "two_sources",
                "feature_missingness_hash": "shared_hash",
                "candidate_cutoff_hour": "9",
                "candidate_cutoff_regime": "midday",
                "settlement_distance_bucket": "0",
                "forecast_source_count": "2",
                "forecast_disagreement": "0.04",
                "forecast_gap": "0.02",
                "forecast_disagreement_bucket": "low",
                "forecast_bucket_pressure": "warm_side",
                "clob_feature_available": "1",
                "clob_midpoint": "",
                "clob_spread": "0.04",
                "clob_liquidity_score": "0.8",
                "casebook_taxonomy": "",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shadow.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            gate = build_source_missingness_location_gate(
                {"candidate_shadow_variants": {"path": str(path)}},
                bottom_markets=("miami",),
                market_tolerance=0.003,
                min_rows=1,
            )

        categories = {row["category"] for row in gate["blockers"]}
        missingness_by_market = {
            row["market_id"]: row
            for row in gate["market_feature_missingness"]
            if row.get("feature_missingness_hash") == "shared_hash"
        }
        decoded = {
            row["feature_missingness_hash"]: row
            for row in gate["missingness_hash_decodes"]
        }

        self.assertEqual(gate["schema_version"], "source_missingness_location_gate_v0.1")
        self.assertEqual(gate["status"], "BLOCK")
        self.assertIn("bottom_market_all_fresh_market_gap", categories)
        self.assertIn("bottom_market_two_source_market_gap", categories)
        self.assertIn("bottom_market_high_impact_missingness", categories)
        self.assertEqual(missingness_by_market["miami"]["status"], "BLOCK")
        self.assertEqual(missingness_by_market["atlanta"]["status"], "PASS")
        self.assertIn("casebook_taxonomy", decoded["shared_hash"]["missing_features"])
        self.assertIn("clob_midpoint", decoded["shared_hash"]["missing_features"])

    def test_promotion_readiness_surfaces_source_missingness_location_gate(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": -0.01}, "blocked_validation": {"passed": True}},
            None,
            {"family_unit": "F", "shadow_markets": [], "blocked_markets": [], "markets": []},
            source_missingness_location_gate={
                "status": "BLOCK",
                "first_blocker": {"detail": "miami all-fresh candidate trails market"},
            },
        )

        blockers = {row["category"]: row for row in readiness["blockers"]}
        self.assertIn("source_missingness_location_gate", blockers)
        self.assertIn(
            "miami all-fresh candidate trails market",
            blockers["source_missingness_location_gate"]["detail"],
        )

    def test_promotion_readiness_surfaces_extra_location_gate(self):
        readiness = promotion_readiness(
            {"aggregate": {}},
            None,
            {"markets": []},
            extra_location_transfer={
                "promotion_gate": {
                    "status": "BLOCK",
                    "serving_promotion_allowed": False,
                    "reasons": ["brier CI is clearly positive versus target-only"],
                }
            },
        )

        categories = {row["category"] for row in readiness["blockers"]}
        self.assertIn("no_market_extra_location_shadow_lane", categories)
        self.assertEqual(readiness["status"], "OPEN")

    def test_promotion_readiness_uses_all_market_wording(self):
        readiness = promotion_readiness(
            {"aggregate": {}},
            None,
            {
                "family_unit": "all",
                "markets": [
                    {"market_id": "nyc", "action": "KEEP_SHADOW", "reason": "shadow"},
                    {"market_id": "toronto", "action": "BLOCK_CANDIDATE", "reason": "blocked"},
                ],
            },
        )
        details = [row["detail"] for row in readiness["blockers"]]

        self.assertIn("1 market(s) remain shadow: nyc", details)
        self.assertIn("1 market(s) are blocked: toronto", details)
        self.assertFalse(any("F market(s)" in detail for detail in details))

    def test_candidate_summary_preserves_gap_driver_slices(self):
        summary = _candidate_summary(
            {
                "aggregate": {},
                "by_hour": [{"group": 7, "n": 10, "delta_vs_market": 0.02}],
                "by_bin_type": [{"group": "eq", "n": 20, "delta_vs_market": 0.01}],
                "by_settlement_distance": [{"group": "0", "n": 5, "delta_vs_market": 0.20}],
                "market_rows": [
                    {
                        "market_id": "miami",
                        "rows": 30,
                        "comparison": {
                            "candidate_brier": 0.07,
                            "market_brier": 0.04,
                            "delta_vs_current": -0.01,
                            "delta_vs_market": 0.03,
                        },
                    },
                ],
                "microstructure": {
                    "gated": {
                        "by_taxonomy": [{"group": "market_lead", "n": 3, "delta_vs_market": 0.30}],
                    },
                },
            },
            "candidate.json",
            "candidate.md",
        )

        slices = summary["slices"]
        self.assertEqual(slices["by_market"][0]["group"], "miami")
        self.assertEqual(slices["by_market"][0]["n"], 30)
        self.assertEqual(slices["by_cutoff_hour"][0]["group"], 7)
        self.assertEqual(slices["by_band_type"][0]["group"], "eq")
        self.assertEqual(slices["by_settlement_distance"][0]["group"], "0")
        self.assertEqual(slices["by_clob_taxonomy"][0]["group"], "market_lead")

    def test_candidate_gap_driver_rows_rank_by_excess_brier(self):
        rows = _candidate_gap_driver_rows({
            "slices": {
                "by_market": [
                    {
                        "group": "miami",
                        "n": 25,
                        "candidate_brier": 0.20,
                        "market_brier": 0.10,
                        "delta_vs_market": 0.10,
                    }
                ],
                "by_cutoff_hour": [
                    {
                        "group": 7,
                        "n": 100,
                        "candidate_brier": 0.10,
                        "market_brier": 0.05,
                        "delta_vs_current": -0.01,
                        "delta_vs_market": 0.05,
                    }
                ],
                "by_band_type": [
                    {
                        "group": "eq",
                        "n": 10,
                        "candidate_brier": 0.50,
                        "market_brier": 0.10,
                        "delta_vs_market": 0.40,
                    }
                ],
            }
        })

        self.assertEqual(rows[0]["slice"], "cutoff_hour")
        self.assertEqual(rows[0]["excess_brier_rows"], 5.0)
        self.assertEqual(rows[2]["slice"], "market")

    def test_gap_owner_table_assigns_experiments_and_claim_lanes(self):
        drivers = [
            {
                "slice": "settlement_distance",
                "group": "0",
                "rows": 100,
                "delta_vs_market": 0.05,
                "excess_brier_rows": 5.0,
            },
            {
                "slice": "clob_taxonomy",
                "group": "market_lead",
                "rows": 20,
                "delta_vs_market": 0.10,
                "excess_brier_rows": 2.0,
            },
        ]
        decisions = {
            "markets": [
                {"market_id": "nyc", "metrics": {"delta_vs_market": 0.02}},
                {"market_id": "seattle", "metrics": {"delta_vs_market": 0.01}},
            ]
        }

        rows = build_gap_owner_table(drivers, decisions)

        self.assertEqual(rows[0]["owner"], "settlement-distance winner catch-up")
        self.assertIn("settlement_distance_0", rows[0]["experiment_artifact"])
        self.assertTrue(rows[0]["counts_toward_core_skill_claim"])
        self.assertEqual(rows[0]["affected_markets"], ["nyc", "seattle"])
        self.assertEqual(rows[1]["claim_lane"], "market_informed_quote_risk")
        self.assertFalse(rows[1]["counts_toward_core_skill_claim"])

    def test_market_skill_claims_separate_core_and_clob_lanes(self):
        claims = model_skill_claims(
            {
                "aggregate": {"delta_vs_market": 0.01},
                "blocked_validation": {"passed": True},
            },
            [{"claim_lane": "market_informed_quote_risk"}],
        )

        self.assertFalse(claims["weather_only_core_model"]["broad_market_skill_claim_allowed"])
        self.assertFalse(claims["market_informed_quote_risk"]["counts_toward_core_skill_claim"])
        self.assertTrue(claims["market_informed_quote_risk"]["may_support_quote_gating"])

    def test_market_skill_diagnostics_targets_non_promoted_markets(self):
        rows = market_skill_diagnostics(
            {
                "slices": {
                    "by_market": [
                        {"group": "nyc", "candidate_brier": 0.08, "market_brier": 0.06, "delta_vs_market": 0.02},
                        {"group": "dallas", "candidate_brier": 0.06, "market_brier": 0.07, "delta_vs_market": -0.01},
                    ]
                }
            },
            {
                "markets": [
                    {
                        "market_id": "nyc",
                        "action": "BLOCK_CANDIDATE",
                        "reason": "not proven better than market",
                        "metrics": {"candidate_brier": 0.08, "market_brier": 0.06, "delta_vs_market": 0.02},
                    },
                    {
                        "market_id": "dallas",
                        "action": "KEEP_SHADOW",
                        "reason": "not proven better than current replay",
                        "metrics": {
                            "candidate_brier": 0.06,
                            "current_brier": 0.06,
                            "market_brier": 0.07,
                            "delta_vs_current": 0.0,
                            "delta_vs_market": -0.01,
                        },
                    },
                    {
                        "market_id": "atlanta",
                        "action": "PROMOTE_CANDIDATE",
                        "reason": "beats current replay and clears market/trust gates",
                        "metrics": {"candidate_brier": 0.04, "market_brier": 0.05, "delta_vs_market": -0.01},
                    },
                ]
            },
        )

        by_market = {row["market_id"]: row for row in rows}
        self.assertEqual([row["market_id"] for row in rows], ["nyc", "dallas"])
        self.assertEqual(by_market["nyc"]["action"], "BLOCK_CANDIDATE")
        self.assertIn("nyc_residual", by_market["nyc"]["experiment_artifact"])
        self.assertEqual(by_market["nyc"]["affected_markets"], ["nyc"])
        self.assertEqual(by_market["nyc"]["owner"], "nyc residual calibration")
        self.assertEqual(by_market["dallas"]["delta_vs_current"], 0.0)
        self.assertEqual(by_market["dallas"]["next_experiment"], "dallas_residual_calibration_daily_first")

    def test_write_gap_experiment_artifacts_creates_open_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [{
                "owner": "exact-band calibration",
                "roadmap_owner": "Item 48",
                "slice": "band_type",
                "group": "eq",
                "excess_brier_rows": 2.5,
                "affected_markets": ["nyc"],
                "claim_lane": "weather_only_core_model",
                "counts_toward_core_skill_claim": True,
                "next_experiment": "exact_band_calibration_daily_first",
                "experiment_artifact": str(Path(tmp) / "exact_band.json"),
                "clearance_rule": "aggregate delta_vs_market must be <= 0",
            }]

            written = write_gap_experiment_artifacts(rows)
            payload = Path(written[0]).read_text(encoding="utf-8")

        self.assertTrue(rows[0]["experiment_artifact_exists"])
        self.assertIn("market_skill_gap_experiment_v0.1", payload)
        self.assertIn("paired_daily_first", payload)

    def test_gap_experiment_artifact_blocks_before_create_when_headroom_is_low(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "exact_band.json"
            rows = [{
                "owner": "exact-band calibration",
                "roadmap_owner": "Item 48",
                "slice": "band_type",
                "group": "eq",
                "excess_brier_rows": 2.5,
                "affected_markets": ["nyc"],
                "claim_lane": "weather_only_core_model",
                "counts_toward_core_skill_claim": True,
                "next_experiment": "exact_band_calibration_daily_first",
                "experiment_artifact": str(artifact),
                "clearance_rule": "aggregate delta_vs_market must be <= 0",
            }]

            with self.assertRaises(OSError):
                write_gap_experiment_artifacts(rows, min_free_bytes=10**18)

            self.assertFalse(artifact.exists())
            self.assertNotIn("experiment_artifact_exists", rows[0])

    def test_summary_outputs_block_before_create_when_headroom_is_low(self):
        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "family_unit": "F",
            "corpus": {},
            "candidate": {"aggregate": {}, "slices": {}},
            "readiness": {"status": "OPEN", "blockers": []},
            "decisions": {"promote_markets": [], "shadow_markets": [], "blocked_markets": [], "markets": []},
            "serving_gauntlet": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "summary.json"
            report_path = Path(tmp) / "report.md"

            with self.assertRaises(OSError):
                _write_json(json_path, payload, min_free_bytes=10**18)
            with self.assertRaises(OSError):
                write_report(report_path, payload, min_free_bytes=10**18)

            self.assertFalse(json_path.exists())
            self.assertFalse(report_path.exists())

    def test_incomplete_manifest_is_written_without_reserve_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "incomplete.json"
            args = SimpleNamespace(
                incomplete_manifest=path,
                family_unit="F",
                out=Path(tmp) / "summary.json",
                report=Path(tmp) / "summary.md",
                corpus_out=Path(tmp) / "corpus.json",
                trust_out=Path(tmp) / "trust.json",
                candidate_json=Path(tmp) / "candidate.json",
                candidate_report=Path(tmp) / "candidate.md",
                min_artifact_free_bytes=10**18,
            )

            written = _write_incomplete_manifest(args, OSError("disk reserve failed"))
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(written, path)
        self.assertEqual(payload["status"], "INCOMPLETE")
        self.assertEqual(payload["error_type"], "OSError")
        self.assertEqual(payload["min_artifact_free_bytes"], 10**18)

    def test_started_and_complete_manifests_track_run_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "incomplete.json"
            args = SimpleNamespace(
                incomplete_manifest=path,
                family_unit="F",
                out=Path(tmp) / "summary.json",
                report=Path(tmp) / "summary.md",
                corpus_out=Path(tmp) / "corpus.json",
                trust_out=Path(tmp) / "trust.json",
                candidate_json=Path(tmp) / "candidate.json",
                candidate_report=Path(tmp) / "candidate.md",
                min_artifact_free_bytes=10**18,
            )
            payload = {
                "readiness": {"status": "OPEN"},
                "decisions": {
                    "promote_markets": ["atlanta"],
                    "shadow_markets": ["dallas"],
                    "blocked_markets": ["nyc"],
                },
            }

            _write_started_manifest(args, long_job_guard_info={"job": "promotion_refresh"})
            started = json.loads(path.read_text(encoding="utf-8"))
            _write_complete_manifest(
                args,
                payload,
                Path(tmp) / "summary.json",
                Path(tmp) / "summary.md",
                long_job_guard_info={"job": "promotion_refresh"},
            )
            complete = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(started["status"], "STARTED")
        self.assertEqual(complete["status"], "COMPLETE")
        self.assertEqual(complete["summary"]["readiness_status"], "OPEN")
        self.assertEqual(complete["summary"]["promote_count"], 1)
        self.assertEqual(complete["summary"]["shadow_count"], 1)
        self.assertEqual(complete["summary"]["blocked_count"], 1)

    def test_load_precomputed_candidate_report_requires_matching_corpus_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.json"
            path.write_text(
                json.dumps({"corpus": {"corpus_hash": "abc"}, "market_rows": []}),
                encoding="utf-8",
            )

            loaded = load_precomputed_candidate_report(path, {"corpus_hash": "abc"})
            with self.assertRaisesRegex(ValueError, "corpus hash mismatch"):
                load_precomputed_candidate_report(path, {"corpus_hash": "def"})

        self.assertEqual(loaded["corpus"]["corpus_hash"], "abc")

    def test_candidate_source_freshness_rows_include_failed_and_stale_groups(self):
        rows = _candidate_source_freshness_rows({
            "slices": {
                "by_source_freshness": [
                    {"group": "all_fresh", "n": 100, "candidate_brier": 0.08, "market_brier": 0.04, "delta_vs_market": 0.04},
                    {"group": "failed:wu_history", "n": 20, "candidate_brier": 0.30, "market_brier": 0.10, "delta_vs_market": 0.20},
                    {"group": "stale:metar", "n": 10, "candidate_brier": 0.05, "market_brier": 0.07, "delta_vs_market": -0.02},
                ],
            }
        })

        self.assertEqual(rows[0]["group"], "all_fresh")
        self.assertEqual(rows[1]["group"], "failed:wu_history")
        self.assertEqual(rows[2]["group"], "stale:metar")

    def test_write_report_emits_source_freshness_slice_when_available(self):
        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "family_unit": "F",
            "corpus": {},
            "candidate": {
                "verdict": "PASS_WITH_SHADOWS",
                "candidate_market_verdict": "PASS_WITH_SHADOWS",
                "cutover_decision": "PER_MARKET_ONLY",
                "aggregate": {},
                "slices": {
                    "by_source_freshness": [
                        {
                            "group": "failed:wu_history",
                            "n": 20,
                            "candidate_brier": 0.30,
                            "market_brier": 0.10,
                            "delta_vs_current": -0.01,
                            "delta_vs_market": 0.20,
                        }
                    ],
                },
            },
            "readiness": {
                "status": "OPEN",
                "blockers": [],
                "shadow_market_details": [
                    {
                        "market_id": "austin",
                        "action": "KEEP_SHADOW",
                        "candidate_brier": 0.04,
                        "current_brier": 0.05,
                        "market_brier": 0.03,
                        "delta_vs_current": -0.01,
                        "delta_vs_market": 0.01,
                        "reason": "not proven better than market on pinned rows",
                    }
                ],
            },
            "decisions": {"promote_markets": [], "shadow_markets": [], "blocked_markets": [], "markets": []},
            "serving_gauntlet": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(Path(tmp) / "report.md", payload)
            text = path.read_text(encoding="utf-8")

        self.assertIn("### Source Freshness Slice", text)
        self.assertIn("### Model-Skill Claim Lanes", text)
        self.assertIn("### Gap Owner Experiments", text)
        self.assertIn("source_freshness_repair_daily_first", text)
        self.assertIn("### Shadow/Block Explanation Detail", text)
        self.assertIn("not proven better than market on pinned rows", text)
        self.assertIn("failed:wu_history", text)
        self.assertNotIn("not available in the candidate replay rows yet", text)

    def test_write_report_uses_all_market_title(self):
        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "family_unit": "all",
            "corpus": {},
            "candidate": {"aggregate": {}, "slices": {}},
            "readiness": {"status": "OPEN", "blockers": []},
            "decisions": {"promote_markets": [], "shadow_markets": [], "blocked_markets": [], "markets": []},
            "serving_gauntlet": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(Path(tmp) / "report.md", payload)
            text = path.read_text(encoding="utf-8")

        self.assertIn("# All-Market Promotion Refresh", text)
        self.assertNotIn("# F-Family Promotion Refresh", text)

    def test_write_report_emits_operational_promotion_gates(self):
        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "family_unit": "F",
            "corpus": {},
            "candidate": {"aggregate": {}, "slices": {}},
            "readiness": {
                "status": "OPEN",
                "blockers": [],
                "hourly_performance_mitigation": {"applied": True},
                "ten_minute_performance_mitigation": {"applied": True},
            },
            "decisions": {"promote_markets": [], "shadow_markets": [], "blocked_markets": [], "markets": []},
            "promotion_allowlist": {
                "schema_version": "promotion_allowlist_v0.1",
                "path": "f_family_promotion_allowlist.json",
                "candidate_id": "candidate_v1",
                "generated_at_utc": "2026-06-15T00:00:00+00:00",
                "policy": {"permission_gate": "candidate_permission_allowed is true only for PROMOTE_CANDIDATE markets"},
                "markets": [
                    {
                        "market_id": "miami",
                        "action": "BLOCK_CANDIDATE",
                        "serving_behavior": "current_or_shadow",
                        "permission_behavior": "current_or_harvest_only",
                        "candidate_brier": 0.0548,
                        "current_brier": 0.0600,
                        "market_brier": 0.0400,
                        "delta_vs_current": -0.0052,
                        "delta_vs_market": 0.0148,
                        "blocker_reason": "candidate trails market by +0.0148 > 0.0030",
                    }
                ],
            },
            "source_missingness_location_gate": {
                "schema_version": "source_missingness_location_gate_v0.1",
                "status": "BLOCK",
                "candidate_shadow_variant_path": "item82_miami_fallback_shadow_variants.csv",
                "market_tolerance": 0.003,
                "min_rows": 30,
                "bottom_markets": ["miami", "nyc", "seattle"],
                "summary": {
                    "row_count": 200,
                    "market_source_freshness_slice_count": 4,
                    "market_forecast_source_count_slice_count": 4,
                    "market_feature_missingness_slice_count": 4,
                    "decoded_missingness_hash_count": 2,
                    "blocker_count": 1,
                },
                "first_blocker": {
                    "category": "bottom_market_all_fresh_market_gap",
                    "market_id": "miami",
                    "detail": "miami all-fresh candidate trails market by +0.0148 > 0.0030",
                },
                "blockers": [
                    {
                        "category": "bottom_market_all_fresh_market_gap",
                        "market_id": "miami",
                        "detail": "miami all-fresh candidate trails market by +0.0148 > 0.0030",
                    }
                ],
                "market_source_freshness": [
                    {
                        "market_id": "miami",
                        "source_freshness_state": "all_fresh",
                        "status": "BLOCK",
                        "n": 80,
                        "candidate_brier": 0.0548,
                        "market_brier": 0.0400,
                        "delta_vs_market": 0.0148,
                    }
                ],
                "market_forecast_source_count": [
                    {
                        "market_id": "miami",
                        "forecast_source_count_bucket": "two_sources",
                        "status": "BLOCK",
                        "n": 80,
                        "candidate_brier": 0.0548,
                        "market_brier": 0.0400,
                        "delta_vs_market": 0.0148,
                    }
                ],
                "market_feature_missingness": [
                    {
                        "market_id": "miami",
                        "feature_missingness_hash": "shared_hash",
                        "status": "BLOCK",
                        "n": 80,
                        "delta_vs_market": 0.0148,
                        "missing_features": ["casebook_taxonomy", "clob_midpoint"],
                    }
                ],
                "missingness_hash_decodes": [
                    {
                        "feature_missingness_hash": "shared_hash",
                        "missing_features": ["casebook_taxonomy", "clob_midpoint"],
                    }
                ],
            },
            "serving_gauntlet": None,
            "hourly_performance": {
                "hourly_performance_gate": {
                    "status": "BLOCK",
                    "first_blocker": {"detail": "current early-hour Brier trails market"},
                },
            },
            "candidate_hourly_performance": {
                "candidate_hourly_gate": {
                    "status": "PASS",
                    "blocker_count": 0,
                },
            },
            "ten_minute_performance": {
                "ten_minute_performance_gate": {
                    "status": "BLOCK",
                    "first_blocker": {"detail": "current weak-slot Brier trails market"},
                },
            },
            "candidate_ten_minute_performance": {
                "candidate_ten_minute_gate": {
                    "status": "PASS",
                    "blocker_count": 0,
                },
            },
            "source_family_inventory": {
                "path": "source_family_inventory.json",
                "promotion_preflight": {"status": "PASS", "blocked_families": []},
            },
            "physical_feature_family_ratchet": {
                "path": "physical_feature_family_ratchet.json",
                "status": "BLOCK",
                "summary": {"blocking_family_count": 2, "settlement_slice_row_count": 0},
                "first_blocker": {"family_id": "forecast_baseline", "status": "ISOLATED_REPLAY_BLOCK"},
            },
            "fleet_observability": {
                "path": "fleet_observability.json",
                "status": "CRITICAL",
                "summary": {
                    "live_forward_slo_status": "BLOCK",
                },
            },
            "evidence_freshness": {
                "status": "BLOCK",
                "counts_for_location_validation": False,
                "gates": [
                    {
                        "name": "settled_day_freshness",
                        "status": "FAIL",
                        "detail": "missing_replay_status=12",
                    }
                ],
            },
            "per_location_artifact_quarantine": {
                "path": "per_location_artifact_quarantine.json",
                "status": "PASS",
                "summary": {
                    "historical_only_count": 22,
                    "active_candidate_violation_count": 0,
                },
            },
            "early_hour_promotion_blocker": {
                "status": "BLOCK",
                "promotion_allowed": False,
                "blocker_count": 1,
                "current_gates": {
                    "hourly_status": "BLOCK",
                    "ten_minute_status": "BLOCK",
                },
                "broad_replay": {"within_market_tolerance": False},
                "production_readiness": {
                    "live_forward_slo_status": "BLOCK",
                    "current_code_soak_status": "BLOCK",
                    "clean_active_day_countability_status": "BLOCK",
                    "counts_toward_early_hour_evidence": False,
                    "early_hour_coverage_status": "BLOCK",
                    "early_hour_coverage_countable_markets": 0,
                    "early_hour_coverage_total_snapshots": 12,
                },
                "blockers": [
                    {
                        "category": "candidate_hourly_mitigation",
                        "severity": "block",
                        "detail": "candidate hourly gate must PASS with matching lineage",
                    }
                ],
            },
            "settled_day_freshness": {"path": "settled_day_freshness.json"},
            "data_layer_audit": {"path": "data_layer_audit.json"},
            "ingest_quality_gate": {"path": "ingest_quality_gate.json"},
            "daily_learning": {"path": "daily_learning.json"},
            "disk_headroom": {"path": "data/backtest", "status": "PASS"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(Path(tmp) / "report.md", payload)
            text = path.read_text(encoding="utf-8")

        self.assertIn("## Operational Promotion Gates", text)
        self.assertIn("Source family preflight", text)
        self.assertIn("Physical family ratchet", text)
        self.assertIn("Hourly gate mitigation", text)
        self.assertIn("10-minute gate mitigation", text)
        self.assertIn("APPLIED", text)
        self.assertIn("candidate hourly gate passed and variant id matched", text)
        self.assertIn("candidate 10-minute gate passed and variant id matched", text)
        self.assertIn("fleet_observability.json", text)
        self.assertIn("Evidence freshness: settled_day_freshness", text)
        self.assertIn("Per-location artifact quarantine", text)
        self.assertIn("Early-hour promotion blocker", text)
        self.assertIn("Clean active-day countability", text)
        self.assertIn("Counts toward early-hour evidence", text)
        self.assertIn("Source/missingness location gate", text)
        self.assertIn("## Early-Hour Promotion Blocker", text)
        self.assertIn("## F-Family Promotion Allowlist", text)
        self.assertIn("## Market Source/Missingness Location Gate", text)
        self.assertIn("Bottom-Market Source Freshness Slices", text)
        self.assertIn("Bottom-Market Forecast Source Count Slices", text)
        self.assertIn("Bottom-Market Feature Missingness Slices", text)
        self.assertIn("casebook_taxonomy, clob_midpoint", text)
        self.assertIn("f_family_promotion_allowlist.json", text)
        self.assertIn("physical_feature_family_ratchet.json", text)
        self.assertIn("candidate trails market by +0.0148", text)
        self.assertIn("candidate hourly gate must PASS with matching lineage", text)
        self.assertIn("settled_day_freshness.json", text)
        self.assertIn("data_layer_audit.json", text)
        self.assertIn("ingest_quality_gate.json", text)
        self.assertIn("daily_learning.json", text)
        self.assertIn("per_location_artifact_quarantine.json", text)

    def test_write_report_emits_serving_blocking_source_freshness(self):
        serving = {
            "verdict": "PARTIAL_PASS",
            "market_rows": [
                {
                    "market_id": "miami",
                    "verdict": "BLOCK",
                    "rows": 11,
                    "comparison": {"code_effect": 0.01},
                    "reason": "code regression",
                }
            ],
            "decomposition": {
                "blocking_markets": {
                    "miami": {
                        "by_source_freshness": [
                            {
                                "group": "failed:wu_history",
                                "n": 11,
                                "replayed_brier": 0.30,
                                "recorded_brier": 0.10,
                                "market_brier": 0.20,
                                "code_effect": 0.20,
                            }
                        ]
                    }
                }
            },
        }
        rows = _serving_blocking_source_freshness_rows(serving)
        self.assertEqual(rows[0][0], "miami")
        self.assertEqual(rows[0][1], "failed:wu_history")

        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "family_unit": "F",
            "corpus": {},
            "candidate": {"aggregate": {}, "slices": {}},
            "readiness": {"status": "OPEN", "blockers": []},
            "decisions": {"promote_markets": [], "shadow_markets": [], "blocked_markets": [], "markets": []},
            "serving_gauntlet": serving,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(Path(tmp) / "report.md", payload)
            text = path.read_text(encoding="utf-8")

        self.assertIn("### Serving Blocking Source Freshness", text)
        self.assertIn("failed:wu_history", text)

    def test_gauntlet_carry_forward_rules(self):
        # 2026-07-11: the gauntlet re-replayed the full corpus (~3.4h) daily
        # even though its inputs only change on retrain/cutover. Carry a
        # recent PASS for an unchanged artifact; never carry FAIL, stale,
        # hash-mismatched, or force-refreshed runs.
        from weather.reporting.promotion.orchestration import (
            _carry_forward_gauntlet,
            _write_gauntlet_manifest,
        )

        report = {
            "verdict": "PASS",
            "corpus_ok": True,
            "fidelity_ok": True,
            "baseline_ok": True,
            "market_rows": [{"market_id": "nyc"}],
            "decomposition": {"total": 1},
            "forecast_tracker": {},
            "results": {"all_rows": ["should", "not", "persist"]},
        }
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(
                serving_gauntlet_report=str(Path(tmp) / "gauntlet.md"),
                heavy_analysis_max_age_days=7.0,
                force_heavy_analysis=False,
            )
            manifest_path = _write_gauntlet_manifest(args, "hash-a", report)
            stored = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            self.assertNotIn("results", stored["report"])

            carried = _carry_forward_gauntlet(args, "hash-a")
            self.assertTrue(carried["carried_forward"])
            self.assertEqual(carried["verdict"], "PASS")
            self.assertEqual(carried["market_rows"], [{"market_id": "nyc"}])

            self.assertIsNone(_carry_forward_gauntlet(args, "hash-b"))
            args.force_heavy_analysis = True
            self.assertIsNone(_carry_forward_gauntlet(args, "hash-a"))
            args.force_heavy_analysis = False
            args.heavy_analysis_max_age_days = 0.0
            self.assertIsNone(_carry_forward_gauntlet(args, "hash-a"))

            args.heavy_analysis_max_age_days = 7.0
            shadows = dict(report, verdict="PASS_WITH_SHADOWS")
            _write_gauntlet_manifest(args, "hash-a", shadows)
            carried_shadows = _carry_forward_gauntlet(args, "hash-a")
            self.assertEqual(carried_shadows["verdict"], "PASS_WITH_SHADOWS")

            failed = dict(report, verdict="FAIL")
            _write_gauntlet_manifest(args, "hash-a", failed)
            self.assertIsNone(_carry_forward_gauntlet(args, "hash-a"))

    def test_heavy_diagnostics_carry_disabled_by_default_and_keyed_on_hash(self):
        from weather.calibration.pooled_candidate_replay import (
            _load_heavy_diagnostics_carry,
            _write_heavy_diagnostics_manifest,
        )

        sections = {
            "microstructure": {"gate": {"status": "PASS"}},
            "source_state_ablation": {"status": "OK"},
            "conservative_bridge": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "promotion_corpus.json"
            args = SimpleNamespace(
                corpus=str(corpus),
                heavy_analysis_max_age_days=7.0,
                force_heavy_analysis=False,
            )
            _write_heavy_diagnostics_manifest(args, "hash-a", sections)

            carried = _load_heavy_diagnostics_carry(args, "hash-a")
            self.assertTrue(carried["microstructure"]["carried_forward"])
            self.assertEqual(carried["source_state_ablation"]["status"], "OK")
            self.assertIsNone(carried["conservative_bridge"])

            self.assertIsNone(_load_heavy_diagnostics_carry(args, "hash-b"))

            # Shadow contract runs share this code path without the promotion
            # flags; the getattr default of 0 must keep carry-forward off.
            shadow_args = SimpleNamespace(corpus=str(corpus))
            self.assertIsNone(_load_heavy_diagnostics_carry(shadow_args, "hash-a"))
            self.assertIsNone(_write_heavy_diagnostics_manifest(shadow_args, "hash-a", sections))


if __name__ == "__main__":
    unittest.main()
