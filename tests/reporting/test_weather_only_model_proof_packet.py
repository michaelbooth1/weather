import json
import pickle
import tempfile
import unittest
from pathlib import Path

from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.reporting.weather_only_model_proof_packet import (
    build_payload,
    render_report,
    roadmap_reference_check,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_artifact(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(
            {
                "schema_version": "pooled_band_model_v0.1",
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "trained_at": "2026-06-22T00:00:00+00:00",
                "family_unit": "F",
                "models": {7: object()},
                "blocked_validation": {"ok": True},
            },
            handle,
        )


def write_roadmap_item(path, number, title, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"# {number}. {title} [PARTIAL 2026-06-22 - TEST]",
                "",
                "Goal: test item.",
                "Source: test.",
                "Why this matters: test.",
                "- [ ] test",
                "Acceptance: test.",
                "",
                body,
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_minimal_pass_packet_inputs(backtest, promotion_payload):
    write_json(backtest / "promotion.json", promotion_payload)
    write_json(
        backtest / "hourly.json",
        {"hourly_performance_gate": {"status": "PASS", "blockers": []}},
    )
    write_json(
        backtest / "ten.json",
        {"ten_minute_performance_gate": {"status": "PASS", "blockers": []}},
    )
    write_json(backtest / "exact.json", {"status": "PASS", "blocker_count": 0})
    write_json(backtest / "bottom.json", {"status": "PASS", "blocker_count": 0})
    write_json(
        backtest / "fleet.json",
        {
            "status": "PASS",
            "live_forward_slo": {
                "status": "PASS",
                "counts_toward_live_forward_gate": True,
            },
        },
    )
    write_json(
        backtest / "progress.json",
        {
            "core_model_trend_claim": {
                "status": "PASS",
                "claim_allowed": True,
                "threshold_failures": [],
            }
        },
    )
    write_json(backtest / "daily.json", {"broad_improvement_claim_allowed": True})
    write_json(backtest / "served.json", {"status": "PASS", "acceptance_passed": True})
    write_json(backtest / "positive.json", {"status": "PASS", "acceptance_passed": True})
    write_json(backtest / "austin.json", {"status": "PASS", "summary": {}, "hard_slices": []})
    write_json(backtest / "winner.json", {"status": "PASS", "parity_gate": {"status": "PASS"}})


def build_minimal_packet(root, artifact):
    backtest = root / "backtest"
    roadmap = root / "roadmap"
    return build_payload(
        artifact_path=artifact,
        promotion_refresh=backtest / "promotion.json",
        hourly=backtest / "hourly.json",
        ten_minute=backtest / "ten.json",
        exact_distance=backtest / "exact.json",
        bottom_location=backtest / "bottom.json",
        fleet_observability=backtest / "fleet.json",
        progress_audit=backtest / "progress.json",
        daily_progress=backtest / "daily.json",
        served_distribution=backtest / "served.json",
        positive_daily_first=backtest / "positive.json",
        austin_requalification=backtest / "austin.json",
        winner_rank_parity=backtest / "winner.json",
        roadmap_root=roadmap,
    )


class TestWeatherOnlyModelProofPacket(unittest.TestCase):
    def test_packet_joins_gates_market_dispositions_and_ratchet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            roadmap = root / "roadmap"
            artifact = root / "models" / "pooled.pkl"
            write_artifact(artifact)
            write_json(
                backtest / "f_family_promotion_refresh.json",
                {
                    "schema_version": "promotion_refresh_v0.1",
                    "generated_at_utc": "2026-06-22T01:00:00+00:00",
                    "candidate": {
                        "verdict": "PASS",
                        "cutover_decision": "PER_MARKET_ONLY",
                        "artifact": {"path": str(artifact)},
                        "candidate_shadow_variants": {
                            "variant_id": "pooled_f_candidate",
                            "active_registry_contract": {"variant_id": "pooled_f_candidate"},
                            "uses_market_features": False,
                        },
                        "aggregate": {
                            "rows": 50,
                            "delta_vs_current": -0.01,
                            "delta_vs_market": 0.004,
                        },
                    },
                    "readiness": {"status": "PASS", "blockers": []},
                    "source_missingness_location_gate": {
                        "status": "PASS",
                        "blockers": [],
                    },
                    "model_skill_claims": {
                        "weather_only_core_model": {
                            "broad_market_skill_claim_allowed": False,
                            "reason": "core candidate still trails market",
                            "delta_vs_market": 0.004,
                            "daily_first_passed": True,
                        },
                        "market_informed_quote_risk": {
                            "counts_toward_core_skill_claim": False,
                            "reason": "quote-risk only",
                        },
                    },
                    "decisions": {
                        "markets": [
                            {
                                "market_id": "nyc",
                                "city": "New York",
                                "action": "PROMOTE_CANDIDATE",
                                "reason": "beats current",
                                "metrics": {
                                    "candidate_brier": 0.04,
                                    "current_brier": 0.05,
                                    "market_brier": 0.03,
                                    "delta_vs_current": -0.01,
                                    "delta_vs_market": 0.01,
                                },
                            },
                            {
                                "market_id": "miami",
                                "city": "Miami",
                                "action": "KEEP_SHADOW",
                                "reason": "thin evidence",
                                "metrics": {
                                    "delta_vs_current": -0.02,
                                    "delta_vs_market": 0.001,
                                },
                            },
                            {
                                "market_id": "toronto",
                                "city": "Toronto",
                                "action": "BLOCK_CANDIDATE",
                                "reason": "early-hour market regression",
                                "metrics": {
                                    "delta_vs_current": 0.02,
                                    "delta_vs_market": 0.03,
                                },
                            },
                        ]
                    },
                },
            )
            write_json(
                backtest / "hourly_model_performance.json",
                {
                    "schema_version": "hourly_model_performance_v0.3",
                    "hourly_performance_gate": {
                        "status": "BLOCK",
                        "first_blocker": {
                            "gate": "early_hour_model_market_regression",
                            "detail": "early-hour model trails market",
                        },
                    },
                },
            )
            write_json(
                backtest / "ten_minute_model_performance.json",
                {
                    "schema_version": "ten_minute_model_performance_v0.1",
                    "ten_minute_performance_gate": {"status": "PASS"},
                    "weak_slots": {"slot_labels": ["03:00"]},
                },
            )
            write_json(
                backtest / "exact_band_distance_zero_calibration.json",
                {
                    "schema_version": "exact_band_distance_zero_calibration_v0.1",
                    "status": "BLOCK",
                    "first_blocker": {"detail": "distance-0 trails market"},
                    "blocker_count": 1,
                },
            )
            write_json(
                backtest / "bottom_location_winner_centering.json",
                {
                    "schema_version": "bottom_location_winner_centering_v0.1",
                    "status": "PASS",
                },
            )
            write_json(
                backtest / "fleet_observability.json",
                {
                    "status": "CRITICAL",
                    "live_forward_slo": {
                        "status": "BLOCK",
                        "counts_toward_live_forward_gate": False,
                        "reason": "snapshot coverage gap",
                    },
                },
            )
            write_json(
                backtest / "progress_audit.json",
                {
                    "core_model_trend_claim": {
                        "status": "DIRECTIONAL",
                        "claim_allowed": False,
                        "threshold_failures": ["needs positive daily-first skill"],
                    }
                },
            )
            write_json(
                backtest / "daily_progress_latest.json",
                {
                    "broad_improvement_claim_allowed": False,
                    "broad_improvement_claim_failures": ["core_model_trend_claim_not_allowed"],
                },
            )
            write_json(
                backtest / "served_distribution_calibration_contract.json",
                {
                    "schema_version": "served_distribution_calibration_contract_v0.1",
                    "status": "PASS",
                    "acceptance_passed": True,
                },
            )
            write_json(
                backtest / "early_hour_positive_daily_first_gate.json",
                {
                    "schema_version": "early_hour_positive_daily_first_gate_v0.1",
                    "status": "BLOCK",
                    "acceptance_passed": False,
                    "first_blocker": {"detail": "need positive daily-first days"},
                },
            )
            write_json(
                backtest / "austin_hgb_requalification.json",
                {
                    "schema_version": "austin_hgb_requalification_v0.1",
                    "generated_at_utc": "2026-06-22T01:30:00+00:00",
                    "status": "PASS",
                    "market_id": "austin",
                    "serving_disposition": "SHADOW",
                    "requalification_verdict": "BLOCK",
                    "requalification_blocker_count": 2,
                    "first_requalification_blocker": {"detail": "Austin proof-packet disposition is SHADOW"},
                    "summary": {
                        "proof_packet_disposition": "SHADOW",
                        "local_delta_vs_market": 0.001,
                        "exact_distance_status": "BLOCK",
                    },
                    "hard_slices": [
                        {
                            "slice_id": "austin_2026_06_22_high_disagreement",
                            "target_date": "2026-06-22",
                        }
                    ],
                },
            )
            write_roadmap_item(
                roadmap / "items" / "item-228-predawn.md",
                228,
                "Predawn Weak-Slot Repair Candidate Gate",
                "Proof-packet blocker: `weather_only_model_proof_packet.gates.ten_minute_gate`.",
            )
            write_roadmap_item(
                roadmap / "items" / "item-230-exact.md",
                230,
                "Exact-Band And Settlement-Distance-0 Early-Hour Calibration",
                "No packet reference yet.",
            )
            write_roadmap_item(
                roadmap / "items" / "item-250-austin.md",
                250,
                "Austin HGB Per-Location Requalification",
                "Proof-packet hard slice: `weather_only_model_proof_packet.hard_slices.austin_hgb_requalification`.",
            )

            payload = build_payload(
                artifact_path=artifact,
                promotion_refresh=backtest / "f_family_promotion_refresh.json",
                hourly=backtest / "hourly_model_performance.json",
                ten_minute=backtest / "ten_minute_model_performance.json",
                exact_distance=backtest / "exact_band_distance_zero_calibration.json",
                bottom_location=backtest / "bottom_location_winner_centering.json",
                fleet_observability=backtest / "fleet_observability.json",
                progress_audit=backtest / "progress_audit.json",
                daily_progress=backtest / "daily_progress_latest.json",
                served_distribution=backtest / "served_distribution_calibration_contract.json",
                positive_daily_first=backtest / "early_hour_positive_daily_first_gate.json",
                austin_requalification=backtest / "austin_hgb_requalification.json",
                roadmap_root=roadmap,
                generated_at_utc="2026-06-22T02:00:00+00:00",
            )
            report = render_report(payload)

        self.assertEqual(payload["schema_version"], "weather_only_model_proof_packet_v0.1")
        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(payload["first_blocker"]["field"], "gates.hourly_gate")
        by_market = {row["market_id"]: row for row in payload["market_dispositions"]}
        self.assertEqual(by_market["nyc"]["disposition"], "SHADOW")
        self.assertEqual(by_market["nyc"]["first_blocking_slice"], "gates.hourly_gate")
        self.assertEqual(by_market["miami"]["disposition"], "SHADOW")
        self.assertEqual(by_market["toronto"]["disposition"], "BLOCK")
        self.assertEqual(by_market["toronto"]["first_blocking_slice"], "promotion_refresh_market_decision")
        self.assertEqual(payload["summary"]["evidence_basis"], "active_artifact")
        self.assertEqual(
            payload["hard_slices"]["austin_hgb_requalification"]["serving_disposition"],
            "SHADOW",
        )
        self.assertEqual(payload["roadmap_reference_check"]["status"], "BLOCK")
        blocked_items = [
            row["item"]
            for row in payload["roadmap_reference_check"]["rows"]
            if row["status"] == "BLOCK"
        ]
        self.assertEqual(blocked_items, [230])
        ratchet_classes = {
            row["gate"]: row["classification"]
            for row in payload["gate_stack_ratchet"]["rows"]
        }
        self.assertEqual(ratchet_classes["clob_overlay_or_taker_trading_packet"], "separate_lane")
        self.assertIn("## Market Dispositions", report)
        self.assertIn("weather-only proof packet", report)

    def test_packet_uses_candidate_mitigation_and_reports_progress_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            roadmap = root / "roadmap"
            artifact = root / "models" / "pooled.pkl"
            write_artifact(artifact)
            write_json(
                backtest / "promotion.json",
                {
                    "candidate": {
                        "verdict": "PASS",
                        "artifact": {"path": str(artifact)},
                        "candidate_shadow_variants": {
                            "variant_id": "active_candidate",
                            "active_registry_contract": {"variant_id": "active_candidate"},
                            "uses_market_features": False,
                        },
                        "aggregate": {"rows": 10, "delta_vs_market": -0.02},
                    },
                    "readiness": {
                        "status": "PASS",
                        "blockers": [],
                        "hourly_performance_mitigation": {
                            "applied": True,
                            "candidate_hourly_status": "PASS",
                            "candidate_variant_id": "active_candidate",
                            "current_hourly_status": "BLOCK",
                        },
                        "ten_minute_performance_mitigation": {
                            "applied": True,
                            "candidate_ten_minute_status": "PASS",
                            "candidate_variant_id": "active_candidate",
                            "current_ten_minute_status": "BLOCK",
                        },
                    },
                    "source_missingness_location_gate": {"status": "PASS", "blockers": []},
                    "model_skill_claims": {
                        "weather_only_core_model": {
                            "broad_market_skill_claim_allowed": True,
                            "reason": "core candidate clears aggregate and daily-first market-skill gates",
                        },
                        "market_informed_quote_risk": {
                            "counts_toward_core_skill_claim": False,
                        },
                    },
                    "decisions": {
                        "markets": [
                            {
                                "market_id": "nyc",
                                "action": "PROMOTE_CANDIDATE",
                                "metrics": {"delta_vs_market": -0.02},
                            }
                        ]
                    },
                },
            )
            write_json(
                backtest / "hourly.json",
                {
                    "hourly_performance_gate": {
                        "status": "BLOCK",
                        "first_blocker": {"detail": "current hourly still trails market"},
                    }
                },
            )
            write_json(
                backtest / "ten.json",
                {
                    "ten_minute_performance_gate": {
                        "status": "BLOCK",
                        "first_blocker": {"detail": "current weak slots still trail market"},
                    }
                },
            )
            write_json(backtest / "exact.json", {"status": "PASS"})
            write_json(backtest / "bottom.json", {"status": "PASS"})
            write_json(
                backtest / "fleet.json",
                {
                    "status": "PASS",
                    "live_forward_slo": {
                        "status": "PASS",
                        "counts_toward_live_forward_gate": True,
                    },
                },
            )
            write_json(
                backtest / "progress.json",
                {
                    "core_model_trend_claim": {
                        "status": "DIRECTIONAL",
                        "claim_allowed": False,
                        "threshold_failures": ["need 3 positive daily-first days; have 1"],
                    }
                },
            )
            write_json(backtest / "daily.json", {"broad_improvement_claim_allowed": True})
            write_json(backtest / "served.json", {"status": "PASS", "acceptance_passed": True})
            write_json(backtest / "positive.json", {"status": "BLOCK", "acceptance_passed": False})
            write_json(backtest / "austin.json", {"status": "PASS", "summary": {}, "hard_slices": []})
            write_json(
                backtest / "winner.json",
                {"status": "PASS", "parity_gate": {"status": "PASS"}},
            )

            payload = build_payload(
                artifact_path=artifact,
                promotion_refresh=backtest / "promotion.json",
                hourly=backtest / "hourly.json",
                ten_minute=backtest / "ten.json",
                exact_distance=backtest / "exact.json",
                bottom_location=backtest / "bottom.json",
                fleet_observability=backtest / "fleet.json",
                progress_audit=backtest / "progress.json",
                daily_progress=backtest / "daily.json",
                served_distribution=backtest / "served.json",
                positive_daily_first=backtest / "positive.json",
                austin_requalification=backtest / "austin.json",
                winner_rank_parity=backtest / "winner.json",
                roadmap_root=roadmap,
            )

        gates = {row["gate"]: row for row in payload["gates"]}
        by_market = {row["market_id"]: row for row in payload["market_dispositions"]}
        self.assertEqual(gates["hourly_gate"]["status"], "PASS")
        self.assertEqual(gates["ten_minute_gate"]["status"], "PASS")
        self.assertEqual(gates["broad_claim_gate"]["status"], "BLOCK")
        self.assertIn("need 3 positive daily-first days", gates["broad_claim_gate"]["detail"])
        self.assertNotIn("core candidate clears", gates["broad_claim_gate"]["detail"])
        self.assertEqual(payload["first_blocker"]["field"], "gates.broad_claim_gate")
        self.assertEqual(by_market["nyc"]["first_blocking_slice"], "gates.broad_claim_gate")

    def test_packet_uses_active_replay_contract_when_candidate_artifact_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            artifact = root / "models" / "pooled.pkl"
            write_artifact(artifact)
            write_minimal_pass_packet_inputs(
                backtest,
                {
                    "candidate": {
                        "verdict": "PASS",
                        "artifact": {"path": str(root / "models" / "source_candidate.pkl")},
                        "candidate_shadow_variants": {
                            "variant_id": "active_rows_v0_1",
                            "active_registry_contract": {"variant_id": "active_rows_v0_1"},
                            "uses_market_features": False,
                        },
                        "aggregate": {"rows": 10, "delta_vs_market": -0.02},
                    },
                    "readiness": {"status": "PASS", "blockers": []},
                    "source_missingness_location_gate": {"status": "PASS", "blockers": []},
                    "model_skill_claims": {
                        "weather_only_core_model": {
                            "broad_market_skill_claim_allowed": True,
                            "reason": "clear",
                        }
                    },
                    "decisions": {"markets": []},
                },
            )

            payload = build_minimal_packet(root, artifact)

        gate = next(row for row in payload["gates"] if row["gate"] == "active_artifact_identity")
        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(payload["summary"]["evidence_basis"], "active_replay_contract")
        self.assertFalse(gate["evidence"]["candidate_artifact_matches"])
        self.assertTrue(gate["evidence"]["active_replay_contract_ok"])
        self.assertEqual(gate["evidence"]["evidence_basis"], "active_replay_contract")
        self.assertIn("active replay/export contract evidence", gate["detail"])

    def test_packet_blocks_mismatched_candidate_artifact_without_active_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            artifact = root / "models" / "pooled.pkl"
            write_artifact(artifact)
            write_minimal_pass_packet_inputs(
                backtest,
                {
                    "candidate": {
                        "verdict": "PASS",
                        "artifact": {"path": str(root / "models" / "other_candidate.pkl")},
                        "candidate_shadow_variants": {
                            "variant_id": "row_export_v0_1",
                            "uses_market_features": False,
                        },
                        "aggregate": {"rows": 10, "delta_vs_market": -0.02},
                    },
                    "readiness": {"status": "PASS", "blockers": []},
                    "source_missingness_location_gate": {"status": "PASS", "blockers": []},
                    "model_skill_claims": {
                        "weather_only_core_model": {
                            "broad_market_skill_claim_allowed": True,
                            "reason": "clear",
                        }
                    },
                    "decisions": {"markets": []},
                },
            )

            payload = build_minimal_packet(root, artifact)

        gate = next(row for row in payload["gates"] if row["gate"] == "active_artifact_identity")
        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(payload["first_blocker"]["field"], "gates.active_artifact_identity")
        self.assertEqual(payload["summary"]["evidence_basis"], "artifact_identity_mismatch")
        self.assertEqual(gate["status"], "BLOCK")
        self.assertEqual(gate["evidence"]["evidence_basis"], "artifact_identity_mismatch")
        self.assertIn("candidate artifact path does not match proof artifact", gate["detail"])

    def test_roadmap_reference_check_allows_diagnostic_only_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            roadmap = Path(tmp) / "roadmap"
            write_roadmap_item(
                roadmap / "items" / "item-999-diagnostic.md",
                999,
                "Diagnostic Item",
                "This remains diagnostic-only until it changes a proof-packet blocker.",
            )

            check = roadmap_reference_check(
                roadmap,
                model_item_packet_fields={999: "gates.hourly_gate"},
            )

        self.assertEqual(check["status"], "PASS")
        self.assertTrue(check["rows"][0]["diagnostic_only"])

    def test_winner_rank_parity_gate_blocks_broad_packet_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest = root / "backtest"
            roadmap = root / "roadmap"
            artifact = root / "models" / "pooled.pkl"
            write_artifact(artifact)
            write_json(
                backtest / "f_family_promotion_refresh.json",
                {
                    "candidate": {
                        "verdict": "PASS",
                        "artifact": {"path": str(artifact)},
                        "aggregate": {"rows": 10},
                    },
                    "readiness": {"status": "PASS", "blockers": []},
                    "source_missingness_location_gate": {"status": "PASS", "blockers": []},
                    "model_skill_claims": {
                        "weather_only_core_model": {
                            "broad_market_skill_claim_allowed": True,
                            "reason": "",
                        },
                        "market_informed_quote_risk": {
                            "counts_toward_core_skill_claim": False,
                        },
                    },
                    "decisions": {"markets": []},
                },
            )
            write_json(
                backtest / "hourly_model_performance.json",
                {"hourly_performance_gate": {"status": "PASS"}},
            )
            write_json(
                backtest / "ten_minute_model_performance.json",
                {"ten_minute_performance_gate": {"status": "PASS"}},
            )
            write_json(backtest / "exact_band_distance_zero_calibration.json", {"status": "PASS"})
            write_json(backtest / "bottom_location_winner_centering.json", {"status": "PASS"})
            write_json(
                backtest / "fleet_observability.json",
                {
                    "status": "PASS",
                    "live_forward_slo": {
                        "status": "PASS",
                        "counts_toward_live_forward_gate": True,
                    },
                },
            )
            write_json(
                backtest / "progress_audit.json",
                {"core_model_trend_claim": {"status": "PASS", "claim_allowed": True}},
            )
            write_json(backtest / "daily_progress_latest.json", {"broad_improvement_claim_allowed": True})
            write_json(
                backtest / "served_distribution_calibration_contract.json",
                {"status": "PASS", "acceptance_passed": True},
            )
            write_json(
                backtest / "early_hour_positive_daily_first_gate.json",
                {"status": "PASS", "acceptance_passed": True},
            )
            write_json(
                backtest / "austin_hgb_requalification.json",
                {"status": "PASS", "summary": {}, "hard_slices": []},
            )
            write_json(
                backtest / "winner_rank_parity.json",
                {
                    "schema_version": "winner_rank_parity_v0.1",
                    "status": "BLOCK",
                    "summary": {
                        "model_top_hit_rate": 0.40,
                        "market_top_hit_rate": 0.60,
                        "market_top_model_miss_excess": 12,
                        "brier_contribution": 0.02,
                    },
                    "parity_gate": {
                        "status": "BLOCK",
                        "blocker_count": 1,
                        "first_blocker": {
                            "gate": "top_hit_gap",
                            "detail": "model top-hit rate trails market",
                        },
                        "blockers": [],
                    },
                },
            )

            payload = build_payload(
                artifact_path=artifact,
                promotion_refresh=backtest / "f_family_promotion_refresh.json",
                hourly=backtest / "hourly_model_performance.json",
                ten_minute=backtest / "ten_minute_model_performance.json",
                exact_distance=backtest / "exact_band_distance_zero_calibration.json",
                bottom_location=backtest / "bottom_location_winner_centering.json",
                fleet_observability=backtest / "fleet_observability.json",
                progress_audit=backtest / "progress_audit.json",
                daily_progress=backtest / "daily_progress_latest.json",
                served_distribution=backtest / "served_distribution_calibration_contract.json",
                positive_daily_first=backtest / "early_hour_positive_daily_first_gate.json",
                austin_requalification=backtest / "austin_hgb_requalification.json",
                winner_rank_parity=backtest / "winner_rank_parity.json",
                roadmap_root=roadmap,
            )
            report = render_report(payload)

        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(payload["first_blocker"]["field"], "gates.winner_rank_parity_gate")
        self.assertEqual(payload["summary"]["winner_rank_parity_status"], "BLOCK")
        self.assertEqual(payload["summary"]["market_top_model_miss_excess"], 12)
        self.assertIn("Winner-Rank Parity", report)


if __name__ == "__main__":
    unittest.main()
