import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.daily_learning import build_learning_payload, write_outputs


def write_daily_artifacts(root, *, blocked=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    ingest_status = "FAIL" if blocked else "PASS"
    data_status = "FAIL" if blocked else "WARN"
    (root / "daily_refresh_status.json").write_text(
        json.dumps(
            {
                "generated_at_utc": "2026-06-16T23:55:00+00:00",
                "summary": {
                    "labels": {
                        "total": 3,
                        "quality_counts": {"complete": 3},
                        "reconciliation_counts": {"matched": 3},
                    },
                    "ingest_quality_gate": {
                        "status": ingest_status,
                        "fail_reasons": ["schema failure"] if blocked else [],
                        "warn_reasons": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "f_family_promotion_refresh.json").write_text(
        json.dumps(
            {
                "generated_at_utc": "2026-06-16T23:56:00+00:00",
                "corpus": {
                    "path": str(root / "promotion_corpus.json"),
                    "corpus_hash": "abc123",
                    "market_day_count": 2,
                    "snapshot_count": 6,
                    "band_row_count": 36,
                },
                "candidate": {
                    "verdict": "PASS",
                    "cutover_decision": "SHADOW",
                    "coverage": {"missing_candidate_rows": 0},
                    "aggregate": {
                        "rows": 36,
                        "candidate_brier": 0.08,
                        "current_brier": 0.09,
                        "market_brier": 0.07,
                        "delta_vs_current": -0.01,
                        "delta_vs_market": 0.01,
                    },
                },
                "decisions": {
                    "promote_markets": ["nyc"],
                    "shadow_markets": ["miami"],
                    "blocked_markets": [],
                    "action_counts": {"promote": 1, "shadow": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "snapshot_evaluation.json").write_text(
        json.dumps(
            {
                "status": {"status": "WARN", "pass_count": 5, "warn_count": 1, "fail_count": 0},
                "gates": [
                    {
                        "name": "candidate_vs_market",
                        "status": "WARN",
                        "severity": "warn",
                        "detail": "candidate trails market",
                        "action": "Inspect market-skill gap slices.",
                    }
                ],
                "snapshot_inventory": {"folder_count": 1, "snapshot_count": 2},
                "improvement_backlog": {
                    "top_slices": [
                        {
                            "source": "candidate_replay",
                            "slice": "market",
                            "group": "miami",
                            "rows": 12,
                            "delta_vs_market": 0.04,
                            "excess_brier_rows": 0.48,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "data_layer_audit.json").write_text(
        json.dumps(
            {
                "gate_summary": {"status": data_status, "pass_count": 2, "warn_count": 1, "fail_count": 1 if blocked else 0},
                "recommendations": [
                    {
                        "priority": "P1",
                        "area": "forecast archive",
                        "recommendation": "Backfill missing forecast archive rows.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "model_variant_evidence_growth.json").write_text(
        json.dumps(
            {
                "status": "ALERT",
                "summary": {"unique_observation_count": 2},
                "delta_vs_baseline": {"unique_observation_count": 0},
                "alerts": [
                    {
                        "severity": "alert",
                        "category": "insufficient_unique_observation_increment",
                        "detail": "unique observation increment is below required 1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "disagreement_casebook.json").write_text(
        json.dumps(
            {
                "summary": {
                    "case_count": 2,
                    "settled_case_count": 1,
                    "open_case_count": 1,
                    "model_win_count": 0,
                    "model_loss_count": 1,
                    "taxonomy_counts": {"market_overreaction": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "shadow_ab_monitor.json").write_text(
        json.dumps({"status": "OK", "summary": {"alert_count": 0}}),
        encoding="utf-8",
    )
    (root / "fleet_observability.json").write_text(
        json.dumps(
            {
                "status": "OK",
                "summary": {},
                "live_forward_slo": {
                    "counts_toward_live_forward_gate": True,
                    "reason": "all collection loops fresh",
                },
            }
        ),
        encoding="utf-8",
    )


class TestDailyLearning(unittest.TestCase):
    def test_build_learning_payload_distills_daily_artifacts_into_retrain_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            snapshots_root = Path(tmp) / "snapshots"
            write_daily_artifacts(backtest_root)

            payload = build_learning_payload(
                backtest_root=backtest_root,
                snapshots_root=snapshots_root,
                generated_at_utc="2026-06-17T04:00:00+00:00",
            )
            json_out, report_out = write_outputs(
                payload,
                json_out=backtest_root / "daily_learning.json",
                report_out=backtest_root / "daily_learning_report.md",
            )
            categories = {row["category"] for row in payload["learnings"]}
            json_exists = Path(json_out).exists()
            report = Path(report_out).read_text(encoding="utf-8")

        self.assertEqual(payload["schema_version"], "daily_learning_v0.1")
        self.assertEqual(payload["status"], "ACTIONABLE")
        self.assertTrue(payload["retrain_plan"]["training_ready"])
        self.assertTrue(payload["retrain_plan"]["promotion_ready"])
        self.assertIn("new_training_evidence", categories)
        self.assertIn("model_gap_slice", categories)
        self.assertIn("experiment_evidence", categories)
        self.assertTrue(json_exists)
        self.assertIn("Daily Log Learning", report)
        self.assertIn("miami", report)

    def test_build_learning_payload_blocks_when_quality_gates_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root, blocked=True)

            payload = build_learning_payload(backtest_root=backtest_root)

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertGreaterEqual(payload["summary"]["blocker_count"], 1)

    def test_build_learning_payload_includes_price_free_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "price_free_model_learning.json").write_text(
                json.dumps(
                    {
                        "schema_version": "price_free_model_learning_v0.1",
                        "status": "OK",
                        "evidence_classification": {
                            "lane": "diagnostic_price_free_not_promotion_evidence",
                            "uses_market_prices": False,
                            "counts_toward_retrain_input": True,
                        },
                        "corpus": {
                            "scored_market_days": 1,
                            "hourly_checkpoint_rows": 24,
                        },
                        "daily_summary": {
                            "scored_market_days": 1,
                            "hourly_checkpoint_rows": 24,
                        },
                        "overall": {
                            "hourly_checkpoint": {
                                "partition_model_top_is_winner_rate": 1.0,
                            }
                        },
                        "current_max_carryover": {
                            "summary": {
                                "risky_or_guarded_count": 2,
                            },
                            "by_market_hour": [
                                {"market_id": "austin", "cutoff_hour": 8, "early_large_gap_count": 1}
                            ],
                            "examples": [
                                {"market_id": "austin", "current_max_state": "early_current_max_history_gap"}
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            categories = {row["category"] for row in payload["learnings"]}

        self.assertIn("price_free_model_learning", categories)
        self.assertIn("current_max_carryover", categories)
        self.assertEqual(payload["scorecard"]["price_free_model_learning"]["status"], "OK")
        self.assertTrue(
            next(row for row in payload["learnings"] if row["category"] == "price_free_model_learning")[
                "retrain_input"
            ]
        )

    def test_build_learning_payload_blocks_on_settled_day_freshness_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "settled_day_freshness.json").write_text(
                json.dumps(
                    {
                        "status": "FAIL",
                        "target_date": "2026-06-17",
                        "summary": {
                            "incomplete_market_count": 12,
                            "needs_finalization_count": 12,
                            "needs_replay_status_repair_count": 12,
                        },
                        "repair_command": "python -m weather.operations.settled_day_freshness repair",
                        "replay_status_repair_command": "python -m weather.operations.replay_status_backfill",
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            learning = next(
                row for row in payload["learnings"]
                if row["source"] == "settled_day_freshness"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertTrue(learning["blocker"])
        self.assertIn("2026-06-17", learning["signal"])
        self.assertIn("replay_status_backfill", learning["action"])

    def test_build_learning_payload_blocks_on_source_family_preflight_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "source_family_inventory.json").write_text(
                json.dumps(
                    {
                        "schema_version": "source_family_inventory_v0.1",
                        "status": "BLOCK",
                        "summary": {"blocking_family_count": 2},
                        "promotion_preflight": {
                            "status": "BLOCK",
                            "blocked_family_count": 2,
                            "blocked_families": ["nws_grid", "clob_microstructure"],
                            "inventory_command": "python -m weather.reporting.source_family_inventory",
                            "ablation_command": "python -m weather.backtesting.replay_ablation --json-out data/backtest/source_family_ablation.json",
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            learning = next(
                row for row in payload["learnings"]
                if row["source"] == "source_family_inventory"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertTrue(learning["blocker"])
        self.assertIn("nws_grid", learning["signal"])
        self.assertIn("replay_ablation", learning["action"])

    def test_build_learning_payload_blocks_on_tape_backup_sla_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "fleet_observability.json").write_text(
                json.dumps(
                    {
                        "status": "CRITICAL",
                        "summary": {"tape_backup_status": "RESTORE_DRILL_MISSING"},
                        "live_forward_slo": {
                            "counts_toward_live_forward_gate": True,
                            "reason": "all collection loops fresh",
                        },
                        "tape_backup": {
                            "status": "RESTORE_DRILL_MISSING",
                            "backup_root": "data/tape_backups",
                            "restore_drill_sla_status": "RESTORE_DRILL_MISSING",
                            "restore_drill_sla_detail": "no restore drill evidence recorded",
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            backup_learning = next(
                row for row in payload["learnings"] if row["category"] == "operational_backup"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertTrue(backup_learning["blocker"])
        self.assertIn("weather.operations.tape_backup run", backup_learning["action"])
        self.assertIn("tape_restore_drill.json", backup_learning["action"])

    def test_build_learning_payload_surfaces_first_data_layer_p0_remediation(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            audit = json.loads((backtest_root / "data_layer_audit.json").read_text(encoding="utf-8"))
            audit["gate_summary"] = {"status": "FAIL", "pass_count": 3, "warn_count": 0, "fail_count": 1}
            audit["remediation_manifest"] = [
                {
                    "priority": "P0",
                    "gate": "supplemental_station_validation",
                    "status": "FAIL",
                    "evidence": "blocked sample: toronto:ghcnh_cyyz_alt_can06158733.",
                    "command": "python -m weather.sources.supplemental_station_validation --markets toronto",
                    "expected_artifact": "data/backtest/supplemental_station_validation.json",
                    "blocks_training": True,
                    "blocks_broad_promotion": True,
                }
            ]
            (backtest_root / "data_layer_audit.json").write_text(
                json.dumps(audit),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            first_gate = payload["retrain_plan"]["first_uncleared_p0_gate"]
            remediation = next(
                row for row in payload["learnings"]
                if row["category"] == "data_layer_gate"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertIn("supplemental_station_validation", first_gate["signal"])
        self.assertIn("supplemental_station_validation --markets toronto", first_gate["action"])
        self.assertIn("data_layer_audit_report.md", first_gate["action"])
        self.assertTrue(remediation["blocker"])

    def test_build_learning_payload_adds_gap_owner_experiments(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion = json.loads((backtest_root / "f_family_promotion_refresh.json").read_text(encoding="utf-8"))
            promotion["gap_owner_table"] = [
                {
                    "slice": "settlement_distance",
                    "group": "0",
                    "owner": "settlement-distance winner catch-up",
                    "next_experiment": "settlement_distance_0_winner_catchup_daily_first",
                    "experiment_artifact": "data/backtest/experiments/settlement_distance_0_winner_catchup_daily_first.json",
                    "excess_brier_rows": 5.0,
                    "counts_toward_core_skill_claim": True,
                    "clearance_rule": "aggregate delta_vs_market must be <= 0",
                }
            ]
            (backtest_root / "f_family_promotion_refresh.json").write_text(
                json.dumps(promotion),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "market_skill_gap"
                and row["source"] == "promotion_refresh"
            )

        self.assertTrue(learning["retrain_input"])
        self.assertIn("settlement_distance_0_winner_catchup", learning["action"])
        self.assertIn("aggregate delta_vs_market", learning["action"])

    def test_build_learning_payload_blocks_on_failed_blocked_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion = json.loads((backtest_root / "f_family_promotion_refresh.json").read_text(encoding="utf-8"))
            promotion["candidate"]["blocked_validation"] = {
                "passed": False,
                "verdict": "BLOCK",
                "split_mode": "daily_first_market_day",
                "reasons": ["daily-first candidate regresses current by +0.0100 > 0.0030"],
            }
            (backtest_root / "f_family_promotion_refresh.json").write_text(
                json.dumps(promotion),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            blocked_learning = next(
                row for row in payload["learnings"] if row["category"] == "blocked_validation"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["promotion_ready"])
        self.assertTrue(blocked_learning["blocker"])
        self.assertIn("daily-first blocked validation", blocked_learning["action"])

    def test_build_learning_payload_blocks_broad_promotion_on_evidence_sla(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            variant = json.loads(
                (backtest_root / "model_variant_evidence_growth.json").read_text(encoding="utf-8")
            )
            variant["evidence_sla"] = {
                "status": "BLOCK",
                "broad_promotion_claim_allowed": False,
                "reasons": ["independent evidence growth below daily target"],
            }
            variant["no_growth_reasons"] = [
                {
                    "scope": "overall",
                    "market_id": "-",
                    "status": "BLOCK",
                    "reason": "variant_rows_only",
                    "owner": "settlement/corpus refresh",
                    "action": "Do not make a broad promotion claim; add new settled labels.",
                }
            ]
            (backtest_root / "model_variant_evidence_growth.json").write_text(
                json.dumps(variant),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "independent_evidence_growth"
            )

        self.assertEqual(payload["status"], "ACTIONABLE")
        self.assertTrue(payload["retrain_plan"]["training_ready"])
        self.assertFalse(payload["retrain_plan"]["promotion_ready"])
        self.assertIn("Broad promotion claim is blocked", learning["signal"])
        self.assertIn("settled labels", learning["action"])

    def test_build_learning_payload_blocks_on_variant_learning_operational_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            daily = json.loads((backtest_root / "daily_refresh_status.json").read_text(encoding="utf-8"))
            daily["summary"]["variant_learning_gate"] = {
                "schema_version": "variant_learning_operational_gate_v0.1",
                "status": "BLOCK",
                "first_blocker": {
                    "component": "model_variant_evidence_growth",
                    "gate": "variant_evidence_sla",
                    "detail": "scored rows grew without independent observations",
                    "remediation_command": "Collect new settled labels.",
                },
                "blockers": [],
            }
            (backtest_root / "daily_refresh_status.json").write_text(json.dumps(daily), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "variant_learning_operational_gate"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertTrue(learning["blocker"])
        self.assertIn("scored rows grew", learning["signal"])
        self.assertEqual(learning["action"], "Collect new settled labels.")
        self.assertEqual(
            payload["retrain_plan"]["variant_learning_gate"]["status"],
            "BLOCK",
        )

    def test_build_learning_payload_blocks_on_hourly_performance_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "hourly_model_performance.json").write_text(
                json.dumps(
                    {
                        "schema_version": "hourly_model_performance_v0.3",
                        "hourly_performance_gate": {
                            "schema_version": "hourly_performance_gate_v0.1",
                            "status": "BLOCK",
                            "first_blocker": {
                                "gate": "early_hour_model_market_regression",
                                "detail": "early-hour model Brier trails market by +0.0120",
                                "remediation_command": "python -m weather.reporting.hourly_model_performance",
                            },
                            "blockers": [],
                        },
                        "daily_summary": {
                            "status": "BLOCK",
                            "best_hours": ["09 daytime"],
                            "worst_hours": ["00 early_morning"],
                            "active_remediation_owners": ["forecast-profile calibration"],
                        },
                        "remediation_registry": {
                            "schema_version": "hourly_remediation_registry_v0.1",
                            "summary": {"row_count": 1},
                            "rows": [
                                {
                                    "probe_name": "early_hour_profile_bias",
                                    "hour_regime": "early_morning",
                                    "metric_delta": -0.012,
                                    "market_count": 4,
                                    "row_count": 72,
                                    "uses_market_prices": False,
                                    "interpretation": "weather-only early-hour remediation improved Brier",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            gate_learning = next(
                row for row in payload["learnings"]
                if row["category"] == "hourly_performance_gate"
            )
            registry_learning = next(
                row for row in payload["learnings"]
                if row["category"] == "hourly_remediation_registry"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["scorecard"]["hourly_model_performance"]["status"], "BLOCK")
        self.assertTrue(gate_learning["blocker"])
        self.assertIn("early-hour model Brier trails market", gate_learning["signal"])
        self.assertIn("hourly_model_performance", gate_learning["source"])
        self.assertTrue(registry_learning["retrain_input"])
        self.assertIn("early_hour_profile_bias", registry_learning["signal"])
        self.assertIn("weather-only early-hour remediation", registry_learning["signal"])

    def test_build_learning_payload_counts_per_market_live_forward_credit_without_broad_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            fleet = json.loads((backtest_root / "fleet_observability.json").read_text(encoding="utf-8"))
            fleet["mm_paper_evidence"] = {
                "exists": True,
                "path": str(backtest_root / "mm_paper_report.json"),
                "by_class": {
                    "model_review_evidence": {
                        "countable_market_count": 11,
                        "blocked_market_count": 1,
                        "all_selected_markets_count": False,
                    },
                    "paper_trading_evidence": {
                        "countable_market_count": 11,
                        "blocked_market_count": 1,
                        "all_selected_markets_count": False,
                    },
                    "live_trade_permission_evidence": {
                        "countable_market_count": 0,
                        "blocked_market_count": 12,
                        "all_selected_markets_count": False,
                    },
                },
                "credit_rows": [
                    {
                        "market_id": "nyc",
                        "evidence_class": "model_review_evidence",
                        "counts": False,
                        "first_failing_gate": "model_freshness",
                    }
                ],
            }
            (backtest_root / "fleet_observability.json").write_text(json.dumps(fleet), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "live_forward_partial_credit"
            )

        self.assertTrue(learning["retrain_input"])
        self.assertIn("11 model-review", learning["signal"])
        self.assertIn("model review only", learning["action"])
        self.assertEqual(
            learning["evidence"]["by_class"]["live_trade_permission_evidence"]["countable_market_count"],
            0,
        )

    def test_build_learning_payload_blocks_broad_slo_with_recovery_checklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            fleet = json.loads((backtest_root / "fleet_observability.json").read_text(encoding="utf-8"))
            fleet["status"] = "CRITICAL"
            fleet["live_forward_slo"] = {
                "status": "BLOCK",
                "counts_toward_live_forward_gate": False,
                "reason": (
                    "latest_model_row_freshness blocks broad live-forward SLO for "
                    "toronto: latest capture is 40 min old"
                ),
                "first_blocker": {
                    "market_id": "toronto",
                    "component": "snapshot_collection",
                    "gate": "latest_model_row_freshness",
                    "owner": "weather snapshot/model loop",
                    "repair_command": "python -m weather.collection.snapshot_tracker --status",
                    "verification_command": "python -m weather.reporting.fleet_observability report",
                },
                "recovery_checklist": [
                    {
                        "market_id": "toronto",
                        "component": "snapshot_collection",
                        "gate": "latest_model_row_freshness",
                        "owner": "weather snapshot/model loop",
                        "before": "latest_age_minutes=40.0",
                        "repair_command": "python -m weather.collection.snapshot_tracker --status",
                        "verification_command": "python -m weather.reporting.fleet_observability report",
                    }
                ],
                "rerun_command": "python -m weather.reporting.fleet_observability report",
                "summary": {
                    "first_blocking_market": "toronto",
                    "first_blocking_gate": "latest_model_row_freshness",
                    "recovery_row_count": 1,
                },
            }
            (backtest_root / "fleet_observability.json").write_text(json.dumps(fleet), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            report_out = backtest_root / "daily_learning_report.md"
            write_outputs(payload, json_out=backtest_root / "daily_learning.json", report_out=report_out)
            blocker = payload["retrain_plan"]["first_uncleared_p0_gate"]
            report = report_out.read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertFalse(payload["retrain_plan"]["promotion_ready"])
        self.assertIn("snapshot_tracker --status", blocker["action"])
        self.assertEqual(
            payload["retrain_plan"]["broad_live_forward_slo"]["first_blocker"]["gate"],
            "latest_model_row_freshness",
        )
        self.assertIn("## Broad Live-Forward SLO Recovery", report)
        self.assertIn("latest_model_row_freshness", report)
        self.assertIn("weather.collection.snapshot_tracker --status", report)

    def test_build_learning_payload_surfaces_core_model_trend_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "progress_audit.json").write_text(
                json.dumps(
                    {
                        "schema_version": "progress_audit_v0.1",
                        "core_model_trend_claim": {
                            "schema_version": "core_model_trend_claim_v0.1",
                            "status": "DIRECTIONAL",
                            "claim_allowed": False,
                            "summary": {
                                "comparable_day_count": 11,
                                "positive_skill_days": 1,
                                "rolling_daily_first_brier_skill": -0.1538,
                                "brier_skill_slope_per_day": 0.0584,
                                "latest_comparable_date": "2026-06-16",
                                "latest_comparable_brier_skill": 0.0330,
                            },
                            "threshold_failures": [
                                "need 3 positive-skill comparable days; have 1",
                                "live-forward SLO is not countable",
                            ],
                            "next_evidence_needed": [
                                "Wait for more comparable days where model Brier beats market Brier.",
                                "Repair live-forward collection health before using active-day evidence in the trend claim.",
                            ],
                            "daily_sequence": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            report_out = backtest_root / "daily_learning_report.md"
            write_outputs(payload, json_out=backtest_root / "daily_learning.json", report_out=report_out)
            trend_learning = next(
                row for row in payload["learnings"]
                if row["category"] == "core_model_trend_claim"
            )
            report = report_out.read_text(encoding="utf-8")

        self.assertTrue(trend_learning["retrain_input"])
        self.assertIn("DIRECTIONAL", trend_learning["signal"])
        self.assertIn("positive-skill", trend_learning["signal"])
        self.assertEqual(payload["scorecard"]["core_model_trend_claim"]["status"], "DIRECTIONAL")
        self.assertIn("## Core Model Trend Claim", report)
        self.assertIn("need 3 positive-skill comparable days", report)


if __name__ == "__main__":
    unittest.main()
