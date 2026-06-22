import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.reporting.progress_audit import (  # noqa: E402
    classify_trend,
    core_model_trend_claim,
    load_daily_progress_ledger,
    load_market_day_labels,
    parse_backtest_report,
    parse_roadmap_baselines,
    render_report,
)


class TestProgressAudit(unittest.TestCase):
    def test_parse_backtest_report_extracts_headline_and_day_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backtest_report.md"
            path.write_text(
                "\n".join([
                    "# Settlement-Scored Backtest",
                    "",
                    "Generated: 2026-06-09 08:46",
                    "",
                    "Market days: 4  |  Total band-rows scored: 4763",
                    "",
                    "| Metric | Value |",
                    "| :--- | :--- |",
                    "| All-snapshot Brier skill vs market | -0.336 |",
                    "| Daily-first Brier skill vs market | -0.347 |",
                    "| All-snapshot log-loss delta (market - model) | -0.0503 |",
                    "",
                    "## Feature Vector Coverage",
                    "",
                    "| Rows | Rows with features | Coverage | Feature schemas |",
                    "| :--- | :--- | :--- | :--- |",
                    "| 4763 | 4059 | 85.2% | toronto_feature_store_v0.1 |",
                    "",
                    "## Score Summary",
                    "",
                    "| Scope | Days | Rows | Model Brier | Market Brier | Brier Delta | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                    "| All snapshots | - | 4763 | 0.0536 | 0.0401 | -0.0135 | -0.336 | 0.1748 | 0.1245 | -0.0503 | 9.1% |",
                    "| Daily-first equal-day average | 4 | 4763 | 0.0531 | 0.0394 | -0.0137 | -0.347 | 0.1733 | 0.1226 | -0.0507 | 9.1% |",
                    "",
                    "## Model Vs Market By Target Day",
                    "",
                    "| Date | Rows | Model Brier | Market Brier | Brier Skill | Model LogLoss | Market LogLoss | LogLoss Delta | Base Rate |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                    "| 2026-06-07 | 1540 | 0.0506 | 0.0536 | +0.055 | 0.1592 | 0.1586 | -0.0006 | 9.1% |",
                ]),
                encoding="utf-8",
            )

            parsed = parse_backtest_report(path)

        self.assertEqual(parsed["market_days"], 4)
        self.assertEqual(parsed["band_rows"], 4763)
        self.assertAlmostEqual(parsed["all_snapshot_brier_skill_vs_market"], -0.336)
        self.assertAlmostEqual(parsed["model_brier"], 0.0536)
        self.assertAlmostEqual(parsed["market_brier"], 0.0401)
        self.assertAlmostEqual(parsed["feature_coverage"]["coverage_rate"], 0.852)
        self.assertEqual(parsed["by_day"][0]["date"], "2026-06-07")
        self.assertAlmostEqual(parsed["by_day"][0]["brier_skill"], 0.055)

    def test_parse_roadmap_baselines_extracts_initial_and_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ROADMAP.md"
            path.write_text(
                "\n".join([
                    "The strict headline report therefore scores 1 clean market day and 704 band rows.",
                    "The uncalibrated model Brier was 0.0583 versus market Brier 0.0394,",
                    "for a Brier skill score of -0.478.",
                    "over 3 settled-looking market days and 1760 band rows. All-snapshot Brier skill was -1.500;",
                    "Brier improved from 0.0954 to 0.0775, log loss improved from 0.3705 to 0.2743,",
                    "and Brier skill versus Polymarket improved from -1.500 to -1.031.",
                ]),
                encoding="utf-8",
            )

            parsed = parse_roadmap_baselines(path)

        self.assertEqual(parsed["initial_strict_toronto"]["band_rows"], 704)
        self.assertAlmostEqual(parsed["initial_strict_toronto"]["model_brier"], 0.0583)
        self.assertAlmostEqual(parsed["initial_strict_toronto"]["brier_skill"], -0.478)
        self.assertAlmostEqual(parsed["pre_label_three_day"]["brier_skill"], -1.5)
        self.assertAlmostEqual(parsed["calibration_pre_label"]["skill_after"], -1.031)

    def test_parse_roadmap_baselines_reads_split_roadmap_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "roadmap"
            items = root / "items"
            items.mkdir(parents=True)
            path = root / "ROADMAP.md"
            path.write_text("# Roadmap\n\nSee the split files.\n", encoding="utf-8")
            (root / "overview.md").write_text(
                "\n".join([
                    "The strict headline report therefore scores 1 clean market day and 704 band rows.",
                    "The uncalibrated model Brier was 0.0583 versus market Brier 0.0394,",
                    "for a Brier skill score of -0.478.",
                ]),
                encoding="utf-8",
            )
            (items / "item-21-market-bin-probability-calibration.md").write_text(
                "\n".join([
                    "over 3 settled-looking market days and 1760 band rows. All-snapshot Brier skill was -1.500;",
                    "Brier improved from 0.0954 to 0.0775, log loss improved from 0.3705 to 0.2743,",
                    "and Brier skill versus Polymarket improved from -1.500 to -1.031.",
                ]),
                encoding="utf-8",
            )

            parsed = parse_roadmap_baselines(path)

        self.assertEqual(parsed["initial_strict_toronto"]["band_rows"], 704)
        self.assertAlmostEqual(parsed["pre_label_three_day"]["brier_skill"], -1.5)
        self.assertAlmostEqual(parsed["calibration_pre_label"]["skill_after"], -1.031)

    def test_load_market_day_labels_counts_quality_and_markets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market_day_labels.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["market_id", "target_date", "quality_grade"])
                writer.writeheader()
                writer.writerow({"market_id": "toronto", "target_date": "2026-06-01", "quality_grade": "complete"})
                writer.writerow({"market_id": "toronto", "target_date": "2026-06-02", "quality_grade": "partial"})
                writer.writerow({"market_id": "nyc", "target_date": "2026-06-02", "quality_grade": "complete"})

            parsed = load_market_day_labels(path)

        self.assertEqual(parsed["rows"], 3)
        self.assertEqual(parsed["quality_counts"]["complete"], 2)
        self.assertEqual(parsed["complete_by_market"]["toronto"], 1)
        self.assertEqual(parsed["target_date_count"], 2)

    def test_classify_trend_requires_positive_skill_for_market_beating(self):
        payload = {
            "roadmap_baselines": {
                "initial_strict_toronto": {
                    "brier_skill": -0.478,
                    "model_brier": 0.0583,
                }
            },
            "current_backtest": {
                "all_snapshot_brier_skill_vs_market": -0.336,
                "model_brier": 0.0536,
            },
            "pooled_candidate_series": [
                {"verdict": "BLOCK", "candidate_brier": 0.1370},
                {"verdict": "SHADOW_ONLY", "candidate_brier": 0.0515},
            ],
            "promotion_refresh": {
                "candidate_cutover_decision": "DO_NOT_CUT_OVER",
                "serving_gauntlet_verdict": "BLOCK",
            },
            "loop_statuses": {
                "snapshot_loop": {"state": "RUNNING"},
                "clob_loop": {"state": "RUNNING"},
            },
        }

        trend = classify_trend(payload)

        self.assertAlmostEqual(trend["model_skill_gain_vs_initial_strict"], 0.142)
        self.assertLess(trend["model_brier_delta_vs_initial_strict"], 0)
        self.assertTrue(trend["candidate_gate_improved"])
        self.assertFalse(trend["model_beats_market_on_current_headline"])
        self.assertTrue(trend["operational_capture_running"])

    def test_core_model_trend_claim_marks_june17_pattern_directional_not_proven(self):
        dates = [f"2026-06-{day:02d}" for day in range(6, 17)]
        skills = [-1.40, -0.26, -0.36, -0.15, -0.20, -0.43, -0.54, -0.65, -0.44, -0.05, 0.03]
        history = {
            "by_date": [
                {
                    "target_date": target_date,
                    "market_days": 12,
                    "scored_rows": 1000,
                    "model_brier": 0.05 - (index * 0.0005),
                    "market_brier": 0.04,
                    "brier_skill_score": skill,
                    "final_top_hit_rate": 1.0,
                }
                for index, (target_date, skill) in enumerate(zip(dates, skills))
            ],
            "days": [
                {
                    "target_date": target_date,
                    "status": "scored",
                    "quality_grade": "partial" if index >= 4 else "complete",
                    "n": 100,
                    "model_brier": 0.05 - (index * 0.0005),
                    "market_brier": 0.04,
                    "model_logloss": 0.15,
                    "market_logloss": 0.12,
                    "base_rate": 0.09,
                }
                for index, target_date in enumerate(dates)
                for _ in range(12)
            ],
        }
        fleet = {
            "status": "CRITICAL",
            "live_forward_slo": {"counts_toward_live_forward_gate": False},
        }
        variant = {
            "delta_vs_baseline": {
                "scored_rows": 269720,
                "unique_observation_count": 0,
                "market_day_count": 0,
            }
        }

        runtime_identity_evidence = {
            "status": "BLOCK",
            "runtime_identity_count": 2,
            "snapshot_row_count": 2446,
            "blocking_reason": "mixed_runtime_identity_unsegmented",
        }

        claim = core_model_trend_claim(
            history,
            fleet=fleet,
            variant_evidence=variant,
            runtime_identity_evidence=runtime_identity_evidence,
        )

        self.assertEqual(claim["status"], "DIRECTIONAL")
        self.assertFalse(claim["claim_allowed"])
        self.assertEqual(claim["summary"]["comparable_day_count"], 11)
        self.assertEqual(claim["summary"]["positive_skill_days"], 1)
        self.assertGreater(claim["summary"]["brier_skill_slope_per_day"], 0)
        self.assertIn("need 3 positive-skill comparable days; have 1", claim["threshold_failures"])
        self.assertTrue(
            any("live-forward SLO" in failure for failure in claim["threshold_failures"])
        )
        self.assertTrue(
            any("unique observations changed by 0" in failure for failure in claim["threshold_failures"])
        )
        self.assertTrue(
            any("mixed runtime identity" in failure for failure in claim["threshold_failures"])
        )
        self.assertEqual(claim["summary"]["runtime_identity_status"], "BLOCK")
        latest = claim["daily_sequence"][-1]
        self.assertTrue(latest["counts_toward_directional_trend"])
        self.assertFalse(latest["counts_toward_proven_claim"])

    def test_render_report_includes_daily_progress_ledger_cross_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "daily_progress_latest.json"
            path.write_text(
                json.dumps({
                    "run_date": "2026-06-19",
                    "broad_improvement_claim_allowed": False,
                    "broad_improvement_claim_failures": "[\"positive_skill_days_below_3\"]",
                    "ops_live_forward_slo_status": "BLOCK",
                    "evidence_independent_baseline_status": "PRESENT",
                    "evidence_frozen_baseline_status": "PRESENT",
                    "evidence_frozen_baseline_brier_delta_current_minus_baseline": -0.02,
                    "trading_mm_evidence_mode": "operator_drill",
                    "trading_taker_quality_status": "SAMPLE_PENDING_NEGATIVE_LATEST",
                }),
                encoding="utf-8",
            )

            ledger = load_daily_progress_ledger(path)

        payload = {
            "generated_at_utc": "2026-06-20T00:00:00+00:00",
            "trend_assessment": {
                "answer": "directional only",
                "model_skill_gain_vs_initial_strict": 0.1,
                "model_brier_delta_vs_initial_strict": -0.01,
            },
            "core_model_trend_claim": {
                "status": "DIRECTIONAL",
                "summary": {
                    "promotion_grade_market_days": 84,
                    "positive_daily_first_days": 3,
                    "rolling_daily_first_brier_skill": 0.01,
                },
                "threshold_failures": [],
            },
            "roadmap_baselines": {
                "initial_strict_toronto": {},
                "pre_label_three_day": {},
                "calibration_pre_label": {},
            },
            "current_backtest": {},
            "market_day_labels": {"quality_counts": {}},
            "location_trust": {"by_market": {}, "grade_counts": {}},
            "promotion_refresh": {
                "early_hour_promotion_status": "BLOCK",
                "early_hour_promotion_allowed": False,
                "early_hour_promotion_blocker_count": 2,
                "early_hour_promotion_blocker": {
                    "status": "BLOCK",
                    "promotion_allowed": False,
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
                        }
                    ],
                },
            },
            "ten_minute_model_performance": {
                "exists": True,
                "status": "BLOCK",
                "weak_slot_labels": ["03:00", "03:10"],
                "weak_slot_summary": {
                    "n": 42,
                    "market_days": 12,
                    "model_brier": 0.0721,
                    "market_brier": 0.0592,
                    "brier_delta": -0.0129,
                },
                "candidate_gate": {"status": "MISSING"},
                "gate": {
                    "first_blocker": {
                        "detail": "10-minute weak-slot model Brier trails market",
                    }
                },
            },
            "promotion_gauntlet_latest": {},
            "fleet_observability": {},
            "frozen_baseline_replay_trend": {
                "exists": True,
                "independent_baseline_status": "PRESENT",
                "baseline_id": "control",
                "coverage": {"shared_observations": 10, "shared_market_days": 2},
                "overall": {"brier_delta_current_minus_baseline": -0.02},
            },
            "loop_statuses": {},
            "pooled_candidate_series": [],
            "daily_progress_ledger_latest": ledger,
        }

        report = render_report(payload)

        self.assertIn("## Daily Progress Ledger Cross-Check", report)
        self.assertIn("2026-06-19", report)
        self.assertIn("operator_drill", report)
        self.assertIn("SAMPLE_PENDING_NEGATIVE_LATEST", report)
        self.assertIn("Live-Forward Vs Weather-Held-Constant", report)
        self.assertIn("Frozen baseline replay trend", report)
        self.assertIn("-0.0200", report)
        self.assertIn("## 10-Minute Weak-Slot Watchlist", report)
        self.assertIn("03:00, 03:10", report)
        self.assertIn("10-minute weak-slot model Brier trails market", report)
        self.assertIn("### Early-Hour Promotion Blocker", report)
        self.assertIn("candidate hourly gate must PASS", report)


if __name__ == "__main__":
    unittest.main()
