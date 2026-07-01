import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.daily.daily_learning import build_learning_payload, render_report, write_outputs


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
    (root / "settled_day_freshness.json").write_text(
        json.dumps(
            {
                "schema_version": "settled_day_freshness_v0.1",
                "generated_at_utc": "2026-06-16T23:55:30+00:00",
                "status": "PASS",
                "target_date": "2026-06-16",
                "summary": {
                    "expected_market_count": 3,
                    "complete_market_count": 3,
                    "incomplete_market_count": 0,
                    "needs_finalization_count": 0,
                    "quality_counts": {"complete": 3},
                    "partial_label_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "settled_day_analysis_barrier.json").write_text(
        json.dumps(
            {
                "schema_version": "settled_day_analysis_barrier_v0.1",
                "generated_at_utc": "2026-06-16T23:55:40+00:00",
                "status": "PASS",
                "target_date": "2026-06-16",
                "blocker_count": 0,
                "label_countability": {
                    "status": "promotion_countable",
                    "promotion_countable": True,
                    "diagnostic_only": False,
                    "partial_label_count": 0,
                    "quality_counts": {"complete": 3},
                    "reason": "all selected settled labels are promotion-countable",
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "event_metadata_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "event_metadata_validation_v0.1",
                "generated_at_utc": "2026-06-16T23:55:50+00:00",
                "status": "PASS",
                "target_date": "2026-06-16",
                "summary": {"first_blocker": {}},
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
                    "market_day_count": 3,
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
                "generated_at_utc": "2026-06-16T23:57:00+00:00",
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
                "generated_at_utc": "2026-06-16T23:58:00+00:00",
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
                "generated_at_utc": "2026-06-16T23:59:00+00:00",
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
                "generated_at_utc": "2026-06-16T23:59:30+00:00",
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
    (root / "model_market_disagreement_analysis.json").write_text(
        json.dumps(
            {
                "schema_version": "model_market_disagreement_analysis_v0.1",
                "generated_at_utc": "2026-06-16T23:59:35+00:00",
                "summary": {
                    "deduped_audit_snapshots": 0,
                    "resolved_count": 0,
                    "pending_count": 0,
                    "rehydration_status": "PASS",
                },
                "rehydration": {
                    "status": "PASS",
                    "target_date": "2026-06-16",
                    "pending_before_count": 0,
                    "rehydrated_count": 0,
                    "model_closer_rehydrated_count": 0,
                    "market_closer_rehydrated_count": 0,
                    "excluded_partial_label_count": 0,
                    "excluded_missing_label_count": 0,
                    "pending_after_count": 0,
                    "unresolved_after_rehydrate_count": 0,
                    "blocker_count": 0,
                    "blockers": [],
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "shadow_ab_monitor.json").write_text(
        json.dumps({
            "generated_at_utc": "2026-06-16T23:59:40+00:00",
            "status": "OK",
            "summary": {"alert_count": 0},
        }),
        encoding="utf-8",
    )
    (root / "fleet_observability.json").write_text(
        json.dumps(
            {
                "generated_at_utc": "2026-06-17T00:00:00+00:00",
                "status": "OK",
                "summary": {},
                "live_forward_slo": {
                    "status": "PASS",
                    "counts_toward_live_forward_gate": True,
                    "reason": "all collection loops fresh",
                },
                "clean_active_day_countability": {
                    "status": "PASS",
                    "target_date": "2026-06-16",
                    "counts_toward_clean_active_day": True,
                    "counts_toward_early_hour_evidence": True,
                    "operational_blocker_count": 0,
                    "early_hour_coverage_proof": {
                        "summary": {
                            "status": "PASS",
                            "countable_market_count": 12,
                            "total_snapshot_count": 588,
                            "total_missing_snapshot_count": 0,
                            "total_gap_count": 0,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "winner_rank_parity.json").write_text(
        json.dumps(
            {
                "schema_version": "winner_rank_parity_v0.1",
                "generated_at_utc": "2026-06-17T00:00:30+00:00",
                "status": "PASS",
                "dates": ["2026-06-16"],
                "summary": {"route_count": 0, "parity_gate_status": "PASS"},
                "parity_gate": {"status": "PASS", "blocker_count": 0, "blockers": []},
                "top_owner_routes": [],
            }
        ),
        encoding="utf-8",
    )


def rewrite_json(path, mutator):
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutator(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


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
        self.assertFalse(payload["retrain_plan"]["promotion_ready"])
        self.assertEqual(payload["retrain_plan"]["promotion_confidence"]["status"], "BLOCK")
        self.assertIn(
            "delta_vs_current_independent_market_days_below_30",
            payload["retrain_plan"]["promotion_ready_reasons"],
        )
        self.assertIn("new_training_evidence", categories)
        self.assertIn("model_gap_slice", categories)
        self.assertIn("experiment_evidence", categories)
        self.assertTrue(json_exists)
        self.assertIn("Daily Log Learning", report)
        self.assertIn("## Input Gate", report)
        self.assertIn("miami", report)

    def test_build_learning_payload_blocks_stale_critical_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            promotion["generated_at_utc"] = "2026-06-15T23:56:00+00:00"
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")

            payload = build_learning_payload(
                backtest_root=backtest_root,
                input_max_skew_hours=1.0,
            )
            gate = payload["input_gate"]
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "analysis_input_gate" and "freshness" in row["signal"]
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertEqual(gate["freshness"]["status"], "FAIL")
        self.assertIn("promotion_refresh", gate["freshness"]["critical_stale_inputs"])
        self.assertTrue(learning["blocker"])

    def test_build_learning_payload_blocks_missing_critical_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "fleet_observability.json").unlink()

            payload = build_learning_payload(backtest_root=backtest_root)
            gate = payload["input_gate"]
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "analysis_input_gate" and "coverage" in row["signal"]
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertEqual(gate["coverage"]["status"], "FAIL")
        self.assertIn("fleet_observability", gate["coverage"]["critical_missing_inputs"])
        self.assertTrue(learning["blocker"])

    def test_build_learning_payload_blocks_inconsistent_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            promotion["corpus"]["market_day_count"] = 2
            promotion["candidate"]["aggregate"]["delta_vs_current"] = 0.01
            promotion["candidate"]["aggregate"]["delta_vs_market"] = -0.01
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")
            (backtest_root / "trading_evidence.json").write_text(
                json.dumps(
                    {
                        "schema_version": "trading_evidence_summary_v0.1",
                        "generated_at_utc": "2026-06-16T23:59:00+00:00",
                        "run_date": "2026-06-15",
                        "status": "OK",
                        "market_making": {"exists": False},
                        "taker": {"exists": False},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            gate = payload["input_gate"]
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "input_inconsistency"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(gate["consistency"]["status"], "FAIL")
        self.assertEqual(
            set(gate["consistency"]["failed_invariants"]),
            {
                "promotion_corpus_vs_settled_labels",
                "trading_evidence_run_date",
                "candidate_delta_vs_current",
                "candidate_delta_vs_market",
            },
        )
        self.assertEqual(learning["priority"], "P0")
        self.assertTrue(learning["blocker"])

    def test_build_learning_payload_blocks_mixed_target_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "settled_day_root_cause.json").write_text(
                json.dumps(
                    {
                        "schema_version": "settled_day_root_cause_v0.1",
                        "generated_at_utc": "2026-06-16T23:58:00+00:00",
                        "target_date": "2026-06-15",
                        "status": "OK",
                        "summary": {},
                    }
                ),
                encoding="utf-8",
            )
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            promotion["corpus"]["date_max"] = "2026-06-15"
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            failed = set(payload["input_gate"]["consistency"]["failed_invariants"])

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertIn("settled_day_root_cause_target_date", failed)
        self.assertIn("promotion_refresh_corpus_date_max", failed)
        self.assertFalse(payload["retrain_plan"]["training_ready"])

    def test_build_learning_payload_blocks_stale_model_scoring_liveness(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "hourly_model_performance.json").write_text(
                json.dumps(
                    {
                        "schema_version": "hourly_model_performance_v0.3",
                        "generated_at_utc": "2026-06-16T23:58:30+00:00",
                        "last_scored_target_date": "2026-06-15",
                        "latest_settled_label_date": "2026-06-16",
                        "corpus": {"date_max": "2026-06-15"},
                        "hourly_performance_gate": {"status": "PASS"},
                        "scoring_liveness": {
                            "status": "BLOCK",
                            "artifact_name": "hourly_model_performance",
                            "last_scored_target_date": "2026-06-15",
                            "latest_settled_label_date": "2026-06-16",
                            "first_blocker": {
                                "gate": "model_scoring_liveness_stale",
                                "detail": "hourly_model_performance is stale",
                                "remediation_command": "python -m weather.reporting.hourly.hourly_model_performance",
                            },
                            "remediation_command": "python -m weather.reporting.hourly.hourly_model_performance",
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "model_scoring_liveness"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(learning["priority"], "P0")
        self.assertTrue(learning["blocker"])
        self.assertIn("hourly_model_performance is stale", learning["signal"])
        self.assertEqual(
            payload["scorecard"]["hourly_model_performance"]["scoring_liveness"]["status"],
            "BLOCK",
        )

    def test_build_learning_payload_blocks_disagreement_rehydration_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            path = backtest_root / "model_market_disagreement_analysis.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["rehydration"] = {
                "status": "BLOCK",
                "target_date": "2026-06-16",
                "pending_before_count": 1,
                "rehydrated_count": 0,
                "excluded_partial_label_count": 0,
                "excluded_missing_label_count": 0,
                "pending_after_count": 1,
                "unresolved_after_rehydrate_count": 1,
                "blocker_count": 1,
                "blockers": [
                    {
                        "gate": "target_date_complete_label_rows_still_pending",
                        "detail": "1 target-date disagreement row remains unresolved despite complete canonical labels",
                    }
                ],
            }
            payload["summary"]["rehydration_status"] = "BLOCK"
            path.write_text(json.dumps(payload), encoding="utf-8")

            learning_payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            learning = next(
                row for row in learning_payload["learnings"]
                if row["category"] == "disagreement_audit_rehydration"
            )

        self.assertEqual(learning_payload["status"], "BLOCKED")
        self.assertEqual(learning["priority"], "P0")
        self.assertTrue(learning["blocker"])
        self.assertIn("unresolved despite complete canonical labels", learning["signal"])

    def test_build_learning_payload_defaults_run_date_to_trading_evidence_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "trading_evidence.json").write_text(
                json.dumps(
                    {
                        "schema_version": "trading_evidence_summary_v0.1",
                        "generated_at_utc": "2026-06-17T00:01:00+00:00",
                        "run_date": "2026-06-15",
                        "status": "OK",
                        "market_making": {"exists": False},
                        "taker": {"exists": False},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            trading_check = next(
                row for row in payload["input_gate"]["consistency"]["checks"]
                if row["name"] == "trading_evidence_run_date"
            )

        self.assertEqual(payload["run_date"], "2026-06-15")
        self.assertEqual(trading_check["status"], "PASS")

    def test_label_consistency_uses_csv_and_explained_corpus_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            daily_path = backtest_root / "daily_refresh_status.json"
            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            daily["summary"].pop("labels")
            daily_path.write_text(json.dumps(daily), encoding="utf-8")
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            promotion["corpus"]["market_day_count"] = 3
            promotion["corpus"]["quality_grades"] = ["complete", "manual_override"]
            promotion["corpus"]["skipped_by_reason"] = {"too_few_replay_inputs": 1}
            promotion["corpus"]["skipped_count"] = 1
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")
            (backtest_root / "market_day_labels.csv").write_text(
                "\n".join(
                    [
                        "event_slug,quality_grade,reconciliation_status,settlement_source",
                        "slug-1,complete,match,daily_summary",
                        "slug-2,complete,match,daily_summary",
                        "slug-3,complete,match,daily_summary",
                        "slug-4,complete,match,daily_summary",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            gate = payload["input_gate"]
            label_check = next(
                row for row in gate["consistency"]["checks"]
                if row["name"] == "promotion_corpus_vs_settled_labels"
            )

        self.assertEqual(payload["scorecard"]["labels"]["source"], "market_day_labels_csv")
        self.assertEqual(payload["scorecard"]["labels"]["total"], 4)
        self.assertEqual(label_check["status"], "PASS")
        self.assertEqual(label_check["evidence"]["countable_corpus_skip_count"], 1)
        self.assertNotIn(
            "promotion_corpus_vs_settled_labels",
            gate["consistency"]["failed_invariants"],
        )

    def test_build_learning_payload_blocks_when_quality_gates_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root, blocked=True)

            payload = build_learning_payload(backtest_root=backtest_root)

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertGreaterEqual(payload["summary"]["blocker_count"], 1)

    def test_promotion_ready_fails_closed_when_candidate_improvement_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            del promotion["candidate"]["aggregate"]["delta_vs_current"]
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            retrain = payload["retrain_plan"]

        self.assertTrue(retrain["training_ready"])
        self.assertFalse(retrain["promotion_ready"])
        self.assertFalse(retrain["beats_current_model"])
        self.assertIn("candidate_delta_vs_current_measured", retrain["promotion_ready_reasons"])

    def test_promotion_ready_requires_confident_independent_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            promotion["corpus"]["market_day_count"] = 40
            promotion["candidate"]["aggregate"]["rows"] = 400
            promotion["candidate"]["paired_delta_samples"] = [
                {
                    "market_day": f"day-{index:02d}",
                    "delta_vs_current": -0.01,
                    "delta_vs_market": 0.002,
                }
                for index in range(40)
            ]
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")
            daily_path = backtest_root / "daily_refresh_status.json"
            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            daily["summary"]["labels"]["total"] = 40
            daily["summary"]["labels"]["quality_counts"] = {"complete": 40}
            daily_path.write_text(json.dumps(daily), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            confidence = payload["retrain_plan"]["promotion_confidence"]

        self.assertTrue(payload["retrain_plan"]["promotion_ready"])
        self.assertEqual(confidence["delta_vs_current"]["status"], "PASS")
        self.assertLessEqual(confidence["delta_vs_current"]["ci_high"], 0)

    def test_partial_labels_are_diagnostic_only_for_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            promotion["corpus"]["market_day_count"] = 40
            promotion["candidate"]["aggregate"]["rows"] = 400
            promotion["candidate"]["paired_delta_samples"] = [
                {
                    "market_day": f"day-{index:02d}",
                    "delta_vs_current": -0.01,
                    "delta_vs_market": -0.002,
                }
                for index in range(40)
            ]
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")
            daily_path = backtest_root / "daily_refresh_status.json"
            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            daily["summary"]["labels"]["total"] = 40
            daily["summary"]["labels"]["quality_counts"] = {"complete": 39, "partial": 1}
            daily_path.write_text(json.dumps(daily), encoding="utf-8")
            barrier_path = backtest_root / "settled_day_analysis_barrier.json"
            barrier = json.loads(barrier_path.read_text(encoding="utf-8"))
            barrier["status"] = "DIAGNOSTIC_ONLY"
            barrier["label_countability"] = {
                "status": "diagnostic_only",
                "promotion_countable": False,
                "diagnostic_only": True,
                "partial_label_count": 1,
                "quality_counts": {"complete": 39, "partial": 1},
                "reason": "1 settled label(s) have quality_grade=partial",
            }
            barrier_path.write_text(json.dumps(barrier), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            categories = {row["category"] for row in payload["learnings"]}

        self.assertEqual(payload["scorecard"]["label_countability"]["status"], "diagnostic_only")
        self.assertFalse(payload["retrain_plan"]["promotion_ready"])
        self.assertIn("labels_promotion_countable", payload["retrain_plan"]["promotion_ready_reasons"])
        self.assertIn("label_countability", categories)
        self.assertFalse(
            next(row for row in payload["learnings"] if row["category"] == "new_training_evidence")[
                "retrain_input"
            ]
        )

    def test_promotion_ready_blocks_correlated_delta_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            promotion["corpus"]["market_day_count"] = 40
            promotion["candidate"]["aggregate"]["rows"] = 400
            promotion["candidate"]["paired_delta_samples"] = [
                {
                    "market_day": "same-market-day",
                    "delta_vs_current": -0.01,
                    "delta_vs_market": -0.002,
                }
                for _index in range(40)
            ]
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")
            daily_path = backtest_root / "daily_refresh_status.json"
            daily = json.loads(daily_path.read_text(encoding="utf-8"))
            daily["summary"]["labels"]["total"] = 40
            daily["summary"]["labels"]["quality_counts"] = {"complete": 40}
            daily_path.write_text(json.dumps(daily), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            confidence = payload["retrain_plan"]["promotion_confidence"]

        self.assertFalse(payload["retrain_plan"]["promotion_ready"])
        self.assertEqual(confidence["delta_vs_current"]["independent_market_day_count"], 1)
        self.assertIn(
            "delta_vs_current_independent_market_days_below_30",
            payload["retrain_plan"]["promotion_ready_reasons"],
        )

    def test_candidate_rows_preserves_zero_without_falling_back_to_n(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion_path = backtest_root / "f_family_promotion_refresh.json"
            promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
            promotion["candidate"]["aggregate"]["rows"] = 0
            promotion["candidate"]["aggregate"]["n"] = 99
            promotion_path.write_text(json.dumps(promotion), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)

        self.assertEqual(payload["scorecard"]["candidate"]["rows"], 0)
        self.assertFalse(payload["retrain_plan"]["promotion_ready"])
        self.assertIn("candidate_rows_present", payload["retrain_plan"]["promotion_ready_reasons"])

    def test_snapshot_fail_gate_blocks_even_when_severity_is_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            snapshot_path = backtest_root / "snapshot_evaluation.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["gates"] = [
                {
                    "name": "candidate_vs_market",
                    "status": "FAIL",
                    "severity": "warn",
                    "detail": "candidate failed without fail severity",
                    "action": "Investigate candidate gate.",
                }
            ]
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            gate_learning = next(
                row for row in payload["learnings"]
                if row["category"] == "validation_gate"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(gate_learning["priority"], "P0")
        self.assertTrue(gate_learning["blocker"])

    def test_capped_learning_sources_sort_before_truncating_and_report_drops(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            audit_path = backtest_root / "data_layer_audit.json"
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["recommendations"] = [
                {"priority": "P2", "area": f"low-{index}", "impact": index}
                for index in range(8)
            ] + [
                {
                    "priority": "P0",
                    "area": "late-p0",
                    "recommendation": "Repair the late P0 recommendation first.",
                    "impact": 0,
                }
            ]
            audit_path.write_text(json.dumps(audit), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            data_learnings = [
                row for row in payload["learnings"]
                if row["source"] == "data_layer_audit" and row["category"] == "data_quality"
            ]
            truncated = payload["summary"]["truncated_sources"]

        self.assertTrue(any(row["signal"] == "late-p0" for row in data_learnings))
        self.assertTrue(all("estimated_impact" in row for row in data_learnings))
        self.assertTrue(any(row["source"] == "data_layer_audit.recommendations" for row in truncated))
        self.assertEqual(
            next(row for row in truncated if row["source"] == "data_layer_audit.recommendations")["dropped_count"],
            1,
        )

    def test_build_learning_payload_blocks_on_taker_finalization_and_tail_no_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "taker_finalization_watchdog.json").write_text(
                json.dumps(
                    {
                        "schema_version": "taker_settlement_finalization_watchdog_v0.1",
                        "status": "BREACH",
                        "summary": {
                            "run_count": 2,
                            "pending_finalization_count": 1,
                            "sla_breach_count": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (backtest_root / "taker_tail_casebook.json").write_text(
                json.dumps(
                    {
                        "schema_version": "taker_tail_casebook_v0.1",
                        "summary": {
                            "status": "BLOCK_BAD_TAIL_SLICES",
                            "tail_fill_count": 3,
                            "losing_tail_fill_count": 2,
                            "no_go_candidate_count": 1,
                        },
                        "no_go_candidates": [
                            {"slice_key": "low_price_tail|atlanta|hour:16", "loss_count": 2}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            categories = {row["category"] for row in payload["learnings"]}
            report = render_report(payload)

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertIn("taker_settlement_finalization", categories)
        self.assertIn("taker_tail_no_go", categories)
        self.assertIn("Taker finalization SLA breaches", report)
        self.assertIn("Taker tail no-go candidates", report)

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
                            "inventory_command": "python -m weather.reporting.source_gates.source_family_inventory",
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

    def test_build_learning_payload_summarizes_sidecar_coverage_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            audit = json.loads((backtest_root / "data_layer_audit.json").read_text(encoding="utf-8"))
            audit["snapshots"] = {
                "sidecar_eligibility": {
                    "primary_label_counts": {
                        "market_aware_ready": 1,
                        "score_only": 2,
                    },
                    "label_counts": {
                        "score_only": 3,
                        "market_aware_ready": 1,
                    },
                    "backfill_candidate_folder_count": 2,
                    "active_day_sidecar_regression_count": 0,
                    "non_reconstructable_gap_counts": {"market_ws_events": 2},
                }
            }
            (backtest_root / "data_layer_audit.json").write_text(
                json.dumps(audit),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            categories = {row["category"] for row in payload["learnings"]}

        self.assertIn("sidecar_coverage_mix", categories)
        self.assertEqual(
            payload["scorecard"]["data_layer_audit"]["sidecar_eligibility"]["primary_label_counts"]["score_only"],
            2,
        )

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

    def test_build_learning_payload_prioritizes_exact_band_and_warm_tail_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            rewrite_json(
                backtest_root / "model_market_disagreement_analysis.json",
                lambda payload: payload.update(
                    {
                        "recommendations": [
                            {
                                "priority": "P1",
                                "category": "model_repair_candidate",
                                "market_id": "nyc",
                                "range_label": "82 F",
                                "direction": "market_higher_than_model",
                                "evidence": {"case_count": 3, "market_closer_count": 3},
                                "route": {
                                    "repair_lane": "exact-band/winner-centering",
                                    "owner": "exact-band winner-centering repair",
                                    "roadmap_owner": "Items 70, 147, 230",
                                    "next_experiment": "audit_exact_band_winner_centering_replay",
                                    "experiment_artifact": "data/backtest/experiments/audit_exact_band_winner_centering_replay.json",
                                    "counts_toward_repair_evidence": True,
                                },
                            },
                            {
                                "priority": "P1",
                                "category": "model_repair_candidate",
                                "market_id": "seattle",
                                "range_label": "90-91 F",
                                "direction": "model_higher_than_market",
                                "evidence": {"case_count": 3, "market_closer_count": 3},
                                "route": {
                                    "repair_lane": "warm-tail dampening",
                                    "owner": "warm-tail spread repair",
                                    "roadmap_owner": "Items 195, 232, 236",
                                    "next_experiment": "audit_warm_tail_dampening_replay",
                                    "experiment_artifact": "data/backtest/experiments/audit_warm_tail_dampening_replay.json",
                                    "counts_toward_repair_evidence": True,
                                },
                            },
                        ],
                    }
                ),
            )
            rewrite_json(
                backtest_root / "winner_rank_parity.json",
                lambda payload: payload.update(
                    {
                        "status": "BLOCK",
                        "summary": {"route_count": 2, "parity_gate_status": "BLOCK"},
                        "parity_gate": {"status": "BLOCK", "blocker_count": 1},
                        "top_owner_routes": [
                            {
                                "slice": "band_type",
                                "value": "eq",
                                "snapshot_count": 8,
                                "owner_items": [230],
                                "model_top_miss_market_top_hit_brier_contribution": 0.012,
                            },
                            {
                                "slice": "forecast_bucket_pressure",
                                "value": "warm_side",
                                "snapshot_count": 6,
                                "owner_items": [194, 195, 232],
                                "model_top_miss_market_top_hit_brier_contribution": 0.009,
                            },
                        ],
                    }
                ),
            )

            payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            research = [
                row for row in payload["learnings"]
                if row["category"] == "market_skill_gap"
                and row["source"] in {"model_market_disagreement_analysis", "winner_rank_parity"}
            ]
            signals = "\n".join(row["signal"] for row in research)
            queue_hypotheses = "\n".join(row["hypothesis"] for row in payload["experiment_queue"]["items"])

        self.assertIn("exact-band/winner-centering", signals)
        self.assertIn("warm-tail dampening", signals)
        self.assertTrue(all(row["retrain_input"] for row in research))
        self.assertEqual(payload["scorecard"]["winner_rank_parity"]["status"], "BLOCK")
        self.assertIn("audit_exact_band_winner_centering_replay", queue_hypotheses)
        self.assertIn("audit_warm_tail_dampening_replay", queue_hypotheses)

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
                                "remediation_command": "python -m weather.reporting.hourly.hourly_model_performance",
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
                            "summary": {
                                "row_count": 1,
                                "early_hour_market_delta_count": 1,
                                "early_hour_blocked_market_count": 1,
                            },
                            "early_hour_market_deltas": [
                                {
                                    "market_id": "toronto",
                                    "status": "BLOCK",
                                    "blocking_gates": ["early_hour_brier_regression"],
                                    "n": 12,
                                    "market_days": 1,
                                    "model_brier": 0.080,
                                    "market_brier": 0.040,
                                    "brier_delta": -0.040,
                                    "model_logloss": 0.320,
                                    "market_logloss": 0.120,
                                    "logloss_delta": -0.200,
                                }
                            ],
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
            market_delta_learning = next(
                row for row in payload["learnings"]
                if row["category"] == "hourly_early_market_delta"
            )
            report = render_report(payload)

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["scorecard"]["hourly_model_performance"]["status"], "BLOCK")
        self.assertEqual(
            payload["scorecard"]["hourly_model_performance"]["early_hour_market_deltas"][0]["market_id"],
            "toronto",
        )
        self.assertTrue(gate_learning["blocker"])
        self.assertIn("early-hour model Brier trails market", gate_learning["signal"])
        self.assertIn("hourly_model_performance", gate_learning["source"])
        self.assertTrue(registry_learning["retrain_input"])
        self.assertIn("early_hour_profile_bias", registry_learning["signal"])
        self.assertIn("weather-only early-hour remediation", registry_learning["signal"])
        self.assertTrue(market_delta_learning["retrain_input"])
        self.assertIn("toronto early-hour model trails market", market_delta_learning["signal"])
        self.assertIn("## Early-Hour Market Deltas", report)

    def test_build_learning_payload_blocks_on_ten_minute_performance_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "ten_minute_model_performance.json").write_text(
                json.dumps(
                    {
                        "schema_version": "ten_minute_model_performance_v0.1",
                        "ten_minute_performance_gate": {
                            "schema_version": "ten_minute_performance_gate_v0.1",
                            "status": "BLOCK",
                            "first_blocker": {
                                "gate": "weak_slot_brier_regression",
                                "detail": "03:00 weak-slot model Brier trails market by 0.0129",
                                "remediation_command": "python -m weather.reporting.hourly.ten_minute_model_performance",
                            },
                            "blockers": [],
                        },
                        "candidate_ten_minute_gate": {
                            "schema_version": "candidate_ten_minute_performance_gate_v0.1",
                            "status": "MISSING",
                        },
                        "weak_slots": {
                            "slot_labels": ["03:00", "03:10"],
                        },
                        "daily_summary": {
                            "weak_slots": ["03:00", "03:10"],
                            "worst_slots": ["03:00"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            gate_learning = next(
                row for row in payload["learnings"]
                if row["category"] == "ten_minute_performance_gate"
            )
            report = render_report(payload)

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(payload["scorecard"]["ten_minute_model_performance"]["status"], "BLOCK")
        self.assertTrue(gate_learning["blocker"])
        self.assertIn("03:00 weak-slot model Brier trails market", gate_learning["signal"])
        self.assertIn("03:00, 03:10", gate_learning["signal"])
        self.assertIn("## 10-Minute Weak-Slot Gate", report)

    def test_build_learning_payload_surfaces_early_hour_promotion_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            promotion = json.loads((backtest_root / "f_family_promotion_refresh.json").read_text(encoding="utf-8"))
            promotion["early_hour_promotion_blocker"] = {
                "schema_version": "early_hour_promotion_blocker_v0.1",
                "status": "BLOCK",
                "promotion_allowed": False,
                "blocker_count": 2,
                "current_gates": {
                    "hourly": {"status": "BLOCK"},
                    "ten_minute": {"status": "BLOCK"},
                },
                "candidate_gates": {
                    "hourly": {"gate_status": "BLOCK"},
                    "ten_minute": {"gate_status": "PASS"},
                },
                "broad_replay": {"within_market_tolerance": False},
                "production_readiness": {
                    "live_forward_slo": {"status": "BLOCK"},
                    "current_code_soak": {"status": "PASS"},
                },
                "blockers": [
                    {
                        "category": "candidate_hourly_mitigation",
                        "severity": "block",
                        "detail": "candidate hourly gate must PASS",
                    },
                    {
                        "category": "broad_replay_market_tolerance",
                        "severity": "block",
                        "detail": "candidate replay must be within tolerance",
                    },
                ],
            }
            (backtest_root / "f_family_promotion_refresh.json").write_text(
                json.dumps(promotion),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "early_hour_promotion_blocker"
            )
            report = render_report(payload)

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["scorecard"]["promotion"]["early_hour_promotion_allowed"])
        self.assertTrue(learning["blocker"])
        self.assertIn("candidate_hourly_mitigation", learning["signal"])
        self.assertIn("candidate-specific hourly and 10-minute gates", learning["action"])
        self.assertIn("## Early-Hour Promotion Blocker", report)
        self.assertIn("candidate hourly gate must PASS", report)

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

    def test_build_learning_payload_surfaces_clean_active_day_countability(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            fleet = json.loads((backtest_root / "fleet_observability.json").read_text(encoding="utf-8"))
            fleet["clean_active_day_countability"] = {
                "status": "BLOCK",
                "target_date": "2026-06-16",
                "counts_toward_clean_active_day": False,
                "counts_toward_early_hour_evidence": False,
                "operational_blocker_count": 1,
                "first_blocker": {
                    "name": "early_hour_coverage",
                    "detail": "12/48 minimum early-hour snapshots",
                },
                "early_hour_coverage_proof": {
                    "summary": {
                        "status": "BLOCK",
                        "countable_market_count": 0,
                        "total_snapshot_count": 12,
                        "total_missing_snapshot_count": 36,
                        "total_gap_count": 0,
                    },
                },
            }
            (backtest_root / "fleet_observability.json").write_text(json.dumps(fleet), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            report = render_report(payload)
            learning = next(
                row for row in payload["learnings"]
                if row["category"] == "clean_active_day_countability"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertFalse(payload["retrain_plan"]["training_ready"])
        self.assertFalse(payload["retrain_plan"]["clean_active_day_countability"]["counts_toward_early_hour_evidence"])
        self.assertTrue(learning["blocker"])
        self.assertIn("early_hour_coverage", learning["signal"])
        self.assertIn("## Clean Active-Day Countability", report)
        self.assertIn("12/48 minimum early-hour snapshots", report)

    def test_build_learning_payload_blocks_on_current_code_soak(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            fleet = json.loads((backtest_root / "fleet_observability.json").read_text(encoding="utf-8"))
            fleet["current_code_soak"] = {
                "status": "BLOCK",
                "counts_toward_active_day": False,
                "cadence_slo_status": "PASS",
                "summary": {
                    "restart_count": 9,
                    "first_blocking_loop": "snapshot_capture",
                    "first_blocking_reason": "runtime_code_state=stale_code",
                    "benign_duplicate_writer_block_count": 3,
                    "duplicate_writer_incident_count": 0,
                },
                "loops": [
                    {
                        "name": "snapshot_capture",
                        "status": "BLOCK",
                        "state": "STALE_CODE",
                        "runtime_code_state": "stale_code",
                        "single_writer": True,
                        "restart_count": 9,
                        "restart_budget": 6,
                        "duplicate_writer_incidents": 0,
                        "benign_duplicate_writer_blocks": 3,
                        "malformed_lines": 0,
                        "blocking_reasons": ["runtime_code_state=stale_code"],
                    }
                ],
            }
            (backtest_root / "fleet_observability.json").write_text(json.dumps(fleet), encoding="utf-8")

            payload = build_learning_payload(backtest_root=backtest_root)
            learning = next(row for row in payload["learnings"] if row["category"] == "current_code_soak")
            report = render_report(payload)

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertTrue(learning["blocker"])
        self.assertIn("snapshot_capture", learning["signal"])
        self.assertIn("## Current-Code Soak Proof", report)
        self.assertIn("runtime_code_state=stale_code", report)

    def test_build_learning_payload_tracks_trading_evidence_without_overclaiming(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backtest_root = root / "backtest"
            write_daily_artifacts(backtest_root)
            mm_run = root / "mm_runs" / "2026-06-19" / "mm-1"
            mm_run.mkdir(parents=True)
            (mm_run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "mm-1",
                        "target_date": "2026-06-19",
                        "mode": "paper-live-forward",
                        "evidence_mode": "operator_drill",
                        "counts_toward_live_forward_gate": False,
                        "preflight_status": "PASS",
                        "markets": ["toronto"],
                        "cumulative_quote_permission_rows": 4019,
                        "cumulative_paper_posted_count": 8026,
                        "cumulative_live_trade_permission_rows": 0,
                        "live_forward_gate": {
                            "status": "BLOCK",
                            "summary": {"evidence_mode_reason": "operator override"},
                            "evidence": {},
                        },
                    }
                ),
                encoding="utf-8",
            )
            taker_run = root / "taker_runs" / "2026-06-19" / "taker-1"
            taker_run.mkdir(parents=True)
            (taker_run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "run_id": "taker-1",
                        "target_date": "2026-06-19",
                        "mode": "paper-taker",
                        "exchange_economics_gate": {
                            "required": True,
                            "ok": True,
                            "status": "PASS",
                            "snapshot_id": "xecon-test",
                            "snapshot_hash": "hash-test",
                            "evidence_basis": "current_exchange_economics",
                        },
                        "exchange_economics_snapshot_id": "xecon-test",
                        "exchange_economics_hash": "hash-test",
                        "exchange_economics_evidence_basis": "current_exchange_economics",
                        "summary": {
                            "cumulative_filled_orders": 50,
                            "budget_spent_usdc": 59.80507,
                            "cumulative_net_pnl_usdc": -17.208695,
                            "root_cause_class": "policy_no_edge",
                            "first_failing_gate": "policy",
                        },
                        "pnl": {
                            "summary": {
                                "filled_order_count": 50,
                                "net_pnl_usdc": -17.208695,
                                "mark_to_market_pnl_usdc": -17.208695,
                                "settled_order_count": 0,
                                "unsettled_order_count": 50,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (taker_run / "settled_pnl.json").write_text(
                json.dumps(
                    {
                        "schema_version": "taker_settlement_finalization_v0.1",
                        "run_id": "taker-1",
                        "target_date": "2026-06-19",
                        "settled_pnl_path": str(taker_run / "settled_pnl.json"),
                        "settled_report_path": str(taker_run / "settled_report.md"),
                        "summary": {
                            "filled_order_count": 4,
                            "budget_spent_usdc": 59.80507,
                            "net_pnl_usdc": 36.687839,
                            "settlement_pnl_usdc": 36.687839,
                            "mark_to_market_pnl_usdc": 0.0,
                            "settled_order_count": 4,
                            "unsettled_order_count": 0,
                            "pnl_source": "settlement_finalization",
                        },
                        "pnl": {
                            "summary": {
                                "filled_order_count": 4,
                                "budget_spent_usdc": 59.80507,
                                "net_pnl_usdc": 36.687839,
                                "settlement_pnl_usdc": 36.687839,
                                "mark_to_market_pnl_usdc": 0.0,
                                "settled_order_count": 4,
                                "unsettled_order_count": 0,
                            }
                        },
                        "reconciliation": {
                            "status": "WARN",
                            "preferred_pnl_source": "settlement_finalization",
                            "warnings": [
                                {"code": "reported_mark_to_market_diverges_from_settlement", "detail": "diff"}
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            categories = {row["category"] for row in payload["learnings"]}
            report = render_report(payload)

        self.assertIn("market_making_evidence", categories)
        self.assertIn("taker_strategy_quality", categories)
        self.assertEqual(
            payload["scorecard"]["trading_evidence"]["market_making"]["evidence_mode"],
            "operator_drill",
        )
        self.assertFalse(
            payload["scorecard"]["trading_evidence"]["market_making"]["counts_toward_live_forward_gate"]
        )
        self.assertEqual(
            payload["scorecard"]["trading_evidence"]["taker"]["quality_gate"]["status"],
            "SAMPLE_PENDING",
        )
        self.assertEqual(
            payload["scorecard"]["trading_evidence"]["taker"]["pnl_source"],
            "settlement_finalization",
        )
        self.assertAlmostEqual(
            payload["scorecard"]["trading_evidence"]["taker"]["settlement_pnl_usdc"],
            36.687839,
        )
        self.assertIn("## Trading Evidence", report)
        self.assertIn("operator_drill", report)
        self.assertIn("settlement_finalization", report)

    def test_build_learning_payload_blocks_taker_latest_tick_starvation(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "trading_evidence.json").write_text(
                json.dumps(
                    {
                        "schema_version": "trading_evidence_summary_v0.1",
                        "generated_at_utc": "2026-06-16T23:59:00+00:00",
                        "run_date": "2026-06-16",
                        "target_date": "2026-06-16",
                        "status": "BLOCK",
                        "market_making": {"exists": False},
                        "taker": {
                            "exists": True,
                            "run_id": "taker-starved",
                            "filled_orders": 0,
                            "net_pnl_usdc": 0.0,
                            "pnl_source": "unscored",
                            "pnl_evidence_status": "UNSCORED",
                            "settled_order_count": 0,
                            "unsettled_order_count": 0,
                            "low_price_tail_fill_count": 0,
                            "root_cause_class": "crashed_before_scoring",
                            "zero_fill_quality_classification": "unscored_stale_labels",
                            "taker_day_classification": "scoring_crash",
                            "zero_would_buy_classification": "scoring_crash",
                            "taker_evidence_countability_status": "NON_COUNTABLE",
                            "blocks_taker_evidence_countability": True,
                            "latest_tick_scoring_liveness": {
                                "status": "BLOCK",
                                "classification": "scoring_crash",
                                "latest_tick_rows": 0,
                            },
                            "quality_gate": {"status": "SAMPLE_PENDING", "sample_ready": False},
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            learning = next(row for row in payload["learnings"] if row["category"] == "taker_strategy_quality")
            report = render_report(payload)

        self.assertEqual(learning["priority"], "P0")
        self.assertTrue(learning["blocker"])
        self.assertIn("taker_day_classification=scoring_crash", learning["signal"])
        self.assertIn("scoring_crash", report)

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
                    "verification_command": "python -m weather.reporting.fleet.fleet_observability report",
                },
                "recovery_checklist": [
                    {
                        "market_id": "toronto",
                        "component": "snapshot_collection",
                        "gate": "latest_model_row_freshness",
                        "owner": "weather snapshot/model loop",
                        "before": "latest_age_minutes=40.0",
                        "repair_command": "python -m weather.collection.snapshot_tracker --status",
                        "verification_command": "python -m weather.reporting.fleet.fleet_observability report",
                    }
                ],
                "snapshot_cadence_proof": {
                    "summary": {
                        "status": "BLOCK",
                        "blocked_market_count": 1,
                        "snapshot_coverage_gap_blocked_market_count": 1,
                        "total_gap_count": 1,
                        "max_gap_minutes": 34.0,
                    },
                    "status_command": "python -m weather.collection.snapshot_tracker --status",
                    "repair_command": "python -m weather.collection.snapshot_tracker --restart",
                    "verification_command": "python -m weather.reporting.fleet.fleet_observability report",
                    "markets": [
                        {
                            "market_id": "toronto",
                            "status": "BLOCK",
                            "blocking_gates": ["snapshot_coverage_gap"],
                            "snapshot_count": 42,
                            "gap_count": 1,
                            "max_gap_minutes": 34.0,
                            "root_cause": "unknown_snapshot_gap",
                            "recoverable_same_day": False,
                            "gap_windows": [
                                {
                                    "after": "2026-06-19T12:00:00-04:00",
                                    "before": "2026-06-19T12:34:00-04:00",
                                    "gap_minutes": 34.0,
                                }
                            ],
                        }
                    ],
                },
                "rerun_command": "python -m weather.reporting.fleet.fleet_observability report",
                "summary": {
                    "first_blocking_market": "toronto",
                    "first_blocking_gate": "latest_model_row_freshness",
                    "recovery_row_count": 1,
                },
            }
            fleet["collection"] = {
                "source_status_proof": {
                    "summary": {
                        "source_status_blocked_market_count": 1,
                        "live_trade_permission_blocked_market_count": 1,
                        "promotion_readiness_blocked_market_count": 1,
                        "top_degraded_family": "open_meteo",
                        "provider_cooldown_source_count": 1,
                    },
                    "markets": [
                        {
                            "market_id": "toronto",
                            "model_review_allowed": True,
                            "paper_trading_allowed": True,
                            "live_trade_permission_allowed": False,
                            "promotion_readiness_allowed": False,
                            "affected_family_count": 1,
                            "blocking_family_count": 0,
                            "provider_cooldown_source_count": 1,
                            "top_degraded_family": "open_meteo",
                            "affected_families": [
                                {
                                    "family": "open_meteo",
                                    "status": "rate_limited_with_fresh_family_coverage",
                                    "fallback_source_count": 0,
                                    "rate_limited_source_count": 1,
                                    "provider_cooldown_source_count": 1,
                                    "max_retry_after_seconds": 60.0,
                                    "max_cache_age_minutes": 0.5,
                                }
                            ],
                        }
                    ],
                }
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
        self.assertIn("Snapshot cadence proof", report)
        self.assertIn("unknown_snapshot_gap", report)
        self.assertIn("12:00->12:34", report)
        self.assertIn("## Source Status Proof", report)
        self.assertIn("open_meteo", report)
        self.assertIn("Live-trade blocked markets", report)
        self.assertEqual(
            payload["retrain_plan"]["broad_live_forward_slo"]["snapshot_cadence_proof"]["summary"][
                "snapshot_coverage_gap_blocked_market_count"
            ],
            1,
        )
        self.assertEqual(
            payload["scorecard"]["fleet"]["source_status_proof"]["summary"][
                "source_status_blocked_market_count"
            ],
            1,
        )

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

    def test_build_learning_payload_emits_calibration_and_bias_drift_learnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "proper_scoring_reliability_scorecard.json").write_text(
                json.dumps(
                    {
                        "schema_version": "proper_scoring_reliability_scorecard_v0.1",
                        "generated_at_utc": "2026-06-16T23:59:50+00:00",
                        "status": "WARN",
                        "lanes": [
                            {
                                "lane": "weather_only",
                                "row_count": 200,
                                "ece": 0.08,
                            }
                        ],
                        "directional_bias": {
                            "source": "fixture",
                            "mean_realized_minus_predicted": 1.2,
                        },
                    }
                ),
                encoding="utf-8",
            )
            ledger_rows = [
                {
                    "schema_version": "daily_progress_ledger_v0.1",
                    "run_date": f"2026-06-{day:02d}",
                    "model_calibration_ece": ece,
                    "model_directional_bias_abs_mean_error": bias,
                }
                for day, ece, bias in [
                    (13, 0.02, 0.1),
                    (14, 0.03, 0.2),
                    (15, 0.02, 0.1),
                ]
            ]
            (backtest_root / "daily_progress_ledger.jsonl").write_text(
                "\n".join(json.dumps(row) for row in ledger_rows) + "\n",
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            categories = {row["category"] for row in payload["learnings"]}
            report = render_report(payload)

        self.assertIn("calibration_drift", categories)
        self.assertIn("directional_bias_drift", categories)
        self.assertEqual(payload["scorecard"]["calibration_monitoring"]["calibration_ece"], 0.08)
        self.assertEqual(payload["scorecard"]["calibration_monitoring"]["directional_bias_mean_error"], 1.2)
        self.assertTrue(payload["retrain_plan"]["retrain_recommendation"]["recommended"])
        self.assertIn("Calibration and bias", report)

    def test_build_learning_payload_emits_experiment_queue_and_reconciles_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            queue_id = "item301:2026-06-23:seattle:cold_miss"
            (backtest_root / "june23_location_bias_repair_packet.json").write_text(
                json.dumps(
                    {
                        "schema_version": "june23_location_bias_repair_v0.1",
                        "generated_at_utc": "2026-06-16T23:59:45+00:00",
                        "status": "ACTIONABLE",
                        "experiment_queue_items": [
                            {
                                "queue_id": queue_id,
                                "source": "june23_location_bias_repair_packet",
                                "target_date": "2026-06-23",
                                "market_id": "seattle",
                                "slice": "market_id=seattle;bias=cold_miss",
                                "hypothesis": "repair seattle cold miss",
                                "artifact_path": str(backtest_root / "june23_location_bias_repair_packet.json"),
                                "clearance_rule": "protect winners",
                                "status": "eligible",
                                "priority": "P1",
                                "command": ["python", "-m", "weather.reporting.location_analysis.june23_location_bias_repair"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (backtest_root / "experiment_queue_results.json").write_text(
                json.dumps(
                    {
                        "schema_version": "experiment_queue_results_v0.1",
                        "generated_at_utc": "2026-06-17T03:35:00+00:00",
                        "status": "OK",
                        "results": [
                            {
                                "queue_id": queue_id,
                                "status": "executed",
                                "resolution_status": "resolved",
                                "returncode": 0,
                                "executed_at_utc": "2026-06-17T03:34:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            queue = payload["experiment_queue"]
            queued = {row["queue_id"]: row for row in queue["items"]}
            report = render_report(payload)

        self.assertEqual(queue["schema_version"], "automatic_experiment_queue_v0.1")
        self.assertEqual(queue["summary"]["item301_count"], 1)
        self.assertEqual(queued[queue_id]["status"], "resolved")
        self.assertEqual(queued[queue_id]["last_result"]["resolution_status"], "resolved")
        self.assertIn("Experiment Queue", report)

    def test_build_learning_payload_suppresses_retrain_recommendation_without_clean_triggers(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            rewrite_json(
                backtest_root / "daily_refresh_status.json",
                lambda payload: payload["summary"].update(
                    {
                        "labels": {
                            "total": 0,
                            "quality_counts": {},
                            "reconciliation_counts": {},
                        }
                    }
                ),
            )
            rewrite_json(
                backtest_root / "settled_day_freshness.json",
                lambda payload: payload["summary"].update(
                    {
                        "complete_market_count": 0,
                        "expected_market_count": 0,
                    }
                ),
            )
            rewrite_json(
                backtest_root / "f_family_promotion_refresh.json",
                lambda payload: (
                    payload["corpus"].update(
                        {
                            "market_day_count": 0,
                            "snapshot_count": 0,
                            "band_row_count": 0,
                        }
                    ),
                    payload["candidate"]["aggregate"].update(
                        {
                            "rows": 0,
                            "candidate_brier": 0.08,
                            "current_brier": 0.07,
                            "market_brier": 0.09,
                            "delta_vs_current": 0.01,
                            "delta_vs_market": -0.01,
                        }
                    ),
                    payload.setdefault("gap_owner_table", []),
                ),
            )
            rewrite_json(
                backtest_root / "snapshot_evaluation.json",
                lambda payload: payload["improvement_backlog"].update({"top_slices": []}),
            )
            rewrite_json(
                backtest_root / "model_variant_evidence_growth.json",
                lambda payload: payload.update(
                    {
                        "status": "OK",
                        "delta_vs_baseline": {"unique_observation_count": 0},
                        "alerts": [],
                    }
                ),
            )
            rewrite_json(
                backtest_root / "disagreement_casebook.json",
                lambda payload: payload["summary"].update(
                    {
                        "case_count": 0,
                        "settled_case_count": 0,
                        "model_loss_count": 0,
                    }
                ),
            )

            payload = build_learning_payload(backtest_root=backtest_root, run_date="2026-06-16")
            recommendation = payload["retrain_plan"]["retrain_recommendation"]

        self.assertFalse(recommendation["recommended"])
        self.assertFalse(recommendation["scheduled_fallback"])
        self.assertEqual(recommendation["reasons"][0]["code"], "no_new_drift_or_novelty")

    def test_build_learning_payload_blocks_stale_compact_rollup(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "progress_audit.json").write_text(
                json.dumps({"generated_at_utc": "2026-06-21T12:00:00+00:00", "status": "OK"}),
                encoding="utf-8",
            )
            (backtest_root / "daily_progress_latest.json").write_text(
                json.dumps({"generated_at_utc": "2026-06-20T12:00:00+00:00", "status": "OK"}),
                encoding="utf-8",
            )

            payload = build_learning_payload(
                backtest_root=backtest_root,
                rollup_generated_at_overrides={},
            )
            report = render_report(payload)
            blocker = next(
                row for row in payload["learnings"]
                if row["category"] == "daily_rollup_freshness"
            )

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertIn("daily_progress_latest", blocker["signal"])
        self.assertIn("repair-stale-locks", blocker["action"])
        self.assertIn("## Daily Rollup Freshness", report)
        self.assertIn("progress_audit", report)

    def test_target_date_aligned_artifacts_do_not_fail_on_newer_current_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            for filename in (
                "daily_refresh_status.json",
                "snapshot_evaluation.json",
                "fleet_observability.json",
                "data_layer_audit.json",
            ):
                rewrite_json(
                    backtest_root / filename,
                    lambda payload: payload.update({"generated_at_utc": "2026-06-20T00:00:00+00:00"}),
                )
            rewrite_json(
                backtest_root / "f_family_promotion_refresh.json",
                lambda payload: payload["corpus"].update({"date_max": "2026-06-16"}),
            )

            payload = build_learning_payload(
                backtest_root=backtest_root,
                run_date="2026-06-16",
                input_max_skew_hours=1.0,
            )
            freshness = payload["input_gate"]["freshness"]
            rows = {row["name"]: row for row in freshness["rows"]}

        self.assertNotIn("promotion_refresh", freshness["critical_stale_inputs"])
        self.assertNotIn("event_metadata_validation", freshness["critical_stale_inputs"])
        self.assertNotIn("settled_day_analysis_barrier", freshness["critical_stale_inputs"])
        self.assertNotIn("model_market_disagreement_analysis", freshness["critical_stale_inputs"])
        self.assertTrue(rows["promotion_refresh"]["target_date_aligned"])
        self.assertEqual(rows["promotion_refresh"]["freshness_status"], "PASS")

    def test_build_learning_payload_checks_active_variant_shadow_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "active_variant_shadow.json").write_text(
                json.dumps({"generated_at_utc": "2026-06-21T12:00:00+00:00", "status": "OK"}),
                encoding="utf-8",
            )
            (backtest_root / "daily_progress_latest.json").write_text(
                json.dumps({"generated_at_utc": "2026-06-21T13:00:00+00:00", "status": "OK"}),
                encoding="utf-8",
            )

            payload = build_learning_payload(
                backtest_root=backtest_root,
                generated_at_utc="2026-06-21T11:00:00+00:00",
                rollup_generated_at_overrides={},
            )
            rollup = payload["scorecard"]["rollup_freshness"]

        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(rollup["latest_required_artifact"], "active_variant_shadow")
        self.assertEqual(rollup["blockers"][0]["rollup"], "daily_learning")

    def test_build_learning_payload_surfaces_root_cause_explanation_tape(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "settled_day_root_cause.json").write_text(
                json.dumps(
                    {
                        "status": "ACTIONABLE",
                        "target_date": "2026-06-20",
                        "summary": {
                            "explanation_snapshot_count": 3,
                            "explanation_coverage_rate": 0.75,
                            "explanation_sections": ["analog_search", "model_explanation"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)
            report = render_report(payload)
            row = next(
                item for item in payload["learnings"]
                if item["category"] == "root_cause_explanation_tape"
            )

        self.assertTrue(row["retrain_input"])
        self.assertIn("3 snapshot", row["signal"])
        self.assertEqual(payload["scorecard"]["settled_day_root_cause"]["summary"]["explanation_snapshot_count"], 3)
        self.assertIn("Root-cause explanation tape", report)

    def test_build_learning_payload_uses_latest_date_stamped_root_cause_when_canonical_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            backtest_root = Path(tmp) / "backtest"
            write_daily_artifacts(backtest_root)
            (backtest_root / "settled_day_root_cause_2026-06-20.json").write_text(
                json.dumps(
                    {
                        "status": "ACTIONABLE",
                        "target_date": "2026-06-20",
                        "summary": {"explanation_snapshot_count": 4},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_learning_payload(backtest_root=backtest_root)

        artifact = payload["input_artifacts"]["settled_day_root_cause"]
        self.assertTrue(artifact["exists"])
        self.assertTrue(artifact["path"].endswith("settled_day_root_cause_2026-06-20.json"))
        self.assertEqual(payload["scorecard"]["settled_day_root_cause"]["summary"]["explanation_snapshot_count"], 4)


if __name__ == "__main__":
    unittest.main()
