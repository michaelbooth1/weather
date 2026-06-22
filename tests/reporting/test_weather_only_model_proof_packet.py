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


if __name__ == "__main__":
    unittest.main()
