import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from weather.reporting.promotion_refresh import (  # noqa: E402
    _candidate_gap_driver_rows,
    _candidate_args,
    _candidate_source_freshness_rows,
    _candidate_summary,
    _family_specs,
    _serving_blocking_source_freshness_rows,
    build_gap_owner_table,
    build_family_decisions,
    market_skill_diagnostics,
    model_skill_claims,
    promotion_readiness,
    write_gap_experiment_artifacts,
    write_report,
)


def _spec(market_id, city, unit="F"):
    return SimpleNamespace(id=market_id, city_label=city, display_unit=unit)


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
        self.assertEqual(rows[1]["claim_lane"], "market_informed_clob_overlay")
        self.assertFalse(rows[1]["counts_toward_core_skill_claim"])

    def test_market_skill_claims_separate_core_and_clob_lanes(self):
        claims = model_skill_claims(
            {
                "aggregate": {"delta_vs_market": 0.01},
                "blocked_validation": {"passed": True},
            },
            [{"claim_lane": "market_informed_clob_overlay"}],
        )

        self.assertFalse(claims["weather_only_core_model"]["broad_market_skill_claim_allowed"])
        self.assertFalse(claims["market_informed_clob_overlay"]["counts_toward_core_skill_claim"])
        self.assertTrue(claims["market_informed_clob_overlay"]["may_support_quote_gating"])

    def test_market_skill_diagnostics_targets_nyc_and_seattle(self):
        rows = market_skill_diagnostics(
            {
                "slices": {
                    "by_market": [
                        {"group": "nyc", "candidate_brier": 0.08, "market_brier": 0.06, "delta_vs_market": 0.02},
                    ]
                }
            },
            {
                "markets": [
                    {
                        "market_id": "nyc",
                        "action": "KEEP_SHADOW",
                        "reason": "not proven better than market",
                        "metrics": {"candidate_brier": 0.08, "market_brier": 0.06, "delta_vs_market": 0.02},
                    }
                ]
            },
        )

        by_market = {row["market_id"]: row for row in rows}
        self.assertEqual(by_market["nyc"]["action"], "KEEP_SHADOW")
        self.assertIn("nyc_residual", by_market["nyc"]["experiment_artifact"])
        self.assertEqual(by_market["seattle"]["next_experiment"], "seattle_residual_calibration_daily_first")

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


if __name__ == "__main__":
    unittest.main()
